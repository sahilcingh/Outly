"""
SMTP email sender — supports generic SMTP and Gmail app-password.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import get_smtp_config, get_gmail_config

log = logging.getLogger(__name__)


def _get_cfg() -> dict | None:
    """Prefer Gmail config; fall back to generic SMTP."""
    return get_gmail_config() or get_smtp_config()


def send_email(to_addr: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises on misconfiguration or failure."""
    cfg = _get_cfg()
    if cfg is None:
        raise RuntimeError("SMTP not configured. Set GMAIL_USER + GMAIL_APP_PASSWORD in .env")
    _send(cfg, to_addr, subject, body)


def send_application_email(
    to_email: str,
    subject: str,
    body: str,
    from_name: str = "",
) -> bool:
    """
    Send a job application email. Returns True on success, False on failure.
    Uses Gmail if configured, falls back to generic SMTP.
    """
    cfg = _get_cfg()
    if not cfg:
        log.error("No SMTP config found — cannot send application email")
        return False
    try:
        _send(cfg, to_email, subject, body, from_name=from_name)
        log.info("Application email sent to %s: %s", to_email, subject[:60])
        return True
    except Exception as e:
        log.error("Failed to send application email to %s: %s", to_email, e)
        return False


def _send(cfg: dict, to_addr: str, subject: str, body: str, from_name: str = "") -> None:
    from_label = f"{from_name} <{cfg['from_addr']}>" if from_name else cfg["from_addr"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_label
    msg["To"]      = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    use_ssl = (not cfg["use_tls"]) and cfg["port"] == 465
    cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with cls(cfg["host"], cfg["port"], timeout=15) as server:
        if cfg["use_tls"] and not use_ssl:
            server.starttls()
        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from_addr"], [to_addr], msg.as_string())
