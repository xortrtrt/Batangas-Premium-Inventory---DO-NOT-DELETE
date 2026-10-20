# MEATTRACK inventory catalog v1

`meattrack-20261017-v1.json` was extracted from an isolated PostgreSQL restoration
of `meattrack-before-order-purge-20261017.dump`. Its source SHA-256 is recorded in
the manifest. It contains 18 finished products, five raw-material definitions,
and four recipe ingredient rows covering two products.

There are 16 products without declared pack sizes and 16 without recipes in the
source. These remain unknown/incomplete; they are not inferred from photographs
or development seed data. Source names, categories, measurements and prices are
preserved, including legacy package products. Catalog images are copied into the
app's existing static image directory with exact name mappings.

No accounts, passwords, source balances, batches, movements or sales data are
included. The importer starts new items at zero, adds missing definitions only,
and blocks all writes on conflicting measurements or recipes. By default it
performs a read-only preview. Existing matching item metadata is never updated.

To reproduce extraction, restore the backup into a separate disposable PostgreSQL
database first, set `CATALOG_SOURCE_URL` to that restoration, and run from `standalone-inventory/`:

```text
python tools/export_inventory_catalog.py --meattrack-root .. --backup ../backups/meattrack-before-order-purge-20261017.dump
```

Do not restore the MEATTRACK backup into the client's Neon database.
