# Independent local setup

The active repository is `C:\Users\patri\OneDrive\Desktop\standalone-inventory`.
Its `.git` directory, history, local edits, static assets, catalog, migrations,
tests and deployment configuration are all contained in this directory.

The repository has its own `.venv`; it no longer uses the capstone environment.
The local environment uses installed Python 3.13. Render's Python 3.11 setting
remains unchanged. Windows installs the explicit `tzdata` requirement for the
Manila business timezone; Linux uses its system timezone database.

Run commands from this directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tools tests
node --test tests/supplies_preview.test.mjs
```

For a new environment, use `py -3.13 -m venv .venv` first. Python 3.11 may also
be used to match Render when that interpreter is installed locally.

## Local inventory database

This checkout has its own PostgreSQL 18 cluster and database, separate from the
old capstone PostgreSQL service and from Neon. The cluster data lives at
`%LOCALAPPDATA%\MeatTrackInventory\postgres-data` outside OneDrive. It listens
only on `127.0.0.1:55434`; the app database is `meattrack_inventory_local`.
The ignored `.env` in this checkout points to that database. No data was copied
from the capstone or Neon databases.

The setup command is for a fresh machine or checkout with no local inventory
cluster and no `.env`. Do not run it against an existing setup:

```powershell
.\.venv\Scripts\python.exe tools\local_database.py setup
```

After restarting Windows, start the local database before launching the app:

```powershell
.\.venv\Scripts\python.exe tools\local_database.py start
.\.venv\Scripts\python.exe tools\local_database.py status
```

Local database and login credentials are stored in
`%LOCALAPPDATA%\MeatTrackInventory\local-credentials.json`. Keep this file and
the ignored `.env` private. The initial app login email is
`inventory-local@localhost.invalid`; the password is the
`local_login_password` value in that credentials file. The app database role
has no superuser, database creation, or role creation privilege. Only the 23
tables defined by `database/schema.sql` and migrations 001–012 were created.

To run the app, start the local database and then run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

## Docker server

Docker Compose runs the inventory web server as `bp-inventory` and PostgreSQL 18
as a private `db` service. Database files persist in the
`bp-inventory_postgres-data` Docker volume; profile uploads persist in
`bp-inventory_profile-uploads`. The database has no host port. The web app is
available only on this computer at `http://127.0.0.1:8001`.

To move this checkout's existing local inventory data into Docker, start Docker
Desktop and the local PostgreSQL cluster, then run the one-time migration:

```powershell
docker desktop start
.\.venv\Scripts\python.exe tools\local_database.py start
.\.venv\Scripts\python.exe tools\migrate_local_db_to_docker.py
```

The migration stops the web container, saves a PostgreSQL dump under
`%LOCALAPPDATA%\MeatTrackInventory\backups`, restores it into an empty Docker
database, compares all table row counts, and starts the web container. It refuses
to overwrite a Docker database that already has tables. The original Windows
database is retained as a separate copy and is not synchronized with Docker.

For later starts, use `docker compose up -d` from this folder. The local
`compose.override.yaml` mounts `app/` into the web container and enables Uvicorn
reload. Saving Python, HTML, CSS, JavaScript, or SVG files restarts the web server
and refreshes an open browser page automatically. The database stays in its named
volume. Changes to dependencies, the Dockerfile, or files outside `app/` still
require `docker compose up -d --build`.

Check the containers and database connection with:

```powershell
docker compose ps
Invoke-RestMethod http://127.0.0.1:8001/health
```

`docker compose stop` stops both services; `docker compose start` starts them
again. The ignored `.env.docker` file is generated from the local `.env`, points
the web service to `db:5432`, and supplies the database's initial credentials.
Keep it private. The local `.env` still targets the Windows database for direct
Python runs. Render continues using its own configuration.

Startup runs database migrations and initializes an account only when none
exists. PostgreSQL tests
require an explicitly disposable `TEST_DATABASE_URL`; absent that setting,
database tests skip. The old capstone's `.env` is not copied into this app.

Render and Neon configuration and Git remote URLs are unchanged by relocation.
Open this new directory in Codex or your editor for subsequent work.

## Capstone recovery backup

The complete capstone backup is at
`C:\Users\patri\Project Backups\Capstone-Meattrack-Latest-2026-11-11`.
It includes the original inventory snapshot, old environment, configuration,
backups and project artifacts. Keep the backup private because it contains
the old `.env` file.

Windows stopped the initial relocation at hidden Git metadata. The remaining
files were copied to this backup and checksum-verified. Automatic approval
review then blocked the final move/removal operation. Consequently the original
`C:\Users\patri\OneDrive\Desktop\Capstone-Meattrack(Latest)` folder still
contains residual files; it is not the active inventory project. Its final
removal must be performed manually. Do not delete the new standalone directory
or the recovery backup.
