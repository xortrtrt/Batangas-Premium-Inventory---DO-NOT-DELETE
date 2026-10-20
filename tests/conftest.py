from __future__ import annotations

import os
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn
import pytest

# Never infer a test database from a deployed DATABASE_URL or a .env file.
os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = "postgresql://unused:unused@127.0.0.1:1/unused"
os.environ["AUTH_RATE_LIMIT_ENABLED"] = "true"
os.environ["CSRF_PROTECTION_ENABLED"] = "true"

from app import database
from tools.migrate_database import migrate_database


@pytest.fixture
def inventory_db(monkeypatch):
    base = os.getenv("TEST_DATABASE_URL")
    if not base:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database.")
    schema = f"inventory_test_{uuid4().hex}"
    admin = psycopg2.connect(base)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_dsn(base, options=f"-csearch_path={schema}")
    migrate_database(dsn)
    monkeypatch.setattr(database, "DSN", dsn)
    monkeypatch.setattr(database, "pool", None)
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO accounts(account_type, name, email, password_hash, team_leader_role)
                VALUES ('owner', 'Test Inventory', 'inventory@test.invalid', 'unused', 'inventory') RETURNING account_id""")
            actor = cur.fetchone()[0]
    try:
        yield dsn, actor
    finally:
        if database.pool:
            database.pool.closeall()
            database.pool = None
        with admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()
