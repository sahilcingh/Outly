"""
User account management — registration, login, password hashing.
Supports the same PostgreSQL / SQLite dual-backend as storage/drafts.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from passlib.context import CryptContext

from storage.drafts import _USE_POSTGRES, _conn, _P, _now, _fetchone_pg

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass
class User:
    id: int
    email: str
    created_at: str


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_users_table() -> None:
    """Create the users table if it does not exist."""
    if _USE_POSTGRES:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
    else:
        with _conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_user(email: str, password: str) -> User | None:
    """
    Register a new user. Returns the created User, or None if email already exists.
    """
    init_users_table()
    email = email.strip().lower()
    pw_hash = _pwd.hash(password)
    created = _now()

    try:
        if _USE_POSTGRES:
            with _conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    f"INSERT INTO users (email, password_hash, created_at) VALUES ({_P},{_P},{_P}) RETURNING id",
                    (email, pw_hash, created),
                )
                user_id = cur.fetchone()[0]
        else:
            with _conn() as conn:
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, created_at) VALUES (?,?,?)",
                    (email, pw_hash, created),
                )
                user_id = cur.lastrowid
        return User(id=user_id, email=email, created_at=created)
    except Exception:
        return None  # email already exists (UNIQUE constraint)


def get_user_by_email(email: str) -> dict | None:
    """Fetch raw user row by email (includes password_hash for verification)."""
    init_users_table()
    email = email.strip().lower()

    if _USE_POSTGRES:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM users WHERE email = {_P} LIMIT 1", (email,))
            return _fetchone_pg(cur)
    else:
        with _conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ? LIMIT 1", (email,)).fetchone()
            return dict(row) if row else None


def verify_login(email: str, password: str) -> User | None:
    """
    Verify email + password. Returns User on success, None on failure.
    """
    row = get_user_by_email(email)
    if not row:
        return None
    if not _pwd.verify(password, row["password_hash"]):
        return None
    return User(id=row["id"], email=row["email"], created_at=row["created_at"])
