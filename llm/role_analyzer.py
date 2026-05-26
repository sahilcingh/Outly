"""
Role analyzer: reads scraped company text and infers
(a) the most valuable candidate role the agency should offer, and
(b) the right person title to contact at the company.
"""

from __future__ import annotations

import json
import re

from config import get_gemini_api_key
from llm.retry import gemini_call

GEMINI_MODEL = "gemini-2.5-flash"

_SYSTEM = """You are a senior recruiter at a specialist staffing agency.
Read the company website text carefully.

Return a JSON object with exactly these fields:
{
  "role_to_offer": "Specific job title of the candidate you would place at this company (e.g. 'Senior Payments Backend Engineer', 'ML Infrastructure Lead', 'DevOps / Platform Engineer'). Must reflect the company's actual technology and current initiatives — not generic.",
  "skills": ["top 3-5 skills this candidate must have, taken from the company's tech stack or product mentions"],
  "contact_title": "Title of the person at this company most likely to be the hiring decision-maker or recruiter (e.g. 'Head of Talent Acquisition', 'VP Engineering', 'CTO', 'HR Manager'). Pick the most specific title the website text supports.",
  "offer_rationale": "One sentence: why this specific role helps this company right now, grounded in something from the text."
}

Rules:
- role_to_offer must be a real, specific job title — not a department or vague description.
- Base everything on what you actually read in the text. Do not invent technologies not mentioned.
- Return strict JSON only."""


def infer_role_and_contact(
    company_text: str,
    model: str = GEMINI_MODEL,
) -> dict | None:
    """
    Analyze scraped company text and return:
      - role_to_offer: specific candidate title to pitch
      - skills: key skills for that role
      - contact_title: who at the company to reach
      - offer_rationale: why this role fits right now

    Returns None on failure.
    """
    api_key = get_gemini_api_key()

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig
    except ImportError:
        raise ImportError("Install google-genai: pip install google-genai")

    text = company_text[:16000] if len(company_text) > 16000 else company_text
    client = genai.Client(api_key=api_key)

    response = gemini_call(
        lambda: client.models.generate_content(
            model=model,
            contents=f"Company website text:\n\n{text}",
            config=GenerateContentConfig(
                system_instruction=_SYSTEM,
                response_mime_type="application/json",
            ),
        ),
        label="role_analyzer",
    )

    return _parse(response.text) if response.text else None


def _parse(content: str) -> dict | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None
