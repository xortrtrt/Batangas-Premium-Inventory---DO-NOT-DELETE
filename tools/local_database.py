"""Create and run an isolated local PostgreSQL database for inventory development.

The cluster lives outside the OneDrive checkout. It never connects to Neon or
the existing PostgreSQL service on port 5432.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import psycopg2
from dotenv import dotenv_values
from psycopg2 import sql


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLUSTER_ROOT = Path(os.environ["LOCALAPPDATA"]) / "MeatTrackInventory"
DATA_DIR = CLUSTER_ROOT / "postgres-data"
LOG_FILE = CLUSTER_ROOT / "postgres.log"
CREDENTIALS_FILE = CLUSTER_ROOT / "local-credentials.json"
ENV_FILE = PROJECT_ROOT / ".env"
DOCKER_ENV_FILE = PROJECT_ROOT / ".env.docker"
PG_BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")
PORT = 55434
CLUSTER_ADMIN = "inventory_cluster_admin"
APP_ROLE = "meattrack_inventory_app"
DB_NAME = "meattrack_inventory_local"
ADMIN_EMAIL = "inventory-local@localhost.invalid"


def run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, text=True, capture_output=True, check=check)


def cluster_running() -> bool:
    if not DATA_DIR.exists():
        return False
    result = run(str(PG_BIN / "pg_ctl.exe"), "-D", str(DATA_DIR), "status", check=False)
    return result.returncode == 0


def start_cluster() -> None:
    if not DATA_DIR.exists():
        raise RuntimeError("Local inventory cluster is missing. Run 'setup' first.")
    if cluster_running():
        print(f"Local inventory PostgreSQL is already running on 127.0.0.1:{PORT}.")
        return
    with socket.socket() as listener:
        if listener.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError(f"Port {PORT} is in use by another process.")
    # On Windows the background postgres process can inherit captured pipes,
    # leaving subprocess.run waiting for EOF after pg_ctl has finished.
    result = subprocess.run((str(PG_BIN / "pg_ctl.exe"), "-D", str(DATA_DIR),
                             "-l", str(LOG_FILE), "-w", "-t", "30", "start"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=45, check=False)
    if result.returncode:
        raise RuntimeError(f"Could not start local inventory PostgreSQL; see {LOG_FILE}.")
    print(f"Local inventory PostgreSQL started on 127.0.0.1:{PORT}.")


def expected_tables() -> set[str]:
    paths = [PROJECT_ROOT / "database" / "schema.sql"]
    paths.extend(sorted((PROJECT_ROOT / "database" / "migrations").glob("*.sql")))
    tables = {"inventory_schema_migrations"}
    for path in paths:
        tables.update(re.findall(r"\bCREATE TABLE\s+(?:IF NOT EXISTS\s+)?([a-z_][a-z_0-9]*)",
                                 path.read_text(encoding="utf-8"), re.IGNORECASE))
    return tables


def create_cluster(cluster_password: str) -> None:
    if DATA_DIR.exists() or CREDENTIALS_FILE.exists():
        raise RuntimeError("An inventory cluster already exists; refusing to replace it.")
    if not (PG_BIN / "initdb.exe").exists():
        raise RuntimeError(f"PostgreSQL 18 is not installed at {PG_BIN}.")
    CLUSTER_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CLUSTER_ROOT,
                                     prefix="initdb-password-", delete=False) as password_file:
        password_file.write(cluster_password + "\n")
        password_path = Path(password_file.name)
    try:
        result = run(str(PG_BIN / "initdb.exe"), "-D", str(DATA_DIR),
                     "--username=" + CLUSTER_ADMIN, "--auth=scram-sha-256",
                     "--encoding=UTF8", "--no-instructions", "--pwfile=" + str(password_path),
                     check=False)
        if result.returncode:
            raise RuntimeError(f"Could not initialize PostgreSQL: {result.stderr or result.stdout}")
    finally:
        password_path.unlink(missing_ok=True)
    with (DATA_DIR / "postgresql.conf").open("a", encoding="utf-8") as config:
        config.write(f"\nlisten_addresses = '127.0.0.1'\nport = {PORT}\n")


def admin_connection(cluster_password: str):
    return psycopg2.connect(host="127.0.0.1", port=PORT, dbname="postgres",
                            user=CLUSTER_ADMIN, password=cluster_password)


def create_database(cluster_password: str, app_password: str) -> None:
    connection = admin_connection(cluster_password)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
            if not cursor.fetchone():
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(APP_ROLE)),
                               (app_password,))
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
            if not cursor.fetchone():
                cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(DB_NAME), sql.Identifier(APP_ROLE)))
    finally:
        connection.close()


def app_url(app_password: str) -> str:
    return f"postgresql://{APP_ROLE}:{quote(app_password, safe='')}@127.0.0.1:{PORT}/{DB_NAME}"


def protect_file(path: Path) -> None:
    """Limit stored local passwords to this Windows user and system admins."""
    if os.name != "nt":
        path.chmod(0o600)
        return
    account = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
    result = run("icacls", str(path), "/inheritance:r", "/grant:r",
                 f"{account}:(F)", "NT AUTHORITY\\SYSTEM:(F)",
                 "BUILTIN\\Administrators:(F)", check=False)
    if result.returncode:
        raise RuntimeError(f"Could not protect local credentials at {path}: {result.stderr}")


def write_env(app_password: str, session_secret: str) -> None:
    if ENV_FILE.exists():
        raise RuntimeError(".env already exists; refusing to overwrite project configuration.")
    ENV_FILE.write_text("\n".join((
        "APP_ENV=development",
        "DATABASE_URL=" + app_url(app_password),
        "SESSION_SECRET_KEY=" + session_secret,
        "BUSINESS_TIMEZONE=Asia/Manila",
        "")), encoding="utf-8")
    protect_file(ENV_FILE)


def bootstrap_account(admin_password: str) -> None:
    environment = os.environ.copy()
    environment.update({"DATABASE_URL": json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))["database_url"],
                        "ADMIN_EMAIL": ADMIN_EMAIL, "ADMIN_PASSWORD": admin_password,
                        "APP_ENV": "development"})
    result = subprocess.run([sys.executable, str(PROJECT_ROOT / "tools" / "init_db.py")],
                            cwd=PROJECT_ROOT, env=environment, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Could not initialize the inventory schema: {result.stderr or result.stdout}")


def verify(app_password: str) -> None:
    expected = expected_tables()
    with psycopg2.connect(app_url(app_password)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            actual = {row[0] for row in cursor.fetchall()}
            if actual != expected:
                raise RuntimeError(f"Table mismatch. Missing: {sorted(expected - actual)}; "
                                   f"unexpected: {sorted(actual - expected)}")
            cursor.execute("SELECT version FROM inventory_schema_migrations ORDER BY version")
            migrations = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT count(*) FROM accounts")
            accounts = cursor.fetchone()[0]
    print(f"Verified {len(actual)} inventory tables and {len(migrations)} migrations; "
          f"{accounts} local account(s).")
    print("Tables: " + ", ".join(sorted(actual)))


def write_docker_env() -> None:
    if not ENV_FILE.exists():
        raise RuntimeError("Local .env is missing. Run 'setup' first.")
    values = dotenv_values(ENV_FILE)
    original_url = values.get("DATABASE_URL") or ""
    parsed = urlsplit(original_url)
    if (parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1"
            or parsed.port != PORT or parsed.path != f"/{DB_NAME}"):
        raise RuntimeError(".env does not point to this project's local inventory database.")
    if not parsed.username or not parsed.password:
        raise RuntimeError("Local database URL must include a username and password.")
    credentials = parsed.netloc.rsplit("@", 1)[0]
    values["DATABASE_URL"] = urlunsplit(parsed._replace(netloc=f"{credentials}@db:5432"))
    values["POSTGRES_USER"] = unquote(parsed.username)
    values["POSTGRES_PASSWORD"] = unquote(parsed.password)
    values["POSTGRES_DB"] = DB_NAME
    values["APP_BASE_URL"] = "http://127.0.0.1:8001"
    values["SESSION_COOKIE_NAME"] = "bp_inventory_docker_session"
    DOCKER_ENV_FILE.write_text("\n".join(f"{key}={value}" for key, value in values.items()
                                          if value is not None) + "\n", encoding="utf-8")
    protect_file(DOCKER_ENV_FILE)
    print(f"Docker environment prepared at {DOCKER_ENV_FILE} (keep private).")


def setup() -> None:
    if ENV_FILE.exists():
        raise RuntimeError("Local inventory setup already exists; refusing to overwrite it.")
    if DATA_DIR.exists() and CREDENTIALS_FILE.exists():
        saved = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
        cluster_password = saved["cluster_password"]
        admin_password = saved["local_login_password"]
        from urllib.parse import unquote
        app_password = unquote(urlsplit(saved["database_url"]).password or "")
    elif DATA_DIR.exists() or CREDENTIALS_FILE.exists():
        raise RuntimeError("Incomplete local inventory cluster; refusing to replace data or credentials.")
    else:
        cluster_password = secrets.token_urlsafe(36)
        app_password = secrets.token_urlsafe(36)
        admin_password = "Aa1!" + secrets.token_urlsafe(28)
        create_cluster(cluster_password)
        CREDENTIALS_FILE.write_text(json.dumps({
            "cluster_admin": CLUSTER_ADMIN,
            "cluster_password": cluster_password,
            "database_name": DB_NAME,
            "database_role": APP_ROLE,
            "database_url": app_url(app_password),
            "local_login_email": ADMIN_EMAIL,
            "local_login_password": admin_password,
        }, indent=2) + "\n", encoding="utf-8")
        protect_file(CREDENTIALS_FILE)
    start_cluster()
    create_database(cluster_password, app_password)
    write_env(app_password, secrets.token_urlsafe(48))
    bootstrap_account(admin_password)
    verify(app_password)
    print(f"Local credentials saved at {CREDENTIALS_FILE} (keep private).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "start", "status", "docker-env"))
    command = parser.parse_args().command
    if command == "setup":
        setup()
    elif command == "start":
        start_cluster()
    elif command == "docker-env":
        write_docker_env()
    else:
        print("running" if cluster_running() else "stopped")


if __name__ == "__main__":
    main()
