from target_context import (
    DEFAULT_INDUSTRY,
    resolve_target_context,
)


def test_defaults_when_none_or_blank() -> None:
    ctx = resolve_target_context(None, None)
    assert ctx.industry == DEFAULT_INDUSTRY
    assert ctx.role_to_offer == ""
    assert ctx.job_title == "HR / Talent Manager"  # no contact discovered yet

    ctx2 = resolve_target_context("  ", "\t")
    assert ctx2.industry == DEFAULT_INDUSTRY
    assert ctx2.role_to_offer == ""


def test_preserves_caller_strings() -> None:
    ctx = resolve_target_context("FinTech", "VP Engineering")
    assert ctx.industry == "FinTech"
    assert ctx.role_to_offer == "VP Engineering"


def test_legacy_job_title_kwarg_and_contact_title() -> None:
    ctx = resolve_target_context("FinTech", job_title="Backend Developer")
    assert ctx.role_to_offer == "Backend Developer"
    ctx.contact_title = "Head of Talent"
    assert ctx.job_title == "Head of Talent"
