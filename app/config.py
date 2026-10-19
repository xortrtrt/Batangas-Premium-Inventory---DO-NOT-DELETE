from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

APP_ENV = os.getenv("APP_ENV", "development")
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "meattrack-inventory-secure-secret-key-2026")

def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

AUTH_RATE_LIMIT_ENABLED = env_bool("AUTH_RATE_LIMIT_ENABLED", False)
CSRF_PROTECTION_ENABLED = env_bool("CSRF_PROTECTION_ENABLED", True)
RATE_LIMIT_HASH_KEY = os.getenv("RATE_LIMIT_HASH_KEY", SESSION_SECRET_KEY + ":rate-limits").strip()
BUSINESS_TIMEZONE = os.getenv("BUSINESS_TIMEZONE", "Asia/Manila").strip() or "Asia/Manila"
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "meattrack_inventory_session").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
LOGIN_OTP_ENABLED = env_bool("LOGIN_OTP_ENABLED", False)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    database_user = quote(os.getenv("POSTGRES_USER", "postgres"), safe="")
    database_password = quote(os.getenv("POSTGRES_PASSWORD", "postgres"), safe="")
    database_host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    database_port = os.getenv("POSTGRES_PORT", "5432")
    database_name = quote(os.getenv("POSTGRES_DB", "meattrack_inventory"), safe="")
    DATABASE_URL = (
        f"postgresql://{database_user}:{database_password}"
        f"@{database_host}:{database_port}/{database_name}"
    )

DATABASE_POOL_MIN = int(os.getenv("DATABASE_POOL_MIN", "1"))
DATABASE_POOL_MAX = int(os.getenv("DATABASE_POOL_MAX", "5"))

CONSENT_VERSION = os.getenv("CONSENT_VERSION", "2026-07-22")

def database_dsn(value: str = DATABASE_URL) -> str:
    """Normalize PostgreSQL URLs accepted by psycopg2 (e.g. Render / Neon postgres:// to postgresql://)."""
    if value.startswith("postgres://"):
        value = "postgresql://" + value.removeprefix("postgres://")
    return value
