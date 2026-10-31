# Batangas Premium Inventory

Standalone extraction of MEATTRACK's inventory workflow for the client's existing
Render service and Neon PostgreSQL database.

## Included

- Raw materials and stock receipts
- Manual raw-material deductions with required reason, stock-unit quantities, and account tracking
- Finished-product catalog and recipes; stock counted in packs
- Production with automatic ingredient deductions
- Finished-product receipts, batches, and expiry tracking
- Finished-goods opening balances by batch, with expiry, a required note, and account tracking
- Manual stock dispatch using earliest-expiring eligible batches
- Immutable inventory movement history, dashboard, and inventory notifications
- Account attribution on every stock movement, with account-name search and sorting
- Existing inventory login and profile/password changes

Sales, reseller management, orders, payments, forecasting, chat, and email
integrations are not included. Dispatch does not create orders or sales records.

Use **Add opening balance** in the Inventory Workspace or Finished Products to
record existing finished goods in positive whole packs. Enter a separate batch
code and expiry date for each batch. This adds to existing stock without consuming
recipe materials; it never replaces a balance. Entries appear under **Opening**
in movement history and participate in the normal expiry and dispatch workflow.
Duplicate submissions are recorded once using a unique database reference.

## Run

Finished Products: select a product name to open its read-only stock details.
The page shows available and physical batch stock, all batches with expiry and
quality status, and product-specific movements with batch balances, account,
timestamp, notes, and dispatch references. Batch and movement histories paginate
independently; Back to Finished Products returns to the catalog.
The catalog and product details follow the MEATTRACK reference's card layout,
photo header, stock summary tiles, batch progress cards, and movement timeline.
Standalone stock metrics show available packs, warehouse packs, batch count,
near-expiry packs, and expired warehouse packs using the existing expiry rules.

Product details → Remove batch opens a reason and confirmation form. Confirming
archives that batch and removes its remaining packs through a recorded stock
correction. Original batches and movement history remain stored; production
ingredients are not restored. Empty batches can also be archived. Removal is
account-attributed, rejects stale stock quantities, and cannot deduct twice.
Migration `006_batch_removal.sql` adds archival metadata without deleting records.
Product Batches → Removed batches lists archived batches with the product,
packs deducted at removal, original receipt quantity, expiry, reason, account,
and removal timestamp. Product details also links to that product's removed
batches. Search and pagination retain the product filter; stock history remains
accessible. This view does not restore stock.

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
recipes remain explicitly incomplete. Archived price and net-content metadata is ignored by the importer and is not stored in the client database.

```text
python tools/import_inventory_catalog.py catalog/meattrack-20261017-v1.json
python tools/import_inventory_catalog.py catalog/meattrack-20261017-v1.json --apply
```

The first command is a read-only preview. The second adds missing definitions,
blocks conflicts, preserves existing records and balances, and creates no source
stock, accounts, or sales. See [catalog details](catalog/README.md).

Inventory Workspace → Create product recipe supports an optional JPG, PNG, or
WebP photo up to 2 MB, with a preview and removal before saving. Migration 009
stores product images in the database so they survive redeploys. The image and
recipe save in one transaction, and the catalog and product details use the
uploaded photo. Products without an upload retain their existing image fallback.

## Finished-goods packages

Area Distributor's Package, Resellers Package, and Trial Package appear under
Packages, separately from individual finished products. They contain finished
packs rather than raw ingredients and do not own manufactured stock.

Save and lock the **Standard** contents once. Saved products and pack quantities
cannot be edited; the application and database both enforce the lock. At each
dispatch choose **Standard** to use that fixed list, or **Customize** to create
one-time contents starting from zero. A customized dispatch never changes the
standard and is not saved as a reusable combination. Dispatching customized
contents does not require a standard to have been configured.

Package dispatch multiplies packs per package by the number of packages and
deducts all components atomically from approved, unexpired batches in earliest
expiry order. Insufficient components reject the entire dispatch. Records retain
the dispatch type and actual product/quantity snapshot.
Inventory Logs show each package dispatch once under its recorded package name,
with an expandable list of finished goods, packs per package, and total packs
dispatched. Search includes the recorded component names; counts and pagination
treat the package as one event. Individual stock deductions remain in the ledger
for product history and stock accountability.
Packages are excluded from raw-material recipes, production, individual stock
receipts/opening balances, and individual-pack dispatch. Migration 007 classifies
the three existing items while retaining their IDs and historical records.
Migration 008 locks existing saved standards. The three package cards are shown
together without package pagination; individual products retain pagination.

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

Website: https://batangas-premium-inventory.onrender.com/

See [deployment and Neon instructions](docs/DEPLOYMENT.md) for backups, safe
release, Render settings, catalog import, and the external five-minute cron
health check. Pushes to `main` automatically deploy to the existing Render service. Catalog imports and data resets never run automatically.

The original service at https://batangas-premium-inventory-do-not-delete.onrender.com/ remains available. Both services use the same existing Neon database; no catalog or accounts were recreated for the new address.


## Local review: raw-material deductions

Open Inventory Workspace → Deduct raw materials. Select a material, enter the
quantity in its displayed stock unit (kg, g, or ml; up to three decimal places),
and supply a reason such as spoilage or wastage. The deduction records the
signed-in account, timestamp, unique reference, and before/after balances.
Insufficient stock is rejected atomically; replaying a successful submission
never deducts it twice. Production and manual deductions lock the same material
stock. Inventory Logs → Raw deductions shows these entries and supports account
search.

Migration `004_raw_material_deductions.sql` must be applied to a local or
backed-up target database before running this version. It adds an optional unique
reference to movement records and retains existing history. No reset or catalog
import is required for this feature.


## Raw-material soft deletion

Raw Materials → Remove material hides an item from active inventory and selection
lists only when no product recipe references it. Check “Yes, I’m sure” and press Remove to confirm.
Its balance, original item ID, and movement history are preserved, including when
stock is above zero. Removal is never triggered by a zero balance: active items
remain visible as `0.00 kg`, `0.00 g`, or `0.00 ml`.

Raw Materials → Removed materials lists hidden items and their saved balances.
Reactivate returns the same item to active inventory. Adding a new item with a
removed material's name is blocked with a link direction to reactivate it instead.
Removal and reactivation record the signed-in account in the activity audit.
