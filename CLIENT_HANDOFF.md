# Batangas Premium Inventory — Client Guide

Open https://batangas-premium-inventory-do-not-delete.onrender.com/ and sign in
using your existing inventory account. The system has no published default
password. Changing your password in Profile survives application restarts.

## Daily inventory workflow

1. **Add raw material:** create a material with its unit and starting quantity in
   Inventory Workspace.
2. **Add quantity:** record incoming stock for an existing material.
3. **Create product recipe:** declare contents per pack and ingredient quantities.
4. **Produce batch:** select the product, packs produced, batch code, and expiry.
   Ingredients are deducted automatically; insufficient stock prevents the whole
   operation.
5. **Review batches:** check approved stock and expiry dates. Expired or rejected
   batches are not available for dispatch.
6. **Dispatch Stock:** choose a finished product, number of whole packs, and a
   note describing the dispatch. The system uses earliest-expiring batches first,
   including multiple batches when needed. It records no sale, payment, or order.
7. **Inventory Logs:** review stock increases and deductions. Dispatch records
   show their reference, note, actor, timestamp, and before/after balances.

The extracted catalog keeps MEATTRACK's original product definitions. Products
without source recipes or pack contents remain incomplete until the inventory
manager supplies the actual information. Nothing is guessed from product images.

## Access and availability

- Use Profile to change your password. Keep account credentials private.
- On Android Chrome, use **Add to Home Screen** for a shortcut to the inventory
  workspace. This is an online application; inventory operations need a connection.
- An external five-minute health check reduces Render idle spin-down. Hosting or
  database interruptions can still occur; a cold start can take about a minute.
- Uploaded profile pictures use Render's temporary filesystem. Product catalog
  pictures are bundled with the application; retain a copy of personal profile
  pictures if you upload them.
