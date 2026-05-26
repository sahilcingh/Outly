"""
SQLite storage for prospecting email drafts.
Drafts are saved for human review before sending.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
import json

from config import DRAFTS_DB_PATH

DB_PATH = DRAFTS_DB_PATH


@dataclass
class Draft:
    id: int | None
    company_name: str
    company_url: str
    subject: str
    body: str
    rationale: str
    status: str  # draft | approved | sent | rejected
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
    channel: str  # email | linkedin | call
    subject: str
    body: str
    rationale: str
    status: str  # draft | approved | sent | rejected
    created_at: str
    send_after: str | None = None  # ISO date string: send on or after this date


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after initial schema creation."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(drafts)")}
    if "prompt_version" not in existing:
        conn.execute("ALTER TABLE drafts ADD COLUMN prompt_version TEXT NOT NULL DEFAULT 'v1'")

    existing_touches = {row[1] for row in conn.execute("PRAGMA table_info(outreach_touches)")}
    if "send_after" not in existing_touches:
        conn.execute("ALTER TABLE outreach_touches ADD COLUMN send_after TEXT")


def init_db() -> None:
    """Create required tables if they do not exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
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
        _migrate(conn)


def company_already_drafted(company_url: str) -> bool:
    """Return True if any draft or touch already exists for this URL."""
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM drafts WHERE company_url = ? LIMIT 1", (company_url,)
        ).fetchone()
        if row:
            return True
        row = conn.execute(
            "SELECT 1 FROM outreach_touches WHERE company_url = ? LIMIT 1", (company_url,)
        ).fetchone()
        return row is not None


def save_draft(
    company_name: str,
    company_url: str,
    subject: str,
    body: str,
    rationale: str,
    prompt_version: str = "v1",
) -> int:
    """Insert a new draft and return its id."""
    init_db()
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO drafts (company_name, company_url, subject, body, rationale, status, created_at, prompt_version)
            VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (company_name, company_url, subject, body, rationale, created, prompt_version),
        )
        conn.commit()
        return cur.lastrowid


def get_draft(draft_id: int) -> Draft | None:
    """Fetch a single draft by id."""
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if not row:
            return None
        return Draft(
            id=row["id"],
            company_name=row["company_name"],
            company_url=row["company_url"],
            subject=row["subject"],
            body=row["body"],
            rationale=row["rationale"],
            status=row["status"],
            created_at=row["created_at"],
            prompt_version=row["prompt_version"],
        )


def list_drafts(status: str | None = None) -> list[Draft]:
    """List drafts, optionally filtered by status."""
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if status:
            rows = conn.execute(
                "SELECT * FROM drafts WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM drafts ORDER BY created_at DESC"
            ).fetchall()
        return [
            Draft(
                id=r["id"],
                company_name=r["company_name"],
                company_url=r["company_url"],
                subject=r["subject"],
                body=r["body"],
                rationale=r["rationale"],
                status=r["status"],
                created_at=r["created_at"],
                prompt_version=r["prompt_version"],
            )
            for r in rows
        ]


def update_draft_status(draft_id: int, status: str) -> bool:
    """Update a draft status. Returns True if a row was updated."""
    if status not in {"draft", "approved", "sent", "rejected"}:
        raise ValueError("status must be one of: draft, approved, sent, rejected")
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE drafts SET status = ? WHERE id = ?",
            (status, draft_id),
        )
        conn.commit()
        return cur.rowcount > 0


def save_company_profile(company_name: str, company_url: str, profile: dict) -> int:
    """Insert a company profile JSON blob and return its id."""
    init_db()
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO company_profiles (company_name, company_url, profile_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (company_name, company_url, json.dumps(profile, ensure_ascii=False), created),
        )
        conn.commit()
        return cur.lastrowid


def save_outreach_touch(
    company_name: str,
    company_url: str,
    touch_index: int,
    channel: str,
    subject: str,
    body: str,
    rationale: str,
    send_after: str | None = None,
) -> int:
    """Insert an outreach touch (draft) and return its id."""
    init_db()
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO outreach_touches
                (company_name, company_url, touch_index, channel, subject, body, rationale, status, created_at, send_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (company_name, company_url, touch_index, channel, subject, body, rationale, created, send_after),
        )
        conn.commit()
        return cur.lastrowid


def update_touch_status(touch_id: int, status: str) -> bool:
    """Update outreach touch status. Returns True if a row was updated."""
    if status not in {"draft", "approved", "sent", "rejected"}:
        raise ValueError("status must be one of: draft, approved, sent, rejected")
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE outreach_touches SET status = ? WHERE id = ?",
            (status, touch_id),
        )
        conn.commit()
        return cur.rowcount > 0


def list_outreach_touches(company_url: str | None = None, status: str | None = None) -> list[OutreachTouch]:
    """List outreach touches, optionally filtered by company_url and/or status."""
    init_db()
    where = []
    params: list[object] = []
    if company_url:
        where.append("company_url = ?")
        params.append(company_url)
    if status:
        where.append("status = ?")
        params.append(status)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM outreach_touches {where_sql} ORDER BY created_at DESC, touch_index ASC",
            tuple(params),
        ).fetchall()
        return [
            OutreachTouch(
                id=r["id"],
                company_name=r["company_name"],
                company_url=r["company_url"],
                touch_index=r["touch_index"],
                channel=r["channel"],
                subject=r["subject"],
                body=r["body"],
                rationale=r["rationale"],
                status=r["status"],
                created_at=r["created_at"],
                send_after=r["send_after"],
            )
            for r in rows
        ]


def list_due_touches(as_of: str | None = None) -> list[OutreachTouch]:
    """Return approved touches whose send_after date is today or earlier."""
    init_db()
    today = as_of or datetime.now(timezone.utc).date().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM outreach_touches
            WHERE status = 'approved'
              AND send_after IS NOT NULL
              AND send_after <= ?
            ORDER BY send_after ASC, touch_index ASC
            """,
            (today,),
        ).fetchall()
        return [
            OutreachTouch(
                id=r["id"],
                company_name=r["company_name"],
                company_url=r["company_url"],
                touch_index=r["touch_index"],
                channel=r["channel"],
                subject=r["subject"],
                body=r["body"],
                rationale=r["rationale"],
                status=r["status"],
                created_at=r["created_at"],
                send_after=r["send_after"],
            )
            for r in rows
        ]
