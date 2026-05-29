"""
Skills extractor: reads a candidate's resume text and returns structured profile
including role title, key skills, experience, and industry fit.
"""

from __future__ import annotations

import json
import logging
import re

from llm.groq_client import groq_json_call

log = logging.getLogger(__name__)

_SYSTEM = """You are a senior technical recruiter. Read this candidate's resume or profile and extract structured information.

Return STRICT JSON only:
{
  "role_title": "Most accurate job title for this candidate (e.g. 'Senior Backend Engineer', 'ML Infrastructure Lead', 'Full-Stack Developer')",
  "skills": ["top 6-10 technical skills from the resume — languages, frameworks, tools, platforms"],
  "experience_years": 3,
  "industries": ["industries this candidate has worked in or is best suited for, e.g. 'Fintech', 'SaaS', 'E-commerce'"],
  "search_queries": [
    "3-5 DuckDuckGo search queries — these MUST be job listing queries that job boards like LinkedIn/Indeed would index, so company names appear in result titles. Format: '<RoleTitle> jobs <location>' or '<Skill1> <Skill2> engineer jobs'. Examples: 'Java Spring Boot engineer jobs India', 'Python backend developer fintech jobs', 'React TypeScript frontend developer jobs 2024'"
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
    text = resume_text[:20000] if len(resume_text) > 20000 else resume_text
    content = groq_json_call(_SYSTEM, f"Candidate resume:\n\n{text}", label="skills_extractor")
    return _parse(content) if content else None


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
