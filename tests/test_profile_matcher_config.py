import json

import pytest

import llm.job_matcher as jm
from config import resolve_min_score
from llm.skills_extractor import MAX_SKILLS, normalize_profile
from storage.profiles import apply_overrides
from tools.job_pdf import build_jobs_pdf


# ── extractor normalisation ──────────────────────────────────────────────────

def test_normalize_profile_keeps_float_years_and_fields():
    raw = {"candidate_name": "Jane Doe", "current_title": "Full Stack Intern",
           "target_roles": ["Full Stack Developer", "Backend Developer"],
           "skills": ["React", "react", "Angular"] + [f"S{i}" for i in range(40)],
           "experience_years": "1.5"}
    p = normalize_profile(raw, "RESUME TEXT")
    assert p["experience_years"] == 1.5
    assert p["candidate_name"] == "Jane Doe"
    assert p["current_title"] == "Full Stack Intern"
    assert p["role_title"] == "Full Stack Developer"      # search role, not the cover-letter title
    assert p["resume_text"] == "RESUME TEXT"
    assert len(p["skills"]) == MAX_SKILLS and p["skills"][:2] == ["React", "Angular"]


def test_normalize_profile_rejects_candidate_placeholder_and_bad_years():
    p = normalize_profile({"candidate_name": "Candidate", "experience_years": "n/a"}, "x")
    assert p["candidate_name"] == "" and p["experience_years"] is None


# ── overrides reach one profile object ───────────────────────────────────────

def test_experience_override_applies_and_sets_level():
    base = {"experience_years": 3, "candidate_name": "Jane Doe"}
    p = apply_overrides(base, {"experience_years": 1.5})
    assert p["experience_years"] == 1.5 and p["level"] == "junior"
    assert base["experience_years"] == 3  # input untouched


def test_override_falls_back_to_default_1_5_and_name_override():
    p = apply_overrides({"candidate_name": ""}, {"candidate_name": "Jane Doe"})
    assert p["experience_years"] == 1.5 and p["candidate_name"] == "Jane Doe" and p["level"] == "junior"
    assert apply_overrides({"candidate_name": "Candidate"}, {})["candidate_name"] == ""


# ── min score resolution ─────────────────────────────────────────────────────

def test_junior_default_is_60_and_ignores_generic_env(monkeypatch):
    monkeypatch.delenv("MIN_MATCH_SCORE_ENTRY", raising=False)
    monkeypatch.setenv("MIN_MATCH_SCORE", "55")      # used to leak into junior and lower the bar
    assert resolve_min_score("junior")[0] == 60
    assert resolve_min_score("entry")[0] == 60
    assert resolve_min_score("mid") == (55, "env MIN_MATCH_SCORE")


def test_min_score_sources(monkeypatch):
    monkeypatch.delenv("MIN_MATCH_SCORE_ENTRY", raising=False)
    assert resolve_min_score("junior")[1].startswith("default")
    monkeypatch.setenv("MIN_MATCH_SCORE_ENTRY", "65")
    assert resolve_min_score("junior") == (65, "env MIN_MATCH_SCORE_ENTRY")
    assert resolve_min_score("junior", override=50) == (50, "saved /minscore preference")


# ── matcher ──────────────────────────────────────────────────────────────────

PROFILE = {"role_title": "Dev", "experience_years": 1.5, "level": "junior",
           "skills": [f"skill{i}" for i in range(30)], "industries": [], "summary": ""}


def _fake_llm(monkeypatch, payload):
    seen = {}

    def fake(system, user, label="", max_tokens=0, **kw):
        seen["prompt"] = user
        return json.dumps(payload)

    monkeypatch.setattr(jm, "groq_json_call", fake)
    return seen


def test_matcher_sends_requirements_first_all_skills_and_long_description(monkeypatch):
    seen = _fake_llm(monkeypatch, {"score": 80})
    desc = "intro " * 400 + "\nRequirements:\n- Django\n" + "tail " * 400
    jm.score_job("Dev", "Acme", "Bengaluru", desc, PROFILE)
    p = seen["prompt"]
    assert p.index("[REQUIREMENTS SECTION]") < p.index("[FULL DESCRIPTION]")
    assert "skill29" in p                      # no [:20] truncation
    assert len(desc) > 1200 and "intro " * 300 in p   # reads well past the old 1200 chars


def test_must_have_missing_caps_score_and_fields_parsed(monkeypatch):
    _fake_llm(monkeypatch, {"score": 85, "required_min_years": "2", "work_location": "Bengaluru",
                            "work_model": "Hybrid", "must_have_missing": ["Go"], "gaps": ["Go"]})
    out = jm.score_job("Dev", "Acme", "Bengaluru", "x" * 200, PROFILE)
    assert out["score"] == jm.MUST_HAVE_CAP == 59
    assert out["required_min_years"] == 2.0 and out["work_model"] == "hybrid"
    assert out["must_have_missing"] == ["Go"] and out["work_location"] == "Bengaluru"


def test_no_missing_must_have_keeps_score_and_null_years(monkeypatch):
    _fake_llm(monkeypatch, {"score": 85, "required_min_years": None, "work_model": "weird"})
    out = jm.score_job("Dev", "Acme", "Bengaluru", "x" * 200, PROFILE)
    assert out["score"] == 85 and out["required_min_years"] is None and out["work_model"] == ""


# ── PDF ──────────────────────────────────────────────────────────────────────

class FakeJob:
    def __init__(self, **kw):
        self.job_title, self.company_name, self.location = "Dev", "Acme", "Bengaluru"
        self.is_remote, self.source, self.apply_method = False, "linkedin", "manual"
        self.status, self.date_posted = "queued", ""
        self.job_url, self.ats_url, self.contact_email, self.subject_line = "http://x", None, None, "Subj"
        self.match_score, self.match_rationale = 66, "why"
        self.key_matches, self.gaps = ["React"], ["Go"]
        self.cover_letter = "Dear Hiring Manager"
        self.match_meta = {}
        self.__dict__.update(kw)


def _pdf_text(jobs) -> str:
    from pypdf import PdfReader
    import io
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(build_jobs_pdf(jobs))).pages)


def test_pdf_shows_raw_score_meta_draft_label_and_fallback_note():
    meta = {"required_min_years": 1.5, "work_location": "Bengaluru", "work_model": "hybrid",
            "must_have_missing": ["Go"], "letter_status": "fallback"}
    text = _pdf_text([FakeJob(match_meta=meta)]).replace("\n", " ")
    for needle in ("Match score: 66", "1.5 yrs", "Bengaluru, hybrid", "Must-have skills missing: Go",
                   "DRAFT - review before sending", "failed the fact-check"):
        assert needle in text, needle


def test_pdf_not_stated_and_no_fallback_note():
    text = _pdf_text([FakeJob()]).replace("\n", " ")
    assert "not stated" in text and "DRAFT - review before sending" in text
    assert "failed the fact-check" not in text


def test_pdf_without_letter_explains_why():
    assert "No cover letter" in _pdf_text([FakeJob(cover_letter="")])
