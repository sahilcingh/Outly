import pytest

import llm.job_matcher as matcher
from tools.prescore import prescore, skill_hits


@pytest.mark.parametrize("text,skills,expected", [
    ("Strong JS and ReactJS skills", ["JavaScript", "React"], 2),        # aliases both ways
    ("Experience with k8s and Postgres", ["Kubernetes", "PostgreSQL"], 2),
    ("Golang microservices", ["Go"], 1),
    ("We react quickly and go above and beyond", ["React", "Go"], 0),    # uncorroborated
    ("React and go, with TypeScript", ["React", "Go"], 2),               # corroborated by TypeScript
    ("Build services in Go on AWS", ["Go"], 1),                         # corroborated by vocab term
    ("Spring hiring drive", ["Spring Boot"], 0),                         # multi-word skill, no hit
    ("", ["Python"], 0),
])
def test_skill_hits_aliases_and_corroboration(text, skills, expected):
    assert skill_hits(text, skills) == expected

PROFILE = {"skills": ["Python", "Django", "PostgreSQL", "React"], "level": "junior",
           "target_roles": ["Backend Developer", "Full Stack Developer"]}

GOOD = {"title": "Backend Developer", "description":
        "About us\nRequirements:\n- Python and Django\n- PostgreSQL\n" + "x" * 120}


def test_strong_match_scores_high():
    p = prescore(GOOD, PROFILE)
    # requirements 3/3 hits (40) + keywords 3/5 (18) + title (20), out of 90
    assert p["score"] == 87 and p["skill_hits"] == 3
    assert set(p["categories"]) == {"requirements", "keywords", "title"}  # no seniority marker: left out


def test_unavailable_categories_are_excluded_not_zeroed():
    # no requirements section, no seniority marker, no skills -> only title is scored
    p = prescore({"title": "Fullstack Engineer", "description": "Build things"}, {**PROFILE, "skills": []})
    assert p["categories"] == {"title": 1.0} and p["score"] == 100
    assert prescore({"title": "", "description": ""}, {})["score"] is None


def test_over_level_and_off_role_score_low():
    p = prescore({"title": "Staff Data Scientist", "description": "Python " + "x" * 120}, PROFILE)
    assert p["categories"]["seniority"] == 0.0 and p["categories"]["title"] == 0.0
    assert p["score"] < 20


def test_matcher_skips_no_overlap_and_ranks_by_prescore(monkeypatch):
    sent = []
    monkeypatch.setattr(matcher, "score_job", lambda **k: sent.append(k["job_title"]) or {"score": 70})
    weak = {"title": "Data Analyst", "description": "Requirements:\n- Excel, Python\n" + "x" * 120}
    none = {"title": "Sales Executive", "description": "Cold calling and CRM " + "x" * 120}
    out = matcher.score_jobs_parallel([weak, none, dict(GOOD)], PROFILE, max_workers=1, max_to_score=1)
    assert sent == ["Backend Developer"]               # best pre-score wins the single LLM slot
    by_title = {j["title"]: j for j in out}
    assert by_title["Sales Executive"]["score"] == 0 and "None of the candidate" in by_title["Sales Executive"]["rationale"]
    assert by_title["Data Analyst"]["rationale"].startswith("Not scored")
