"""
Persist the candidate profile extracted from the Telegram-uploaded resume.

Stored in the database (PostgreSQL in prod, SQLite locally) so it survives
Render redeploys — a local file would be wiped on the free tier's ephemeral disk.
Single profile per user; always the latest sent resume.
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

# Legacy file location — read as a one-time fallback for older deployments
_LEGACY_PATH = None
try:
    from config import DATA_DIR
    _LEGACY_PATH = DATA_DIR / "telegram_profile.json"
except Exception:
    pass


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
    CREATE TABLE IF NOT EXISTS candidate_profiles (
        user_id      INTEGER PRIMARY KEY,
        profile_json TEXT NOT NULL,
        updated_at   TEXT
    )
    """
    with _conn() as conn:
        conn.cursor().execute(sql)


def save_profile(profile: dict, user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_scheduler_user_id()
    payload = json.dumps(profile, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    ph = "%s" if _USE_POSTGRES else "?"
    try:
        _ensure_table()
        with _conn() as conn:
            cur = conn.cursor()
            if _USE_POSTGRES:
                cur.execute(
                    f"""INSERT INTO candidate_profiles (user_id, profile_json, updated_at)
                        VALUES ({ph},{ph},{ph})
                        ON CONFLICT (user_id)
                        DO UPDATE SET profile_json = EXCLUDED.profile_json,
                                      updated_at   = EXCLUDED.updated_at""",
                    (uid, payload, now),
                )
            else:
                cur.execute(
                    f"""INSERT OR REPLACE INTO candidate_profiles
                        (user_id, profile_json, updated_at) VALUES ({ph},{ph},{ph})""",
                    (uid, payload, now),
                )
        log.info("Candidate profile saved to DB for user %s", uid)
    except Exception as e:
        log.error("Failed to save profile to DB: %s", e)


def load_profile(user_id: int | None = None) -> dict | None:
    uid = user_id if user_id is not None else get_scheduler_user_id()
    ph = "%s" if _USE_POSTGRES else "?"
    try:
        _ensure_table()
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT profile_json FROM candidate_profiles WHERE user_id = {ph}", (uid,))
            row = cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        log.error("Failed to load profile from DB: %s", e)

    # One-time fallback: migrate a legacy file profile into the DB if present
    if _LEGACY_PATH and _LEGACY_PATH.exists():
        try:
            data = json.loads(_LEGACY_PATH.read_text(encoding="utf-8"))
            if data:
                save_profile(data, uid)
                log.info("Migrated legacy file profile into DB")
                return data
        except Exception:
            pass
    return None
