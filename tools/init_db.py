"""Initialize inventory safely; never reset an existing account on restart."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from app.config import database_dsn
from app.security import hash_password, validate_password_policy
from tools.migrate_database import migrate_database


def init_database() -> bool:
    dsn = database_dsn()
    migrate_database(dsn)
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('inventory-account-bootstrap'))")
            # Inactive accounts count: restarts must never bypass deactivation.
            cur.execute("""SELECT 1 FROM accounts WHERE account_type = 'owner'
                OR (account_type = 'team_leader' AND team_leader_role = 'inventory') LIMIT 1""")
            if cur.fetchone():
                return True
            email = os.getenv("ADMIN_EMAIL", "").strip().lower()
            password = os.getenv("ADMIN_PASSWORD", "")
            if not email or "@" not in email or not password:
                raise RuntimeError("No inventory account exists. Set ADMIN_EMAIL and ADMIN_PASSWORD for one-time creation.")
            password = validate_password_policy(password)
            cur.execute("""INSERT INTO accounts
                (account_type, name, email, password_hash, team_leader_role, is_active, activation_status)
                VALUES ('owner', 'Inventory Admin', %s, %s, 'inventory', true, 'active')""",
                (email, hash_password(password)))
    return True


if __name__ == "__main__":
    init_database()
    print("Inventory schema and account are ready.")
