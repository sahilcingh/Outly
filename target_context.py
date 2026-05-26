"""
Prospecting context — carries everything the pipeline discovers about a target company
and what the agency is offering, so all LLM modules share one consistent object.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_INDUSTRY = "B2B Company"


@dataclass
class TargetContext:
    industry: str = DEFAULT_INDUSTRY

    # The candidate profile the agency is offering to place.
    # Auto-inferred from scraped company text; user may override via UI/CLI.
    role_to_offer: str = ""

    # Contact person discovered on the company website (team/contact/leadership pages).
    contact_name: str | None = None   # e.g. "Priya Sharma"
    contact_title: str | None = None  # e.g. "Head of Talent Acquisition"
    contact_email: str | None = None  # e.g. "priya@company.com" (rarely public)

    # Live signals fetched during pipeline execution
    hiring_signals: list[str] = field(default_factory=list)   # open job titles
    news_signals: list[dict] = field(default_factory=list)    # recent headlines

    @property
    def job_title(self) -> str:
        """Backward-compatible alias used by profiler and sequencer."""
        return self.contact_title or "HR / Talent Manager"


def resolve_target_context(
    industry: str | None = None,
    role_to_offer: str | None = None,
    # legacy param name kept so existing callers (web.py, main.py) don't break
    job_title: str | None = None,
) -> TargetContext:
    ind = (industry or "").strip() or DEFAULT_INDUSTRY
    role = (role_to_offer or job_title or "").strip()
    return TargetContext(industry=ind, role_to_offer=role)
