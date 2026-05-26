"""
Split clean text into overlapping chunks for embedding/LLM context.
Uses sentence-boundary awareness to avoid mid-sentence cuts.
"""

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    """A single text chunk with metadata."""

    text: str
    index: int
    start_char: int
    end_char: int


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    """
    Split text into overlapping chunks, preferring sentence boundaries.

    Args:
        text: Clean, normalized text (from text_cleaner).
        chunk_size: Approximate max characters per chunk.
        overlap: Number of characters to overlap between consecutive chunks.

    Returns:
        List of Chunk objects with text and positional metadata.
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    if len(text) <= chunk_size:
        return [Chunk(text=text, index=0, start_char=0, end_char=len(text))]

    # Split on sentence boundaries: . ? ! followed by space or end
    sentence_pattern = re.compile(r"(?<=[.!?])\s+")
    sentences = sentence_pattern.split(text)

    chunks: list[Chunk] = []
    current_parts: list[str] = []
    current_length = 0
    chunk_index = 0
    cursor = 0

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        sent_len = len(sent) + (1 if current_parts else 0)  # space between parts

        if current_length + sent_len <= chunk_size:
            current_parts.append(sent)
            current_length += sent_len
        else:
            if current_parts:
                chunk_text_str = " ".join(current_parts)
                end_pos = cursor + len(chunk_text_str)
                chunks.append(
                    Chunk(
                        text=chunk_text_str,
                        index=chunk_index,
                        start_char=cursor,
                        end_char=end_pos,
                    )
                )
                chunk_index += 1

                # Overlap: carry last N chars into next chunk (at word boundary)
                overlap_text = ""
                if overlap > 0 and len(chunk_text_str) > overlap:
                    overlap_text = chunk_text_str[-overlap:].strip()
                    first_space = overlap_text.find(" ")
                    if first_space > 0:
                        overlap_text = overlap_text[first_space + 1 :]

                current_parts = [overlap_text, sent] if overlap_text else [sent]
                current_length = len(overlap_text) + len(sent) + (2 if overlap_text else 1)
                cursor = end_pos - len(overlap_text) if overlap_text else end_pos
            else:
                # Sentence longer than chunk_size: force-split by chars
                for i in range(0, len(sent), chunk_size - overlap):
                    part = sent[i : i + chunk_size]
                    if part.strip():
                        chunks.append(
                            Chunk(
                                text=part.strip(),
                                index=chunk_index,
                                start_char=cursor,
                                end_char=cursor + len(part),
                            )
                        )
                        chunk_index += 1
                        cursor += len(part)
                current_parts = []
                current_length = 0

    if current_parts:
        chunk_text_str = " ".join(current_parts)
        chunks.append(
            Chunk(
                text=chunk_text_str.strip(),
                index=chunk_index,
                start_char=cursor,
                end_char=cursor + len(chunk_text_str),
            )
        )

    return chunks
