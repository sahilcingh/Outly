"""
Generate a tailored cover letter for a specific job application.
Sounds like a real human application — not a recruitment consultant pitch.
"""

from __future__ import annotations

import logging

from llm.groq_client import groq_json_call

log = logging.getLogger(__name__)

_SYSTEM = """You are helping a job seeker write a professional, personalized cover letter.
The letter must sound genuine and human — not templated.
Respond ONLY with valid JSON — no markdown, no extra text."""

_PROMPT = """
CANDIDATE:
Name: {candidate_name}
Role applying for: {job_title}
Their background: {role_title} with {years_exp} years experience
Key skills: {skills}
Summary: {summary}

JOB:
Title: {job_title}
Company: {company}
Location: {location}
Key requirements from description:
{requirements}

Write a cover letter in four paragraphs:
1. OPENING (2 sentences): Express genuine interest in the specific role and company. Mention one specific thing about the company that attracted the candidate (infer from context).
2. RELEVANT EXPERIENCE (3 sentences): Describe the candidate's most relevant experience and 2-3 specific skills or achievements that directly answer the job requirements.
3. WHY THIS COMPANY (2 sentences): Explain why this specific company and role is a strong fit for where the candidate wants to grow — make it feel personal, not generic.
4. CLOSING (1-2 sentences): Professional CTA — express enthusiasm for a conversation, note availability.

Rules:
- First person ("I have...", "My experience...")
- Opening: "Dear Hiring Manager," (no specific name unless one is obvious)
- Sign off: "Best regards,\n{candidate_name}"
- Tone: Confident but not arrogant. Professional but warm. 300-380 words total.
- DO NOT use phrases like "I am writing to apply" — start with something more direct.
- DO NOT mention salary, references, or attachments.

Return exactly this JSON:
{{
  "cover_letter": "<the full cover letter as a single string with \\n for line breaks>",
  "subject_line": "<email subject line: 'Application for [Job Title] — [Candidate Name]'>"
}}
"""


def generate_cover_letter(
    job_title: str,
    company: str,
    location: str,
    description: str,
    candidate_profile: dict,
    candidate_name: str = "",
    revision_feedback: str = "",
) -> dict:
    """
    Generate a tailored cover letter.
    Returns {"cover_letter": str, "subject_line": str}
    """
    skills = candidate_profile.get("skills", [])
    summary = (candidate_profile.get("summary", "") or "")[:500]
    role_title = candidate_profile.get("role_title", "Software Engineer")

    # Extract key requirements from description (first 1500 chars)
    desc_snippet = (description or "")[:1500]

    name = candidate_name or "Candidate"

    prompt = _PROMPT.format(
        candidate_name = name,
        job_title      = job_title,
        company        = company,
        location       = location,
        role_title     = role_title,
        years_exp      = candidate_profile.get("years_experience", "several"),
        skills         = ", ".join(skills[:15]),
        summary        = summary,
        requirements   = desc_snippet,
    )
    if revision_feedback:
        prompt += f"\n\nPREVIOUS VERSION WAS REJECTED. User's requested changes:\n{revision_feedback}\nIncorporate these changes into the new version."

    try:
        import json as _json
        raw = groq_json_call(system=_SYSTEM, user=prompt)
        result = _json.loads(raw) if isinstance(raw, str) else raw
        return {
            "cover_letter": str(result.get("cover_letter", "")).strip(),
            "subject_line": str(result.get("subject_line", f"Application for {job_title} — {name}")).strip(),
        }
    except Exception as e:
        log.warning("Cover letter generation failed for '%s' at '%s': %s", job_title, company, e)
        return {
            "cover_letter": f"Dear Hiring Manager,\n\nI am interested in the {job_title} role at {company}. Please find my application attached.\n\nBest regards,\n{name}",
            "subject_line": f"Application for {job_title} — {name}",
        }
