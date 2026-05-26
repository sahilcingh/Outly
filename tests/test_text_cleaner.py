from utils.text_cleaner import clean_text


def test_clean_text_normalizes_whitespace_and_unicode() -> None:
    raw = "Hello\u00a0\u00a0world!\n\nThis\tis\u200b a test."
    out = clean_text(raw)
    assert out == "Hello world! This is a test."


def test_clean_text_empty_input() -> None:
    assert clean_text("") == ""
    assert clean_text(None) == ""

