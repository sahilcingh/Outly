"""
Contact extractor: scrapes company team/leadership/contact pages to find
the most relevant person to receive a recruiter cold email (HR, Talent,
Engineering leadership, or a founder for small companies).
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
_TIMEOUT = 8

# Pages most likely to have team/contact info, ordered by relevance
_CONTACT_PATHS = (
    "/about/team", "/team", "/leadership", "/about/leadership",
    "/people", "/about/people", "/contact", "/about-us",
    "/company/team", "/company/about", "/careers/team",
)

# Title keywords → priority (lower = higher priority for outreach)
_TITLE_PRIORITY: list[tuple[re.Pattern, int]] = [
    (re.compile(r"\btalent\b|\brecruit", re.I), 1),
    (re.compile(r"\bhr\b|human.resourc|people.ops|people.partner", re.I), 2),
    (re.compile(r"\bhead of (engineering|tech|product)\b", re.I), 3),
    (re.compile(r"\bvp.*(engineer|tech|product)\b|\bdirector.*(engineer|tech)\b", re.I), 4),
    (re.compile(r"\bcto\b|\bchief.tech", re.I), 5),
    (re.compile(r"\bcpo\b|\bchief.product", re.I), 6),
    (re.compile(r"\bceo\b|\bfounder\b|\bco-founder\b", re.I), 7),
]

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")


def _fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True)
        return resp.text if resp.status_code < 400 else None
    except Exception:
        return None


def _title_priority(title: str) -> int:
    """Return priority score for a job title string (lower = higher priority)."""
    for pattern, score in _TITLE_PRIORITY:
        if pattern.search(title):
            return score
    return 99


def _extract_contacts_from_html(html: str) -> list[dict]:
    """
    Parse HTML for (name, title, email) entries on team/leadership pages.
    Returns a list of dicts sorted by title priority.
    """
    soup = BeautifulSoup(html, "html.parser")
    found: list[dict] = []

    # Collect all visible emails from the page
    page_emails = _EMAIL_RE.findall(html)
    # Filter obvious no-reply/support addresses
    page_emails = [
        e for e in page_emails
        if not re.search(r"noreply|no-reply|support|info@|contact@|hello@|sales@", e, re.I)
    ]

    # Strategy 1: structured person cards (common on team/about pages)
    # Look for containers with both a heading (name) and a paragraph/span (title)
    for container in soup.find_all(["div", "article", "li", "section"], recursive=True):
        texts = [t.strip() for t in container.stripped_strings]
        if len(texts) < 2 or len(texts) > 15:
            continue

        name = None
        title = None

        for i, t in enumerate(texts):
            # A "name" is 2-4 words, mostly capitalized, no numbers
            if re.match(r"^[A-Z][a-z]+([ \-][A-Z][a-z]+){1,3}$", t) and not name:
                name = t
            # A "title" mentions a role keyword
            elif _title_priority(t) < 99 and not title:
                title = t

        if name and title:
            # Try to associate an email — look for one in this container's text
            container_text = container.get_text(" ")
            emails_here = _EMAIL_RE.findall(container_text)
            email = emails_here[0] if emails_here else None
            found.append({"name": name, "title": title, "email": email})

    # Strategy 2: scan all text blocks for "Name, Title" patterns
    full_text = soup.get_text(" ")
    for m in re.finditer(
        r"([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})[,\n\|•–-]+\s*([A-Za-z /&]{5,60})",
        full_text
    ):
        name_candidate = m.group(1).strip()
        title_candidate = m.group(2).strip()
        if _title_priority(title_candidate) < 99:
            found.append({"name": name_candidate, "title": title_candidate, "email": None})

    # Deduplicate by name, keep highest priority title
    seen: dict[str, dict] = {}
    for entry in found:
        n = entry["name"]
        if n not in seen or _title_priority(entry["title"]) < _title_priority(seen[n]["title"]):
            seen[n] = entry

    result = sorted(seen.values(), key=lambda x: _title_priority(x["title"]))

    # Attach a page email to any entry that didn't get one
    if page_emails and result:
        for entry in result:
            if not entry["email"]:
                entry["email"] = page_emails[0]
                break

    return result


def find_contact(base_url: str) -> dict | None:
    """
    Scrape company team/contact/leadership pages to find the best outreach contact.

    Returns the highest-priority person found:
      {"name": str, "title": str, "email": str|None, "source_url": str}
    or None if no relevant contact is found.
    """
    base = base_url.rstrip("/")
    best: dict | None = None
    best_priority = 99

    for path in _CONTACT_PATHS:
        url = base + path
        html = _fetch(url)
        if not html:
            continue

        contacts = _extract_contacts_from_html(html)
        if not contacts:
            continue

        top = contacts[0]
        p = _title_priority(top["title"])
        log.debug("Found %d contacts at %s — top: %s (%s, priority %d)",
                  len(contacts), url, top.get("name"), top.get("title"), p)

        if p < best_priority:
            best_priority = p
            best = {**top, "source_url": url}

        # Priority 1-2 (talent/HR) is ideal — stop early
        if best_priority <= 2:
            break

    if best:
        log.info("Contact found: %s — %s (from %s)", best.get("name"), best.get("title"), best.get("source_url"))
    else:
        log.info("No structured contact found — will address by title from role analysis.")

    return best
