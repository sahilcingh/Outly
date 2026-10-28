import json

import llm.cover_letter as cl
from llm.cover_letter import generate_cover_letter, validate_cover_letter

RESUME = (
    "Jane Doe\nFull Stack Intern, Acme Labs (2023-2024)\n"
    "Skills: React, Node.js, PostgreSQL, JavaScript, Python, Tailwind CSS\n"
    "Built a chat app used by 50 students."
)
PROFILE = {
    "candidate_name": "Jane Doe",
    "current_title": "Full Stack Intern",
    "experience_years": 1.5,
    "skills": ["React", "Node.js", "PostgreSQL", "JavaScript", "Python", "Tailwind CSS"],
    "resume_text": RESUME,
}
GOOD = "Dear Hiring Manager,\n\nI built a chat app used by 50 students with React and Node.\n\nBest regards,\nJane Doe"


def _call(**kw):
    args = dict(job_title="Developer", company="Acme", location="Bengaluru",
                description="Build things", candidate_profile=PROFILE)
    args.update(kw)
    return generate_cover_letter(**args)


def _llm(monkeypatch, letters):
    """Fake Groq returning the given letters in order; records prompts + temperature."""
    calls = []

    def fake(system, user, label="", temperature=0.7, **kw):
        calls.append({"user": user, "temperature": temperature})
        return json.dumps({"cover_letter": letters[min(len(calls), len(letters)) - 1]})

    monkeypatch.setattr(cl, "groq_json_call", fake)
    return calls


# ── validator ────────────────────────────────────────────────────────────────

def test_valid_letter_passes():
    assert validate_cover_letter(GOOD, RESUME) == (True, [])


def test_invented_number_fails():
    ok, v = validate_cover_letter("I handle 10,000 transactions per minute and cut latency by 30%.", RESUME)
    assert not ok
    assert any("10000" in x for x in v) and any("'30'" in x for x in v)


def test_absent_technology_fails():
    ok, v = validate_cover_letter("I have hands-on experience with AWS Lambda and DynamoDB.", RESUME)
    assert not ok
    assert {"aws", "lambda", "dynamodb"} <= {x.split("'")[1] for x in v}


def test_gap_skill_claim_fails():
    letter = "I have a solid foundation in C# and .NET Core, plus hands-on experience with Workato."
    ok, v = validate_cover_letter(letter, RESUME, gaps=["Workato", "C#"])
    assert not ok
    assert any("c#" in x for x in v) and any("claims gap skill 'Workato'" in x for x in v)


def test_java_not_satisfied_by_javascript():
    assert not validate_cover_letter("I know Java well.", RESUME)[0]


def test_claim_verbs_need_resume_support():
    assert not validate_cover_letter("I led a team of engineers.", RESUME)[0]
    assert validate_cover_letter("I led a team.", RESUME + " Led the team.")[0]


def test_candidate_placeholder_fails():
    assert not validate_cover_letter("Best regards,\nCandidate", RESUME)[0]


def test_alias_node_js_matches_node():
    assert validate_cover_letter("I use Node and Postgres.", RESUME + " Postgres")[0]


def test_numbers_in_allow_text_are_ok():
    assert validate_cover_letter("I have 1.5 years of experience.", RESUME, allow_text="1.5")[0]
    assert not validate_cover_letter("I have 1.5 years of experience.", RESUME)[0]


# ── generation flow ──────────────────────────────────────────────────────────

def test_good_letter_returned_and_temperature_low(monkeypatch):
    calls = _llm(monkeypatch, [GOOD])
    out = _call(gaps=["Workato"])
    assert out["status"] == "ok" and out["cover_letter"] == GOOD
    assert out["subject_line"] == "Application for Developer - Jane Doe"
    assert len(calls) == 1 and calls[0]["temperature"] == 0.3
    assert "Workato" in calls[0]["user"] and "DO NOT CLAIM" in calls[0]["user"]
    assert "Full Stack Intern" in calls[0]["user"] and RESUME in calls[0]["user"]


def test_regenerates_once_with_violations(monkeypatch):
    calls = _llm(monkeypatch, ["I cut latency by 30% using AWS.", GOOD])
    out = _call()
    assert out["status"] == "ok" and out["cover_letter"] == GOOD
    assert len(calls) == 2
    assert "number '30'" in calls[1]["user"] and "technology 'aws'" in calls[1]["user"]


def test_fallback_template_after_two_failures(monkeypatch):
    calls = _llm(monkeypatch, ["I use AWS and Kubernetes."])
    out = _call()
    assert out["status"] == "fallback" and len(calls) == 2
    letter = out["cover_letter"]
    assert validate_cover_letter(letter, RESUME, allow_text="Developer Acme 1.5")[0]
    assert "Jane Doe" in letter and "Full Stack Intern" in letter and "Candidate" not in letter


def test_blocked_without_name(monkeypatch):
    calls = _llm(monkeypatch, [GOOD])
    out = _call(candidate_profile={**PROFILE, "candidate_name": ""})
    assert out["status"] == "blocked" and out["cover_letter"] == "" and calls == []
    out = _call(candidate_profile={**PROFILE, "candidate_name": "Candidate"})
    assert out["status"] == "blocked"


def test_blocked_without_resume_text(monkeypatch):
    _llm(monkeypatch, [GOOD])
    assert _call(candidate_profile={**PROFILE, "resume_text": ""})["status"] == "blocked"


def test_llm_error_falls_back(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(cl, "groq_json_call", boom)
    out = _call()
    assert out["status"] == "fallback" and "Candidate" not in out["cover_letter"]


def test_company_and_job_title_may_contain_tech_words(monkeypatch):
    letter = "Dear Hiring Manager,\n\nI would love to join Oracle as an Azure Developer, using my React skills.\n\nBest regards,\nJane Doe"
    _llm(monkeypatch, [letter])
    out = _call(job_title="Azure Developer", company="Oracle")
    assert out["status"] == "ok"
    # ...but claiming the skill elsewhere in the letter is still caught
    ok, v = validate_cover_letter("I have used Azure daily.", RESUME, allow_phrases=("Azure Developer", "Oracle"))
    assert not ok


def test_postgres_tuple_rows_keep_new_columns():
    import storage.jobs as j
    row = (1, 1, "T", "C", None, "u", "Blr", 0, "", "x", "d", 65, "r", "[]", "[]", "L", "S", "manual",
           None, None, "queued", None, "now", "Jane", "FSI", None, 0, "", 73, '{"work_model": "hybrid"}')
    job = j._row_to_job(row)
    assert job.sort_score == 73 and job.match_meta == {"work_model": "hybrid"} and job.status == "queued"
