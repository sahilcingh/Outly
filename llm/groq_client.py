"""
Shared Groq API client for all LLM calls.
Groq free tier: 14,400 req/day, 30 RPM — much more generous than Gemini free tier.
"""

from __future__ import annotations

import logging
import time

from config import get_groq_api_key, GROQ_DEFAULT_MODEL

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 4
_BASE_DELAY = 15
_MAX_DELAY = 90


def groq_json_call(
    system: str,
    user: str,
    model: str = GROQ_DEFAULT_MODEL,
    label: str = "Groq",
    max_tokens: int = 2048,
) -> str | None:
    """
    Make a Groq API call expecting JSON output.
    Retries on rate limit errors with exponential backoff.
    Returns response text or None on failure.
    """
    try:
        from groq import Groq
    except ImportError:
        raise ImportError("Install groq: pip install groq")

    api_key = get_groq_api_key()
    client = Groq(api_key=api_key)

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
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
                log.warning("%s rate limit (attempt %d/%d) — retrying in %ds", label, attempt, _MAX_ATTEMPTS, delay)
                time.sleep(delay)
            else:
                log.error("%s still rate limited after %d attempts.", label, _MAX_ATTEMPTS)

    raise last_exc  # type: ignore[misc]
