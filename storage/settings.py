"""
Per-user chat-settable search preferences (location, min match score,
remote-only) — set via Telegram commands instead of only Render env vars.

Same dual-mode DB pattern as storage/profiles.py. Missing/unset fields fall
back to the global config.py defaults, so this table only needs to hold
overrides a user has actually made.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DRAFTS_DB_PATH, get_database_url, get_scheduler_user_id

log = logging.getLogger(__name__)

_DATABASE_URL = get_database_url()
_USE_POSTGRES = bool(_DATABASE_URL)

if _USE_POSTGRES:
    import psycopg2
    _PG_DSN = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Keys a user is allowed to override, and how to coerce/validate each.
_ALLOWED_KEYS = ("location", "min_score", "remote_only")


@contextmanager
def _conn():
    if _USE_POSTGRES:
        conn = psycopg2.connect(_PG_DSN)
    else:
        conn = sqlite3.connect(str(DRAFTS_DB_PATH))
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_table() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS user_search_settings (
        user_id      INTEGER PRIMARY KEY,
        settings_json TEXT NOT NULL,
        updated_at   TEXT
    )
    """
    with _conn() as conn:
        conn.cursor().execute(sql)


def get_settings(user_id: int | None = None) -> dict:
    """Return the user's saved preference overrides (may be empty)."""
    uid = user_id if user_id is not None else get_scheduler_user_id()
    ph = "%s" if _USE_POSTGRES else "?"
    try:
        _ensure_table()
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT settings_json FROM user_search_settings WHERE user_id = {ph}", (uid,))
            row = cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        log.error("Failed to load search settings: %s", e)
    return {}


def set_setting(key: str, value, user_id: int | None = None) -> None:
    """Set a single preference override (merged into any existing ones)."""
    if key not in _ALLOWED_KEYS:
        raise ValueError(f"Unknown setting: {key}")
    uid = user_id if user_id is not None else get_scheduler_user_id()
    current = get_settings(uid)
    current[key] = value
    payload = json.dumps(current, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    ph = "%s" if _USE_POSTGRES else "?"
    try:
        _ensure_table()
        with _conn() as conn:
            cur = conn.cursor()
            if _USE_POSTGRES:
                cur.execute(
                    f"""INSERT INTO user_search_settings (user_id, settings_json, updated_at)
                        VALUES ({ph},{ph},{ph})
                        ON CONFLICT (user_id)
                        DO UPDATE SET settings_json = EXCLUDED.settings_json,
                                      updated_at    = EXCLUDED.updated_at""",
                    (uid, payload, now),
                )
            else:
                cur.execute(
                    f"""INSERT OR REPLACE INTO user_search_settings
                        (user_id, settings_json, updated_at) VALUES ({ph},{ph},{ph})""",
                    (uid, payload, now),
                )
    except Exception as e:
        log.error("Failed to save search setting %s=%r: %s", key, value, e)
        raise
