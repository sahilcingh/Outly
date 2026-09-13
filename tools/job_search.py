"""
Job search via python-jobspy — LinkedIn, Indeed, Glassdoor, Google scraping.
Falls back gracefully if one site blocks; returns empty list on total failure.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# naukri needs a real Akamai-bypassing browser session to get past its
# reCAPTCHA wall (confirmed 406 in testing) — not worth attempting until
# that's built, so it's left out rather than burning a request every search.
# zip_recruiter (US), bayt (Gulf), and bdjobs (Bangladesh) aren't relevant here.
_SITES = ["linkedin", "indeed", "glassdoor", "google"]

# jobspy's Country.get_glassdoor_url() returns a trailing slash, and the
# Glassdoor scraper's location lookup separately prepends its own "/" —
# together that builds "https://www.glassdoor.co.in//findPopularLocationAjax..."
# (double slash), which Glassdoor's server rejects with 400 "location not
# parsed". Confirmed against the live site; there's an open, unmerged upstream
# fix for this. Patched here rather than waiting on a jobspy release.
def _patch_glassdoor_double_slash() -> None:
    try:
        from jobspy.model import Country
    except ImportError:
        return
    if getattr(Country.get_glassdoor_url, "_outly_patched", False):
        return
    _orig = Country.get_glassdoor_url

    def _patched(self):
        return _orig(self).rstrip("/")
    _patched._outly_patched = True
    Country.get_glassdoor_url = _patched


_patch_glassdoor_double_slash()


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
        ("myworkdayjobs.com",  "ats_workday"),
        ("successfactors.com", "ats_successfactors"),
        ("taleo.net",          "ats_taleo"),
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
    Search LinkedIn, Indeed, Glassdoor, and Google for jobs matching query.
    Returns a flat list of JobListing objects, capped at `max_results`.
    Tries all sites together first; on failure retries each site individually.
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
                # results_wanted is a per-site target inside jobspy, not a
                # total split across sites — pass it through as-is regardless
                # of how many sites are in this batch.
                results_wanted=results_per_site,
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

    # Try every site together first (fastest path). jobspy re-raises a
    # worker's exception from the whole batched call, so one flaky/blocked
    # site (Glassdoor is more bot-sensitive than LinkedIn/Indeed) would
    # otherwise take down the entire search. Fall back to scraping each site
    # individually and merging whatever succeeds.
    df = _scrape(_SITES)
    if df is None:
        log.warning("Combined scrape failed — retrying each site individually...")
        import pandas as pd
        frames = []
        for site in _SITES:
            time.sleep(2)
            site_df = _scrape([site])
            if site_df is not None:
                frames.append(site_df)
            else:
                log.warning("%s scrape failed/returned nothing.", site)
        df = pd.concat(frames, ignore_index=True) if frames else None
    if df is None:
        log.warning("All job scraping attempts failed.")
        return []

    for _, row in df.iterrows():
        title       = _safe_str(row.get("title"))
        company     = _safe_str(row.get("company"))
        job_url     = _safe_str(row.get("job_url"))
        if not title or not company or not job_url:
            continue

        # job_url is the board's own listing page (LinkedIn/Indeed); job_url_direct,
        # when jobspy can resolve it, is the employer's real ATS application page
        # (e.g. a company's Workday portal) — prefer it so users land one click
        # closer to actually applying instead of bouncing through the job board.
        # LinkedIn specifically now gates this behind a sign-in wall for most
        # listings (confirmed live — the public job page no longer embeds the
        # external apply URL), so job_url_direct is usually empty for LinkedIn
        # and the board link is the best we can do there without logging in.
        job_url_direct = _safe_str(row.get("job_url_direct"))
        apply_url = job_url_direct or job_url

        emails      = _safe_emails(row.get("emails"))
        method, target = _detect_apply(apply_url, emails)

        listing = JobListing(
            title        = title,
            company      = company,
            location     = _safe_str(row.get("location")) or location,
            job_url      = apply_url,
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


def filter_by_geo(listings: list[JobListing]) -> tuple[list[JobListing], int]:
    """
    Business rule: India-only. Drops every listing not based in India,
    remote included — a remote role for a US/EU team still doesn't count.
    Returns (kept_listings, dropped_count).

    Delegates to tools.location (the same check the Telegram scheduler uses)
    so there's one source of truth for "is this India" — two separate
    near-duplicate implementations previously drifted apart and silently
    dropped Indeed's "State, IN" results in one of them.
    """
    from tools.location import is_india_job
    kept = [l for l in listings if is_india_job(l.location, l.is_remote)]
    return kept, len(listings) - len(kept)


def search_jobs_locations(
    query: str,
    locations: list[str],
    results_per_site: int = 15,
    hours_old: int = 24,
    remote_only: bool = False,
    max_results: int = 40,
) -> list[JobListing]:
    """
    Run the search across several locations in priority order and merge the
    results, de-duplicated by job_url, keeping the first (highest-priority)
    occurrence. Earlier locations in the list are searched first.
    """
    seen: set[str] = set()
    merged: list[JobListing] = []
    for loc in locations:
        if len(merged) >= max_results:
            break
        batch = search_jobs(
            query=query,
            location=loc,
            results_per_site=results_per_site,
            hours_old=hours_old,
            remote_only=remote_only,
            max_results=max_results,
        )
        for l in batch:
            if l.job_url in seen:
                continue
            seen.add(l.job_url)
            merged.append(l)
            if len(merged) >= max_results:
                break
    log.info("Merged %d listings across locations %s", len(merged), locations)
    return merged
