"""Ordered, checksum-protected migrations for the inventory database only."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import database_dsn


def migrate_database(dsn: str | None = None) -> None:
    with psycopg2.connect(dsn or database_dsn()) as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('inventory-schema-migrations'))")
            cur.execute("SELECT to_regclass('inventory_items')")
            if cur.fetchone()[0] is None:
                baseline = (PROJECT_ROOT / "database/schema.sql").read_text(encoding="utf-8").strip()
                cur.execute(baseline.removeprefix("BEGIN;").removesuffix("COMMIT;"))
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_schema_migrations (
                    version text PRIMARY KEY, checksum_sha256 text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            for path in sorted((PROJECT_ROOT / "database/migrations").glob("*.sql")):
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                cur.execute("SELECT checksum_sha256 FROM inventory_schema_migrations WHERE version = %s", (path.name,))
                applied = cur.fetchone()
                if applied:
                    if applied[0] != checksum:
                        raise RuntimeError(f"Applied inventory migration changed: {path.name}")
                    continue
                cur.execute(sql)
                cur.execute("INSERT INTO inventory_schema_migrations VALUES (%s, %s, now())", (path.name, checksum))


if __name__ == "__main__":
    migrate_database()
    print("Inventory database migrations are up to date.")
