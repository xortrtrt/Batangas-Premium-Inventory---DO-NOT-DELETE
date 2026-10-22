# Existing Render service and Neon database

Keep the existing service `batangas-premium-inventory-do-not-delete` and its current
Neon database. Do not create a replacement service, change the domain, reset the
database during ordinary releases, or use MEATTRACK's development seed script. An explicitly authorized catalog-only reset is described below.

## Render configuration

- Root directory: `standalone-inventory` when deploying the full repository;
  leave it blank if the repository already contains only this directory's contents.
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT`
- Health check: `/health`
- Keep the existing `DATABASE_URL` supplied by Neon, including TLS options such as
  `sslmode=require`. Keep the existing `SESSION_SECRET_KEY`.
- Set `APP_ENV=production`, `CSRF_PROTECTION_ENABLED=true`,
  `AUTH_RATE_LIMIT_ENABLED=true`, and `BUSINESS_TIMEZONE=Asia/Manila`.
  Production also enforces throttling in code if an older Render environment
  still explicitly sets that flag to false.
- `ADMIN_EMAIL` and `ADMIN_PASSWORD` are required only for a completely new
  installation with no inventory-authorized account. Existing accounts, including
  disabled accounts, are never reset or reactivated at startup.

The application runs only its inventory migrations at startup under a PostgreSQL
advisory lock. A migration or bootstrap failure stops startup. It never imports
catalog data automatically.

## Release procedure

1. Back up the existing Neon database before deployment. Use a private local
   environment variable, not a connection string pasted into a command or log:

   ```powershell
   pg_dump --dbname=$env:DATABASE_URL --format=custom --file=inventory-before-release.dump
   ```

2. Stop inventory edits for the release window. Test the release against a
   disposable database first. Do not point tests at Neon production.
3. Deploy to the existing Render service. Its startup performs ordered,
   checksum-protected migrations without replacing existing tables or records.
4. In a local checkout using the same pinned requirements and the target
   `DATABASE_URL`, preview the catalog import:

   ```text
   python tools/import_inventory_catalog.py catalog/meattrack-20261017-v1.json
   ```

5. Review the report. Conflicting units or recipes block the
   entire import. Existing target metadata and stock remain unchanged. After the
   report has no conflicts, run:

   ```text
   python tools/import_inventory_catalog.py catalog/meattrack-20261017-v1.json --apply
   ```

6. Check login, materials, recipes, batches, production, dispatch, movement logs,
   and `/health`. Compare the pre-import quantities and movement counts. Resume
   inventory work only after verification.

Rollback application code using Render's existing release history if needed.
The dispatch migration is additive and leaves historical records in place; do
not delete dispatch records or downgrade the database schema to roll back code.

## External five-minute health check

The cron-job.org job was created and enabled on October 20, 2026 (Asia/Manila),
job ID `8682652`. A manual test returned HTTP 200 with the database connected. The first scheduled
execution also succeeded at 12:00:21 PM (Asia/Manila), taking 239 ms.
Use the existing job rather than creating duplicates. Its configuration is:

- Title: `Batangas Premium Inventory — Health Check`
- URL: `https://batangas-premium-inventory-do-not-delete.onrender.com/health`
- Schedule: every five minutes, timezone `Asia/Manila`, without an expiry date.
- Method: `GET`; no authentication, request body, or custom headers.
- Timeout: 30 seconds. Require HTTP 200; redirects should not count as success.
- Do not save response bodies routinely. Test the job and confirm the JSON body
  says `{"status":"ok","database":"connected"}`.

This checks the app and the existing Neon connection. The endpoint does not
create browser sessions or modify inventory. An initial Render cold start can
time out or return a loading page; retry once the service has started.

Periodic traffic reduces idle spin-down, but Render can still restart or suspend
free services and external schedules can be delayed. It is not an uptime
guarantee. See https://render.com/docs/free. Database checks also keep Neon compute
active more often; review the existing Neon plan's compute allowance.

Profile uploads currently use local files. Render's free filesystem is ephemeral;
keep copies of any profile pictures. Product catalog images ship with the app and
survive redeployments. No object-storage service is introduced by this release.


## Explicit catalog-only reset

`tools/reset_inventory.py` is a separate administrative operation and is never
called by startup or deployment. It defaults to a read-only preview. It keeps
finished-product IDs, names, categories, descriptions, units, activation status,
and bundled image mappings. It clears operational records, raw materials,
recipes, old logins, and sessions, then creates exactly four inventory logins.
Migration 003 removes product price/net-content columns and permits username-only
accounts without invented email addresses. Recipes still specify ingredient
amounts per finished pack.

Apply a reset only after explicit authorization, a complete custom-format
`pg_dump`, and a successful restore/reset rehearsal on a disposable database.
Pause edits, save a final backup, and deploy the compatible application before
applying the reset. Keep generated credentials in a private local JSON file
outside the repository, containing an `accounts` array with `username` and
`password` for BPadmin1 through BPadmin4. Each password must be unique.

```text
python tools/reset_inventory.py
python tools/reset_inventory.py --apply --backup <validated-backup.dump> --credentials-file <private-accounts.json>
```

The tool stops on unexpected tables, locks the known inventory tables, and resets
in one transaction. Only the history-protection triggers are disabled for that
transaction and re-enabled before commit; failures roll back both data and
trigger changes. Schema-migration records remain. Business settings fall back
to the application's defaults. Never use the reset tool for routine stock edits.
After migration 003, code that queries removed columns requires the pre-release
backup for rollback; merely selecting an older Render release is insufficient.
