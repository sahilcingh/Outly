"""
Skills extractor: reads a candidate's resume text and returns structured profile
including role title, key skills, experience, and industry fit.
"""

from __future__ import annotations

import json
import logging
import re

from config import get_gemini_api_key
from llm.retry import gemini_call

log = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"

_SYSTEM = """You are a senior technical recruiter. Read this candidate's resume or profile and extract structured information.

Return STRICT JSON only:
{
  "role_title": "Most accurate job title for this candidate (e.g. 'Senior Backend Engineer', 'ML Infrastructure Lead', 'Full-Stack Developer')",
  "skills": ["top 6-10 technical skills from the resume — languages, frameworks, tools, platforms"],
  "experience_years": 3,
  "industries": ["industries this candidate has worked in or is best suited for, e.g. 'Fintech', 'SaaS', 'E-commerce'"],
  "search_queries": [
    "3-5 DuckDuckGo search queries to find companies that would hire this candidate",
    "e.g. 'fintech startups hiring Python FastAPI engineers India'",
    "e.g. 'machine learning companies using PyTorch hiring 2024'",
    "e.g. 'B2B SaaS companies using React Node.js'"
  ],
  "summary": "One sentence: what makes this candidate uniquely valuable to a hiring company"
}

Rules:
- skills must be specific technologies, not soft skills
- search_queries must be realistic DuckDuckGo queries that would surface actual job postings or company pages
- role_title must be a real, hirable job title"""


def extract_skills(resume_text: str) -> dict | None:
    """
    Analyze resume text and return structured candidate profile.
    Returns dict with role_title, skills, experience_years, industries,
    search_queries, summary — or None on failure.
    """
    api_key = get_gemini_api_key()
    try:
        from google import genai
        from google.genai.types import GenerateContentConfig
    except ImportError:
        raise ImportError("Install google-genai: pip install google-genai")

    text = resume_text[:20000] if len(resume_text) > 20000 else resume_text
    client = genai.Client(api_key=api_key)

    response = gemini_call(
        lambda: client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"Candidate resume:\n\n{text}",
            config=GenerateContentConfig(
                system_instruction=_SYSTEM,
                response_mime_type="application/json",
            ),
        ),
        label="skills_extractor",
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
