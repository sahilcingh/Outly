"""
Gemini API drafter for B2B prospecting emails.
Emails are addressed TO the discovered contact person at the company,
OFFERING a specific candidate role inferred from the company's website.
"""

import json
import re

from target_context import TargetContext, resolve_target_context
from llm.groq_client import groq_json_call

GEMINI_MODEL = None  # kept for signature compatibility; unused
PROMPT_VERSION = "v4"


def _drafter_system_instruction(ctx: TargetContext) -> str:
    # Who we're writing to
    if ctx.contact_name and ctx.contact_title:
        recipient = f"{ctx.contact_name} ({ctx.contact_title})"
        greeting = f"Hi {ctx.contact_name.split()[0]},"
    elif ctx.contact_name:
        recipient = ctx.contact_name
        greeting = f"Hi {ctx.contact_name.split()[0]},"
    elif ctx.contact_title:
        recipient = ctx.contact_title
        greeting = f"Hi [first name],"
    else:
        recipient = "the relevant hiring or talent leader"
        greeting = "Hi,"

    # What we're offering
    role = ctx.role_to_offer or "a specialist candidate"

    # Build hiring signal context
    hiring_str = ""
    if ctx.hiring_signals:
        top = ", ".join(ctx.hiring_signals[:4])
        hiring_str = f"\nACTIVE JOB OPENINGS AT THIS COMPANY: {top}"

    # Build news signal context
    news_str = ""
    if ctx.news_signals:
        headlines = "; ".join(n["title"] for n in ctx.news_signals[:2])
        news_str = f"\nRECENT COMPANY NEWS: {headlines}"

    return f"""You are a senior recruitment consultant at a premier specialist staffing agency. You are writing a professional cold outreach email on behalf of your consultancy to introduce a pre-vetted candidate for placement.

RECIPIENT: {recipient}
CANDIDATE BEING OFFERED: {role}
INDUSTRY CONTEXT: {ctx.industry}{hiring_str}{news_str}

Read the scraped website text about the target company carefully. Write a professional, well-structured outreach email that:

Opening line: "{greeting}"

EMAIL STRUCTURE (follow this exactly):
1. INTRO (1-2 sentences): Briefly introduce yourself as a specialist recruitment consultant and why you are reaching out to this company specifically — reference a concrete signal (job opening, recent news, or product/tech from the website).
2. CANDIDATE PITCH (2-3 sentences): Describe the {role} you are representing. Highlight 2-3 specific skills or achievements that directly align with the company's technology, product, or current initiatives mentioned in the website. Be specific — name the technologies or goals.
3. VALUE PROPOSITION (1-2 sentences): Explain how placing this candidate will help the company achieve its goals — reference something specific from their website (a product feature, scaling challenge, tech stack, or expansion initiative).
4. CALL TO ACTION (1 sentence): A clear, low-friction next step (e.g. "I'd love to share their profile — would a 20-minute call this week work for you?").

Priority signals to reference:
- If ACTIVE JOB OPENINGS are listed above, mention you have a strong candidate for that specific role.
- If RECENT COMPANY NEWS is listed above, reference it as the reason for reaching out now.
- Otherwise, reference a specific product, tech stack, or initiative from the website text.

Rules:
1. 150-200 words in the body — professional but not lengthy.
2. Always make it clear this is a specialist staffing/recruitment consultancy placing a pre-vetted candidate.
3. Name specific technologies, products, or initiatives from the company website — never be vague.
4. No generic phrases ("hope you're well", "touching base", "synergy", "circling back").
5. Write in first person ("I" / "we" for the agency).
6. Sound professional, confident, and consultative — not salesy.

Output STRICT JSON only:
{{"subject": "compelling email subject line", "body": "full professional email body with proper paragraphs", "rationale": "one sentence: what specific signal from the website you used and why this candidate fits"}}"""


def draft_email(
    company_text: str,
    *,
    industry: str | None = None,
    job_title: str | None = None,
    context: TargetContext | None = None,
    model: str = GEMINI_MODEL,
) -> dict | None:
    ctx = context if context is not None else resolve_target_context(industry, job_title)
    text = company_text[:32000] if len(company_text) > 32000 else company_text
    content = groq_json_call(_drafter_system_instruction(ctx), f"Target company website text:\n\n{text}", label="drafter")
    return _parse_json_response(content) if content else None


def _parse_json_response(content: str) -> dict | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None
