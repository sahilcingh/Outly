"""
Experience-requirement matching — parse the minimum years of experience a
job description asks for, and drop listings that ask for more than the
candidate has.

Complements tools.seniority (title-based level filter): a listing titled
plain "Software Engineer" passes the title filter for anyone, but its
description can still say "5+ years required" — this catches that case.
"""

from __future__ import annotations

import re

# Checked most-specific first. Word "years"/"yrs" required so plain numbers
# elsewhere in the description (salary, phone numbers) aren't misread.
_RANGE    = re.compile(r"(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.I)
_PLUS     = re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs?)\b", re.I)
_AT_LEAST = re.compile(r"(?:minimum|min\.?|at\s*least)\s*(?:of\s*)?(\d{1,2})\s*(?:years?|yrs?)\b", re.I)
_PLAIN    = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s*(?:of\s*)?experience\b", re.I)


def extract_min_experience(description: str) -> int | None:
    """
    Best-effort extraction of the minimum years of experience a job
    description asks for. Returns None when no explicit requirement is
    found — ambiguous, so the caller should keep the listing rather than
    guess (the title-based seniority filter and LLM scorer still apply).
    """
    text = description or ""
    for pattern in (_RANGE, _PLUS, _AT_LEAST, _PLAIN):
        m = pattern.search(text)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                continue
    return None


def filter_by_experience(listings: list, candidate_years) -> tuple[list, int]:
    """
    Drop listings whose description states a minimum experience requirement
    the candidate doesn't meet. Listings with no explicit requirement are
    kept as-is. Returns (kept, dropped_count).
    """
    try:
        years = float(candidate_years)
    except (TypeError, ValueError):
        return listings, 0

    kept = []
    for l in listings:
        required = extract_min_experience(getattr(l, "description", ""))
        if required is not None and years < required:
            continue
        kept.append(l)
    return kept, len(listings) - len(kept)
