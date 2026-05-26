from target_context import (
    DEFAULT_INDUSTRY,
    DEFAULT_JOB_TITLE,
    resolve_target_context,
)


def test_defaults_when_none_or_blank() -> None:
    ctx = resolve_target_context(None, None)
    assert ctx.industry == DEFAULT_INDUSTRY
    assert ctx.job_title == DEFAULT_JOB_TITLE

    ctx2 = resolve_target_context("  ", "\t")
    assert ctx2.industry == DEFAULT_INDUSTRY
    assert ctx2.job_title == DEFAULT_JOB_TITLE


def test_preserves_caller_strings() -> None:
    ctx = resolve_target_context("FinTech", "VP Engineering")
    assert ctx.industry == "FinTech"
    assert ctx.job_title == "VP Engineering"
