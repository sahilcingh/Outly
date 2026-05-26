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
        return r.text if r.status_code < 400 else None
    except Exception:
        return None


def _extract_titles(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    # Structured job cards first
    for tag in soup.find_all(["h2", "h3", "h4", "a", "li"],
                              class_=re.compile(r"job|position|role|opening|listing", re.I)):
        text = tag.get_text(strip=True)
        if 4 < len(text) < 90 and _TECH_KEYWORDS.search(text):
            candidates.append(text)

    # Fallback: scan all lines
    if not candidates:
        for line in soup.get_text("\n").split("\n"):
            line = line.strip()
            if 4 < len(line) < 90 and _TECH_KEYWORDS.search(line):
                candidates.append(line)

    seen: set[str] = set()
    result: list[str] = []
    for t in candidates:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)

    return result[:10]


def _slug(company_name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", company_name.lower())


def find_hiring_signals(base_url: str, company_name: str) -> list[str]:
    """
    Return open technical job titles found at this company (up to 8).
    Returns an empty list if no roles are found.
    """
    base = base_url.rstrip("/")
    slug = _slug(company_name)

    # 1. Company's own careers pages
    for path in _CAREERS_PATHS:
        html = _fetch(base + path)
        if html:
            titles = _extract_titles(html)
            if titles:
                log.info("Hiring signals from %s%s: %s", base, path, titles[:3])
                return titles[:8]

    # 2. Common ATS platforms
    ats_urls = [
        f"https://boards.greenhouse.io/{slug}",
        f"https://jobs.lever.co/{slug}",
        f"https://apply.workable.com/{slug}",
    ]
    for url in ats_urls:
        html = _fetch(url)
        if html:
            titles = _extract_titles(html)
            if titles:
                log.info("Hiring signals from ATS %s: %s", url, titles[:3])
                return titles[:8]

    log.info("No open tech roles found for '%s'", company_name)
    return []
