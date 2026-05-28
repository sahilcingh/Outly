"""
Resume parser: extracts plain text from an uploaded PDF or text file.
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)


def parse_resume(file_bytes: bytes, filename: str) -> str:
    """
    Extract plain text from a resume file.
    Supports PDF and plain text (.txt / .md).
    Returns extracted text, or empty string on failure.
    """
    fname = filename.lower()

    if fname.endswith(".pdf"):
        return _parse_pdf(file_bytes)

    # Plain text fallback
    try:
        return file_bytes.decode("utf-8", errors="replace").strip()
    except Exception as e:
        log.warning("Could not decode text file: %s", e)
        return ""


def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        log.warning("pypdf not installed — cannot parse PDF")
        return ""

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        log.info("Parsed PDF: %d pages, %d chars", len(reader.pages), len(text))
        return text
    except Exception as e:
        log.warning("PDF parsing failed: %s", e)
        return ""
