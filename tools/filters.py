"""
Job-listing filters that work on text: requirements-section extraction, avoid
lists (skills / domains), and (company, title) de-duplication.
"""

from __future__ import annotations

import re

# ── Requirements section ─────────────────────────────────────────────────────
_REQ_WORDS = (r"requirements?|qualifications?|must[\s-]?haves?(?:\s+skills)?|"
              r"what\s+you(?:'|’)?ll\s+need|what\s+we(?:'|’)?re\s+looking\s+for|"
              r"required\s+(?:skills|qualifications|experience)|minimum\s+qualifications|"
              r"skills\s+required|key\s+skills|who\s+you\s+are|experience")
_NICE_WORDS = (r"nice[\s-]?to[\s-]?haves?|good[\s-]?to[\s-]?haves?|"
               r"preferred(?:\s+qualifications|\s+skills)?|bonus(?:\s+points)?|pluses|plus|"
               r"desirable|added\s+advantage|extra\s+credit")


def _head(words: str):
    # optional markdown, the heading words, optional ":", optional inline content on the same line
    return re.compile(r"^[#*_\s]*(?:" + words + r")[#*_\s]*(?::[#*_\s]*(?P<rest>.*?))?[#*_\s]*$", re.I)


_REQ = _head(_REQ_WORDS)
_NICE = _head(_NICE_WORDS)


def _classify(line: str):
    """(kind, inline_rest) for a heading line, else (None, "")."""
    s = line.strip()
    if not s or len(s) > 200:
        return None, ""
    for kind, rx in (("req", _REQ), ("nice", _NICE)):
        m = rx.match(s)
        if m:
            return kind, (m.group("rest") or "").strip()
    if len(s) <= 60 and (s.endswith(":") or (s.isupper() and " " in s and s[0].isalpha())):
        return "other", ""
    return None, ""


def extract_requirements_section(description: str) -> str:
    """
    Text under Requirements / Qualifications / Must have / ... headings (also
    "Qualifications: Python, SQL" on one line), with nice-to-have / preferred /
    bonus sections left out. "" if none is found.
    """
    mode, out = None, []
    for line in (description or "").splitlines():
        kind, rest = _classify(line)
        if kind:
            mode = kind
            if kind == "req" and rest:
                out.append(rest)
            continue
        if mode == "req" and line.strip():
            out.append(line.strip())
    return "\n".join(out)


def build_job_text(description: str, limit: int = 4000) -> str:
    """Requirements section first, then the description, ~`limit` chars total."""
    desc = description or ""
    req = extract_requirements_section(desc)[:1500]
    if not req:
        return desc[:limit]
    return f"[REQUIREMENTS SECTION]\n{req}\n\n[FULL DESCRIPTION]\n" + desc[: max(0, limit - len(req))]


# ── Term matching ────────────────────────────────────────────────────────────
def has_term(text: str, term: str) -> bool:
    """Case-insensitive whole-term match ('sap' is not in 'sapient'; '.net' is in 'ASP.NET')."""
    t = term.lower().strip()
    if not t:
        return False
    left = r"(?<![a-z0-9])" if t[0].isalnum() else ""
    right = r"(?![a-z0-9])" if t[-1].isalnum() else ""
    return re.search(left + re.escape(t) + right, (text or "").lower()) is not None


# ── Avoid list ───────────────────────────────────────────────────────────────
def filter_by_avoid(listings: list, terms: list[str]) -> tuple[list, int]:
    """
    Drop listings with an avoid term in the title, or in the requirements
    (must-have) section. Nice-to-have/bonus sections and the rest of the
    description are ignored. Returns (kept, dropped_count).
    """
    kept = []
    for l in listings:
        must = extract_requirements_section(getattr(l, "description", ""))
        title = getattr(l, "title", "")
        if any(has_term(title, t) or has_term(must, t) for t in terms):
            continue
        kept.append(l)
    return kept, len(listings) - len(kept)


# ── De-duplication ───────────────────────────────────────────────────────────
_CO_NOISE = {"pvt", "ltd", "inc", "llp", "private", "limited", "llc", "corp"}


def dedupe_key(company: str, title: str) -> tuple[str, str]:
    co = [w for w in re.sub(r"[^a-z0-9 ]", " ", (company or "").lower()).split() if w not in _CO_NOISE]
    return " ".join(co), " ".join(re.sub(r"[^a-z0-9 ]", " ", (title or "").lower()).split())


def dedupe_listings(listings: list, seen=()) -> tuple[list, int]:
    """
    One listing per normalized (company, title); the best-ranked location wins
    (Bengaluru first). Keys in `seen` (already shown in earlier digests) are
    skipped. Returns (kept, dropped_count).
    """
    from tools.location import location_rank
    seen_keys = {dedupe_key(c, t) for c, t in seen}
    best: dict = {}
    for l in listings:
        k = dedupe_key(l.company, l.title)
        if k in seen_keys:
            continue
        if k not in best or location_rank(l.location) < location_rank(best[k].location):
            best[k] = l
    kept = list(best.values())
    return kept, len(listings) - len(kept)
