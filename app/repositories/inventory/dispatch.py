"""Manual inventory dispatch, independent of orders and sales."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.inventory_measurements import parse_whole_packs
from .._shared import _add_log_cursor, get_transaction_cursor
from .movements import _inventory_actor_name


def dispatch_stock(product_id: int, quantity: object, note: str, submission_reference: str,
                   actor_account_id: int) -> dict:
    amount = parse_whole_packs(quantity, "Dispatch quantity")
    clean_note = note.strip()
    if not clean_note or len(clean_note) > 500:
        raise ValueError("Enter a dispatch note of 1 to 500 characters.")
    try:
        reference = str(UUID(submission_reference))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid dispatch reference. Reload the workspace and try again.") from None

    with get_transaction_cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"dispatch:{reference}",))
        cur.execute("SELECT * FROM inventory_dispatches WHERE dispatch_id = %s", (reference,))
        existing = cur.fetchone()
        if existing:
            if (existing["product_item_id"] != product_id or existing["quantity"] != amount
                    or existing["note"] != clean_note or existing["actor_account_id"] != actor_account_id):
                raise ValueError("This dispatch reference was already used for different details. Reload the workspace.")
            return {"dispatch_id": reference, "already_recorded": True}

        cur.execute("""SELECT item_id, name, unit FROM inventory_items
            WHERE item_id = %s AND item_type = 'finished_product' AND is_active = true FOR UPDATE""", (product_id,))
        product = cur.fetchone()
        if not product:
            raise ValueError("Choose an active finished product.")
        cur.execute("""SELECT batch_id, quantity_available FROM inventory_batches
            WHERE item_id = %s AND quality_status = 'approved' AND expiry_date >= CURRENT_DATE
              AND quantity_available > 0 ORDER BY expiry_date, batch_id FOR UPDATE""", (product_id,))
        batches = cur.fetchall()
        available = sum((row["quantity_available"] for row in batches), Decimal(0))
        if available < amount:
            raise ValueError(f"Not enough {product['name']}. Available: {available:g} packs.")
        cur.execute("""INSERT INTO inventory_dispatches
            (dispatch_id, product_item_id, quantity, note, actor_account_id) VALUES (%s, %s, %s, %s, %s)""",
            (reference, product_id, amount, clean_note, actor_account_id))
        actor_name = _inventory_actor_name(cur, actor_account_id)
        remaining = amount
        for batch in batches:
            if not remaining:
                break
            before = batch["quantity_available"]
            take = min(before, remaining)
            after = before - take
            cur.execute("UPDATE inventory_batches SET quantity_available = %s WHERE batch_id = %s", (after, batch["batch_id"]))
            cur.execute("""INSERT INTO inventory_movements
                (item_id, affected_batch_id, movement_type, quantity_delta, unit, balance_before,
                 balance_after, actor_account_id, actor_name, note, dispatch_id)
                VALUES (%s, %s, 'stock_dispatch', %s, %s, %s, %s, %s, %s, %s, %s)""",
                (product_id, batch["batch_id"], -take, product["unit"], before, after,
                 actor_account_id, actor_name, clean_note, reference))
            cur.execute("""UPDATE alerts SET status = 'resolved' WHERE product_batch_id = %s
                AND status IN ('open', 'acknowledged') AND %s = 0""", (batch["batch_id"], after))
            remaining -= take
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="dispatched_stock",
                        entity_type="inventory_items", entity_id=product_id)
    return {"dispatch_id": reference, "already_recorded": False}
