"""Copy the existing local inventory database into an empty Compose database."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from urllib.parse import unquote, urlsplit

import psycopg2
from dotenv import dotenv_values

from local_database import CLUSTER_ROOT, DB_NAME, PG_BIN, PORT, PROJECT_ROOT, cluster_running, write_docker_env


def run(*args: str, capture: bool = False, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=PROJECT_ROOT, env=env, check=True,
                            text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def row_counts(query_runner) -> dict[str, int]:
    tables = query_runner("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    counts: dict[str, int] = {}
    for table in tables:
        if not table.replace("_", "").isalnum():
            raise RuntimeError(f"Unexpected table name: {table}")
        counts[table] = int(query_runner(f'SELECT count(*) FROM "{table}"')[0])
    return counts


def main() -> None:
    values = dotenv_values(PROJECT_ROOT / ".env")
    source_url = values.get("DATABASE_URL") or ""
    source = urlsplit(source_url)
    if (source.hostname, source.port, source.path) != ("127.0.0.1", PORT, f"/{DB_NAME}"):
        raise RuntimeError(".env does not point to the isolated local inventory database.")
    if not cluster_running():
        raise RuntimeError("Start local PostgreSQL with tools/local_database.py start first.")
    if not (PG_BIN / "pg_dump.exe").exists():
        raise RuntimeError("PostgreSQL 18 pg_dump is missing.")

    # Stop the web writer before taking the backup. The source cluster remains intact.
    run("docker", "compose", "stop", "web")
    backup_dir = CLUSTER_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"inventory-before-docker-{datetime.now():%Y%m%d-%H%M%S}.dump"
    pg_env = os.environ.copy()
    pg_env.update(PGHOST="127.0.0.1", PGPORT=str(PORT), PGDATABASE=DB_NAME,
                  PGUSER=unquote(source.username or ""), PGPASSWORD=unquote(source.password or ""))
    run(str(PG_BIN / "pg_dump.exe"), "--format=custom", "--file", str(backup), env=pg_env)
    run(str(PG_BIN / "pg_restore.exe"), "--list", str(backup), capture=True)
    print(f"Source backup saved: {backup} ({backup.stat().st_size} bytes)")

    with psycopg2.connect(source_url) as connection:
        def source_query(sql: str) -> list[str]:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                return [str(row[0]) for row in cursor.fetchall()]
        source_counts = row_counts(source_query)

    write_docker_env()
    run("docker", "compose", "config", "--quiet")
    run("docker", "compose", "up", "-d", "--wait", "db")
    container = run("docker", "compose", "ps", "-q", "db", capture=True)
    if not container:
        raise RuntimeError("Compose database container is unavailable.")
    db_user = unquote(source.username or "")

    def target_query(sql: str) -> list[str]:
        output = run("docker", "compose", "exec", "-T", "db", "psql", "-X", "-A", "-t",
                     "-v", "ON_ERROR_STOP=1", "-U", db_user, "-d", DB_NAME,
                     "-c", sql, capture=True)
        return output.splitlines() if output else []

    existing = target_query("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    if existing:
        raise RuntimeError("Docker database already has tables; refusing to overwrite them.")

    temporary_dump = "/tmp/inventory-before-docker.dump"
    run("docker", "cp", str(backup), f"{container}:{temporary_dump}")
    try:
        run("docker", "compose", "exec", "-T", "db", "pg_restore", "--exit-on-error",
            "--single-transaction", "--no-owner", "--no-acl", "-U", db_user,
            "-d", DB_NAME, temporary_dump)
    finally:
        run("docker", "compose", "exec", "-T", "db", "rm", "-f", temporary_dump)

    target_counts = row_counts(target_query)
    if target_counts != source_counts:
        raise RuntimeError("Restored table counts differ from the local database; web not started.")
    print(f"Verified {len(target_counts)} tables and their row counts in Docker.")
    run("docker", "compose", "up", "-d", "--build", "--wait", "web")
    print("Docker web and database are healthy; the original local database is unchanged.")


if __name__ == "__main__":
    main()
