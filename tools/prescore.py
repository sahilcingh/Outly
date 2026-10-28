"""
Deterministic CV-vs-job pre-score (no LLM). Ported in spirit from freehire's
cvmatch (MIT): fixed category weights, and a category that can't be evaluated
is left out of both numerator and denominator rather than scored zero.
Used to decide which jobs are worth an LLM scoring call, not to replace it.
"""

from __future__ import annotations

import re

from tools.filters import extract_requirements_section, has_term
from tools.seniority import _RANK, infer_job_level

WEIGHTS = {"requirements": 40, "keywords": 30, "title": 20, "seniority": 10}
_REQ_SAT, _KW_SAT = 3, 5   # skill hits that earn a category's full weight

# Title words that say nothing about the kind of role.
_GENERIC = {"software", "developer", "engineer", "engineering", "senior", "junior", "sr", "jr",
            "lead", "intern", "associate", "trainee", "fresher", "graduate", "i", "ii", "iii"}


# canonical -> other spellings, so "JS" in a listing counts for a "JavaScript" resume.
_ALIASES = {
    "javascript": {"js"}, "typescript": {"ts"}, "node.js": {"node", "nodejs"},
    "react": {"react.js", "reactjs"}, "next.js": {"next", "nextjs"}, "vue": {"vue.js", "vuejs"},
    "angular": {"angularjs", "angular.js"}, "express": {"express.js", "expressjs"},
    "go": {"golang"}, "c#": {"csharp"}, ".net": {"dotnet"}, "postgresql": {"postgres"},
    "mongodb": {"mongo"}, "kubernetes": {"k8s"}, "aws": {"amazon web services"},
    "gcp": {"google cloud"}, "machine learning": {"ml"}, "rest": {"restful", "rest api"},
    "tailwind": {"tailwindcss", "tailwind css"}, "ci/cd": {"cicd"},
}
# Everyday words that are also tech names. They only count when the same text
# names an unambiguous tech term too (freehire's corroboration rule), so
# "react quickly" or "go above and beyond" alone is not a skill hit.
_AMBIGUOUS = {"go", "react", "swift", "spring", "rust", "express", "rest", "next", "node", "ts", "ml"}
_STRONG_VOCAB = {f for c, v in _ALIASES.items() for f in {c, *v}} - _AMBIGUOUS


def _forms(skill: str) -> set[str]:
    s = skill.lower().strip()
    canon = next((c for c, v in _ALIASES.items() if s == c or s in v), s)
    return {canon, *_ALIASES.get(canon, ())}


def skill_hits(text: str, skills: list[str]) -> int:
    """How many of `skills` the text names, via aliases, with ambiguous words corroborated."""
    found = [{f for f in _forms(s) if has_term(text, f)} for s in skills]
    strong = (any(f not in _AMBIGUOUS for fs in found for f in fs)
              or any(has_term(text, f) for f in _STRONG_VOCAB))
    return sum(bool(fs) and (strong or bool(fs - _AMBIGUOUS)) for fs in found)


def _title_fit(title: str, roles: list[str]) -> float | None:
    t = re.sub(r"[^a-z0-9]+", " ", title.lower())
    compact = t.replace(" ", "")
    best = None
    for role in roles:
        words = [w for w in re.sub(r"[^a-z0-9]+", " ", role.lower()).split() if w not in _GENERIC]
        if words:
            fit = sum(w in compact for w in words) / len(words)
            best = fit if best is None else max(best, fit)
    return best


def _seniority_fit(title: str, level: str) -> float | None:
    job = infer_job_level(title)
    if job is None or level not in _RANK:
        return None
    gap = _RANK[job] - _RANK[level]
    return 1.0 if gap <= 0 else 0.5 if gap == 1 else 0.0


def prescore(job: dict, profile: dict) -> dict:
    """{"score": 0-100 or None, "skill_hits": int, "categories": {name: 0..1}}."""
    skills = profile.get("skills") or []
    title = job.get("title", "")
    desc = job.get("description", "")
    req = extract_requirements_section(desc)
    hits = skill_hits(f"{title}\n{desc}", skills)

    fits = {
        "requirements": min(1.0, skill_hits(req, skills) / _REQ_SAT) if skills and req else None,
        "keywords":     min(1.0, hits / _KW_SAT) if skills else None,
        "title":        _title_fit(title, profile.get("target_roles") or [profile.get("role_title", "")]),
        "seniority":    _seniority_fit(title, profile.get("level", "")),
    }
    fits = {k: v for k, v in fits.items() if v is not None}
    total = sum(WEIGHTS[k] for k in fits)
    score = round(sum(WEIGHTS[k] * v for k, v in fits.items()) / total * 100) if total else None
    return {"score": score, "skill_hits": hits, "categories": fits}
