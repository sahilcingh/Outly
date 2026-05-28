"""
Storage for prospecting email drafts.
Auto-detects backend:
  - DATABASE_URL set → PostgreSQL (production / Render + Neon)
  - DATABASE_URL not set → SQLite (local development)
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator

from config import DRAFTS_DB_PATH, get_database_url

# ---------------------------------------------------------------------------
# Detect backend once at import time
# ---------------------------------------------------------------------------

_DATABASE_URL = get_database_url()
_USE_POSTGRES = bool(_DATABASE_URL)

if _USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    # Neon/Render supply "postgres://..." but psycopg2 needs "postgresql://..."
    _PG_DSN = _DATABASE_URL.replace("postgres://", "postgresql://", 1)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Draft:
    id: int | None
    company_name: str
    company_url: str
    subject: str
    body: str
    rationale: str
    status: str          # draft | approved | sent | rejected
    created_at: str
    prompt_version: str = "v1"


@dataclass
class CompanyProfile:
    id: int | None
    company_name: str
    company_url: str
    profile_json: dict
    created_at: str


@dataclass
class OutreachTouch:
    id: int | None
    company_name: str
    company_url: str
    touch_index: int
    channel: str         # email | linkedin | call
    subject: str
    body: str
    rationale: str
    status: str          # draft | approved | sent | rejected
    created_at: str
    send_after: str | None = None


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

@contextmanager
def _pg_conn() -> Generator:
    conn = psycopg2.connect(_PG_DSN)
    conn.autocommit = False
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
    DRAFTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DRAFTS_DB_PATH)
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


# Placeholder differs between backends
_P = "%s" if _USE_POSTGRES else "?"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create tables if they do not exist. Safe to call multiple times."""
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id BIGSERIAL PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    company_url TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    prompt_version TEXT NOT NULL DEFAULT 'v1'
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS company_profiles (
                    id BIGSERIAL PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    company_url TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS outreach_touches (
                    id BIGSERIAL PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    company_url TEXT NOT NULL,
                    touch_index INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    send_after TEXT
                )
            """)
    else:
        DRAFTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _sqlite_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    company_url TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    prompt_version TEXT NOT NULL DEFAULT 'v1'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS company_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    company_url TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outreach_touches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    company_url TEXT NOT NULL,
                    touch_index INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    send_after TEXT
                )
            """)
            # Migrations for older SQLite DBs
            existing = {row[1] for row in conn.execute("PRAGMA table_info(drafts)")}
            if "prompt_version" not in existing:
                conn.execute("ALTER TABLE drafts ADD COLUMN prompt_version TEXT NOT NULL DEFAULT 'v1'")
            existing_t = {row[1] for row in conn.execute("PRAGMA table_info(outreach_touches)")}
            if "send_after" not in existing_t:
                conn.execute("ALTER TABLE outreach_touches ADD COLUMN send_after TEXT")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fetchall_pg(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetchone_pg(cur) -> dict | None:
    if cur.description is None:
        return None
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

def company_already_drafted(company_url: str) -> bool:
    init_db()
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT 1 FROM drafts WHERE company_url = {_P} LIMIT 1", (company_url,))
            if cur.fetchone():
                return True
            cur.execute(f"SELECT 1 FROM outreach_touches WHERE company_url = {_P} LIMIT 1", (company_url,))
            return bool(cur.fetchone())
    else:
        with _sqlite_conn() as conn:
            if conn.execute("SELECT 1 FROM drafts WHERE company_url = ? LIMIT 1", (company_url,)).fetchone():
                return True
            return bool(conn.execute("SELECT 1 FROM outreach_touches WHERE company_url = ? LIMIT 1", (company_url,)).fetchone())


def save_draft(
    company_name: str,
    company_url: str,
    subject: str,
    body: str,
    rationale: str,
    prompt_version: str = "v1",
) -> int:
    init_db()
    created = _now()
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""INSERT INTO drafts (company_name, company_url, subject, body, rationale, status, created_at, prompt_version)
                    VALUES ({_P},{_P},{_P},{_P},{_P},'draft',{_P},{_P}) RETURNING id""",
                (company_name, company_url, subject, body, rationale, created, prompt_version),
            )
            return cur.fetchone()[0]
    else:
        with _sqlite_conn() as conn:
            cur = conn.execute(
                "INSERT INTO drafts (company_name, company_url, subject, body, rationale, status, created_at, prompt_version) VALUES (?,?,?,?,?,'draft',?,?)",
                (company_name, company_url, subject, body, rationale, created, prompt_version),
            )
            return cur.lastrowid


def get_draft(draft_id: int) -> Draft | None:
    init_db()
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM drafts WHERE id = {_P}", (draft_id,))
            row = _fetchone_pg(cur)
    else:
        with _sqlite_conn() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
            row = dict(row) if row else None

    if not row:
        return None
    return Draft(
        id=row["id"], company_name=row["company_name"], company_url=row["company_url"],
        subject=row["subject"], body=row["body"], rationale=row["rationale"],
        status=row["status"], created_at=row["created_at"], prompt_version=row["prompt_version"],
    )


def list_drafts(status: str | None = None) -> list[Draft]:
    init_db()
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            if status:
                cur.execute(f"SELECT * FROM drafts WHERE status = {_P} ORDER BY created_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM drafts ORDER BY created_at DESC")
            rows = _fetchall_pg(cur)
    else:
        with _sqlite_conn() as conn:
            if status:
                rows = [dict(r) for r in conn.execute("SELECT * FROM drafts WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()]
            else:
                rows = [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY created_at DESC").fetchall()]

    return [
        Draft(id=r["id"], company_name=r["company_name"], company_url=r["company_url"],
              subject=r["subject"], body=r["body"], rationale=r["rationale"],
              status=r["status"], created_at=r["created_at"], prompt_version=r["prompt_version"])
        for r in rows
    ]


def update_draft_status(draft_id: int, status: str) -> bool:
    if status not in {"draft", "approved", "sent", "rejected"}:
        raise ValueError("status must be one of: draft, approved, sent, rejected")
    init_db()
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE drafts SET status = {_P} WHERE id = {_P}", (status, draft_id))
            return cur.rowcount > 0
    else:
        with _sqlite_conn() as conn:
            cur = conn.execute("UPDATE drafts SET status = ? WHERE id = ?", (status, draft_id))
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Company profiles
# ---------------------------------------------------------------------------

def save_company_profile(company_name: str, company_url: str, profile: dict) -> int:
    init_db()
    created = _now()
    blob = json.dumps(profile, ensure_ascii=False)
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO company_profiles (company_name, company_url, profile_json, created_at) VALUES ({_P},{_P},{_P},{_P}) RETURNING id",
                (company_name, company_url, blob, created),
            )
            return cur.fetchone()[0]
    else:
        with _sqlite_conn() as conn:
            cur = conn.execute(
                "INSERT INTO company_profiles (company_name, company_url, profile_json, created_at) VALUES (?,?,?,?)",
                (company_name, company_url, blob, created),
            )
            return cur.lastrowid


# ---------------------------------------------------------------------------
# Outreach touches
# ---------------------------------------------------------------------------

def save_outreach_touch(
    company_name: str, company_url: str, touch_index: int, channel: str,
    subject: str, body: str, rationale: str, send_after: str | None = None,
) -> int:
    init_db()
    created = _now()
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""INSERT INTO outreach_touches
                    (company_name, company_url, touch_index, channel, subject, body, rationale, status, created_at, send_after)
                    VALUES ({_P},{_P},{_P},{_P},{_P},{_P},{_P},'draft',{_P},{_P}) RETURNING id""",
                (company_name, company_url, touch_index, channel, subject, body, rationale, created, send_after),
            )
            return cur.fetchone()[0]
    else:
        with _sqlite_conn() as conn:
            cur = conn.execute(
                "INSERT INTO outreach_touches (company_name, company_url, touch_index, channel, subject, body, rationale, status, created_at, send_after) VALUES (?,?,?,?,?,?,?,'draft',?,?)",
                (company_name, company_url, touch_index, channel, subject, body, rationale, created, send_after),
            )
            return cur.lastrowid


