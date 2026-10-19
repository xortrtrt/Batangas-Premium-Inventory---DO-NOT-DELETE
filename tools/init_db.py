from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from psycopg2.extras import RealDictCursor
from app.config import database_dsn
from app.security import hash_password

logger = logging.getLogger("app.init_db")

def init_database() -> bool:
    dsn = database_dsn()
    if not dsn:
        logger.warning("DATABASE_URL is not set. Skipping database initialization.")
        return False

    schema_path = PROJECT_ROOT / "database" / "schema.sql"
    
    logger.info("Checking database schema and seed...")
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check if tables exist
            cur.execute("SELECT to_regclass('public.inventory_items') AS exists;")
            res = cur.fetchone()
            if not res or not res["exists"]:
                logger.info("Applying schema.sql...")
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema_sql = f.read()
                cur.execute(schema_sql)
                logger.info("Schema created successfully!")
            else:
                logger.info("Tables already exist.")

            # Seed or update admin account
            admin_email = os.getenv("ADMIN_EMAIL", "admin@batangaspremium.test").strip().lower()
            admin_pass = os.getenv("ADMIN_PASSWORD", "Admin123!@#")
            hashed = hash_password(admin_pass)
            
            cur.execute("SELECT account_id FROM accounts WHERE lower(email) = %s;", (admin_email,))
            row = cur.fetchone()
            if not row:
                cur.execute("""
                    INSERT INTO accounts (account_type, name, email, password_hash, team_leader_role, is_active, activation_status)
                    VALUES ('owner', 'Inventory Admin', %s, %s, 'inventory', true, 'active');
                """, (admin_email, hashed))
                logger.info("Admin account created: %s", admin_email)
            else:
                cur.execute("""
                    UPDATE accounts
                    SET password_hash = %s, is_active = true, activation_status = 'active', account_type = 'owner', team_leader_role = 'inventory'
                    WHERE account_id = %s;
                """, (hashed, row["account_id"]))
                logger.info("Admin account updated: %s", admin_email)
        return True
    except Exception as e:
        logger.error("Error during database initialization: %s", e)
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_database()
