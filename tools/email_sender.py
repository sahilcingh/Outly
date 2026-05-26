"""
SMTP email sender for approved drafts.

Requires SMTP_HOST, SMTP_USER, SMTP_PASS in .env (SMTP_PORT defaults to 587).
"""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import get_smtp_config


def send_email(to_addr: str, subject: str, body: str) -> None:
    """Send a plain-text email via configured SMTP server.

    Raises RuntimeError if SMTP settings are not configured.
    Raises smtplib.SMTPException on delivery failure.
    """
    cfg = get_smtp_config()
    if cfg is None:
        raise RuntimeError(
            "SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASS in .env"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    cls = smtplib.SMTP_SSL if not cfg["use_tls"] and cfg["port"] == 465 else smtplib.SMTP
    with cls(cfg["host"], cfg["port"]) as server:
        if cfg["use_tls"]:
            server.starttls()
        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from_addr"], [to_addr], msg.as_string())
