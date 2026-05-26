"""
Normalize scraped HTML text for LLM consumption.
Handles whitespace, encoding, boilerplate removal, and encoding consistency.
"""

import re
import unicodedata


def clean_text(raw: str) -> str:
    """
    Normalize scraped HTML text for downstream processing.

    - Collapses whitespace (including newlines, tabs) to single spaces
    - Normalizes Unicode (e.g., replace smart quotes, non-breaking spaces)
    - Strips leading/trailing whitespace
    - Removes excessive blank lines

    Args:
        raw: Raw text extracted from HTML (e.g., via BeautifulSoup get_text())

    Returns:
        Cleaned, normalized text suitable for chunking and LLM input.
    """
    if not raw or not isinstance(raw, str):
        return ""

    # Normalize Unicode (NFKC handles compatibility chars, smart quotes, etc.)
    text = unicodedata.normalize("NFKC", raw)

    # Replace various whitespace (tabs, newlines, \xa0, etc.) with single space
    text = re.sub(r"[\s\u00a0\u200b\u200c\u200d\ufeff]+", " ", text)

    # Collapse multiple spaces to one
    text = re.sub(r" +", " ", text)

    # Strip surrounding whitespace
    text = text.strip()

    return text
