"""
ATS boards: turn a posting URL into (platform, board) and read that board's
public JSON feed of open roles. Ported in spirit from freehire (MIT):
URL-only board recognition, and the "ats_absent" ghost-job signal: a listing
whose title is not on the employer's own board is likely stale or reposted.
Fail-safe throughout: an unknown URL or unreadable board is never evidence.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import requests

log = logging.getLogger(__name__)

_TIMEOUT = 6

_HOSTS = {
    "boards.greenhouse.io":     "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co":            "lever",
    "jobs.ashbyhq.com":         "ashby",
    "apply.workable.com":       "workable",
}
# Platform path words that are never a tenant (e.g. greenhouse embed/, workable j/<id>).
_RESERVED = {"embed", "j", "api", "v1"}

# platform -> (feed url, key holding the job list or None, title field, url field)
_FEEDS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{}/jobs", "jobs", "title", "absolute_url"),
    "lever":      ("https://api.lever.co/v0/postings/{}?mode=json",      None,   "text",  "hostedUrl"),
    "ashby":      ("https://api.ashbyhq.com/posting-api/job-board/{}",   "jobs", "title", "jobUrl"),
    "workable":   ("https://apply.workable.com/api/v1/widget/accounts/{}", "jobs", "title", "url"),
}


def parse_board(url: str | None) -> tuple[str, str] | None:
    """(platform, board) for a known ATS posting/board URL, else None. No network."""
    u = urlparse(url or "")
    platform = _HOSTS.get(u.netloc.lower())
    if not platform:
        return None
    # Greenhouse embeds carry the board in ?for=<board>
    board = parse_qs(u.query).get("for", [""])[0] or u.path.strip("/").split("/")[0]
    if not board or board in _RESERVED:
        return None
    return platform, board


def board_jobs(platform: str, board: str) -> list[dict] | None:
    """Open roles on a board as [{"title", "url"}], or None if the feed can't be read."""
    feed, key, title_f, url_f = _FEEDS[platform]
    try:
        r = requests.get(feed.format(board), timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        jobs = data[key] if key else data
        return [{"title": j[title_f], "url": j.get(url_f) or ""} for j in jobs if j.get(title_f)]
    except Exception as e:
        log.debug("ATS feed %s/%s unreadable: %s", platform, board, e)
        return None


def _norm(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def filter_ghost_jobs(listings: list) -> tuple[list, int]:
    """Drop listings whose title is absent from their employer's live ATS board."""
    boards = {b for l in listings if (b := parse_board(l.ats_url))}
    if not boards:
        return listings, 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        live = dict(zip(boards, ex.map(lambda b: board_jobs(*b), boards)))

    def on_board(l) -> bool:
        jobs = live.get(parse_board(l.ats_url))
        if not jobs:  # not an ATS link, board unreadable or empty: no evidence, keep
            return True
        t = _norm(l.title)
        return any(t in n or n in t for n in (_norm(j["title"]) for j in jobs))

    kept = [l for l in listings if on_board(l)]
    return kept, len(listings) - len(kept)
