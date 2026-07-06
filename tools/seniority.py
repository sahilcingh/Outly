"""
Seniority matching — keep job listings at or near the candidate's level.

Infers a job's seniority from its title and filters out roles above the
candidate's ceiling, so an entry/fresher candidate isn't shown Senior/Staff/
Lead/Principal/Manager positions.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Ordered low → high. Index is the rank.
LEVELS = ["entry", "junior", "mid", "senior", "lead", "staff", "principal", "director", "exec"]
_RANK = {name: i for i, name in enumerate(LEVELS)}

# Title patterns, checked most-senior first. Word boundaries avoid false hits
# (e.g. "ii" inside a word). First match wins.
_PATTERNS = [
    ("exec",      r"\b(chief|c[te]o|cxo|svp|evp|vp|vice\s*president)\b"),
    ("director",  r"\b(director|head\s+of)\b"),
    ("principal", r"\bprincipal\b"),
    ("staff",     r"\bstaff\b"),
    ("lead",      r"\b(lead|architect|engineering\s+manager|\bmanager)\b"),
    ("senior",    r"\b(senior|sr\.?|snr|iii)\b"),
    ("mid",       r"\b(mid|ii|sde[-\s]?2|l2|level\s*2)\b"),
    ("junior",    r"\b(junior|jr\.?|associate|sde[-\s]?1|level\s*1)\b"),
    ("entry",     r"\b(intern|internship|trainee|graduate|grad|entry|fresher|apprentice)\b"),
]


def level_from_years(years) -> str:
    """Map years of experience to a candidate level."""
    try:
        y = float(years)
    except (TypeError, ValueError):
        return "entry"
    if y <= 1:
        return "entry"
    if y <= 3:
        return "junior"
    if y <= 5:
        return "mid"
    return "senior"


def infer_job_level(title: str) -> str | None:
    """Infer a job's seniority from its title. None = no explicit marker."""
    t = (title or "").lower()
    for level, pattern in _PATTERNS:
        if re.search(pattern, t):
            return level
    return None


def _ceiling(candidate_level: str, strict: bool) -> int:
    """Highest job rank the candidate should see."""
    cand = _RANK.get(candidate_level, 0)
    if strict:
        # Entry may still apply to junior; otherwise cap at own level.
        return cand + 1 if cand == 0 else cand
    # Balanced: allow one level up.
    return cand + 1


def job_allowed(title: str, candidate_level: str, strict: bool = True) -> bool:
    """
    True if the job's title is at/below the candidate's ceiling.
    Unmarked titles (plain 'Software Engineer') are kept — they're often open
    to juniors and the scorer weighs them anyway.
    """
    job_level = infer_job_level(title)
    if job_level is None:
        return True
    return _RANK[job_level] <= _ceiling(candidate_level, strict)


def filter_by_level(listings: list, candidate_level: str, strict: bool = True) -> tuple[list, int]:
    """
    Filter a list of objects with a `.title` attribute by seniority.
    Returns (kept, dropped_count).
    """
    kept = [l for l in listings if job_allowed(getattr(l, "title", ""), candidate_level, strict)]
    return kept, len(listings) - len(kept)


def search_query_for_level(base_query: str, candidate_level: str) -> str:
    """Bias the job-board search toward the right seniority."""
    prefix = {"entry": "entry level", "junior": "junior"}.get(candidate_level)
    if prefix and prefix not in base_query.lower():
        return f"{prefix} {base_query}"
    return base_query
