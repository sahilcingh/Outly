"""
Generate a tailored cover letter for a specific job application.

The candidate's resume text is the single source of truth: the prompt forbids
anything not in it, and validate_cover_letter() enforces that after generation
(numbers, technologies, claim verbs). A letter that fails twice is replaced by
a short template built only from resume facts and flagged for review.
"""

from __future__ import annotations

import json
import logging
import re

from llm.groq_client import groq_json_call
from tools.filters import has_term

log = logging.getLogger(__name__)

COVER_LETTER_TEMPERATURE = 0.3

_SYSTEM = """You are helping a job seeker write a professional, personalized cover letter.
The letter must sound genuine and human, not templated, and must be strictly truthful.
Respond ONLY with valid JSON, no markdown, no extra text."""

_PROMPT = """
CANDIDATE RESUME (the ONLY source of truth about the candidate):
\"\"\"
{resume_text}
\"\"\"

Name: {candidate_name}
Current/most recent job title (use exactly as written): {current_title}
Experience: {years_exp} years
Skills: {skills}

JOB:
Title: {job_title}
Company: {company}
Location: {location}
Key requirements from description:
{requirements}

DO NOT CLAIM (the candidate lacks these; never say they have them):
{do_not_claim}

Write a cover letter in four paragraphs:
1. OPENING (2 sentences): Express genuine interest in the specific role and company.
2. RELEVANT EXPERIENCE (3 sentences): Describe the candidate's most relevant experience, using only projects, employers, titles and skills that appear in the resume and relate to the job requirements.
3. WHY THIS COMPANY (2 sentences): Explain why this role fits where the candidate wants to grow. Do not state facts about the company that are not in the job description.
4. CLOSING (1-2 sentences): Professional call to action, enthusiasm for a conversation.

STRICT TRUTH RULES:
- Use ONLY facts, job titles, employers, technologies, numbers and project names that appear in the resume text above.
- NEVER invent metrics, percentages, user counts, transaction volumes, latencies, team sizes, or "led" / "architected" / "spearheaded" claims that are not in the resume.
- NEVER mention a technology, cloud service, framework or tool that is not in the resume, even if the job requires it.
- If the job requires something the candidate lacks, either omit it or say honestly that they are keen to learn it. Never claim it.
- Use the candidate's exact job titles as written in the resume (e.g. "Full Stack Intern", never "Full Stack Engineer").

Style rules:
- First person ("I have...", "My experience...")
- Opening line: "Dear Hiring Manager,"
- Sign off: "Best regards," on one line, then {candidate_name} on the next line
- Tone: confident but not arrogant, professional but warm. 250-350 words.
- Do not start with "I am writing to apply".
- Do not mention salary, references, or attachments.
{extra}
Return exactly this JSON:
{{
  "cover_letter": "<the full cover letter as a single string with \\n for line breaks>"
}}
"""

# ── Validator ────────────────────────────────────────────────────────────────

# Technologies the model tends to invent. Matched as whole terms against
# the normalized letter and resume.
_TECH = [
    # languages
    "python", "java", "javascript", "typescript", "c#", "c++", "golang", "rust", "kotlin",
    "php", "ruby", "scala", "dart", "perl", "bash", "sql", "html", "css", "solidity",
    # frameworks / libraries
    "react", "react native", "angular", "vue", "nextjs", "svelte", "node", "expressjs",
    "nestjs", "django", "flask", "fastapi", "spring boot", ".net", "asp.net", "laravel",
    "rails", "flutter", "jquery", "redux", "tailwind", "tailwind css", "bootstrap",
    "graphql", "grpc", "kafka", "rabbitmq", "tensorflow", "pytorch", "scikit-learn",
    "pandas", "numpy", "langchain", "opencv", "pyspark", "apache spark", "hadoop", "airflow",
    # clouds / services / devops
    "aws", "azure", "gcp", "google cloud", "lambda", "dynamodb", "eks", "ecs", "sqs", "sns",
    "ec2", "s3", "cloudfront", "rds", "kubernetes", "docker", "terraform", "ansible",
    "jenkins", "github actions", "ci/cd", "firebase", "supabase", "heroku", "vercel",
    "netlify", "cloudflare",
    # databases
    "mysql", "postgresql", "mongodb", "redis", "sqlite", "oracle", "elasticsearch",
    "cassandra", "snowflake",
    # tools / platforms
    "git", "jira", "figma", "postman", "linux", "workato", "salesforce", "sap", "tableau",
    "power bi", "alteryx", "matlab", "simulink", "firmware", "plc", "selenium", "cypress", "jest",
]

