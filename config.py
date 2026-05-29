"""
Centralized configuration for the prospecting agent.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

WORKSPACE_ROOT = Path(__file__).resolve().parent

def _resolve_data_dir() -> Path:
    """
    Resolve the data directory. Falls back to the workspace data/ folder if the
    configured path can't be created (e.g. DATA_DIR=/data without a mounted disk).
    """
    configured = Path(os.getenv("DATA_DIR", str(WORKSPACE_ROOT / "data")))
    try:
        configured.mkdir(parents=True, exist_ok=True)
        return configured
    except (PermissionError, OSError):
        fallback = WORKSPACE_ROOT / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

DATA_DIR = _resolve_data_dir()
DRAFTS_DB_PATH = DATA_DIR / "drafts.db"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        raise ValueError(f"{name} not set. Put it in `.env` or environment variables.")
    return value


def get_gemini_api_key() -> str:
    return require_env("GEMINI_API_KEY")


def get_database_url() -> str | None:
    """Return PostgreSQL DATABASE_URL if set, else None (falls back to SQLite)."""
    return os.getenv("DATABASE_URL", "").strip() or None


# gemini-2.0-flash: 1500 req/day free, available on v1beta, fast and capable
GEMINI_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")


def get_secret_key() -> str:
    """Secret key for signing session cookies. Must be set in production."""
    return os.getenv("SECRET_KEY", "dev-secret-change-in-production")


def get_app_password() -> str | None:
    """Password required to access the app. If not set, auth is disabled (local dev only)."""
    return os.getenv("APP_PASSWORD", "").strip() or None


# ---------------------------------------------------------------------------
# SMTP (optional) — set these in .env to enable --send
# ---------------------------------------------------------------------------

def get_smtp_config() -> dict | None:
    """Return SMTP settings dict if all required vars are present, else None."""
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASS", "").strip()
    if not (host and user and password):
        return None
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": user,
        "password": password,
        "from_addr": os.getenv("SMTP_FROM", user),
        "use_tls": os.getenv("SMTP_TLS", "true").lower() != "false",
    }
