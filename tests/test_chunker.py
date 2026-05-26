from utils.chunker import chunk_text


def test_chunk_text_returns_single_chunk_for_short_text() -> None:
    text = "One short sentence."
    chunks = chunk_text(text, chunk_size=512, overlap=64)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].index == 0


def test_chunk_text_overlaps_and_increments_indices() -> None:
    text = (
        "This is sentence one. "
        "This is sentence two. "
        "This is sentence three. "
        "This is sentence four."
    )
    chunks = chunk_text(text, chunk_size=40, overlap=10)
    assert len(chunks) >= 2
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.text.strip() for c in chunks)

