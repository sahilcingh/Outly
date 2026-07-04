"""
Storage for job applications.
Same dual-mode pattern as storage/drafts.py — PostgreSQL in prod, SQLite locally.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator

from config import DRAFTS_DB_PATH, get_database_url

_DATABASE_URL = get_database_url()
_USE_POSTGRES = bool(_DATABASE_URL)

if _USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    _PG_DSN = _DATABASE_URL.replace("postgres://", "postgresql://", 1)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class JobApplication:
    id: int | None
    user_id: int | None
    job_title: str
    company_name: str
    company_url: str | None
    job_url: str
    location: str
    is_remote: bool
    date_posted: str
    source: str                 # linkedin | indeed
    job_description: str
    match_score: int            # 0-100
    match_rationale: str
    key_matches: str            # JSON list stored as text
    gaps: str                   # JSON list stored as text
    cover_letter: str
    subject_line: str
    apply_method: str           # email | ats_greenhouse | ats_lever | ... | manual
    contact_email: str | None
    ats_url: str | None
    status: str                 # queued | telegram_pending | awaiting_feedback | applied | rejected
    applied_at: str | None
    created_at: str
    candidate_name: str
    candidate_role: str
    telegram_message_id: int | None = None
    revision_count: int = 0
    revision_feedback: str = ""


# ---------------------------------------------------------------------------
# Connection helpers (identical pattern to drafts.py)
# ---------------------------------------------------------------------------

@contextmanager
def _pg_conn() -> Generator:
    conn = psycopg2.connect(_PG_DSN)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _sqlite_conn() -> Generator:
    conn = sqlite3.connect(str(DRAFTS_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _conn():
    return _pg_conn() if _USE_POSTGRES else _sqlite_conn()


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS job_applications (
    id                  {pk},
    user_id             INTEGER,
    job_title           TEXT NOT NULL,
    company_name        TEXT NOT NULL,
    company_url         TEXT,
    job_url             TEXT NOT NULL,
    location            TEXT,
    is_remote           INTEGER DEFAULT 0,
    date_posted         TEXT,
    source              TEXT,
    job_description     TEXT,
    match_score         INTEGER DEFAULT 0,
    match_rationale     TEXT,
    key_matches         TEXT DEFAULT '[]',
    gaps                TEXT DEFAULT '[]',
    cover_letter        TEXT,
    subject_line        TEXT,
    apply_method        TEXT DEFAULT 'manual',
    contact_email       TEXT,
    ats_url             TEXT,
    status              TEXT DEFAULT 'queued',
    applied_at          TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    candidate_name      TEXT DEFAULT '',
    candidate_role      TEXT DEFAULT '',
    telegram_message_id INTEGER DEFAULT NULL,
    revision_count      INTEGER DEFAULT 0,
    revision_feedback   TEXT DEFAULT ''
)
"""

_MIGRATIONS = [
    "ALTER TABLE job_applications ADD COLUMN telegram_message_id INTEGER DEFAULT NULL",
    "ALTER TABLE job_applications ADD COLUMN revision_count INTEGER DEFAULT 0",
    "ALTER TABLE job_applications ADD COLUMN revision_feedback TEXT DEFAULT ''",
]


