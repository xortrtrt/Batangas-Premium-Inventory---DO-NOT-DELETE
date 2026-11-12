# Batangas Premium Inventory design context

This is the client's English-language inventory workspace for use in the
Philippines. The cleanup preserves the existing appearance and interactions.

The existing runtime CSS is canonical: `app/static/css/portal_base.css` owns
shared tokens, typography, controls, dialogs and responsive shell;
`app/static/css/portals/inventory.css` owns inventory layouts;
`product_details.css` owns product/package detail layouts; `supplies.css` owns
the independent supplies workspace. Keep source order and selector specificity.

The established identity uses bundled Rubik, a near-black sidebar, gold accents,
cream surfaces, and semantic stock colors. Product and package photos remain
part of inventory. No new tokens or visual redesign are introduced here.

Supply dialogs keep the shared inventory modal shell. At desktop width, the
photo editor shows one item per full-width row with its image beside the item
details and upload controls. Stock in/out dialogs use compact, consistent
spacing, equal-height top-aligned controls, and counting units beside the Quantity
label. Only the fields scroll; the action footer stays visible within the modal. Narrow
screens stack the photo card and scroll within the dialog.

The shared sidebar has no notification trigger. On narrow screens, the topbar
contains only the menu button; the notification history route remains available
to existing bookmarks.

Shared templates live under `app/templates/portals/`; shared behavior lives in
`core.js`, `portal.js`, and `forms.js`. Preserve native labeled form controls,
focus states, responsive tables, notifications, sign-out confirmation and
reduced-motion rules when retiring excluded-feature code.

See `docs/PROJECT_SCOPE.md` for the client-approved application boundary and
`UX-CONTRACT.md` for the implementation owners of existing behavior.

Form helper instructions are omitted by user preference. Keep field labels,
required/optional markers, quantity units, live status, validation messages,
empty states, and consequential confirmation messages.

Supply Movements follows the Stock Movements ledger: shared ledger tokens,
header/count, category and search controls, pagination, and signed transaction
rows. Each transaction is immediately visible in chronological order across
supplies, without item disclosures. Account, reason, time, and before/after
balances remain visible on phones. History defaults to all dates; date filtering
uses the existing native date control and Manila business-day boundaries.
