# Inventory behavior preservation contract

The client needs standalone inventory; reseller, sales, payments and chat flows
are excluded. `README.md`, `docs/PROJECT_SCOPE.md`, repository transactions and
database constraints describe the maintained domain behavior. This cleanup adds
no new interaction patterns and does not claim a full accessibility audit.

| Capability | Existing implementation owner | Cleanup constraint |
| --- | --- | --- |
| Navigation and dialogs | `portals/base.html`, `portal.js`, `portal_base.css` | Preserve inventory aliases, drawer, focus and sign-out behavior. |
| Selects, dates and forms | Existing native controls in inventory templates, `forms.js`, backend validators | Preserve labels, units, validation, and Manila business-day rules. |
| Search and pagination | `portal.js`, query-string filters, repository paging | Preserve request cancellation, URLs, results replacement and `portal:content-updated`. |
| Status feedback | Shared toast markup, `core.js`, supplied error redirects | Preserve readable messages and existing notification behavior. |
| Stock writes | Inventory repositories and SQL constraints | Preserve atomicity, locks, immutable history and existing replay protection. |
| Images | `uploads.py`, database image repositories, bundled fallbacks | Preserve validation, previews and product/package/supply photos. |
| Responsive shell and scrolling | Shared runtime CSS documented in `DESIGN.md` | Preserve active selectors and media-query order. |

Tests in `tests/` cover domain transactions and HTTP behavior. PostgreSQL tests
require an explicitly disposable `TEST_DATABASE_URL`; never substitute the
client's deployed connection. The supplies Node test covers preview behavior
after content replacement. Browser CSS parsing can check that cleanup retains
all inventory selectors and their declaration order.

Batch identity follows the manual-number rule in `README.md` (migration 012).
The shared `batch_identity_fields` macro owns batch number/date inputs for opening
balances and production, using the existing native labeled text/date controls.
Platform-owned date/select popups remain accepted for this English-language app;
default batch dates come from Manila business time on the server. Batch lists,
product details, and removed batches show the date beside the manual number.

Packaging and supplies use three independent routes, shared by inventory, owner,
and team-leader aliases: `supplies` shows stock balances; `supplies-manage` owns
creation, stock in/out, and photo updates; `supplies-movements` shows
immutable transactions in one flat chronological list. `supplies-manage` follows Inventory Workspace: task cards open the shared
inventory dialogs. `supplies` follows Finished Products: a stock browser with
search, cards, and entry actions. Movements has its own ledger page. There is no
shared hero or tab strip between modules; contextual links connect their tasks. Cross-page links
load the complete page so sidebar state, assets, and page titles stay aligned.
Legacy `supplies?tab=...` links redirect while preserving filters and drafts.
Successful creation returns to stocks; successful stock in/out opens movements;
failed stock entries return to the entry page with the existing per-entry draft.
Each list retains server pagination and search in its URL. Movement history
counts and paginates transactions, defaults to all dates/newest first, and retains
category, sort, and optional Manila movement date in the URL. No item disclosure
is required to read movement details.
Supply forms use native constraint metadata with inline validation in
`supplies.js`; server validation remains authoritative. Validation preserves
field names, associates error descriptions, focuses the first invalid field,
and blocks duplicate submissions. The existing image-upload owner handles
preview selection and clearing on the entry page.
