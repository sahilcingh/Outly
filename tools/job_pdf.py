"""
Generate a PDF digest of job applications — the same data shown on the
Job Queue web page — for sending to Telegram.

Uses fpdf2 (pure Python, no headless browser) so it deploys cleanly on Render.
Core fonts are Latin-1 only, so all text is sanitized to safe characters.
"""

from __future__ import annotations

import io
import logging
from urllib.parse import quote

log = logging.getLogger(__name__)

# ── Colors (RGB) ────────────────────────────────────────────────────────────
_ORANGE   = (249, 115, 22)
_INK      = (17, 24, 39)
_GRAY     = (107, 114, 128)
_LIGHT    = (243, 244, 246)
_GREEN    = (22, 101, 52)
_YELLOW   = (133, 77, 14)
_RED      = (153, 27, 27)
_BORDER   = (209, 213, 219)

# Common Unicode → ASCII replacements (core fonts can't render the originals)
_REPLACEMENTS = {
    "—": "-", "–": "-", "‒": "-", "―": "-",
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "…": "...", "•": "-", "·": "-", "‣": "-",
    " ": " ", " ": " ", "​": "",
    "→": "->", "←": "<-", "✓": "[ok]", "✗": "[x]",
    "₹": "Rs.", "™": "(TM)", "®": "(R)", "©": "(c)",
}


def _san(text) -> str:
    """Make any text safe for fpdf2 core (Latin-1) fonts."""
    s = str(text or "")
    for uni, asc in _REPLACEMENTS.items():
        s = s.replace(uni, asc)
    # Drop anything still outside Latin-1 (emoji, CJK, etc.)
    return s.encode("latin-1", "ignore").decode("latin-1")


def _score_color(score: int):
    if score >= 70:
        return _GREEN
    if score >= 40:
        return _YELLOW
    return _RED


def _apply_link(job) -> tuple[str, str]:
    """
    Return (url, button_label) for the one-tap apply action.

    For email jobs, builds a mailto: link pre-filled with the subject and full
    cover letter so tapping opens the mail app ready to send. For everything
    else, links straight to the job / ATS posting.
    """
    if job.apply_method == "email" and job.contact_email:
        subject = job.subject_line or f"Application for {job.job_title}"
        body = job.cover_letter or ""
        url = f"mailto:{job.contact_email}?subject={quote(subject)}&body={quote(body)}"
        return url, "APPLY BY EMAIL  (opens your mail app, pre-filled)"
    target = job.ats_url or job.job_url
    return target, "APPLY / VIEW JOB  (tap to open)"


def build_jobs_pdf(jobs: list, title: str = "Job Review Queue") -> bytes:
    """
    Render a list of JobApplication objects to a PDF and return raw bytes.
    Mirrors the Job Queue page: score, company, match analysis, gaps, cover letter.
    """
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(left=15, top=15, right=15)
    epw = pdf.epw  # effective page width

    # ── Cover header ──────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*_ORANGE)
    pdf.rect(0, 0, 210, 28, style="F")
    pdf.set_xy(15, 8)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, _san(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(15, 30)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 6, _san(f"{len(jobs)} jobs  |  Outly automated application digest"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if not jobs:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 8, "No jobs to show.", new_x="LMARGIN", new_y="NEXT")
        return _output(pdf)

    for idx, job in enumerate(jobs, 1):
        _render_job(pdf, job, idx, epw)

    return _output(pdf)


def _render_job(pdf, job, idx: int, epw: float) -> None:
    from fpdf import FPDF  # noqa: F401

    score = int(getattr(job, "match_score", 0) or 0)

    # Keep a job card from splitting awkwardly: start fresh if little room left
    if pdf.get_y() > 240:
        pdf.add_page()

    # ── Title bar: "#id  Job Title" + score badge ──────────────────────────────
    pdf.set_fill_color(*_LIGHT)
    y0 = pdf.get_y()
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*_INK)
    title_txt = _san(f"{idx}. {job.job_title}")
    pdf.multi_cell(epw - 24, 6, title_txt, new_x="LMARGIN", new_y="NEXT")

    # Score badge on the right
    r, g, b = _score_color(score)
    pdf.set_xy(pdf.l_margin + epw - 20, y0)
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(20, 8, f"{score}%", align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(pdf.l_margin, max(pdf.get_y(), y0 + 8))

    # ── Company + meta line ─────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 5, _san(job.company_name), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_GRAY)
    meta_bits = [
        job.location or "Remote",
        "Remote" if job.is_remote else "",
        job.source,
        job.apply_method.replace("ats_", "ATS: ") if job.apply_method else "",
        f"Status: {job.status}",
        f"Posted: {job.date_posted}" if job.date_posted else "",
    ]
    meta = "  |  ".join(b for b in meta_bits if b)
    pdf.multi_cell(0, 4, _san(meta), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)

    # ── APPLY button (clickable) ────────────────────────────────────────────────
    apply_url, label = _apply_link(job)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(*_ORANGE)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, _san(label), fill=True, align="C", link=apply_url,
             new_x="LMARGIN", new_y="NEXT")
    # Plain-text target below, so the address/URL is visible & copyable too
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*_GRAY)
    if job.apply_method == "email" and job.contact_email:
        target_txt = f"Email: {job.contact_email}"
    else:
        target_txt = job.ats_url or job.job_url
    pdf.multi_cell(0, 4, _san(target_txt), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)

    # ── Match rationale ─────────────────────────────────────────────────────────
    if job.match_rationale:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 4, "Why you match:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_GRAY)
        pdf.multi_cell(0, 4, _san(job.match_rationale), new_x="LMARGIN", new_y="NEXT")

    # ── Matches / gaps ──────────────────────────────────────────────────────────
    if job.key_matches:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_GREEN)
        pdf.multi_cell(0, 4, _san("Strengths: " + ", ".join(job.key_matches)),
                       new_x="LMARGIN", new_y="NEXT")
    if job.gaps:
        pdf.set_text_color(*_RED)
        pdf.multi_cell(0, 4, _san("Gaps: " + ", ".join(job.gaps)),
                       new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # ── Cover letter (full) ─────────────────────────────────────────────────────
    if job.subject_line:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(0, 4, _san(f"Subject: {job.subject_line}"),
                       new_x="LMARGIN", new_y="NEXT")
    if job.cover_letter:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 4, "Cover Letter:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(0, 4, _san(job.cover_letter), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 4, "(No cover letter yet - generate from the web app)",
                 new_x="LMARGIN", new_y="NEXT")

    # ── Divider ─────────────────────────────────────────────────────────────────
    pdf.ln(2)
    pdf.set_draw_color(*_BORDER)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.l_margin + epw, y)
    pdf.ln(4)


def _output(pdf) -> bytes:
    """Return PDF as bytes across fpdf2 versions."""
    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    # Older fpdf2 returned str
    return out.encode("latin-1")
