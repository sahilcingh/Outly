"""
Gemini API drafter for B2B prospecting emails.
Emails are addressed TO the discovered contact person at the company,
OFFERING a specific candidate role inferred from the company's website.
"""

import json
import re

from config import get_gemini_api_key
from target_context import TargetContext, resolve_target_context
from llm.retry import gemini_call

GEMINI_MODEL = "gemini-2.5-flash"
PROMPT_VERSION = "v3"


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

    return f"""You are a recruiter at a premier specialist staffing agency writing a cold outreach email.

RECIPIENT: {recipient}
CANDIDATE BEING OFFERED: {role}
INDUSTRY CONTEXT: {ctx.industry}{hiring_str}{news_str}

Read the scraped website text about the target company and write ONE short, highly personalized cold email:

Opening line: "{greeting}"

Your pitch: You have a vetted {role} who can directly help with a specific initiative, challenge, or technology mentioned in the website text or signals above. Name that initiative or tech explicitly — do not be vague.

Priority signals to reference (use the most relevant one):
- If ACTIVE JOB OPENINGS are listed above, mention that you can help fill one of those roles fast.
- If RECENT COMPANY NEWS is listed above, reference it as the reason you're reaching out now.
- Otherwise, reference a specific product, tech stack, or initiative from the website text.

Rules:
1. Under 100 words in the body.
2. Reference 1-2 specific things (job opening, recent news, or website detail).
3. Make it clear you are offering to place a {role} — not selling software or a service.
4. No generic phrases ("hope you're well", "touching base", "synergy", "reaching out").
5. End with one clear, low-friction call to action (e.g. "Worth a 15-min call?").
6. Write in first person ("I").

Output STRICT JSON only:
{{"subject": "email subject line", "body": "full email body", "rationale": "one sentence: what specific signal (job opening / news / website detail) you used and why this role fits"}}"""


def draft_email(
    company_text: str,
    *,
    industry: str | None = None,
    job_title: str | None = None,
    context: TargetContext | None = None,
    model: str = GEMINI_MODEL,
) -> dict | None:
    ctx = context if context is not None else resolve_target_context(industry, job_title)
    api_key = get_gemini_api_key()

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig
    except ImportError:
        raise ImportError("Install google-genai: pip install google-genai")

    text = company_text[:32000] if len(company_text) > 32000 else company_text
    client = genai.Client(api_key=api_key)

    response = gemini_call(
        lambda: client.models.generate_content(
            model=model,
            contents=f"Target company website text:\n\n{text}",
            config=GenerateContentConfig(
                system_instruction=_drafter_system_instruction(ctx),
                response_mime_type="application/json",
            ),
        ),
        label="drafter",
    )

    content = response.text
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
