"""
Shared retry helper for Gemini API calls.
Handles 503 UNAVAILABLE and 429 RESOURCE_EXHAUSTED with exponential backoff.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_ATTEMPTS = 4
_BASE_DELAY = 15   # seconds — longer base to respect per-minute rate limits
_MAX_DELAY = 90    # cap at 90s — no point waiting more than 1.5 min


def _parse_retry_delay(msg: str) -> float | None:
    """Extract retryDelay seconds from a Gemini error message if present."""
    # Matches: 'retryDelay': '27s' or retryDelay: 60s
    m = re.search(r"retryDelay['\"\s:]+(\d+(?:\.\d+)?)s", msg)
    if m:
        return min(float(m.group(1)) + 2, _MAX_DELAY)  # +2s buffer
    return None


def gemini_call(fn: Callable[[], T], label: str = "Gemini") -> T:
    """
    Call fn() with exponential backoff on transient Gemini API errors.

    Retries on: 503 UNAVAILABLE, 429 RESOURCE_EXHAUSTED.
    Respects the retryDelay hint from the API response when present.
    Raises immediately on any other error.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:
            msg = str(exc)
            is_transient = any(
                code in msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")
            )
            if not is_transient:
                raise

            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                # Use API's suggested retry delay if available, else exponential backoff
                suggested = _parse_retry_delay(msg)
                delay = suggested if suggested else min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
                log.warning(
                    "%s rate limit (attempt %d/%d) — retrying in %.0fs. %s",
                    label, attempt, _MAX_ATTEMPTS, delay, msg[:120],
                )
                time.sleep(delay)
            else:
                log.error(
                    "%s still unavailable after %d attempts. Giving up.",
                    label, _MAX_ATTEMPTS,
                )

    raise last_exc  # type: ignore[misc]
