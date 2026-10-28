"""End-to-end check of scheduler.job_runner._search_and_queue with everything external mocked."""

import logging

import pytest

import config
import llm.cover_letter as cover
import llm.job_matcher as matcher
import scheduler.job_runner as runner
import storage.jobs as jobs
import storage.settings as settings
import tools.job_search as job_search
import tools.telegram_bot as tg
from tools.job_search import JobListing


def L(title="Software Engineer", company="Acme", location="Bengaluru, Karnataka, India",
      description="Requirements:\n- Python\n" + "x" * 150, url=None, remote=False):
    return JobListing(title=title, company=company, location=location,
                      job_url=url or f"http://j/{title}/{company}/{location}",
                      description=description, is_remote=remote, date_posted="", source="linkedin")


PROFILE = {"role_title": "Full Stack Developer", "target_roles": ["Full Stack Developer"],
           "current_title": "Full Stack Intern", "experience_years": 3, "candidate_name": "Jane Doe",
           "skills": ["React"], "resume_text": "Jane Doe Full Stack Intern React"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("MIN_MATCH_SCORE_ENTRY", raising=False)
    monkeypatch.setenv("MIN_MATCH_SCORE", "55")
    state = {"saved": [], "scored_profile": None, "letter_profile": None, "prefs": {"experience_years": 1.5}}

    def run(listings, scores, prefs=None):
        monkeypatch.setattr(job_search, "search_jobs", lambda **k: listings)
        monkeypatch.setattr(settings, "get_settings", lambda uid=None: prefs if prefs is not None else state["prefs"])
        monkeypatch.setattr(jobs, "init_jobs_table", lambda: None)
        monkeypatch.setattr(jobs, "get_existing_job_urls", lambda uid=None: set())
        monkeypatch.setattr(jobs, "get_seen_job_keys", lambda uid=None: [])
        monkeypatch.setattr(jobs, "save_job_application", lambda **kw: state["saved"].append(kw) or 1)
        monkeypatch.setattr(tg, "send_message", lambda *a, **k: None)
        monkeypatch.setattr(runner, "_dispatch_queued_jobs", lambda *a, **k: None)

        def fake_score(job_dicts, profile, **k):
            state["scored_profile"] = profile
            out = []
            for j in job_dicts:
                extra = scores.get(j["title"], {"score": 0})
                out.append({**j, "rationale": "", "key_matches": [], "gaps": [], **extra})
            return out

        def fake_letter(**kw):
            state["letter_profile"] = kw["candidate_profile"]
            return {"cover_letter": "letter", "subject_line": "s", "status": "ok", "violations": []}

        monkeypatch.setattr(matcher, "score_jobs_parallel", fake_score)
        monkeypatch.setattr(cover, "generate_cover_letter", fake_letter)
        runner._search_and_queue(dict(PROFILE), limit=10)
        return state

    return run


def test_gate_uses_raw_score_and_bonus_only_sorts(env):
    listings = [L("Dev A"), L("Dev B"), L("Dev C", location="Pune, Maharashtra, India", remote=True)]
    # raw 55 + Bengaluru bonus 8 = 63 would have passed the old gate; raw 60 must pass; 65 outranks via bonus
    state = env(listings, {"Dev A": {"score": 55}, "Dev B": {"score": 60}, "Dev C": {"score": 66}})
    saved = {s["job_title"]: s for s in state["saved"]}
    assert set(saved) == {"Dev B", "Dev C"}           # Dev C: remote + India-based
    assert "Dev A" not in saved                       # raw 55 < 60 even though 55+8 >= 60
    assert saved["Dev B"]["match_score"] == 60        # raw score stored/displayed
    assert saved["Dev B"]["sort_score"] == 68         # bonus kept separately
    assert [x["job_title"] for x in state["saved"]] == ["Dev C", "Dev B"]  # ordered by sort_score (69 > 68)


def test_override_reaches_matcher_and_letters(env):
    state = env([L("Dev B")], {"Dev B": {"score": 70}})
    for p in (state["scored_profile"], state["letter_profile"]):
        assert p["experience_years"] == 1.5 and p["level"] == "junior" and p["candidate_name"] == "Jane Doe"


def test_filters_applied_before_queue(env):
    listings = [
        L("Good Dev"),
        L("Kochi Dev", location="Kochi, Kerala, India"),
        L("Software Developer 2"),
        L("Two Years Dev", description="Requirements:\n- 2+ years of Python\n" + "x" * 150),
        L("Azure Dev", description="Requirements:\n- Azure\n" + "x" * 150),
        L("Data Analyst"),
        L("Remote India Dev", location="Remote, India", remote=True),
    ]
    scores = {l.title: {"score": 80} for l in listings}
    state = env(listings, scores)
    assert {s["job_title"] for s in state["saved"]} == {"Good Dev", "Remote India Dev"}


def test_matcher_min_years_and_unknown_name(env):
    state = env([L("Needs Two"), L("Needs One")],
                {"Needs Two": {"score": 80, "required_min_years": 2},
                 "Needs One": {"score": 80, "required_min_years": 1}})
    assert [s["job_title"] for s in state["saved"]] == ["Needs One"]
    assert state["saved"][0]["match_meta"]["required_min_years"] == 1


def test_logs_effective_min_score_and_source(env, caplog):
    caplog.set_level(logging.INFO)
    env([L("Dev B")], {"Dev B": {"score": 70}})
    assert any("Effective min_score=60 (source: default (junior))" in r.message for r in caplog.records)
