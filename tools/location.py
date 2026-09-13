"""
Location filtering — keep jobs in India, prefer Bengaluru.

Job boards return a free-text location per listing (e.g. "Bengaluru,
Karnataka, India", "Remote", "New York, United States"). We keep India
locations, drop clearly-foreign ones, and rank Bengaluru first.
"""

from __future__ import annotations

import re

# Major Indian cities/regions (lowercase). Bengaluru handled separately.
_INDIA_CITIES = [
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "new delhi", "ncr",
    "hyderabad", "pune", "chennai", "kolkata", "gurgaon", "gurugram", "noida",
    "ahmedabad", "jaipur", "indore", "kochi", "coimbatore", "chandigarh",
    "trivandrum", "thiruvananthapuram", "mysore", "mysuru", "nagpur", "surat",
    "vadodara", "bhubaneswar", "visakhapatnam", "karnataka", "maharashtra",
    "telangana", "tamil nadu", "kerala", "gujarat", "haryana", "uttar pradesh",
]

_BENGALURU = ("bengaluru", "bangalore", "bangaluru")

# Foreign markers — if present, drop even if "remote" appears.
_FOREIGN = [
    "united states", "u.s.", "usa", " us", "united kingdom", " uk", "canada",
    "australia", "germany", "singapore", "dubai", "uae", "netherlands", "ireland",
    "france", "spain", "poland", "philippines", "malaysia", "indonesia", "vietnam",
    "europe", "emea", "americas", "latam", "brazil", "mexico", "japan", "china",
]

_US_STATES = [
    "california", "texas", "washington", "massachusetts", "florida",
    "illinois", "colorado", "arizona", "oregon",
]


def is_bengaluru(location: str) -> bool:
    loc = (location or "").lower()
    return any(c in loc for c in _BENGALURU)


def _has_india_signal(loc: str) -> bool:
    if any(c in loc for c in _INDIA_CITIES):
        return True
    # Indeed commonly returns "<state abbrev>, IN" (2-letter country code),
    # e.g. "TN, IN", "UL, IN" — no city/state name we'd otherwise recognize.
    return bool(re.search(r",\s*in$", loc)) or loc == "in"


def is_india_job(location: str, is_remote: bool = False) -> bool:
    """
    True if the listing should be kept for an India-only search.
    India signals win first (so 'Mumbai, Maharashtra, India' is never mistaken
    for a US state); then explicit foreign locations are dropped.

    India-only means India — a remote role isn't kept just because it's
    remote; "Remote" with no country marker is ambiguous (often a foreign
    team) and is dropped rather than assumed to be India-based.
    `is_remote` is accepted for API-compatibility with callers that also use
    it for other things (e.g. location_rank), but no longer grants a pass.
    """
    loc = (location or "").lower().strip()

    # India city/region → keep (takes precedence over ambiguous tokens)
    if _has_india_signal(loc):
        return True

    # Explicit foreign country / US state → drop
    if any(f in loc for f in _FOREIGN) or any(s in loc for s in _US_STATES):
        return False

    # Everything else (including bare "Remote"/"Anywhere"/blank with no
    # country marker) → drop to stay strictly India.
    return False


def location_rank(location: str) -> int:
    """0 = Bengaluru (best), 1 = other India, 2 = remote/unknown."""
    if is_bengaluru(location):
        return 0
    loc = (location or "").lower()
    if any(c in loc for c in _INDIA_CITIES):
        return 1
    return 2
