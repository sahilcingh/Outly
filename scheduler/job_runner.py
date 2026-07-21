"""
Scheduled job search and Telegram dispatch.

Runs automatically on weekdays at 09:30 and 14:30 IST.
Monday limit = 20 applications, other weekdays = 10.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time

log = logging.getLogger(__name__)

# De-dupe overlapping/duplicate triggers (e.g. in-process scheduler AND an
# external cron both firing the same 9:30 slot). Only one run may start within
# this window — the rest are skipped, so you never get two PDFs for one slot.
_run_lock = threading.Lock()
_last_run_monotonic = 0.0
_MIN_GAP_SECONDS = 20 * 60  # 20 minutes


def run_scheduled_search() -> None:
    """
    Main scheduler entry point. Called by APScheduler (and the /tasks/run-search
    endpoint). Guarded so duplicate triggers for the same slot run only once.
    """
    global _last_run_monotonic
    with _run_lock:
        now = time.monotonic()
        if now - _last_run_monotonic < _MIN_GAP_SECONDS:
            log.info("Skipping duplicate run — last run was %.0fs ago (< %ds guard)",
                     now - _last_run_monotonic, _MIN_GAP_SECONDS)
            return
        _last_run_monotonic = now

    is_monday = datetime.datetime.now().weekday() == 0
    limit = 20 if is_monday else 10

    log.info("Scheduled job search started (limit=%d, monday=%s)", limit, is_monday)

    from storage.profiles import load_profile
    from tools.telegram_bot import send_message

    profile = load_profile()
    if not profile:
        send_message(
            "⚠️ *Scheduled Job Search*\n\n"
            "No resume found. Send me your resume PDF in this chat to activate automatic job searching."
        )
        log.warning("Scheduled search skipped: no candidate profile")
        return

    role_title = profile.get("role_title", "Software Engineer")
    send_message(f"🔍 *Scheduled Job Search*\nSearching for *{role_title}* positions… (limit: {limit})")

    # Run the heavy work in the same thread (APScheduler already runs in its own thread pool)
    _search_and_queue(profile, limit)


def _search_and_queue(profile: dict, limit: int) -> None:
    from tools.job_search import search_jobs
    from llm.job_matcher import score_jobs_parallel
    from llm.cover_letter import generate_cover_letter
    from storage.jobs import (
        init_jobs_table, save_job_application, get_existing_job_urls, get_queued_jobs
    )
    from storage.profiles import load_profile
    from tools.telegram_bot import send_message
    from config import (
        get_scheduler_user_id, get_candidate_level, is_seniority_strict,
        get_job_locations, get_job_hours_old, get_job_hours_fresh, get_extra_job_keywords,
    )
    from tools.seniority import level_from_years, filter_by_level, search_query_for_level
    from tools.location import is_india_job, location_rank

    user_id = get_scheduler_user_id()
    role_title = profile.get("role_title", "Software Engineer")
    skills = profile.get("skills", [])
    candidate_name = profile.get("candidate_name", "")

    # Resolve seniority: env override wins, else derive from resume years
    level = get_candidate_level() or level_from_years(profile.get("experience_years"))
    strict = is_seniority_strict()
    profile["level"] = level  # so the scorer sees it

    locations = get_job_locations()        # Bengaluru first, then India
    fresh_hours = get_job_hours_fresh()    # tight window, tried first (~couple hrs)
    max_hours = get_job_hours_old()        # widen to this if fresh is empty (cap)
    base_query = search_query_for_level(role_title, level)

    # (query, location) pairs to scrape, in priority order. For entry/junior we
    # also search internships and apprenticeships (broad India location only, to
    # bound scrape time).
    pairs = [(base_query, loc) for loc in locations]
    if level in ("entry", "junior"):
        broad_loc = locations[-1] if locations else "India"
        for kw in get_extra_job_keywords():
            pairs.append((f"{role_title} {kw}", broad_loc))

    init_jobs_table()
    existing_urls = get_existing_job_urls(user_id)

    def _fetch(hours: int) -> list:
        """Search all (query, location) pairs for a recency window, merge + filter."""
        by_url: dict = {}
        for q, loc in pairs:
            try:
                batch = search_jobs(query=q, location=loc, results_per_site=12,
                                    hours_old=hours, max_results=40)
            except Exception as e:
                log.warning("search failed for %r @ %s: %s", q, loc, e)
                continue
            for l in batch:
                by_url.setdefault(l.job_url, l)
            if len(by_url) >= 60:
                break
        batch = list(by_url.values())
        # India only (remote allowed); drop US/abroad
        batch = [l for l in batch if is_india_job(l.location, l.is_remote)]
        # At/below the candidate's seniority ceiling (keeps internships/apprenticeships)
        batch, _dropped = filter_by_level(batch, level, strict)
        # Not already saved
        return [l for l in batch if l.job_url not in existing_urls]

    # ── Two-tier recency: try the last few hours, widen to 24h only if empty ──
    try:
        new_listings = _fetch(fresh_hours)
        used_hours = fresh_hours
        if not new_listings and max_hours > fresh_hours:
            log.info("Nothing in last %dh — widening to %dh", fresh_hours, max_hours)
            new_listings = _fetch(max_hours)
            used_hours = max_hours
    except Exception as e:
        log.error("Job search failed: %s", e)
        send_message(f"⚠️ Job search failed: {e}")
        return

    log.info("Found %d new India %s-level listings (last %dh)",
             len(new_listings), level, used_hours)

    if not new_listings:
        send_message(
            f"ℹ️ No new {level}-level jobs in India posted in the last {max_hours}h "
            f"this round. Queue up to date."
        )
        _dispatch_queued_jobs(user_id, limit)
        return

    # ── Score ────────────────────────────────────────────────────────────────
    job_dicts = [
        {
            "title":        l.title,
            "company":      l.company,
            "location":     l.location,
            "description":  l.description,
            "job_url":      l.job_url,
            "is_remote":    l.is_remote,
            "date_posted":  l.date_posted,
            "source":       l.source,
            "apply_method": l.apply_method,
            "contact_email":l.contact_email,
            "ats_url":      l.ats_url,
            "company_url":  l.company_url,
        }
        for l in new_listings
    ]
    scored = score_jobs_parallel(job_dicts, profile)

    # Prefer Bengaluru: small score nudge so local roles rank above equal matches
    for j in scored:
        rank = location_rank(j.get("location", ""))
        if rank == 0:      # Bengaluru
            j["score"] = min(100, j.get("score", 0) + 8)
        elif rank == 1:    # elsewhere in India
            j["score"] = min(100, j.get("score", 0) + 3)
    scored.sort(key=lambda j: j.get("score", 0), reverse=True)

    # Strict resume alignment: drop anything below the match threshold. Aligned
    # roles (full-time, internship, or apprenticeship) score high; off-domain
    # ones score low and are excluded here — so only résumé-matching jobs queue.
    from config import get_min_match_score
    min_score = get_min_match_score()
    before_gate = len(scored)
    scored = [j for j in scored if j.get("score", 0) >= min_score]
    if before_gate - len(scored):
        log.info("Relevance gate (score >= %d) dropped %d off-profile jobs",
                 min_score, before_gate - len(scored))

    if not scored:
        send_message(
            f"ℹ️ Found new {level}-level jobs in India, but none matched your "
            f"résumé strongly enough (score ≥ {min_score}) this round."
        )
        _dispatch_queued_jobs(user_id, limit)
        return

    # Cover letters are generated lazily at dispatch time (see _dispatch_queued_jobs),
    # so a job dispatched in a later run still gets a fresh letter. Here we only
    # pre-generate for the top `limit` that will be dispatched this same run.
    letter_targets = {id(j) for j in scored[:limit]}

    saved = 0
    for job in scored:
        score = job.get("score", 0)
        cover_letter, subject_line = "", f"Application for {job['title']} — {candidate_name or role_title}"

        if id(job) in letter_targets:
            try:
                cl = generate_cover_letter(
                    job_title=job["title"],
                    company=job["company"],
                    location=job.get("location", ""),
                    description=job.get("description", ""),
                    candidate_profile=profile,
                    candidate_name=candidate_name,
                )
                cover_letter = cl.get("cover_letter", "")
                subject_line = cl.get("subject_line", subject_line)
            except Exception as e:
                log.warning("Cover letter failed for %s: %s", job["title"], e)

        try:
            save_job_application(
                user_id=user_id,
                job_title=job["title"],
                company_name=job["company"],
                job_url=job["job_url"],
                location=job.get("location", ""),
                is_remote=bool(job.get("is_remote", False)),
                date_posted=job.get("date_posted", ""),
                source=job.get("source", ""),
                job_description=job.get("description", ""),
                match_score=score,
                match_rationale=job.get("rationale", ""),
                key_matches=job.get("key_matches", []),
                gaps=job.get("gaps", []),
                cover_letter=cover_letter,
                subject_line=subject_line,
                apply_method=job.get("apply_method", "manual"),
                contact_email=job.get("contact_email"),
                ats_url=job.get("ats_url"),
                company_url=job.get("company_url"),
                candidate_name=candidate_name,
                candidate_role=role_title,
            )
            saved += 1
        except Exception as e:
            log.warning("Could not save job %s: %s", job["title"], e)

    send_message(f"✅ Added *{saved}* new jobs to queue. Sending top {limit} for your review…")
    _dispatch_queued_jobs(user_id, limit)


def _dispatch_queued_jobs(user_id: int, limit: int) -> None:
    """Build a PDF digest of up to `limit` queued jobs and send it to Telegram.

    No approve/reject step — the user reads the PDF and applies directly via the
    tappable apply links. Dispatched jobs are marked 'sent' so they don't
    reappear in every future digest. A cover letter is filled in lazily for any
    job missing one before it goes into the PDF.
    """
    from storage.jobs import (
        get_queued_jobs, update_cover_letter, get_job_application, update_job_status
    )
    from llm.cover_letter import generate_cover_letter
    from storage.profiles import load_profile

    queued = get_queued_jobs(user_id=user_id, limit=limit)
    if not queued:
        return

    profile = load_profile() or {}

    # Ensure every job has a cover letter (fill lazily if missing)
    finalized = []
    for job in queued:
        if not (job.cover_letter or "").strip() and (job.job_description or "").strip():
            try:
                cl = generate_cover_letter(
                    job_title=job.job_title,
                    company=job.company_name,
                    location=job.location,
                    description=job.job_description,
                    candidate_profile=profile,
                    candidate_name=job.candidate_name or "",
                )
                letter = cl.get("cover_letter", "")
                if letter:
                    update_cover_letter(job.id, letter)
                    job = get_job_application(job.id)  # reload with the new letter
            except Exception as e:
                log.warning("Lazy cover letter failed for #%d: %s", job.id, e)
        finalized.append(job)

    # Send the full PDF digest (all data + tappable apply links)
    _send_jobs_pdf(finalized)

    # Mark them 'sent' so the next run's digest only carries fresh jobs
    for job in finalized:
        try:
            update_job_status(job.id, "sent")
        except Exception as e:
            log.warning("Could not mark job #%d sent: %s", job.id, e)


def _send_jobs_pdf(jobs: list) -> None:
    """Build a PDF digest of the given jobs and send it to Telegram."""
    if not jobs:
        return
    try:
        from tools.job_pdf import build_jobs_pdf
        from tools.telegram_bot import send_document
        pdf_bytes = build_jobs_pdf(jobs, title="Job Review Queue")
        send_document(
            pdf_bytes,
            filename="outly_jobs.pdf",
            caption=f"Your {len(jobs)} matched jobs. Full details attached; "
                    f"approve/reject each below.",
        )
    except Exception as e:
        log.error("Failed to build/send jobs PDF: %s", e)
