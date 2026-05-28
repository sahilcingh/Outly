"""
Company finder: given a candidate's skills and search queries,
finds real companies that would be a good hiring match.
Uses DuckDuckGo search + existing website verifier.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Domains to skip — job boards, directories, social media, news, wikis
_SKIP_DOMAINS = frozenset([
    "linkedin.com", "indeed.com", "glassdoor.com", "naukri.com",
    "monster.com", "ziprecruiter.com", "greenhouse.io", "lever.co",
    "workable.com", "dice.com", "stackoverflow.com", "wellfound.com",
    "angellist.com", "builtin.com", "simplyhired.com", "careerbuilder.com",
    "wikipedia.org", "quora.com", "reddit.com", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "youtube.com", "medium.com",
    "techcrunch.com", "forbes.com", "crunchbase.com", "bloomberg.com",
    "github.com", "gitlab.com", "kaggle.com", "huggingface.co",
    "timesjobs.com", "shine.com", "foundit.in", "apna.co",
])


def _root_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc or url
        parts = host.lstrip("www.").split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return url


def _domain_to_name(domain: str) -> str:
    """Convert 'stripe.com' → 'Stripe'."""
    name = domain.split(".")[0]
    return name.replace("-", " ").replace("_", " ").title()


def find_companies_for_candidate(
    search_queries: list[str],
    skills: list[str],
    max_companies: int = 8,
) -> list[dict]:
    """
    Search DuckDuckGo with LLM-generated queries to find companies
    that match this candidate's skills.

    Returns a list of dicts:
      {"name": str, "url": str, "snippet": str}
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        log.warning("duckduckgo_search not installed")
        return []

    from tools.search_tool import find_official_website

    seen_domains: set[str] = set()
    candidates: list[dict] = []

    # Run each LLM-generated search query
    for query in search_queries[:5]:
        if len(candidates) >= max_companies:
            break
        log.info("Company search query: %s", query)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=10, safesearch="off"))
        except Exception as e:
            log.warning("DDG search failed for query '%s': %s", query, e)
            continue

        for r in results:
            url = r.get("href", "")
            title = r.get("title", "")
            snippet = r.get("body", "")

            if not url:
                continue

            root = _root_domain(url)
            if root in _SKIP_DOMAINS or root in seen_domains:
                continue

            # Must look like a company domain (not a path-heavy URL)
            parsed = urlparse(url)
            if len(parsed.path.strip("/").split("/")) > 2:
                continue

            seen_domains.add(root)
            company_name = _domain_to_name(root)

            candidates.append({
                "name": company_name,
                "url": f"{parsed.scheme}://{parsed.netloc}",
                "snippet": snippet[:200],
            })

            if len(candidates) >= max_companies:
                break

    # Fallback: skill-based direct queries if not enough results
    if len(candidates) < 3 and skills:
        skill_str = " ".join(skills[:4])
        fallback_query = f"companies hiring {skill_str} engineer"
        log.info("Fallback company search: %s", fallback_query)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(fallback_query, max_results=10, safesearch="off"))
            for r in results:
                url = r.get("href", "")
                if not url:
                    continue
                root = _root_domain(url)
                if root in _SKIP_DOMAINS or root in seen_domains:
                    continue
                seen_domains.add(root)
                parsed = urlparse(url)
                candidates.append({
                    "name": _domain_to_name(root),
                    "url": f"{parsed.scheme}://{parsed.netloc}",
                    "snippet": r.get("body", "")[:200],
                })
                if len(candidates) >= max_companies:
                    break
        except Exception as e:
            log.warning("Fallback search failed: %s", e)

    log.info("Found %d company candidates", len(candidates))
    return candidates[:max_companies]
