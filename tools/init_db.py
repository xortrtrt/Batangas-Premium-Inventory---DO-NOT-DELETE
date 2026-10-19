from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from psycopg2.extras import RealDictCursor
from app.config import database_dsn
from app.security import hash_password

def init_database():
    dsn = database_dsn()
    schema_path = PROJECT_ROOT / "database" / "schema.sql"
    
    print(f"Connecting to database...")
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if tables exist
        cur.execute("SELECT to_regclass('public.inventory_items') AS exists;")
        res = cur.fetchone()
        if not res or not res["exists"]:
            print("Applying schema.sql...")
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            cur.execute(schema_sql)
            conn.commit()
            print("Schema created successfully!")
        else:
            print("Tables already exist. Skipping schema creation.")

        # Seed admin account
        admin_email = os.getenv("ADMIN_EMAIL", "admin@batangaspremium.test").strip().lower()
        admin_pass = os.getenv("ADMIN_PASSWORD", "Admin123!@#")
        
        cur.execute("SELECT account_id FROM accounts WHERE lower(email) = %s;", (admin_email,))
        if not cur.fetchone():
            hashed = hash_password(admin_pass)
            cur.execute("""
                INSERT INTO accounts (account_type, name, email, password_hash, team_leader_role, is_active, activation_status)
                VALUES ('owner', 'Inventory Admin', %s, %s, 'inventory', true, 'active');
            """, (admin_email, hashed))
            conn.commit()
            print(f"Admin account created:")
            print(f"  Email:    {admin_email}")
            print(f"  Password: {admin_pass}")
        else:
            print(f"Admin account ({admin_email}) already exists.")

    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    init_database()
