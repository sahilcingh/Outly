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
# None (not 0.0) — time.monotonic()'s epoch is arbitrary (often system boot
# time on Linux), not "process start". A fresh short-lived process (e.g. a
# GitHub Actions runner that just booted) can have monotonic() < 20 minutes,
# which made the very first call in that process look like a duplicate of a
# run "0s ago" and silently skip every time. None means "no previous run yet
# in this process" unambiguously, regardless of what the clock reads.
_last_run_monotonic: float | None = None
_MIN_GAP_SECONDS = 20 * 60  # 20 minutes


def run_scheduled_search() -> None:
    """
    Main scheduler entry point. Called by APScheduler (and the /tasks/run-search
    endpoint). Guarded so duplicate triggers for the same slot run only once.
    """
    global _last_run_monotonic
    with _run_lock:
        now = time.monotonic()
        if _last_run_monotonic is not None and now - _last_run_monotonic < _MIN_GAP_SECONDS:
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


def _log_drop(stage: str, before: int, after: int) -> None:
    if before > after:
        log.info("Filter %-14s dropped %d", stage, before - after)


def _search_and_queue(profile: dict, limit: int) -> None:
    from tools.job_search import search_jobs, filter_intern_roles, filter_by_blocklist
    from tools.experience import filter_by_experience
    from tools.filters import filter_by_avoid, dedupe_listings
    from tools.ats_board import filter_ghost_jobs
    from llm.job_matcher import score_jobs_parallel
    from llm.cover_letter import generate_cover_letter
    from storage.jobs import (
        init_jobs_table, save_job_application, get_existing_job_urls, get_seen_job_keys
    )
    from storage.profiles import apply_overrides
    from tools.telegram_bot import send_message
    from config import (
        get_scheduler_user_id, is_seniority_strict, resolve_min_score,
        get_job_locations, get_job_hours_old, get_job_hours_fresh, get_extra_job_keywords,
        get_blocked_companies, get_block_internships, get_preferred_locations,
        allow_remote_india, get_avoid_skills, get_avoid_domains,
    )
    from tools.seniority import filter_by_level, search_query_for_level
    from tools.location import is_india_job, is_preferred_location, location_rank
    from storage.settings import get_settings

    user_id = get_scheduler_user_id()

    # Chat-settable overrides (via /location, /minscore, /remote, /experience,
    # /name, /cities) win over the global env-var defaults for this user.
    # The overridden profile is the ONE object the filters, matcher and cover
    # letter generator all see (name, experience_years, level).
    prefs = get_settings(user_id)
    profile = apply_overrides(profile, prefs)
    level = profile["level"]
    candidate_years = profile["experience_years"]
    candidate_name = profile["candidate_name"]
    role_title = profile.get("role_title", "Software Engineer")
    target_roles = profile.get("target_roles") or [role_title]
    strict = is_seniority_strict()

    if not candidate_name:
        log.warning("Candidate name unknown: cover letters will be blocked. "
                    "Set it with /name <full name> or re-upload the resume.")

    min_score, min_score_src = resolve_min_score(level, prefs.get("min_score"))
    log.info("Effective min_score=%d (source: %s) | level=%s | experience_years=%s",
             min_score, min_score_src, level, candidate_years)

    locations = [prefs["location"]] if prefs.get("location") else get_job_locations()
    remote_only_pref = bool(prefs.get("remote_only", False))

    preferred = list(prefs.get("preferred_locations") or get_preferred_locations())
    if prefs.get("location"):
        city = prefs["location"].split(",")[0].strip().lower()
        if city and city != "india" and city not in preferred:
            preferred.append(city)
    remote_india_ok = allow_remote_india()
    avoid_terms = get_avoid_skills() + get_avoid_domains()

    fresh_hours = get_job_hours_fresh()    # tight window, tried first (~couple hrs)
    max_hours = get_job_hours_old()        # widen to this if fresh is empty (cap)
    base_query = search_query_for_level(target_roles[0], level)

    # (query, location) pairs to scrape, in priority order. A second target role
    # is searched in the broad (last) location only. For entry/junior we also
    # search internships and apprenticeships (broad India location only).
    pairs = [(base_query, loc) for loc in locations]
    broad_loc = locations[-1] if locations else "India"
    if len(target_roles) > 1:
        pairs.append((search_query_for_level(target_roles[1], level), broad_loc))
    if level in ("entry", "junior"):
        for kw in get_extra_job_keywords():
            pairs.append((f"{target_roles[0]} {kw}", broad_loc))

    init_jobs_table()
    existing_urls = get_existing_job_urls(user_id)
    seen_keys = get_seen_job_keys(user_id)

    def _fetch(hours: int) -> list:
        """Search all (query, location) pairs for a recency window, merge + filter."""
        by_url: dict = {}
        for q, loc in pairs:
            try:
                batch = search_jobs(query=q, location=loc, results_per_site=12,
                                    hours_old=hours, max_results=40,
                                    remote_only=remote_only_pref)
            except Exception as e:
                log.warning("search failed for %r @ %s: %s", q, loc, e)
                continue
            for l in batch:
                by_url.setdefault(l.job_url, l)
            if len(by_url) >= 60:
                break
        batch = list(by_url.values())
        log.info("Fetched %d unique listings (last %dh)", len(batch), hours)

        def stage(name: str, before: list, after: list) -> list:
            _log_drop(name, len(before), len(after))
            return after

        # India only, then only preferred cities (or remote roles explicitly in India)
        batch = stage("not-india", batch, [l for l in batch if is_india_job(l.location, l.is_remote)])
        batch = stage("location", batch, [
            l for l in batch
            if is_preferred_location(l.location, l.is_remote, preferred, remote_india_ok)
        ])
        # User preference: no internship roles at all, and never these companies.
        if get_block_internships():
            batch = stage("internship", batch, filter_intern_roles(batch)[0])
        batch = stage("blocklist", batch, filter_by_blocklist(batch, get_blocked_companies())[0])
        # Description states more years than the candidate has: skip it.
        batch = stage("experience", batch, filter_by_experience(batch, candidate_years)[0])
        # At/below the candidate's seniority ceiling (keeps apprenticeships)
        batch = stage("seniority", batch, filter_by_level(batch, level, strict)[0])
        # Avoid-listed skills (must-have) / domains: dropped before any LLM scoring
        batch = stage("avoid-list", batch, filter_by_avoid(batch, avoid_terms)[0])
        # Not already saved
        batch = stage("already-saved", batch, [l for l in batch if l.job_url not in existing_urls])
        # Same company+title across cities / earlier digests: keep one, prefer Bengaluru
        batch = stage("duplicate", batch, dedupe_listings(batch, seen_keys)[0])
        # Role no longer on the employer's own ATS board (network, so last)
        return stage("ghost", batch, filter_ghost_jobs(batch)[0])

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

    log.info("Found %d new %s-level listings in preferred locations (last %dh)",
             len(new_listings), level, used_hours)

    if not new_listings:
        send_message(
            f"ℹ️ No new {level}-level jobs in your preferred locations posted in the last "
            f"{max_hours}h this round. Queue up to date."
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

    # Strict resume alignment: gate on the RAW score (location bonus not included).
    before = len(scored)
    scored = [j for j in scored if j.get("score", 0) >= min_score]
    _log_drop(f"score<{min_score}", before, len(scored))

    # The matcher read the whole requirements section: drop what asks for more
    # years than the candidate has.
    before = len(scored)
    scored = [j for j in scored
              if j.get("required_min_years") is None or j["required_min_years"] <= candidate_years]
    _log_drop("matcher-min-yoe", before, len(scored))

    # Prefer Bengaluru: nudge ordering only. "score" stays raw (shown in the PDF);
    # the bonus lives in "sort_score".
    for j in scored:
        rank = location_rank(j.get("location", ""))
        bonus = 8 if rank == 0 else 3 if rank == 1 else 0
        j["sort_score"] = min(100, j.get("score", 0) + bonus)
    scored.sort(key=lambda j: j["sort_score"], reverse=True)

    if not scored:
        send_message(
            f"ℹ️ Found new {level}-level jobs, but none matched your "
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
        cover_letter = ""
        subject_line = f"Application for {job['title']}" + (f" - {candidate_name}" if candidate_name else "")
        meta = {
            "required_min_years": job.get("required_min_years"),
            "work_location":      job.get("work_location", ""),
            "work_model":         job.get("work_model", ""),
            "must_have_missing":  job.get("must_have_missing", []),
        }

        if id(job) in letter_targets:
            try:
                cl = generate_cover_letter(
                    job_title=job["title"],
                    company=job["company"],
                    location=job.get("location", ""),
                    description=job.get("description", ""),
                    candidate_profile=profile,
                    candidate_name=candidate_name,
                    gaps=list(job.get("gaps", [])) + list(job.get("must_have_missing", [])),
                )
                cover_letter = cl.get("cover_letter", "")
                subject_line = cl.get("subject_line") or subject_line
                meta["letter_status"] = cl.get("status", "")
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
                candidate_role=profile.get("current_title") or role_title,
                sort_score=job["sort_score"],
                match_meta=meta,
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
    job missing one (or still carrying the old "Candidate" placeholder) before
    it goes into the PDF.
    """
    import re
    from storage.jobs import (
        get_queued_jobs, update_cover_letter, get_job_application, update_job_status
    )
    from llm.cover_letter import generate_cover_letter
    from storage.profiles import load_profile, apply_overrides
    from storage.settings import get_settings

    queued = get_queued_jobs(user_id=user_id, limit=limit)
    if not queued:
        return

    # Same overridden profile object the search/scoring path used
    profile = apply_overrides(load_profile() or {}, get_settings(user_id))

    def _needs_letter(job) -> bool:
        text = f"{job.cover_letter or ''} {job.subject_line or ''}"
        return not (job.cover_letter or "").strip() or re.search(r"\bCandidate\b", text) is not None

    # Ensure every job has a cover letter (fill lazily if missing)
    finalized = []
    for job in queued:
        if _needs_letter(job) and (job.job_description or "").strip():
            try:
                cl = generate_cover_letter(
                    job_title=job.job_title,
                    company=job.company_name,
                    location=job.location,
                    description=job.job_description,
                    candidate_profile=profile,
                    candidate_name=profile.get("candidate_name", ""),
                    gaps=list(job.gaps) + list(job.match_meta.get("must_have_missing", [])),
                )
                letter = cl.get("cover_letter", "")
                if letter:
                    update_cover_letter(job.id, letter, letter_status=cl.get("status"),
                                        subject_line=cl.get("subject_line"))
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
