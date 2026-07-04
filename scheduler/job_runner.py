"""
Scheduled job search and Telegram dispatch.

Runs automatically on weekdays at 09:30 and 14:30 IST.
Monday limit = 20 applications, other weekdays = 10.
"""

from __future__ import annotations

import datetime
import logging
import threading

log = logging.getLogger(__name__)


def run_scheduled_search() -> None:
    """
    Main scheduler entry point. Called by APScheduler.
    - Loads saved candidate profile
    - Searches LinkedIn + Indeed for matching jobs
    - Scores, generates cover letters, saves to DB
    - Sends top N queued jobs to Telegram for approval
    """
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
        init_jobs_table, save_job_application, job_already_saved, get_queued_jobs
    )
    from storage.profiles import load_profile
    from tools.telegram_bot import send_message
    from config import get_scheduler_user_id

    user_id = get_scheduler_user_id()
    role_title = profile.get("role_title", "Software Engineer")
    skills = profile.get("skills", [])
    candidate_name = profile.get("candidate_name", "")

    init_jobs_table()

    # ── Search ──────────────────────────────────────────────────────────────
    try:
        listings = search_jobs(
            query=role_title,
            location="Remote",
            results_per_site=20,
            hours_old=168,
        )
    except Exception as e:
        log.error("Job search failed: %s", e)
        send_message(f"⚠️ Job search failed: {e}")
        return

    new_listings = [l for l in listings if not job_already_saved(user_id, l.job_url)]
    log.info("Found %d listings, %d new", len(listings), len(new_listings))

    if not new_listings:
        send_message("ℹ️ No new jobs found this round. Queue already up to date.")
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

    # Cover letters are generated lazily at dispatch time (see _dispatch_queued_jobs),
    # so a job dispatched in a later run still gets a fresh letter. Here we only
    # pre-generate for the top `limit` that will be dispatched this same run.
    eligible = [j for j in scored if j.get("score", 0) >= 50]
    letter_targets = {id(j) for j in eligible[:limit]}

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
    """Send up to `limit` queued jobs to Telegram for approval.

    Generates a cover letter on the fly for any job missing one, so jobs that
    were queued in an earlier run (without a pre-generated letter) still go out
    complete.
    """
    from storage.jobs import (
        get_queued_jobs, set_telegram_pending, update_cover_letter, get_job_application
    )
    from tools.telegram_bot import send_job_for_approval
    from llm.cover_letter import generate_cover_letter
    from storage.profiles import load_profile

    queued = get_queued_jobs(user_id=user_id, limit=limit)
    if not queued:
        return

    profile = load_profile() or {}

    for job in queued:
        try:
            # Lazy cover letter: fill in if missing (letter cap was hit at save time)
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

            msg_id = send_job_for_approval(job)
            if msg_id:
                set_telegram_pending(job.id, msg_id)
            else:
                log.warning("Could not send job #%d to Telegram", job.id)
        except Exception as e:
            log.error("dispatch_queued_jobs error for job #%d: %s", job.id, e)
