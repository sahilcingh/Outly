"""
Job search via python-jobspy — LinkedIn + Indeed scraping.
Falls back gracefully if one site blocks; returns empty list on total failure.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    job_url: str
    description: str
    is_remote: bool
    date_posted: str
    source: str                        # linkedin | indeed
    emails: list[str] = field(default_factory=list)
    company_url: str | None = None
    apply_method: str = "manual"       # email | ats_greenhouse | ats_lever | ats_workable | ats_ashby | manual
    ats_url: str | None = None
    contact_email: str | None = None


def _detect_apply(job_url: str, emails: list[str]) -> tuple[str, str | None]:
    """Detect how to apply: email, known ATS, or manual."""
    if emails:
        return "email", emails[0]
    u = (job_url or "").lower()
    for fragment, method in [
        ("greenhouse.io",      "ats_greenhouse"),
        ("lever.co",           "ats_lever"),
        ("workable.com",       "ats_workable"),
        ("ashbyhq.com",        "ats_ashby"),
        ("rippling.com",       "ats_rippling"),
        ("smartrecruiters",    "ats_smartrecruiters"),
        ("jobvite.com",        "ats_jobvite"),
        ("icims.com",          "ats_icims"),
    ]:
        if fragment in u:
            return method, job_url
    return "manual", job_url


def _safe_str(val) -> str:
    """Convert a pandas value to string, returning '' for NaN/None."""
    if val is None:
        return ""
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return ""
    except Exception:
        pass
    return str(val).strip()


def _safe_bool(val) -> bool:
    if val is None:
        return False
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return False
    except Exception:
        pass
    return bool(val)


def _safe_emails(val) -> list[str]:
    if val is None:
        return []
    s = _safe_str(val)
    if not s:
        return []
    # jobspy returns comma-separated or a list repr
    emails = [e.strip().strip("[]'\"") for e in s.replace(";", ",").split(",")]
    return [e for e in emails if "@" in e]


def search_jobs(
    query: str,
    location: str = "Remote",
    results_per_site: int = 15,
    hours_old: int = 168,           # 1 week
    remote_only: bool = False,
    max_results: int = 40,          # hard ceiling on returned listings
) -> list[JobListing]:
    """
    Search LinkedIn and Indeed for jobs matching query.
    Returns a flat list of JobListing objects, capped at `max_results`.
    Tries LinkedIn + Indeed together; on block retries each site individually.
    jobspy can over-deliver past results_wanted, so we truncate to max_results.
    """
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log.error("python-jobspy not installed. Run: pip install python-jobspy")
        return []

    listings: list[JobListing] = []

    def _scrape(sites: list[str]) -> "pd.DataFrame | None":
        import pandas as pd
        try:
            df = scrape_jobs(
                site_name=sites,
                search_term=query,
                location=location,
                results_wanted=results_per_site * len(sites),
                hours_old=hours_old,
                is_remote=bool(remote_only),
                country_indeed="India",
                linkedin_fetch_description=True,
                verbose=0,
            )
            return df if df is not None and not df.empty else None
        except Exception as e:
            log.warning("scrape_jobs failed for %s: %s", sites, e)
            return None

    # Try both sites together first; retry individually on failure
    df = _scrape(["linkedin", "indeed"])
    if df is None:
        log.warning("Combined scrape failed — retrying LinkedIn alone...")
        time.sleep(2)
        df = _scrape(["linkedin"])
    if df is None:
        log.warning("LinkedIn alone failed — retrying Indeed alone...")
        time.sleep(2)
        df = _scrape(["indeed"])
    if df is None:
        log.warning("All job scraping attempts failed.")
        return []

    for _, row in df.iterrows():
        title       = _safe_str(row.get("title"))
        company     = _safe_str(row.get("company"))
        job_url     = _safe_str(row.get("job_url"))
        if not title or not company or not job_url:
            continue

        emails      = _safe_emails(row.get("emails"))
        method, target = _detect_apply(job_url, emails)

        listing = JobListing(
            title        = title,
            company      = company,
            location     = _safe_str(row.get("location")) or location,
            job_url      = job_url,
            description  = _safe_str(row.get("description")),
            is_remote    = _safe_bool(row.get("is_remote")),
            date_posted  = _safe_str(row.get("date_posted")),
            source       = _safe_str(row.get("site")) or "unknown",
            emails       = emails,
            company_url  = _safe_str(row.get("company_url")) or None,
            apply_method = method,
            ats_url      = target if method != "email" else None,
            contact_email= target if method == "email" else None,
        )
        listings.append(listing)
        if len(listings) >= max_results:
            break

    log.info("Found %d job listings for query '%s' (cap %d)", len(listings), query, max_results)
    return listings