def update_touch_status(touch_id: int, status: str) -> bool:
    if status not in {"draft", "approved", "sent", "rejected"}:
        raise ValueError("status must be one of: draft, approved, sent, rejected")
    init_db()
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE outreach_touches SET status = {_P} WHERE id = {_P}", (status, touch_id))
            return cur.rowcount > 0
    else:
        with _sqlite_conn() as conn:
            cur = conn.execute("UPDATE outreach_touches SET status = ? WHERE id = ?", (status, touch_id))
            return cur.rowcount > 0


def list_outreach_touches(company_url: str | None = None, status: str | None = None) -> list[OutreachTouch]:
    init_db()
    where, params = [], []
    if company_url:
        where.append(f"company_url = {_P}"); params.append(company_url)
    if status:
        where.append(f"status = {_P}"); params.append(status)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM outreach_touches {where_sql} ORDER BY created_at DESC, touch_index ASC", params)
            rows = _fetchall_pg(cur)
    else:
        with _sqlite_conn() as conn:
            rows = [dict(r) for r in conn.execute(
                f"SELECT * FROM outreach_touches {where_sql} ORDER BY created_at DESC, touch_index ASC", params
            ).fetchall()]

    return [
        OutreachTouch(
            id=r["id"], company_name=r["company_name"], company_url=r["company_url"],
            touch_index=r["touch_index"], channel=r["channel"], subject=r["subject"],
            body=r["body"], rationale=r["rationale"], status=r["status"],
            created_at=r["created_at"], send_after=r.get("send_after"),
        )
        for r in rows
    ]


def list_due_touches(as_of: str | None = None) -> list[OutreachTouch]:
    init_db()
    today = as_of or datetime.now(timezone.utc).date().isoformat()
    if _USE_POSTGRES:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM outreach_touches WHERE status = 'approved' AND send_after IS NOT NULL AND send_after <= {_P} ORDER BY send_after ASC, touch_index ASC",
                (today,),
            )
            rows = _fetchall_pg(cur)
    else:
        with _sqlite_conn() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM outreach_touches WHERE status = 'approved' AND send_after IS NOT NULL AND send_after <= ? ORDER BY send_after ASC, touch_index ASC",
                (today,),
            ).fetchall()]

    return [
        OutreachTouch(
            id=r["id"], company_name=r["company_name"], company_url=r["company_url"],
            touch_index=r["touch_index"], channel=r["channel"], subject=r["subject"],
            body=r["body"], rationale=r["rationale"], status=r["status"],
            created_at=r["created_at"], send_after=r.get("send_after"),
        )
        for r in rows
    ]
