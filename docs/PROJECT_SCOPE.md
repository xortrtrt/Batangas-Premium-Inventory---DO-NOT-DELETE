# Standalone inventory scope

This directory is the client's Render application. It now lives independently
at `C:\Users\patri\OneDrive\Desktop\standalone-inventory`. The larger capstone
project is retained separately as a recoverable backup and is not deployed here.

## Keep

- `app/`: inventory routes, authentication, account/profile management, sessions,
  audit context, notifications, templates, and their referenced static assets.
- Food inventory: raw materials, recipes, production, finished-product batches,
  opening balances, expiry, dispatch, batch removal, packages, and movement logs.
- Packaging & Supplies: independent items, stock in/out, daily movements, photos,
  and the immutable supply ledger.
- `database/schema.sql` and every numbered migration: startup builds the schema
  from the baseline and applies the migrations in order. Applied migration
  checksums must not change, even when old SQL contains legacy names.
- `catalog/` and import/export tools: required inventory catalog definitions and
  recovery workflows. The archived v1 manifest intentionally retains original
  price/content metadata; the importer excludes those fields from storage.
- `tools/`, `tests/`, deployment configuration, dependency pins, license notices,
  and client/deployment documentation.

## Names that are still inventory dependencies

- Owner accounts and inventory team-leader accounts are existing inventory login
  identities. `/portal/owner/*` and `/portal/team-leader/*` are inventory URL
  aliases, not additional business portals. Existing notifications use aliases.
- Resellers Package and Area Distributor's Package are bundles of finished goods.
  Keep their names, catalog definitions, photos, package dispatch, and tests.
- `lifecycle-*` CSS is shared by product and package details. `proof-modal*`
  styles are also used by sign-out confirmation. Neither can be deleted by name.
- Negative tests mentioning reseller, sales, forecasting, or chatbot routes verify
  that those excluded features stay inaccessible.

## Excluded features

Reseller accounts/management, sales/orders/cart, payments and proofs, refunds,
forecasting, support chat, email integrations, and Capacitor/mobile application
builds do not belong in the standalone application. No such backend modules are
present in this checkout.

## Cleanup performed

- Removed 258 unused CSS blocks for chat, inquiry, order, payment/proof, cart-trigger, and sales-return
  CSS rules only where every selector required an unreferenced feature class.
  Shared selector groups and sign-out modal styles are retained.
- Removed unused refund navigation/event branches from shared filtering code.
- Renamed the used product category class to `inventory-product-category` in its
  template and both stylesheets; removed unused sales profile classes.
- Removed unused money formatting/parsing helpers and account-directory sorting.
- Removed unreferenced `reseller-card.png` and `batch-flow.png`. All referenced
  branding, product/package, login, fallback, and supplies images remain.
- Added readable IDs to image-validation test cases so oversized byte payloads
  do not exceed Windows' environment-variable limit in pytest.

No database records, migration checksums, deployment commands, parent capstone
files, or existing uncommitted supplies/image functionality are removed.

Generated `.pytest_cache/`, `.ruff_cache/`, and `__pycache__/` directories are
disposable and ignored by Git. They may reappear after validation. The ignored
`test-results/` directory contains inventory screenshots and deployment/import
evidence, so it is retained rather than treated as unrelated capstone content.

## Verification

- Python suite: 19 passed, 130 skipped; PostgreSQL cases require a disposable
  `TEST_DATABASE_URL` and were not exercised during cleanup.
- Ruff, JavaScript syntax check, supplies Node test, and Git whitespace checks pass.
- All Jinja templates compile. Chromium parsed all three edited stylesheets;
  retained CSS declarations and cascade order match the original after the
  coordinated product-category class rename.
- Dashboard and profile renders at 390px and 1366px retain identical computed
  styles for every rendered element. These are database-free render comparisons,
  not a claim of full browser coverage of stock writes.
- All retained image assets have references in inventory templates, scripts,
  image fallbacks, or the catalog.
