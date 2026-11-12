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

See [project scope and cleanup notes](docs/PROJECT_SCOPE.md) for the standalone
deployment boundary, retained compatibility names, and excluded capstone features.

Use **Add opening balance** in the Inventory Workspace or Finished Products to
record existing finished goods in positive whole packs. Enter a separate batch
code and expiry date for each batch. This adds to existing stock without consuming
recipe materials; it never replaces a balance. Entries appear under **Opening**
in movement history and participate in the normal expiry and dispatch workflow.
Duplicate submissions are recorded once using a unique database reference.

Batch numbers remain manually entered text: `001`, `Batch-001`, and other labels
up to 100 characters are accepted, preserving leading zeros and letter case.
The same number may be used by different products or on different batch dates.
Only the same product + batch date + number is rejected as a duplicate (ignoring
letter case and surrounding spaces). This rule is shared by production, direct
finished-product receipts, and opening balances, including archived batches.
Choose the original production date as the **Batch date** for existing stock;
new forms default to today in Manila and accept earlier dates, not future dates.
Receipt dates, encoding timestamps, and stock movements still record when stock
was entered; selecting an earlier batch date does not backdate those movements.
Migration `012_product_batch_dates.sql` preserves all stock/history and backfills
existing batch dates from their recorded receipt dates. Historical production
dates are not inferred. Batch lists and product details display the batch date.

## Run

For the local Docker container named `bp-inventory`, see
[Docker server setup](docs/LOCAL_SETUP.md#docker-server).

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
Inventory movements show each package dispatch once under its recorded package name,
with an expandable list of finished goods, packs per package, and total packs
dispatched. Search includes the recorded component names; counts and pagination
treat the package as one event. Individual stock deductions remain in the ledger
for product history and stock accountability.
Packages are excluded from raw-material recipes, production, individual stock
receipts/opening balances, and individual-pack dispatch. Migration 007 classifies
the three existing items while retaining their IDs and historical records.
Migration 008 locks existing saved standards. The three package cards are shown
together without package pagination; individual products retain pagination.

## Packaging & Supplies

Packaging and supplies use three connected sidebar modules. Supplies Workspace
uses task cards and dialogs, matching Inventory Workspace, for creating items,
adding stock, deducting stock, and updating photos. Packaging & Supplies is a
stock browser matching Finished Products, with links into the workspace for
the selected item. Supply movements is a separate transaction ledger.
Create each size or variant as a separate item, select
one fixed counting unit, and optionally enter starting stock. Pieces, pairs,
boxes, rolls, and packs use whole quantities; meters allow three decimal places.
Starting quantities are stock-in entries labeled Opening stock.

All entries use the current Manila timestamp, signed-in account, reason, and
before/after balances. Stock-out cannot exceed the available balance. Writes
are transactional, serialized per item, and protected against duplicate
submissions. Entries cannot be edited or backdated: correct a mistake with a
new, explained stock-in or stock-out entry.

Supply movements shows every transaction as a visible row, newest first across
all dates. Rows show the supply item, movement, account, reason, signed quantity,
before/after balance, and timestamp. Search includes items, categories, reasons,
and accounts; category, order, and optional movement-date filters stay in the URL.
Pagination counts individual transactions, including repeated movements for one
item. Date filters use Manila midnight boundaries. Mixed units are never added
into a single quantity.

Migration 010 adds separate supply item and immutable supply movement tables.
Food recipes, production, packages, stock reports, and logs stay independent.
The food-inventory reset preserves supplies and their history; actor identifiers
and names are stored as snapshots, independent of replaced food-portal accounts.
No supply items or balances are seeded automatically.
The supplies modules include optional item photos, thumbnail
movement rows, and a selected-item stock preview. Upload JPG, PNG, or WebP photos
up to 2 MB when creating an item, or open Update item photos in Supplies Workspace.
Migration 011 stores supplies photos in the database, independent of stock
movements, so redeployments do not remove them. Photo changes leave balances and
creation-submission replay protection intact. Items without photos use the
bundled stockroom illustration.
Failed supplies stock submissions retain direction, item, quantity, and reason
in up to five separate server-side drafts per session. Successful retries clear
their draft. Daily summary labels remain available to screen readers at desktop
and mobile widths. Product and supply photos are checked with Pillow using file
verification and pixel decoding, with matching MIME types, a 2 MB file limit,
and a 16-megapixel decoded-image limit.

## Tests

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check app tools tests
node --test tests/supplies_preview.test.mjs
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
stock. Inventory movements → Raw deductions shows these entries and supports account
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
