"""
Skills extractor: reads a candidate's resume text and returns structured profile
including name, current title, target roles, key skills, experience, and industry fit.
"""

from __future__ import annotations

import json
import logging
import re

from llm.groq_client import groq_json_call

log = logging.getLogger(__name__)

MAX_SKILLS = 25

_SYSTEM = """You are a senior technical recruiter. Read this candidate's resume or profile and extract structured information.

Return STRICT JSON only:
{
  "candidate_name": "The candidate's full name exactly as written at the top of the resume, or \\"\\" if there is none",
  "current_title": "The candidate's most recent job title EXACTLY as written in the resume (e.g. 'Full Stack Intern'). Do not upgrade or reword it. \\"\\" if none",
  "target_roles": ["2-3 realistic, hirable roles to search for, suited to the candidate's level (e.g. 'Full Stack Developer', 'Backend Developer')"],
  "skills": ["up to 25 technical skills (languages, frameworks, tools, platforms) taken from the resume, in the order they appear in the resume's skills section (strongest first)"],
  "experience_years": 1.5,
  "industries": ["industries this candidate has worked in or is best suited for, e.g. 'Fintech', 'SaaS', 'E-commerce'"],
  "search_queries": [
    "3-5 DuckDuckGo search queries — these MUST be job listing queries that job boards like LinkedIn/Indeed would index, so company names appear in result titles. Format: '<RoleTitle> jobs <location>' or '<Skill1> <Skill2> engineer jobs'. Examples: 'Java Spring Boot engineer jobs India', 'Python backend developer fintech jobs', 'React TypeScript frontend developer jobs 2024'"
  ],
  "summary": "One sentence: what makes this candidate uniquely valuable to a hiring company"
}

Rules:
- skills must be specific technologies that literally appear in the resume, not soft skills; never add one that is not there
- experience_years is a decimal number. If the resume states an explicit figure (e.g. "1.5 years of experience") use exactly that. Otherwise add up internships, freelance and full-time work realistically from their dates; do NOT round up (1.5 stays 1.5, not 2). Use 0 for a fresher with no work history
- search_queries must be realistic DuckDuckGo queries that would surface actual job postings or company pages
- target_roles must be real, hirable job titles"""


def extract_skills(resume_text: str) -> dict | None:
    """
    Analyze resume text and return structured candidate profile.
    Returns dict with candidate_name, current_title, target_roles, role_title,
    skills, experience_years, industries, search_queries, summary and the raw
    resume_text (single source of truth for cover letters) — or None on failure.
    """
    text = resume_text[:20000] if len(resume_text) > 20000 else resume_text
    content = groq_json_call(_SYSTEM, f"Candidate resume:\n\n{text}", label="skills_extractor")
    parsed = _parse(content) if content else None
    return normalize_profile(parsed, resume_text) if parsed else None


def normalize_profile(raw: dict, resume_text: str) -> dict:
    """Coerce the model's JSON into the profile shape the rest of the app expects."""
    name = str(raw.get("candidate_name") or "").strip()
    if name.lower() == "candidate":
        name = ""
    current_title = str(raw.get("current_title") or raw.get("role_title") or "").strip()
    roles = [str(r).strip() for r in (raw.get("target_roles") or []) if str(r).strip()][:3]
    if not roles and current_title:
        roles = [current_title]

    try:
        years = round(max(0.0, min(50.0, float(raw.get("experience_years")))), 1)
    except (TypeError, ValueError):
        years = None

    skills, seen = [], set()
    for s in raw.get("skills") or []:
        s = str(s).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            skills.append(s)

    profile = dict(raw)
    profile.update(
        candidate_name=name,
        current_title=current_title,
        target_roles=roles,
        # role_title = the search role (kept for existing callers); cover letters use current_title
        role_title=roles[0] if roles else (current_title or "Software Engineer"),
        skills=skills[:MAX_SKILLS],
        experience_years=years,
        resume_text=resume_text,
    )
    return profile


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
