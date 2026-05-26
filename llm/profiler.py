"""
Company profiler: turns scraped company text into a structured profile JSON.
"""

from __future__ import annotations

import json
import re
from typing import Any

from config import get_gemini_api_key
from target_context import TargetContext, resolve_target_context
from llm.retry import gemini_call

GEMINI_MODEL = "gemini-2.5-flash"


def _escape_braces(s: str) -> str:
    return s.replace("{", "{{").replace("}", "}}")


def _profiler_system_instruction(ctx: TargetContext) -> str:
    ind = _escape_braces(ctx.industry)
    job = _escape_braces(ctx.job_title)
    return f"""You are a prospecting research assistant.

Caller-provided framing (use only to prioritize what to extract and how to label relevance; do not invent facts not in the website text):
- Industry / market lens: {ind}
- Target recipient job title (for downstream outreach): {job}

Given raw website text about a company, produce a structured profile useful for outreach.

Rules:
- Only use information supported by the provided text. If unknown, set null or [].
- The JSON field "industry" must describe the company as implied by the website text, not merely repeat the caller's lens unless the text supports it.
- Be concise. No buzzwords.
- Return STRICT JSON only (no markdown) matching this schema:
{{
  "one_liner": string|null,
  "product": string|null,
  "industry": string|null,
  "target_customers": [string],
  "positioning": [string],
  "signals": [string],
  "likely_pain_points": [string],
  "hooks": [string],
  "disallowed_claims": [string]
}}
"""


def build_company_profile(
    company_text: str,
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

    text = company_text[:32000] if len(company_text) > 32000 else company_text

    client = genai.Client(api_key=api_key)
    response = gemini_call(
        lambda: client.models.generate_content(
            model=model,
            contents=f"Website text:\n\n{text}",
            config=GenerateContentConfig(
                system_instruction=_profiler_system_instruction(ctx),
                response_mime_type="application/json",
            ),
        ),
        label="profiler",
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