def init_jobs_table() -> None:
    pk = "SERIAL PRIMARY KEY" if _USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    sql = _CREATE_TABLE.format(pk=pk)
    # CREATE TABLE in its own transaction
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
    # Each migration in its own transaction so a failure doesn't abort the others
    for migration in _MIGRATIONS:
        try:
            with _conn() as conn:
                cur = conn.cursor()
                cur.execute(migration)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_job_application(
    user_id: int | None,
    job_title: str,
    company_name: str,
    job_url: str,
    location: str,
    is_remote: bool,
    date_posted: str,
    source: str,
    job_description: str,
    match_score: int,
    match_rationale: str,
    key_matches: list,
    gaps: list,
    cover_letter: str,
    subject_line: str,
    apply_method: str,
    contact_email: str | None,
    ats_url: str | None,
    company_url: str | None = None,
    candidate_name: str = "",
    candidate_role: str = "",
) -> int:
    """Insert a new job application row; returns the new row id."""
    ph = "%s" if _USE_POSTGRES else "?"
    sql = f"""
        INSERT INTO job_applications
            (user_id, job_title, company_name, company_url, job_url, location,
             is_remote, date_posted, source, job_description, match_score,
             match_rationale, key_matches, gaps, cover_letter, subject_line,
             apply_method, contact_email, ats_url, candidate_name, candidate_role,
             created_at, status)
        VALUES
            ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},
             {ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        {'RETURNING id' if _USE_POSTGRES else ''}
    """
    vals = (
        user_id,
        job_title[:200],
        company_name[:200],
        (company_url or "")[:500],
        job_url[:1000],
        (location or "")[:200],
        1 if is_remote else 0,
        (date_posted or "")[:50],
        (source or "")[:50],
        job_description or "",
        match_score,
        match_rationale or "",
        json.dumps(key_matches or []),
        json.dumps(gaps or []),
        cover_letter or "",
        subject_line or "",
        (apply_method or "manual")[:50],
        (contact_email or "")[:200],
        (ats_url or "")[:1000],
        (candidate_name or "")[:200],
        (candidate_role or "")[:200],
        datetime.now(timezone.utc).isoformat(),
        "queued",
    )
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, vals)
        if _USE_POSTGRES:
            row = cur.fetchone()
            return row[0]
        return cur.lastrowid


def list_job_applications(
    user_id: int | None = None,
    status: str | None = None,
    min_score: int = 0,
) -> list[JobApplication]:
    ph = "%s" if _USE_POSTGRES else "?"
    clauses, params = [], []
    if user_id is not None:
        clauses.append(f"user_id = {ph}")
        params.append(user_id)
    if status:
        clauses.append(f"status = {ph}")
        params.append(status)
    if min_score > 0:
        clauses.append(f"match_score >= {ph}")
        params.append(min_score)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM job_applications {where} ORDER BY match_score DESC, created_at DESC"

    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [_row_to_job(r) for r in rows]


def get_job_application(job_id: int) -> JobApplication | None:
    ph = "%s" if _USE_POSTGRES else "?"
    sql = f"SELECT * FROM job_applications WHERE id = {ph}"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (job_id,))
        row = cur.fetchone()
    return _row_to_job(row) if row else None


def update_job_status(job_id: int, status: str) -> bool:
    ph = "%s" if _USE_POSTGRES else "?"
    applied_at = datetime.now(timezone.utc).isoformat() if status == "applied" else None
    sql = f"UPDATE job_applications SET status = {ph}, applied_at = {ph} WHERE id = {ph}"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (status, applied_at, job_id))
        return cur.rowcount > 0


def update_cover_letter(job_id: int, cover_letter: str) -> bool:
    ph = "%s" if _USE_POSTGRES else "?"
    sql = f"UPDATE job_applications SET cover_letter = {ph} WHERE id = {ph}"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (cover_letter, job_id))
        return cur.rowcount > 0


def get_queued_jobs(user_id: int | None = None, limit: int = 10) -> list[JobApplication]:
    """Fetch jobs with status 'queued', sorted by match_score desc. Used by scheduler."""
    ph = "%s" if _USE_POSTGRES else "?"
    if user_id is not None:
        sql = f"SELECT * FROM job_applications WHERE user_id = {ph} AND status = 'queued' ORDER BY match_score DESC, created_at DESC LIMIT {ph}"
        params = (user_id, limit)
    else:
        sql = f"SELECT * FROM job_applications WHERE status = 'queued' ORDER BY match_score DESC, created_at DESC LIMIT {ph}"
        params = (limit,)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_job(r) for r in rows]


def set_telegram_pending(job_id: int, message_id: int) -> None:
    ph = "%s" if _USE_POSTGRES else "?"
    sql = f"UPDATE job_applications SET status = 'telegram_pending', telegram_message_id = {ph} WHERE id = {ph}"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (message_id, job_id))


