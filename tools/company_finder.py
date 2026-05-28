"""
Company finder: given a candidate's skills, finds real companies that would hire them.

Strategy:
1. Search DuckDuckGo with skill-based queries (job boards are FINE as input)
2. Extract company names from job listing titles ("Engineer at Stripe" → "Stripe")
   and from ATS platform URLs (lever.co/razorpay → "Razorpay")
3. Verify each company name with find_official_website() — already bulletproof
4. Return verified companies with their official URLs
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# ATS platforms whose URL paths contain the company slug
_ATS_EXTRACTORS = [
    (re.compile(r"boards\.greenhouse\.io/([^/?#]+)"), "greenhouse"),
    (re.compile(r"jobs\.lever\.co/([^/?#]+)"),        "lever"),
    (re.compile(r"apply\.workable\.com/([^/?#]+)"),   "workable"),
    (re.compile(r"linkedin\.com/company/([^/?#]+)"),  "linkedin"),
    (re.compile(r"linkedin\.com/jobs/view/\d+.*?at ([A-Za-z0-9 &\-\.]{2,40})"), "linkedin_title"),
    (re.compile(r"careers\.([a-z0-9\-]+)\.(com|io|in)/"), "careers_sub"),
]

# Job title keywords — a token matching these is NOT a company name
_JOB_WORDS = re.compile(
    r"^(senior|junior|lead|staff|principal|remote|full.?time|part.?time|contract|"
    r"engineer|developer|manager|analyst|designer|intern|architect|consultant|"
    r"specialist|associate|director|head|hiring|we.?re|our|the|and|for|with|"
    r"backend|frontend|fullstack|full.stack|software|data|ml|ai|devops|cloud|"
    r"mobile|android|ios|web|site|platform|infrastructure|security|qa|"
    r"product|business|sales|marketing|hr|finance|operations)$",
    re.I,
)

# Separators used in job titles to separate role from company
_SEP_PATTERNS = [
    r"\s+at\s+",         # "Engineer at Stripe"
    r"\s+@\s+",          # "Engineer @ Stripe"
    r"\s+[-–—]\s+",      # "Engineer - Stripe" or "Engineer — Stripe"
    r"\s*\|\s*",          # "Engineer | Stripe"
    r"\s*::\s*",          # "Engineer :: Stripe"
]


def _slug_to_name(slug: str) -> str:
    """Convert URL slug like 'razorpay-india' → 'Razorpay India'."""
    return slug.replace("-", " ").replace("_", " ").title()


def _is_company_token(token: str) -> bool:
    """Return True if token looks like a company name fragment (not a job keyword)."""
    token = token.strip()
    if not token or len(token) < 2 or len(token) > 60:
        return False
    words = token.split()
    # Reject if all words are job keywords
    non_job = [w for w in words if not _JOB_WORDS.match(w)]
    return len(non_job) >= 1


def _extract_from_url(url: str) -> str | None:
    """Try to extract a company name directly from the URL."""
    for pattern, source in _ATS_EXTRACTORS:
        m = pattern.search(url)
        if m:
            raw = m.group(1).strip()
            if raw and len(raw) > 1:
                name = _slug_to_name(raw)
                log.debug("Company from %s URL: %s", source, name)
                return name
    return None


def _extract_from_title(title: str) -> str | None:
    """
    Extract company name from a job listing title.
    Works for: "Backend Engineer at Razorpay", "Python Dev | Stripe", etc.
    """
    for sep in _SEP_PATTERNS:
        parts = re.split(sep, title, maxsplit=3)
        if len(parts) < 2:
            continue
        # Try last segment first (company usually at end)
        for candidate in reversed(parts[1:]):
            candidate = candidate.strip().rstrip(".,;-—|")
            if _is_company_token(candidate):
                # Strip trailing location info ("Stripe · San Francisco")
                candidate = re.split(r"\s*[·•,]\s*", candidate)[0].strip()
                if candidate and len(candidate) > 1:
                    return candidate
    return None


def _build_search_queries(skills: list[str], role_title: str, industry: str | None) -> list[str]:
    """
    Build targeted DuckDuckGo queries that reliably return job listings
    with company names embedded in titles/snippets.
    """
    top_skills = " ".join(skills[:3])
    queries = []

    # Job listing queries — job boards index these and embed company names in titles
    queries.append(f'"{top_skills}" engineer jobs')
    if industry:
        queries.append(f'{industry} companies hiring {skills[0]} developer')
        queries.append(f'{industry} "{skills[0]}" "{skills[1] if len(skills)>1 else ""}" jobs')
    queries.append(f'{role_title} jobs site:linkedin.com')
    queries.append(f'"{skills[0]}" "{skills[1] if len(skills)>1 else top_skills}" software company')

    # ATS platform queries — directly surface company slug in URL
    queries.append(f'site:boards.greenhouse.io {top_skills}')
    queries.append(f'site:jobs.lever.co {top_skills}')

    return [q for q in queries if q.strip()]


def find_companies_for_candidate(
    search_queries: list[str],
    skills: list[str],
    role_title: str = "",
    industry: str | None = None,
    max_companies: int = 8,
) -> list[dict]:
    """
    Find companies matching a candidate's skills.
    Returns list of {"name": str, "url": str, "snippet": str}.
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        log.warning("duckduckgo_search not installed")
        return []

    from tools.search_tool import find_official_website

    # Combine LLM queries with our reliable job-listing queries
    all_queries = list(search_queries or []) + _build_search_queries(skills, role_title, industry)
    # Deduplicate while preserving order
    seen_q: set[str] = set()
    unique_queries = []
    for q in all_queries:
        if q.lower() not in seen_q:
            seen_q.add(q.lower())
            unique_queries.append(q)

    extracted_names: list[str] = []
    seen_names: set[str] = set()

    for query in unique_queries[:8]:
        if len(extracted_names) >= max_companies * 2:
            break
        log.info("Company search: %s", query)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=10, safesearch="off"))
        except Exception as e:
            log.warning("DDG failed for '%s': %s", query, e)
            continue

        for r in results:
            url   = r.get("href", "")
            title = r.get("title", "")

            # Try URL-based extraction first (most reliable)
            name = _extract_from_url(url)

            # Fall back to title-based extraction
            if not name:
                name = _extract_from_title(title)

            # Fall back to domain name for non-job-board URLs
            if not name:
                try:
                    parsed = urlparse(url)
                    host = parsed.netloc.lstrip("www.")
                    root = ".".join(host.split(".")[-2:])
                    # Skip obvious non-company domains
                    skip = {"linkedin.com","indeed.com","glassdoor.com","naukri.com",
                            "monster.com","google.com","bing.com","yahoo.com",
                            "quora.com","reddit.com","wikipedia.org","medium.com",
                            "github.com","stackoverflow.com","timesjobs.com"}
                    if root not in skip and len(parsed.path.strip("/").split("/")) <= 2:
                        name = _slug_to_name(host.split(".")[0])
                except Exception:
                    pass

            if name:
                key = name.lower().strip()
                if key not in seen_names and len(key) > 2:
                    seen_names.add(key)
                    extracted_names.append(name)

    log.info("Extracted %d candidate company names", len(extracted_names))

    # Now verify each name using find_official_website() — already bulletproof
    verified: list[dict] = []
    for name in extracted_names:
        if len(verified) >= max_companies:
            break
        log.info("Verifying company: %s", name)
        try:
            result = find_official_website(name)
            if result and result.url:
                verified.append({
                    "name": name,
                    "url": result.url,
                    "snippet": result.snippet or "",
                })
                log.info("Verified: %s → %s", name, result.url)
        except Exception as e:
            log.warning("Could not verify '%s': %s", name, e)
            continue

    log.info("Verified %d companies for prospecting", len(verified))
    return verified
