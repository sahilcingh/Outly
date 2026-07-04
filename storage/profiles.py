"""
Persist the candidate profile extracted from the Telegram-uploaded resume.
Single-profile storage: always the latest sent resume.
"""

from __future__ import annotations

import json
import logging

from config import DATA_DIR

log = logging.getLogger(__name__)

_PROFILE_PATH = DATA_DIR / "telegram_profile.json"


def save_profile(profile: dict) -> None:
    try:
        _PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Candidate profile saved to %s", _PROFILE_PATH)
    except Exception as e:
        log.error("Failed to save profile: %s", e)


def load_profile() -> dict | None:
    if not _PROFILE_PATH.exists():
        return None
    try:
        return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("Failed to load profile: %s", e)
        return None