def set_awaiting_feedback(job_id: int) -> None:
    ph = "%s" if _USE_POSTGRES else "?"
    sql = f"UPDATE job_applications SET status = 'awaiting_feedback' WHERE id = {ph}"
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (job_id,))


def save_revision(job_id: int, feedback: str, new_cover_letter: str) -> None:
    ph = "%s" if _USE_POSTGRES else "?"
    sql = f"""UPDATE job_applications
              SET revision_feedback = {ph}, cover_letter = {ph},
                  revision_count = revision_count + 1, status = 'queued'
              WHERE id = {ph}"""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (feedback, new_cover_letter, job_id))


def get_awaiting_feedback_job(user_id: int | None) -> JobApplication | None:
    """Fallback: find the most recent job awaiting feedback (for when in-memory state is lost)."""
    ph = "%s" if _USE_POSTGRES else "?"
    if user_id is not None:
        sql = f"SELECT * FROM job_applications WHERE user_id = {ph} AND status = 'awaiting_feedback' ORDER BY created_at DESC LIMIT 1"
        params = (user_id,)
    else:
        sql = "SELECT * FROM job_applications WHERE status = 'awaiting_feedback' ORDER BY created_at DESC LIMIT 1"
        params = ()
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
    return _row_to_job(row) if row else None


def job_already_saved(user_id: int | None, job_url: str) -> bool:
    """Prevent duplicate entries for the same job URL per user."""
    ph = "%s" if _USE_POSTGRES else "?"
    if user_id is not None:
        sql = f"SELECT 1 FROM job_applications WHERE user_id = {ph} AND job_url = {ph} LIMIT 1"
        params = (user_id, job_url)
    else:
        sql = f"SELECT 1 FROM job_applications WHERE job_url = {ph} LIMIT 1"
        params = (job_url,)
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Row converter
# ---------------------------------------------------------------------------

def _row_to_job(row) -> JobApplication:
    if isinstance(row, dict):
        d = row
    else:
        try:
            d = dict(row)
        except Exception:
            keys = [
                "id", "user_id", "job_title", "company_name", "company_url",
                "job_url", "location", "is_remote", "date_posted", "source",
                "job_description", "match_score", "match_rationale", "key_matches",
                "gaps", "cover_letter", "subject_line", "apply_method",
                "contact_email", "ats_url", "status", "applied_at", "created_at",
                "candidate_name", "candidate_role",
            ]
            d = dict(zip(keys, row))

    def _jl(v):
        try:
            return json.loads(v or "[]")
        except Exception:
            return []

    return JobApplication(
        id              = d.get("id"),
        user_id         = d.get("user_id"),
        job_title       = d.get("job_title", ""),
        company_name    = d.get("company_name", ""),
        company_url     = d.get("company_url") or None,
        job_url         = d.get("job_url", ""),
        location        = d.get("location", ""),
        is_remote       = bool(d.get("is_remote", 0)),
        date_posted     = d.get("date_posted", ""),
        source          = d.get("source", ""),
        job_description = d.get("job_description", ""),
        match_score     = int(d.get("match_score", 0)),
        match_rationale = d.get("match_rationale", ""),
        key_matches     = _jl(d.get("key_matches")),
        gaps            = _jl(d.get("gaps")),
        cover_letter    = d.get("cover_letter", ""),
        subject_line    = d.get("subject_line", ""),
        apply_method    = d.get("apply_method", "manual"),
        contact_email   = d.get("contact_email") or None,
        ats_url         = d.get("ats_url") or None,
        status          = d.get("status", "queued"),
        applied_at      = d.get("applied_at") or None,
        created_at      = d.get("created_at", ""),
        candidate_name      = d.get("candidate_name", ""),
        candidate_role      = d.get("candidate_role", ""),
        telegram_message_id = d.get("telegram_message_id"),
        revision_count      = int(d.get("revision_count") or 0),
        revision_feedback   = d.get("revision_feedback") or "",
    )
