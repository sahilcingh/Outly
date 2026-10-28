import pytest

import tools.ats_board as ab
from tools.job_search import JobListing


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/stripe/jobs/123", ("greenhouse", "stripe")),
    ("https://job-boards.greenhouse.io/acme/jobs/9", ("greenhouse", "acme")),
    ("https://boards.greenhouse.io/embed/job_app?for=acme&token=1", ("greenhouse", "acme")),
    ("https://boards.greenhouse.io/embed/job_app?token=1", None),
    ("https://jobs.lever.co/palantir/abc-def", ("lever", "palantir")),
    ("https://jobs.ashbyhq.com/ramp/uuid", ("ashby", "ramp")),
    ("https://apply.workable.com/huggingface/j/ABC/", ("workable", "huggingface")),
    ("https://apply.workable.com/j/ABC", None),
    ("https://www.linkedin.com/jobs/view/1", None),
    ("", None),
    (None, None),
])
def test_parse_board(url, expected):
    assert ab.parse_board(url) == expected


def L(title, url):
    return JobListing(title=title, company="Acme", location="", job_url=url, description="",
                      is_remote=False, date_posted="", source="linkedin", ats_url=url)


def test_filter_ghost_jobs(monkeypatch):
    feeds = {
        ("lever", "acme"): [{"title": "Senior Backend Engineer (Python)", "url": ""}],
        ("lever", "down"): None,   # unreadable feed
        ("lever", "empty"): [],    # empty board
    }
    calls = []
    monkeypatch.setattr(ab, "board_jobs", lambda p, b: calls.append((p, b)) or feeds[(p, b)])
    live = L("Senior Backend Engineer", "https://jobs.lever.co/acme/1")
    ghost = L("Data Analyst", "https://jobs.lever.co/acme/2")
    keep = [
        live,
        L("Anything", "https://jobs.lever.co/down/1"),
        L("Anything", "https://jobs.lever.co/empty/1"),
        L("Anything", "https://www.linkedin.com/jobs/view/1"),
    ]
    kept, dropped = ab.filter_ghost_jobs(keep + [ghost])
    assert kept == keep and dropped == 1
    assert sorted(calls) == sorted(feeds)  # each board fetched once


def test_filter_ghost_jobs_no_ats_links_skips_network(monkeypatch):
    monkeypatch.setattr(ab, "board_jobs", lambda *a: pytest.fail("network"))
    ls = [L("X", "https://www.linkedin.com/jobs/view/1")]
    assert ab.filter_ghost_jobs(ls) == (ls, 0)