# Verbs that claim ownership/leadership; only allowed if the resume uses them.
_CLAIM_WORDS = ["led", "architected", "spearheaded", "pioneered", "orchestrated", "single-handedly"]

_ALIASES = {
    "node.js": "node", "nodejs": "node", "react.js": "react", "reactjs": "react",
    "vue.js": "vue", "vuejs": "vue", "next.js": "nextjs", "express.js": "expressjs",
    "postgres": "postgresql", "k8s": "kubernetes"
}


def _norm(text: str) -> str:
    t = (text or "").lower()
    for a, b in _ALIASES.items():
        t = re.sub(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", b, t)
    return t


def _numbers(text: str) -> set[str]:
    """Numeric tokens in text, normalised ('10,000' -> '10000', '92%' -> '92')."""
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d+(?:[.,]\d+)*", text or "")}


def validate_cover_letter(
    letter: str,
    resume_text: str,
    gaps=(),
    allow_text: str = "",
    allow_phrases=(),
) -> tuple[bool, list[str]]:
    """
    Check a generated letter against the resume. Returns (ok, violations).

    - every number/percentage must appear in the resume (or in `allow_text`,
      e.g. the job title and the candidate's experience figure)
    - every known technology keyword in the letter must appear in the resume
    - ownership claims ("led", "architected", ...) must be supported by the resume
    - phrases from the matcher's `gaps` must not be claimed
    - the placeholder word "Candidate" must never appear

    `allow_phrases` (the job title and company) may be named in the letter even
    if they contain a technology word (e.g. "Oracle", "Azure Developer").
    """
    violations: list[str] = []
    resume_n = _norm(resume_text)
    letter_n = _norm(letter)
    for ph in allow_phrases:
        if str(ph).strip():
            letter_n = letter_n.replace(_norm(str(ph)), " ")

    allowed_nums = _numbers(resume_text) | _numbers(allow_text)
    for n in sorted(_numbers(letter) - allowed_nums):
        violations.append(f"number '{n}' is not in the resume")

    for kw in _TECH:
        if has_term(letter_n, kw) and not has_term(resume_n, kw):
            violations.append(f"technology '{kw}' is not in the resume")

    for w in _CLAIM_WORDS:
        if has_term(letter_n, w) and not has_term(resume_n, w):
            violations.append(f"claim '{w}' is not supported by the resume")

    for gap in gaps or ():
        g = _norm(str(gap)).strip()
        if 0 < len(g.split()) <= 3 and has_term(letter_n, g) and not has_term(resume_n, g):
            violations.append(f"claims gap skill '{gap}'")

    if re.search(r"\bcandidate\b", letter or "", re.I):
        violations.append("contains the placeholder word 'Candidate'")

    return (not violations), violations


# ── Generation ───────────────────────────────────────────────────────────────

def _fmt_years(y) -> str:
    try:
        return f"{float(y):g}"
    except (TypeError, ValueError):
        return ""


def _fallback_letter(name: str, job_title: str, company: str, profile: dict) -> str:
    """Short, safe letter built only from resume facts (title, years, skills found in the resume)."""
    resume = profile.get("resume_text", "")
    skills = [s for s in profile.get("skills", []) if has_term(_norm(resume), _norm(s))][:6]
    title = profile.get("current_title", "")
    years = _fmt_years(profile.get("experience_years"))
    intro = "I am applying for the {} role at {}.".format(job_title, company)
    if title:
        intro += f" My most recent role was {title}"
        intro += f", with about {years} years of experience." if years else "."
    skill_line = f" My skills include {', '.join(skills)}." if skills else ""
    return (
        "Dear Hiring Manager,\n\n"
        f"{intro}{skill_line} I would welcome the chance to discuss how I can contribute "
        "to your team and to keep learning on the job.\n\n"
        f"Best regards,\n{name}"
    )


def generate_cover_letter(
    job_title: str,
    company: str,
    location: str,
    description: str,
    candidate_profile: dict,
    candidate_name: str = "",
    revision_feedback: str = "",
    gaps=(),
) -> dict:
    """
    Generate a tailored, fact-checked cover letter.

    Returns {"cover_letter", "subject_line", "status", "violations"} where status is
      "ok"       - passed validation (first try or after one regeneration)
      "fallback" - failed validation twice; safe template used, needs review
      "blocked"  - no candidate name or no resume text; nothing generated
    """
    profile = candidate_profile or {}
    name = (candidate_name or profile.get("candidate_name") or "").strip()
    resume_text = (profile.get("resume_text") or "").strip()

    if not name or name.lower() == "candidate":
        log.warning("Cover letter blocked for '%s' at '%s': candidate name unknown "
                    "(set it with /name or re-upload the resume)", job_title, company)
        return {"cover_letter": "", "subject_line": "", "status": "blocked",
                "violations": ["candidate name unknown"]}
    if not resume_text:
        log.warning("Cover letter blocked for '%s' at '%s': no resume text on the profile "
                    "(re-upload the resume)", job_title, company)
        return {"cover_letter": "", "subject_line": "", "status": "blocked",
                "violations": ["resume text missing"]}

    gaps = [str(g) for g in (gaps or []) if str(g).strip()]
    years = _fmt_years(profile.get("experience_years"))
    subject = f"Application for {job_title} - {name}"
    allow_text = f"{job_title} {company} {years}"

    base_prompt = _PROMPT.format(
        resume_text    = resume_text[:12000],
        candidate_name = name,
        current_title  = profile.get("current_title") or "(see resume)",
        years_exp      = years or "(see resume)",
        skills         = ", ".join(profile.get("skills", [])),
        job_title      = job_title,
        company        = company,
        location       = location,
        requirements   = (description or "")[:1500],
        do_not_claim   = "\n".join(f"- {g}" for g in gaps) or "- (none listed)",
        extra          = "{extra}",
    )
    if revision_feedback:
        base_prompt += (f"\n\nPREVIOUS VERSION WAS REJECTED. User's requested changes:\n{revision_feedback}\n"
                        "Incorporate these changes, still obeying every STRICT TRUTH RULE.")

    def attempt(violations: list[str]) -> str:
        extra = ""
        if violations:
            extra = ("\nYOUR PREVIOUS DRAFT BROKE THE TRUTH RULES. Fix every one of these "
                     "and do not repeat them:\n" + "\n".join(f"- {v}" for v in violations) + "\n")
        raw = groq_json_call(system=_SYSTEM, user=base_prompt.replace("{extra}", extra),
                             label="cover_letter", temperature=COVER_LETTER_TEMPERATURE)
        result = json.loads(raw) if isinstance(raw, str) else raw
        return str(result.get("cover_letter", "")).strip()

    violations: list[str] = []
    for _ in range(2):
        try:
            letter = attempt(violations)
        except Exception as e:
            log.warning("Cover letter generation failed for '%s' at '%s': %s", job_title, company, e)
            violations = [f"generation error: {e}"]
            continue
        ok, violations = validate_cover_letter(letter, resume_text, gaps, allow_text, (job_title, company))
        if ok and letter:
            return {"cover_letter": letter, "subject_line": subject, "status": "ok", "violations": []}
        log.info("Cover letter for '%s' failed validation: %s", job_title, violations)

    log.warning("Cover letter for '%s' at '%s' failed validation twice; using safe template",
                job_title, company)
    return {
        "cover_letter": _fallback_letter(name, job_title, company, profile),
        "subject_line": subject,
        "status": "fallback",
        "violations": violations,
    }
