"""
Outreach sequencer: generates a short multi-touch outreach plan from a company profile.
"""

from __future__ import annotations

import json
import re
from typing import Any

from config import get_gemini_api_key, GEMINI_DEFAULT_MODEL
from target_context import TargetContext, resolve_target_context
from llm.retry import gemini_call

GEMINI_MODEL = GEMINI_DEFAULT_MODEL


def _escape_braces(s: str) -> str:
    return s.replace("{", "{{").replace("}", "}}")


def _sequencer_system_instruction(ctx: TargetContext) -> str:
    ind = _escape_braces(ctx.industry)
    job = _escape_braces(ctx.job_title)
    return f"""You write concise B2B outreach for a premier recruitment and staffing firm.

Your Agency's Core Offer: Providing the absolute perfect, highly-vetted candidates for specialized roles.

Target Prospect Context:
- Target Industry: {ind}
- Target Job Title: {job}

Given a structured company profile (JSON), generate a 3-touch EMAIL sequence addressed to the {job}, pitching your ability to recruit the perfect candidate for their current initiatives.

Rules:
- Max 90 words per email body.
- Write in the first person ("I"). You are pitching your recruiting services to them.
- Avoid generic phrases ("touching base", etc.).
- Return STRICT JSON only (no markdown) matching this schema:
{{
  "sequence_name": string,
  "touches": [
    {{"touch_index": 1, "channel": "email", "subject": string, "body": string, "rationale": string}},
    {{"touch_index": 2, "channel": "email", "subject": string, "body": string, "rationale": string}},
    {{"touch_index": 3, "channel": "email", "subject": string, "body": string, "rationale": string}}
  ]
}}
"""


def generate_email_sequence(
    company_profile: dict[str, Any],
    *,
    industry: str | None = None,
    job_title: str | None = None,
    context: TargetContext | None = None,
    model: str = GEMINI_MODEL,
) -> dict[str, Any] | None:
    ctx = context if context is not None else resolve_target_context(industry, job_title)
    api_key = get_gemini_api_key()

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig
    except ImportError:
        raise ImportError("Install google-genai: pip install google-genai")

    client = genai.Client(api_key=api_key)
    payload = json.dumps(company_profile, ensure_ascii=False)

    response = gemini_call(
        lambda: client.models.generate_content(
            model=model,
            contents=f"Company profile JSON:\n\n{payload}",
            config=GenerateContentConfig(
                system_instruction=_sequencer_system_instruction(ctx),
                response_mime_type="application/json",
            ),
        ),
        label="sequencer",
    )

    content = response.text
    return _parse_json_response(content) if content else None


def _parse_json_response(content: str) -> dict[str, Any] | None:
    try:
        out = json.loads(content)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if match:
        try:
            out = json.loads(match.group(1).strip())
            return out if isinstance(out, dict) else None
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            out = json.loads(match.group(0))
            return out if isinstance(out, dict) else None
        except json.JSONDecodeError:
            pass

    return None
