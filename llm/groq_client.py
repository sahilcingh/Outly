"""
Shared Groq API client for all LLM calls.
Groq free tier: 14,400 req/day, 30 RPM.

A process-wide throttle enforces a minimum interval between request *starts*
so parallel callers (job scoring, cover letters, etc.) never blow past 30 RPM.
This is the single choke point for all Groq traffic in the app.
"""

from __future__ import annotations

import logging
import threading
import time

from config import get_groq_api_key, GROQ_DEFAULT_MODEL

log = logging.getLogger(__name__)

# ── Retry policy (our own loop; the SDK's internal retries are disabled below) ──
_MAX_ATTEMPTS = 5
_BASE_DELAY = 8
_MAX_DELAY = 60

# ── Global rate limiter ────────────────────────────────────────────────────────
# 30 RPM = 1 request / 2s. Use 2.3s to leave headroom for clock skew + bursts.
_MIN_INTERVAL = 2.3
_rate_lock = threading.Lock()
_last_call_ts = 0.0

# ── Reused client (creating a Groq() per call is wasteful) ─────────────────────
_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from groq import Groq
                # max_retries=0: we own the retry loop below. The SDK's built-in
                # retries were stacking on top of ours and multiplying backoff.
                _client = Groq(api_key=get_groq_api_key(), max_retries=0)
    return _client


def _throttle() -> None:
    """Block until at least _MIN_INTERVAL has elapsed since the last request start."""
    global _last_call_ts
    with _rate_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.monotonic()


def groq_json_call(
    system: str,
    user: str,
    model: str = GROQ_DEFAULT_MODEL,
    label: str = "Groq",
    max_tokens: int = 2048,
) -> str | None:
    """
    Make a Groq API call expecting JSON output.
    Globally throttled to stay under 30 RPM; retries on rate-limit errors.
    Returns the raw JSON string (callers parse it) or raises on hard failure.
    """
    try:
        from groq import Groq  # noqa: F401  (import guard for a clear error msg)
    except ImportError:
        raise ImportError("Install groq: pip install groq")

    client = _get_client()

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        _throttle()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as exc:
            msg = str(exc)
            is_rate_limit = any(k in msg for k in ("429", "rate_limit", "Rate limit", "quota"))
            if not is_rate_limit:
                raise
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
                log.warning("%s rate limit (attempt %d/%d) — retrying in %ds",
                            label, attempt, _MAX_ATTEMPTS, delay)
                time.sleep(delay)
            else:
                log.error("%s still rate limited after %d attempts.", label, _MAX_ATTEMPTS)

    raise last_exc  # type: ignore[misc]
