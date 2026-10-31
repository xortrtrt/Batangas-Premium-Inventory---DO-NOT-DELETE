"""Archive a batch and record any remaining stock as a traceable correction."""
from decimal import Decimal

from app.inventory_measurements import parse_decimal_exact
from .._shared import _add_log_cursor, get_transaction_cursor
from .movements import _insert_inventory_movement


def remove_product_batch(product_id: int, batch_id: int, reason: str, confirmed: bool,
                         expected_quantity: object, actor_account_id: int) -> bool:
    if not confirmed:
        raise ValueError("Confirm the batch removal before continuing.")
    note = reason.strip()
    if not note or len(note) > 500:
        raise ValueError("Enter a removal reason of 1 to 500 characters.")
    expected = parse_decimal_exact(expected_quantity, "Displayed batch stock", nonnegative=True)
    with get_transaction_cursor() as cur:
        cur.execute("""SELECT COALESCE(NULLIF(username,''),name) name FROM accounts
            WHERE account_id=%s AND is_active=true
            AND activation_status='active' AND (account_type='owner'
            OR (account_type='team_leader' AND team_leader_role='inventory'));""", (actor_account_id,))
        actor = cur.fetchone()
        if not actor:
            raise ValueError("Sign in with an active inventory account before removing a batch.")
        # Dispatch and batch receipts also lock the product before its batches.
        cur.execute("""SELECT item_id FROM inventory_items WHERE item_id=%s
            AND item_type='finished_product' FOR UPDATE;""", (product_id,))
        if not cur.fetchone():
            raise ValueError("Product was not found.")
        cur.execute("SELECT * FROM inventory_batches WHERE batch_id=%s AND item_id=%s FOR UPDATE;",
                    (batch_id, product_id))
        batch = cur.fetchone()
        if not batch:
            raise ValueError("Batch was not found for this product.")
        if batch["removed_at"] is not None:
            return False
        before = batch["quantity_available"]
        if before != expected:
            raise ValueError("Batch stock changed. Review the current quantity before confirming removal again.")
        cur.execute("""UPDATE inventory_batches SET quantity_available=0, removed_at=now(),
            removed_by_account_id=%s, removal_reason=%s WHERE batch_id=%s;""",
                    (actor_account_id, note, batch_id))
        if before > 0:
            _insert_inventory_movement(
                cur, item_id=product_id, affected_batch_id=batch_id, movement_type="owner_correction",
                quantity_delta=-before, unit=batch["unit"], balance_before=before, balance_after=Decimal("0"),
                actor_account_id=actor_account_id, actor_name=actor["name"],
                note=f"Batch removed: {batch['batch_code']}. {note}",
            )
        cur.execute("""UPDATE alerts SET status='resolved' WHERE product_batch_id=%s
            AND status IN ('open','acknowledged');""", (batch_id,))
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="removed_product_batch",
                        entity_type="inventory_batches", entity_id=batch_id)
    return True
