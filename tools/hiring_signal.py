"""
Hiring signal detector: checks if a company has open technical roles.
Checks the company's own /careers page first, then common ATS platforms
(Greenhouse, Lever, Workable) using a slug derived from the company name.
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_TIMEOUT = 6

_TECH_KEYWORDS = re.compile(
    r"\b(engineer|developer|architect|devops|platform|backend|frontend|full.?stack|"
    r"data scientist|machine learning|ml |infrastructure|sre|site reliability|"
    r"security|product manager|tech lead|engineering manager|cto|vp.eng)\b",
    re.I,
)

_CAREERS_PATHS = (
    "/careers", "/jobs", "/join", "/join-us",
    "/work-with-us", "/open-positions", "/hiring",
)


def _fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True)
        if r.status_code < 400:
            return r.text
    except Exception:
        pass

    log.debug("requests failed for %s — trying Playwright fallback.", url)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=_HEADERS["User-Agent"])
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        log.debug("Playwright also failed for %s: %s", url, e)
        return None


from urllib.parse import urljoin

def _extract_jobs(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict] = []
    seen: set[str] = set()

    # Find anchor tags containing job keywords
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if 4 < len(text) < 90 and _TECH_KEYWORDS.search(text):
            # Try to filter out generic links like "Engineering Blog" or "Products"
            # if they don't look like a role title. 
            key = text.lower()
            if key not in seen:
                seen.add(key)
                href = a["href"]
                full_url = urljoin(base_url, href)
                candidates.append({"title": text, "url": full_url})

    # If no anchor tags, try structured job cards and we won't have URLs
    if not candidates:
        for tag in soup.find_all(["h2", "h3", "h4", "li"],
                                  class_=re.compile(r"job|position|role|opening|listing", re.I)):
            text = tag.get_text(strip=True)
            if 4 < len(text) < 90 and _TECH_KEYWORDS.search(text):
                key = text.lower()
                if key not in seen:
                    seen.add(key)
                    # Try to find a link nearby
                    a_near = tag.find_parent("a", href=True) or tag.find_next("a", href=True)
                    url = urljoin(base_url, a_near["href"]) if a_near else base_url
                    candidates.append({"title": text, "url": url})

    return candidates[:10]


def _slug(company_name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", company_name.lower())


def find_hiring_signals(base_url: str, company_name: str) -> list[dict]:
    """
    Return open technical job objects found at this company (up to 8).
    Returns an empty list if no roles are found.
    Each item is {"title": str, "url": str}
    """
    base = base_url.rstrip("/")
    slug = _slug(company_name)

    # 1. Company's own careers pages
    for path in _CAREERS_PATHS:
        url_to_fetch = base + path
        html = _fetch(url_to_fetch)
        if html:
            jobs = _extract_jobs(html, url_to_fetch)
            if jobs:
                log.info("Hiring signals from %s: %s", url_to_fetch, [j["title"] for j in jobs[:3]])
                return jobs[:8]

    # 2. Common ATS platforms
    ats_urls = [
        f"https://boards.greenhouse.io/{slug}",
        f"https://jobs.lever.co/{slug}",
        f"https://apply.workable.com/{slug}",
    ]
    for url in ats_urls:
        html = _fetch(url)
        if html:
            jobs = _extract_jobs(html, url)
            if jobs:
                log.info("Hiring signals from ATS %s: %s", url, [j["title"] for j in jobs[:3]])
                return jobs[:8]

    log.info("No open tech roles found for '%s'", company_name)
    return []
