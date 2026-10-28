from dataclasses import dataclass

import pytest

from tools.experience import extract_min_experience, filter_by_experience
from tools.filters import (
    build_job_text, dedupe_listings, extract_requirements_section, filter_by_avoid, has_term,
)
from tools.location import is_india_job, is_preferred_location
from tools.seniority import description_is_exec, filter_by_level, infer_job_level, job_allowed


@dataclass
class L:
    title: str = "Software Engineer"
    company: str = "Acme"
    location: str = "Bengaluru, India"
    description: str = ""
    is_remote: bool = False


# ── seniority ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,level", [
    ("Software Developer 2", "mid"),
    ("Software Engineer II", "mid"),
    ("Backend Engineer 2", "mid"),
    ("SDE-2", "mid"),
    ("Software Engineer 3", "senior"),
    ("Assistant Vice President, Engineering", "exec"),
    ("AVP - Technology", "exec"),
    ("VP Engineering", "exec"),
    ("Junior Developer", "junior"),
    ("Software Developer", None),
])
def test_title_levels(title, level):
    assert infer_job_level(title) == level


def test_developer_2_dropped_for_junior_but_plain_kept():
    assert not job_allowed("Software Developer 2", "junior")
    assert job_allowed("Software Developer", "junior")


def test_exec_in_description_heading():
    assert description_is_exec("About the role\nAssistant Vice President - Technology\nWe are hiring")
    assert description_is_exec("AVP, Platform Engineering")
    assert not description_is_exec("You will report to the VP of Engineering")
    assert not job_allowed("Software Engineer", "junior", description="Vice President, Engineering\nblah")
    kept, dropped = filter_by_level([L(description="AVP Technology\nx"), L()], "junior")
    assert dropped == 1 and len(kept) == 1


# ── experience ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("1.5+ years of experience", 1.5),
    ("2 to 4 years", 2.0),
    ("2-4 years of experience", 2.0),
    ("Minimum of 2 years in Python", 2.0),
    ("minimum 3 yrs", 3.0),
    ("3+ yrs required", 3.0),
    ("0-2 years", 0.0),
    ("2 years' experience with React", 2.0),
    ("Competitive salary of 12 lakhs", None),
    ("", None),
])
def test_extract_min_experience(text, expected):
    assert extract_min_experience(text) == expected


def test_candidate_1_5_years_drops_2_plus():
    jobs = [L(description="2+ years"), L(description="2 to 4 years"), L(description="1.5+ years"),
            L(description="1-3 years"), L(description="no requirement")]
    kept, dropped = filter_by_experience(jobs, 1.5)
    assert dropped == 2 and [j.description for j in kept] == ["1.5+ years", "1-3 years", "no requirement"]


# ── location ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("loc,remote,ok", [
    ("Bengaluru, Karnataka, India", False, True),
    ("Bangalore", False, True),
    ("Morena, Madhya Pradesh, India", False, False),
    ("Amravati, Maharashtra, India", False, False),
    ("Nagpur, Maharashtra, India", False, False),
    ("Indore, Madhya Pradesh, India", False, False),
    ("Kochi, Kerala, India", False, False),
    ("Chennai, Tamil Nadu, India", False, False),
    ("Noida, Uttar Pradesh, India", False, False),
    ("Hyderabad, Telangana, India", False, False),
    ("Remote, India", True, True),
    ("Remote", True, False),
    ("Remote, United States", True, False),
])
def test_preferred_location(loc, remote, ok):
    assert is_preferred_location(loc, remote) is ok


def test_remote_india_can_be_disabled_and_cities_added():
    assert not is_preferred_location("Remote, India", True, allow_remote_india=False)
    assert is_preferred_location("Pune, Maharashtra, India", False, preferred=["bengaluru", "pune"])
    assert is_india_job("Pune, India")


# ── requirements section / job text ──────────────────────────────────────────

DESC = """About us
We build things.

Requirements:
- 2+ years of Python
- Experience with Azure

Nice to have:
- Tableau

Benefits:
- Free lunch
"""


