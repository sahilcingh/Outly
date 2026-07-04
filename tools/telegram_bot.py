"""
Telegram Bot API client for the job application automation.

Uses the Bot API directly via requests — no additional library required.
All calls target the configured TELEGRAM_CHAT_ID (the user's personal chat).
"""

from __future__ import annotations

import logging

import requests

from config import get_telegram_token, get_telegram_chat_id

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str | None:
    return get_telegram_token()


def _chat_id() -> str | None:
    return get_telegram_chat_id()


def _call(method: str, data: dict) -> dict | None:
    token = _token()
    if not token:
        log.warning("TELEGRAM_BOT_TOKEN not set — skipping Telegram call")
        return None
    url = _API.format(token=token, method=method)
    try:
        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()
        if not result.get("ok"):
            log.warning("Telegram API error (%s): %s", method, result.get("description"))
        return result
    except Exception as e:
        log.error("Telegram request failed (%s): %s", method, e)
        return None


def _markup(job_id: int) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve_{job_id}"},
            {"text": "❌ Reject",  "callback_data": f"reject_{job_id}"},
        ]]
    }


def send_message(text: str, parse_mode: str = "Markdown") -> int | None:
    """Send a plain text message. Returns message_id or None."""
    chat_id = _chat_id()
    if not chat_id:
        log.warning("TELEGRAM_CHAT_ID not set")
        return None
    result = _call("sendMessage", {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": parse_mode,
    })
    return result["result"]["message_id"] if result and result.get("ok") else None


def send_job_for_approval(job) -> int | None:
    """
    Send a job application to Telegram for the user to approve or reject.
    Returns the Telegram message_id (used to edit on revision).
    `job` is a JobApplication instance.
    """
    chat_id = _chat_id()
    if not chat_id:
        return None

    score = job.match_score
    score_emoji = "🟢" if score >= 70 else "🟡" if score >= 40 else "🔴"

    apply_info = ""
    if job.apply_method == "email" and job.contact_email:
        apply_info = f"📧 *Apply via:* Email → `{job.contact_email}`"
    elif job.ats_url:
        short = job.ats_url[:60] + ("…" if len(job.ats_url) > 60 else "")
        apply_info = f"🔗 *Apply via:* ATS → {short}"
    else:
        apply_info = f"🔗 *Apply via:* {job.job_url[:60]}"

    matches = ""
    if job.key_matches:
        matches = "\n".join(f"  ✅ {m}" for m in job.key_matches[:4])
    gaps = ""
    if job.gaps:
        gaps = "\n".join(f"  ⚠️ {g}" for g in job.gaps[:2])

    letter_preview = (job.cover_letter or "")[:900]
    if len(job.cover_letter or "") > 900:
        letter_preview += "\n…_(truncated — full letter in web app)_"

    revision_note = ""
    if job.revision_count > 0:
        revision_note = f"\n_📝 This is revision #{job.revision_count}_\n"

    text = (
        f"🔍 *Job Review — #{job.id}*{revision_note}\n\n"
        f"*{job.job_title}* at *{job.company_name}*\n"
        f"📍 {job.location or 'Remote'} | {job.source} | Score: {score_emoji} {score}%\n\n"
        f"{apply_info}\n\n"
        f"*Why you match:*\n{matches}\n"
        + (f"*Gaps:*\n{gaps}\n" if gaps else "")
        + f"\n*Rationale:* {(job.match_rationale or '')[:200]}\n\n"
        f"───────────────\n"
        f"*Cover Letter:*\n{letter_preview}"
    )

    result = _call("sendMessage", {
        "chat_id":      chat_id,
        "text":         text,
        "parse_mode":   "Markdown",
        "reply_markup": _markup(job.id),
    })
    return result["result"]["message_id"] if result and result.get("ok") else None


def edit_job_message(message_id: int, job) -> None:
    """Update an existing job message after cover letter revision."""
    chat_id = _chat_id()
    if not chat_id or not message_id:
        return

    letter_preview = (job.cover_letter or "")[:900]
    text = (
        f"📝 *Revised Cover Letter — #{job.id}*\n\n"
        f"*{job.job_title}* at *{job.company_name}*\n"
        f"Score: {job.match_score}%\n\n"
        f"*Cover Letter (revision {job.revision_count}):*\n{letter_preview}"
    )
    _call("editMessageText", {
        "chat_id":      chat_id,
        "message_id":   message_id,
        "text":         text,
        "parse_mode":   "Markdown",
        "reply_markup": _markup(job.id),
    })


def send_document(file_bytes: bytes, filename: str, caption: str = "") -> int | None:
    """Send a file (PDF, etc.) to the configured chat. Returns message_id or None."""
    token = _token()
    chat_id = _chat_id()
    if not token or not chat_id:
        log.warning("Telegram token/chat_id missing — cannot send document")
        return None
    url = _API.format(token=token, method="sendDocument")
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={"document": (filename, file_bytes, "application/pdf")},
            timeout=30,
        )
        result = resp.json()
        if not result.get("ok"):
            log.warning("sendDocument error: %s", result.get("description"))
            return None
        return result["result"]["message_id"]
    except Exception as e:
        log.error("sendDocument failed: %s", e)
        return None


def answer_callback(callback_query_id: str, text: str = "") -> None:
    _call("answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text,
    })


def register_webhook(webhook_url: str) -> bool:
    result = _call("setWebhook", {"url": webhook_url})
    if result and result.get("ok"):
        log.info("Telegram webhook registered: %s", webhook_url)
        return True
    log.error("Telegram webhook registration failed: %s", result)
    return False


def download_document(file_id: str) -> bytes | None:
    """Download a file from Telegram and return raw bytes."""
    token = _token()
    if not token:
        return None
    info = _call("getFile", {"file_id": file_id})
    if not info or not info.get("ok"):
        return None
    file_path = info["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        log.error("Failed to download Telegram file: %s", e)
        return None
