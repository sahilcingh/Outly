"""
Company suggester: uses Gemini to suggest real companies that hire
candidates with specific skills. Much more reliable than scraping search results.
"""

from __future__ import annotations

import json
import logging
import re

from llm.groq_client import groq_json_call

log = logging.getLogger(__name__)

_SYSTEM = """You are a senior technical recruiter with deep knowledge of the tech industry.
Given a candidate's role and skills, suggest real companies that actively hire people with those skills.

Return a JSON array of exactly the number of companies requested. Each item:
{
  "name": "Exact company name (e.g. Razorpay, Flipkart, Stripe)",
  "reason": "One sentence: why this company hires this skill set"
}

Rules:
- Only suggest REAL, verifiable companies with an active website
- Prioritize companies known to use the candidate's specific tech stack
- Mix company sizes: 2-3 large tech companies, rest mid-size startups/scaleups
- If an industry is specified, focus on that industry
- If location/country context is available, prefer companies in that region
- Never suggest generic company names or fictional companies
- Do NOT suggest consulting firms or staffing agencies themselves"""


def suggest_companies(
    role_title: str,
    skills: list[str],
    industry: str | None = None,
    count: int = 10,
) -> list[dict]:
    """
    Ask Gemini to suggest companies that hire this candidate profile.
    Returns list of {"name": str, "reason": str}.
    """
    skills_str = ", ".join(skills[:8])
    industry_line = f"Industry focus: {industry}" if industry else "Industry: any tech company"

    prompt = f"""Candidate profile:
Role: {role_title}
Key skills: {skills_str}
{industry_line}

Suggest {count} real companies that would actively hire this candidate.
Return a JSON array of {count} objects with "name" and "reason" fields."""

    content = groq_json_call(_SYSTEM, prompt, label="company_suggester")
    return _parse(content, count) if content else []


def _parse(content: str, count: int) -> list[dict]:
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data[:count]
        # Sometimes Gemini wraps in {"companies": [...]}
        for v in data.values():
            if isinstance(v, list):
                return v[:count]
    except json.JSONDecodeError:
        pass
    # Fallback: find array in text
    match = re.search(r"\[[\s\S]*\]", content)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data[:count]
        except json.JSONDecodeError:
            pass
    return []