def test_requirements_section_excludes_nice_to_have():
    req = extract_requirements_section(DESC)
    assert "Python" in req and "Azure" in req
    assert "Tableau" not in req and "lunch" not in req


def test_requirements_section_headings_variants():
    assert "React" in extract_requirements_section("**Must have**\nReact\n")
    assert "SQL" in extract_requirements_section("What you'll need\n- SQL\n")
    assert extract_requirements_section("Just a paragraph of text.") == ""


def test_build_job_text_puts_requirements_first_and_caps_length():
    long_desc = "intro\n\nQualifications\n- Django\n\n" + "x" * 10000
    text = build_job_text(long_desc, limit=4000)
    assert text.startswith("[REQUIREMENTS SECTION]\n- Django")
    assert len(text) <= 4000 + 100
    assert build_job_text("short") == "short"


# ── avoid list ───────────────────────────────────────────────────────────────

AVOID = [".net", "c#", "azure", "sap", "power bi", "data analyst"]


def test_has_term_boundaries():
    assert has_term("ASP.NET developer", ".net")
    assert has_term("C# and Java", "c#")
    assert not has_term("sapient corp", "sap")
    assert has_term("SAP consultant", "sap")


def test_avoid_in_title_dropped():
    kept, n = filter_by_avoid([L(title="Data Analyst"), L(title=".NET Developer"), L()], AVOID)
    assert n == 2 and len(kept) == 1


def test_avoid_must_have_dropped_but_nice_to_have_kept():
    must = L(description="Requirements:\n- Strong Azure experience\n")
    nice = L(description="Requirements:\n- Python\n\nNice to have:\n- Azure\n- Power BI\n")
    elsewhere = L(description="We migrated from Azure last year. Requirements:\n- Python")
    kept, n = filter_by_avoid([must, nice, elsewhere], AVOID)
    assert n == 1 and nice in kept and elsewhere in kept


# ── dedupe ───────────────────────────────────────────────────────────────────

def test_dedupe_keeps_bengaluru_version():
    kochi = L(company="IBM", title="Software Developer", location="Kochi, India")
    blr = L(company="IBM Pvt. Ltd.", title="Software  Developer", location="Bengaluru, India")
    other = L(company="IBM", title="Tester")
    kept, n = dedupe_listings([kochi, blr, other])
    assert n == 1 and blr in kept and kochi not in kept and other in kept


def test_dedupe_skips_previously_shown():
    kept, n = dedupe_listings([L(company="Acme", title="Software Engineer"), L(title="Other")],
                              seen=[("ACME Inc", "software engineer")])
    assert n == 1 and [j.title for j in kept] == ["Other"]


# ── regressions found in the second test pass ────────────────────────────────

def test_indiana_is_not_india():
    assert not is_india_job("Remote, Indiana, United States", True)
    assert not is_preferred_location("Remote, Indiana, United States", True)
    assert is_india_job("Mumbai, India") and is_india_job("TN, IN")


def test_exec_heading_ignores_collaboration_lines():
    assert not description_is_exec("Collaborate with VP of Engineering on roadmap")
    assert not description_is_exec("Partner with the Vice President of Product")
    assert description_is_exec("Role: Assistant Vice President")


def test_inline_requirement_headings_and_inline_nice_to_have():
    assert "Python" in extract_requirements_section("About\nQualifications: B.E, Python, SQL\n")
    req = extract_requirements_section("Requirements:\n- Python\nGood to have: Tableau\n- Power BI\nBenefits:\n- x")
    assert "Python" in req and "Tableau" not in req and "Power BI" not in req


def test_avoid_term_in_inline_qualifications_dropped():
    kept, n = filter_by_avoid([L(description="Qualifications: C#, .NET Core")], AVOID)
    assert n == 1


def test_exp_label_years():
    assert extract_min_experience("Exp: 3 yrs") == 3.0
    assert extract_min_experience("Experience - 2 years") == 2.0
    assert extract_min_experience("expert 3 years") is None
