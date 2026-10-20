# Batangas Premium Inventory

Standalone extraction of MEATTRACK's inventory workflow for the client's existing
Render service and Neon PostgreSQL database.

## Included

- Raw materials and stock receipts
- Finished-product catalog, declared pack contents, and recipes
- Production with automatic ingredient deductions
- Finished-product receipts, batches, and expiry tracking
- Manual stock dispatch using earliest-expiring eligible batches
- Immutable inventory movement history, dashboard, and inventory notifications
- Existing inventory login and profile/password changes

Sales, reseller management, orders, payments, forecasting, chat, and email
integrations are not included. Dispatch does not create orders or sales records.

## Run

Use Python 3.11 and the pinned runtime dependencies:

```text
python -m pip install -r requirements.txt
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Configure private values using `.env.example` as a reference. Keep the existing
Neon `DATABASE_URL` and deployment secret. A first installation without any
inventory account requires explicit `ADMIN_EMAIL` and `ADMIN_PASSWORD`. Startup
applies inventory-only migrations and never overwrites an existing account.

## Catalog

The versioned catalog contains 18 MEATTRACK products, five raw materials, and four
recipe rows from the October 17 local backup. Images are bundled. Missing source
recipes and pack sizes remain explicitly incomplete.

```text
python tools/import_inventory_catalog.py catalog/meattrack-20261017-v1.json
python tools/import_inventory_catalog.py catalog/meattrack-20261017-v1.json --apply
```

The first command is a read-only preview. The second adds missing definitions,
blocks conflicts, preserves existing records and balances, and creates no source
stock, accounts, or sales. See [catalog details](catalog/README.md).

## Tests

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check app tools tests
```

Set `TEST_DATABASE_URL` to an explicit disposable PostgreSQL database to run the
database tests. Each test creates and drops only its own isolated schema. The
tests never use `DATABASE_URL` as an implicit test target. Do not supply the
client's Neon production connection as `TEST_DATABASE_URL`.

## Existing deployment

Website: https://batangas-premium-inventory-do-not-delete.onrender.com/

See [deployment and Neon instructions](docs/DEPLOYMENT.md) for backups, safe
release, Render settings, catalog import, and the external five-minute cron
health check. Changes in this checkout do not automatically deploy to the site.
