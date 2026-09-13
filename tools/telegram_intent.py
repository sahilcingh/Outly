"""
Natural-language intent classifier for Telegram messages that don't match an
exact bot command — e.g. "search now please", "only show me jobs above 70",
"switch to remote only". Maps free text onto the same fixed action set the
exact commands already support; never invents a new capability beyond them.
"""

from __future__ import annotations

import json
import logging

from llm.groq_client import groq_json_call

log = logging.getLogger(__name__)

_ACTIONS = (
    "search", "status", "queue", "help",
    "set_location", "set_min_score", "set_remote",
    "unknown",
)

_SYSTEM = """You classify a Telegram message sent to a job-search bot into exactly
one supported action. Respond ONLY with valid JSON — no markdown, no extra text."""

_PROMPT = """
Message: "{text}"

Supported actions:
- "search": user wants a job search run right now
- "status": user wants a summary of job counts by status
- "queue": user wants the current job queue PDF re-sent
- "help": user wants the list of commands / what the bot can do
- "set_location": user wants to change the search location (extract "value": the location as a string, e.g. "Mumbai" or "Bengaluru, India")
- "set_min_score": user wants to change the minimum match score threshold (extract "value": an integer 0-100)
- "set_remote": user wants to turn remote-only search on or off (extract "value": true or false)
- "unknown": the message doesn't clearly map to any of the above (small talk, an unrelated question, or too ambiguous to act on)

Return exactly this JSON:
{{
  "action": "<one of the actions above>",
  "value": <string, integer, boolean, or null — only set when the action needs one, else null>
}}
"""


def classify_intent(text: str) -> dict:
    """
    Best-effort free-text -> fixed action classifier for the Telegram bot.
    Always returns {"action": ..., "value": ...}; falls back to "unknown" on
    any failure so the caller can fall back to the plain "didn't recognize" reply.
    """
    try:
        raw = groq_json_call(
            system=_SYSTEM,
            user=_PROMPT.format(text=(text or "")[:300]),
            label="telegram_intent",
            max_tokens=150,
        )
        result = json.loads(raw) if isinstance(raw, str) else raw
        action = result.get("action", "unknown")
        if action not in _ACTIONS:
            action = "unknown"
        return {"action": action, "value": result.get("value")}
    except Exception as e:
        log.warning("Telegram intent classification failed for %r: %s", text, e)
        return {"action": "unknown", "value": None}
