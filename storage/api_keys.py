"""
API key management — generate, validate, and revoke API keys per user.
Keys are stored as SHA-256 hashes. The full key is shown only once at creation.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from storage.drafts import _USE_POSTGRES, _conn, _P, _now, _fetchone_pg, _fetchall_pg


@dataclass
class ApiKey:
    id: int
    user_id: int
    name: str
    preview: str       # e.g. "outly_sk_a1b2..." — first 20 chars for display
    created_at: str
    last_used_at: str | None
    is_active: bool


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_api_keys_table() -> None:
    if _USE_POSTGRES:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    name TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    preview TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                )
            """)
    else:
        with _conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    preview TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1
                )
            """)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> str:
    return f"outly_sk_{secrets.token_hex(24)}"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_api_key(user_id: int, name: str) -> tuple[str, ApiKey]:
    """
    Generate a new API key for a user.
    Returns (full_key, ApiKey) — full_key is shown only once, then discarded.
    """
    init_api_keys_table()
    full_key = generate_key()
    key_hash = _hash(full_key)
    preview = full_key[:20] + "..."
    created = _now()

    if _USE_POSTGRES:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO api_keys (user_id, name, key_hash, preview, created_at) "
                f"VALUES ({_P},{_P},{_P},{_P},{_P}) RETURNING id",
                (user_id, name, key_hash, preview, created),
            )
            key_id = cur.fetchone()[0]
    else:
        with _conn() as conn:
            cur = conn.execute(
                "INSERT INTO api_keys (user_id, name, key_hash, preview, created_at) VALUES (?,?,?,?,?)",
                (user_id, name, key_hash, preview, created),
            )
            key_id = cur.lastrowid

    api_key = ApiKey(id=key_id, user_id=user_id, name=name, preview=preview,
                     created_at=created, last_used_at=None, is_active=True)
    return full_key, api_key


def get_user_by_api_key(raw_key: str) -> dict | None:
    """
    Validate an API key and return the associated user row.
    Also updates last_used_at.
    Returns None if key is invalid or inactive.
    """
    init_api_keys_table()
    key_hash = _hash(raw_key)
    now = _now()

    if _USE_POSTGRES:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT ak.id as key_id, ak.user_id, u.email "
                f"FROM api_keys ak JOIN users u ON u.id = ak.user_id "
                f"WHERE ak.key_hash = {_P} AND ak.is_active = TRUE",
                (key_hash,),
            )
            row = _fetchone_pg(cur)
            if row:
                conn.cursor().execute(
                    f"UPDATE api_keys SET last_used_at = {_P} WHERE id = {_P}",
                    (now, row["key_id"]),
                )
    else:
        with _conn() as conn:
            row = conn.execute(
                "SELECT ak.id as key_id, ak.user_id, u.email "
                "FROM api_keys ak JOIN users u ON u.id = ak.user_id "
                "WHERE ak.key_hash = ? AND ak.is_active = 1",
                (key_hash,),
            ).fetchone()
            row = dict(row) if row else None
            if row:
                conn.execute(
                    "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                    (now, row["key_id"]),
                )

    return row


def list_api_keys(user_id: int) -> list[ApiKey]:
    init_api_keys_table()
    if _USE_POSTGRES:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM api_keys WHERE user_id = {_P} ORDER BY created_at DESC",
                (user_id,),
            )
            rows = _fetchall_pg(cur)
    else:
        with _conn() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()]

    return [
        ApiKey(id=r["id"], user_id=r["user_id"], name=r["name"], preview=r["preview"],
               created_at=r["created_at"], last_used_at=r.get("last_used_at"),
               is_active=bool(r["is_active"]))
        for r in rows
    ]


def revoke_api_key(key_id: int, user_id: int) -> bool:
    """Revoke a key — only the owning user can revoke."""
    init_api_keys_table()
    if _USE_POSTGRES:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE api_keys SET is_active = FALSE WHERE id = {_P} AND user_id = {_P}",
                (key_id, user_id),
            )
            return cur.rowcount > 0
    else:
        with _conn() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET is_active = 0 WHERE id = ? AND user_id = ?",
                (key_id, user_id),
            )
            return cur.rowcount > 0
