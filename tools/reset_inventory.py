"""Explicit, backed-up inventory reset. Never invoked by application startup."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import database_dsn
from app.security import hash_password, validate_password_policy

CLEAR_TABLES = (
    "accounts", "activity_logs", "alerts", "business_settings", "inventory_batches",
    "inventory_dispatches", "inventory_movements", "notification_recipients", "notifications",
    "product_recipes", "security_events", "user_consents", "web_sessions",
)
KNOWN_TABLES = {*CLEAR_TABLES, "inventory_items", "inventory_schema_migrations"}
LEGACY_TOKEN_TABLES = {"account_password_otps", "account_activation_tokens"}
HISTORY_TRIGGERS = (
    ("inventory_movements", "inventory_movements_immutable"),
    ("inventory_movements", "inventory_movements_no_truncate"),
    ("inventory_dispatches", "inventory_dispatches_immutable"),
    ("inventory_dispatches", "inventory_dispatches_no_truncate"),
)


def reset_inventory(dsn: str, *, apply: bool = False, backup: Path | None = None,
                    credentials: list[dict] | None = None) -> dict:
    """Preserve product identities; purge operational data and replace the logins atomically."""
    hashed_accounts = []
    if apply:
        if backup is None or not backup.is_file() or backup.stat().st_size < 50:
            raise ValueError("A full database backup is required before applying the reset.")
        with backup.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                raise ValueError("Expected a PostgreSQL custom-format backup.")
        expected = [f"BPadmin{i}" for i in range(1, 5)]
        if not credentials or [item.get("username") for item in credentials] != expected:
            raise ValueError("Provide exactly BPadmin1 through BPadmin4.")
        passwords = [validate_password_policy(item["password"]) for item in credentials]
        if len(set(passwords)) != 4:
            raise ValueError("Each new account needs a unique password.")
        hashed_accounts = [(name, hash_password(password)) for name, password in zip(expected, passwords)]

    with psycopg2.connect(dsn) as connection:
        connection.set_session(readonly=not apply)
        with connection.cursor(cursor_factory=RealDictCursor) as cur:
            if apply:
                cur.execute("SET LOCAL lock_timeout = '15s'")
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('inventory-schema-migrations'))")
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")
            tables = {row["tablename"] for row in cur.fetchall()}
            if not KNOWN_TABLES.issubset(tables) or tables - KNOWN_TABLES - LEGACY_TOKEN_TABLES:
                raise ValueError("Unexpected database tables; reset stopped for inspection.")
            clear_tables = (*CLEAR_TABLES, *sorted(tables & LEGACY_TOKEN_TABLES))
            if apply:
                cur.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in sorted(tables))))

            def catalog():
                cur.execute("""SELECT item_id, item_type, name, category, description, unit, is_active, created_at
                    FROM inventory_items WHERE item_type='finished_product' ORDER BY item_id""")
                return cur.fetchall()

            products = catalog()
            if not products:
                raise ValueError("No finished products found; reset stopped.")
            counts = {}
            for table in clear_tables:
                cur.execute(sql.SQL("SELECT count(*) AS total FROM {}").format(sql.Identifier(table)))
                counts[table] = cur.fetchone()["total"]
            cur.execute("SELECT count(*) AS total FROM inventory_items WHERE item_type='raw_material'")
            counts["raw_materials"] = cur.fetchone()["total"]
            report = {"applied": False, "finished_products_kept": len(products), "records_to_clear": counts}
            if not apply:
                return report

            # The user-authorized full reset is the sole exception to immutable history.
            # Trigger changes and all data changes share this transaction; failures roll back both.
            for table, trigger in HISTORY_TRIGGERS:
                cur.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
                    sql.Identifier(table), sql.Identifier(trigger)))
            cur.execute(sql.SQL("TRUNCATE TABLE {} CONTINUE IDENTITY").format(
                sql.SQL(", ").join(sql.Identifier(table) for table in clear_tables)))
            cur.execute("DELETE FROM inventory_items WHERE item_type='raw_material'")
            cur.execute("UPDATE inventory_items SET quantity_available=0 WHERE item_type='finished_product'")
            for username, password_hash in hashed_accounts:
                cur.execute("""INSERT INTO accounts
                    (account_type, name, username, email, password_hash, team_leader_role, is_active, activation_status)
                    VALUES ('owner', %s, %s, NULL, %s, 'inventory', true, 'active')""",
                    (username, username, password_hash))
            for table, trigger in HISTORY_TRIGGERS:
                cur.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER {}").format(
                    sql.Identifier(table), sql.Identifier(trigger)))
            if catalog() != products:
                raise RuntimeError("Finished-product catalog changed unexpectedly; reset rolled back.")
            report.update(applied=True, accounts_created=[name for name, _ in hashed_accounts])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--credentials-file", type=Path, help="Local JSON file containing an accounts array.")
    args = parser.parse_args()
    credentials = json.loads(args.credentials_file.read_text(encoding="utf-8"))["accounts"] if args.credentials_file else None
    print(json.dumps(reset_inventory(database_dsn(), apply=args.apply, backup=args.backup,
                                     credentials=credentials), indent=2))
