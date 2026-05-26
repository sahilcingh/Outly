"""
Shared retry helper for Gemini API calls.
Handles 503 UNAVAILABLE and 429 RESOURCE_EXHAUSTED with exponential backoff.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_ATTEMPTS = 4
_BASE_DELAY = 3  # seconds — doubles each retry: 3s, 6s, 12s


def gemini_call(fn: Callable[[], T], label: str = "Gemini") -> T:
    """
    Call fn() with exponential backoff on transient Gemini API errors.

    Retries on: 503 UNAVAILABLE, 429 RESOURCE_EXHAUSTED.
    Raises immediately on any other error.

    Args:
        fn: Zero-argument callable that performs the Gemini API call.
        label: Human-readable name shown in log messages.

    Returns:
        Whatever fn() returns on success.

    Raises:
        The last exception if all attempts are exhausted.
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
                delay = _BASE_DELAY * (2 ** (attempt - 1))
                log.warning(
                    "%s transient error (attempt %d/%d) — retrying in %ds. %s",
                    label, attempt, _MAX_ATTEMPTS, delay, msg[:80],
                )
                time.sleep(delay)
            else:
                log.error(
                    "%s still unavailable after %d attempts. Giving up.",
                    label, _MAX_ATTEMPTS,
                )

    raise last_exc  # type: ignore[misc]
