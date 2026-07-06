"""
Score a job listing against a candidate's resume profile.
Returns a 0-100 match score and a short rationale.
"""

from __future__ import annotations

import concurrent.futures
import logging

from llm.groq_client import groq_json_call

log = logging.getLogger(__name__)

_SYSTEM = """You are an expert technical recruiter scoring how well a job listing matches a candidate's profile.
Respond ONLY with valid JSON — no markdown, no extra text."""

_PROMPT = """
CANDIDATE PROFILE:
Role title: {role_title}
Skills: {skills}
Industries: {industries}
Summary: {summary}

JOB LISTING:
Title: {job_title}
Company: {company}
Location: {location}
Description (first 1200 chars):
{description}

Score this match from 0 to 100:
- 80-100: Strong match — role title aligns well, majority of required skills present
- 60-79: Good match — role fits, some skill gaps but candidate can grow into them
- 40-59: Partial match — adjacent role or partial skill overlap
- 0-39: Poor match — different domain or major requirement gaps

Return exactly this JSON:
{{
  "score": <integer 0-100>,
  "rationale": "<2-3 sentences explaining the score>",
  "key_matches": ["<skill or requirement that aligns>", ...],
  "gaps": ["<important requirement candidate lacks>", ...]
}}
"""


def score_job(
    job_title: str,
    company: str,
    location: str,
    description: str,
    candidate_profile: dict,
) -> dict:
    """
    Score a single job against the candidate profile.
    Returns {"score": int, "rationale": str, "key_matches": list, "gaps": list}
    or a safe default on failure.
    """
    prompt = _PROMPT.format(
        role_title   = candidate_profile.get("role_title", "Software Engineer"),
        skills       = ", ".join(candidate_profile.get("skills", [])[:20]),
        industries   = ", ".join(candidate_profile.get("industries", [])[:5]),
        summary      = (candidate_profile.get("summary", "") or "")[:400],
        job_title    = job_title,
        company      = company,
        location     = location,
        description  = (description or "")[:1200],
    )
    try:
        import json as _json
        raw = groq_json_call(system=_SYSTEM, user=prompt)
        result = _json.loads(raw) if isinstance(raw, str) else raw
        score = int(result.get("score", 0))
        return {
            "score":       max(0, min(100, score)),
            "rationale":   str(result.get("rationale", ""))[:500],
            "key_matches": result.get("key_matches", [])[:6],
            "gaps":        result.get("gaps", [])[:4],
        }
    except Exception as e:
        log.warning("Job scoring failed for '%s' at '%s': %s", job_title, company, e)
        return {"score": 0, "rationale": "Scoring failed.", "key_matches": [], "gaps": []}


def score_jobs_parallel(
    jobs: list[dict],
    candidate_profile: dict,
    max_workers: int = 4,
    max_to_score: int = 20,
) -> list[dict]:
    """
    Score job dicts against the candidate profile.

    Rate limiting is handled globally in groq_client (30 RPM throttle), so
    workers here just overlap network latency — the throttle serializes starts.

    - Jobs with no usable description are skipped (LinkedIn omits many): score 0.
    - Only the first `max_to_score` scoreable jobs hit the LLM; the rest are
      returned unscored so a single search doesn't burn minutes or daily quota.
    """
    scoreable = [j for j in jobs if len((j.get("description") or "").strip()) > 100]
    no_desc   = [j for j in jobs if len((j.get("description") or "").strip()) <= 100]

    # Cap LLM work. LinkedIn returns newest-first, so the head is the freshest.
    to_score = scoreable[:max_to_score]
    overflow = scoreable[max_to_score:]

    if no_desc:
        log.info("Skipping %d jobs with missing/short descriptions", len(no_desc))
    if overflow:
        log.info("Capping scoring at %d jobs; %d left unscored this run",
                 max_to_score, len(overflow))

    for j in no_desc:
        j.update({"score": 0, "rationale": "No job description available.",
                  "key_matches": [], "gaps": []})
    for j in overflow:
        j.update({"score": 0, "rationale": "Not scored (search cap reached).",
                  "key_matches": [], "gaps": []})

    def _score_one(job: dict) -> dict:
        result = score_job(
            job_title         = job.get("title", ""),
            company           = job.get("company", ""),
            location          = job.get("location", ""),
            description       = job.get("description", ""),
            candidate_profile = candidate_profile,
        )
        return {**job, **result}

    scored: list[dict] = []
    if to_score:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            scored = list(pool.map(_score_one, to_score))

    all_jobs = scored + overflow + no_desc
    return sorted(all_jobs, key=lambda j: j.get("score", 0), reverse=True)
