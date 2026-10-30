from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.inventory_measurements import parse_decimal_exact

from .._shared import (
    _add_log_cursor,
    canonical_inventory_unit,
    clean_row,
    get_transaction_cursor,
    normalize_inventory_name,
    parse_inventory_decimal,
    raw_material_categories,
    require_inventory_choice,
    stock_units,
)
from .movements import _insert_inventory_movement, _inventory_actor_name


def remove_raw_material(raw_material_id: int, confirmed: bool, actor_account_id: int) -> None:
    """Remove from active inventory explicitly, without erasing stock accountability."""
    if actor_account_id is None:
        raise ValueError("Sign in before removing a raw material.")
    with get_transaction_cursor() as cur:
        cur.execute("""SELECT item_id, name, unit, quantity_available, is_active FROM inventory_items
            WHERE item_id=%s AND item_type='raw_material' FOR UPDATE""", (raw_material_id,))
        material = cur.fetchone()
        if material is None or not material["is_active"]:
            raise ValueError("This raw material is no longer in active inventory.")
        if confirmed is not True:
            raise ValueError("Confirm that you want to remove this material.")
        cur.execute("""SELECT p.name FROM product_recipes pr
            JOIN inventory_items p ON p.item_id=pr.product_item_id
            WHERE pr.material_item_id=%s ORDER BY p.name LIMIT 1""", (raw_material_id,))
        recipe = cur.fetchone()
        if recipe:
            raise ValueError(f"{material['name']} is used by the {recipe['name']} recipe. "
                             "Update the recipe before removing this material.")
        _inventory_actor_name(cur, actor_account_id)
        cur.execute("UPDATE inventory_items SET is_active=false WHERE item_id=%s", (raw_material_id,))
        cur.execute("""UPDATE alerts SET status='resolved' WHERE raw_material_id=%s
            AND status IN ('open','acknowledged')""", (raw_material_id,))
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="removed_raw_material",
                        entity_type="inventory_items", entity_id=raw_material_id)


def reactivate_raw_material(raw_material_id: int, actor_account_id: int) -> None:
    if actor_account_id is None:
        raise ValueError("Sign in before reactivating a raw material.")
    with get_transaction_cursor() as cur:
        cur.execute("""SELECT item_id, name, is_active FROM inventory_items
            WHERE item_id=%s AND item_type='raw_material' FOR UPDATE""", (raw_material_id,))
        material = cur.fetchone()
        if material is None or material["is_active"]:
            raise ValueError("Choose a removed raw material to reactivate.")
        _inventory_actor_name(cur, actor_account_id)
        cur.execute("UPDATE inventory_items SET is_active=true WHERE item_id=%s", (raw_material_id,))
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="reactivated_raw_material",
                        entity_type="inventory_items", entity_id=raw_material_id)


def deduct_raw_material(raw_material_id: int, quantity: object, note: str,
                        submission_reference: str, actor_account_id: int) -> dict:
    amount = parse_decimal_exact(quantity, "Deduction quantity", scale=3, positive=True)
    clean_note = note.strip()
    if not clean_note or len(clean_note) > 500:
        raise ValueError("Enter a deduction reason of 1 to 500 characters.")
    try:
        reference = str(UUID(submission_reference))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid deduction reference. Reload the workspace and try again.") from None
    with get_transaction_cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"raw-deduction:{reference}",))
        cur.execute("SELECT * FROM inventory_movements WHERE raw_deduction_reference=%s", (reference,))
        existing = cur.fetchone()
        if existing:
            if (existing["item_id"] != raw_material_id or existing["quantity_delta"] != -amount
                    or existing["note"] != clean_note or existing["actor_account_id"] != actor_account_id):
                raise ValueError("This deduction reference was already used for different details. Reload the workspace.")
            return {"already_recorded": True, "reference": reference}
        cur.execute("""SELECT item_id, name, unit, quantity_available FROM inventory_items
            WHERE item_id=%s AND item_type='raw_material' AND is_active=true FOR UPDATE""", (raw_material_id,))
        material = cur.fetchone()
        if material is None:
            raise ValueError("Choose an active raw material.")
        if actor_account_id is None:
            raise ValueError("Sign in before deducting raw materials.")
        actor_name = _inventory_actor_name(cur, actor_account_id)
        before = material["quantity_available"]
        if before < amount:
            raise ValueError(f"Not enough {material['name']}. Available: {before:g} {material['unit']}.")
        after = before - amount
        cur.execute("UPDATE inventory_items SET quantity_available=%s WHERE item_id=%s", (after, raw_material_id))
        cur.execute("""INSERT INTO inventory_movements
            (item_id, movement_type, quantity_delta, unit, balance_before, balance_after,
             actor_account_id, actor_name, note, raw_deduction_reference)
            VALUES (%s, 'raw_deduction', %s, %s, %s, %s, %s, %s, %s, %s)""",
            (raw_material_id, -amount, material["unit"], before, after, actor_account_id, actor_name, clean_note, reference))
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="deducted_raw_material",
                        entity_type="inventory_items", entity_id=raw_material_id)
    return {"already_recorded": False, "reference": reference}


def add_raw_inventory_item(
    name: str,
    category: str,
    unit: str,
    quantity: object,
    actor_account_id: int | None = None,
) -> dict:
    item_name = normalize_inventory_name(name, "Item name")
    item_category = require_inventory_choice(category, raw_material_categories, "Category")
    item_unit = require_inventory_choice(unit, stock_units, "Unit")
    amount = parse_inventory_decimal(quantity, "Quantity", "0.001")
    if amount <= 0:
        raise ValueError("Quantity must be greater than zero.")

    with get_transaction_cursor() as cur:
        actor_name = _inventory_actor_name(cur, actor_account_id)
        cur.execute("""
            SELECT item_id, name, unit, is_active
            FROM inventory_items
            WHERE item_type = 'raw_material'
              AND lower(name) = lower(%s)
            ORDER BY item_id
            FOR UPDATE;
        """, (item_name,))
        matches = cur.fetchall()

        if matches:
            existing = matches[0]
            if not existing["is_active"]:
                raise ValueError(f"{existing['name']} is in Removed materials. Reactivate it there instead of adding a duplicate.")
            mismatched = next(
                (item for item in matches if canonical_inventory_unit(item["unit"]) != canonical_inventory_unit(item_unit)),
                None,
            )
            if mismatched or canonical_inventory_unit(existing["unit"]) != canonical_inventory_unit(item_unit):
                raise ValueError(f"{existing['name']} is already tracked in {existing['unit']}. Use the same unit.")
            raise ValueError(f"{existing['name']} already exists. Use Add quantity instead.")

        cur.execute("""
            INSERT INTO inventory_items (item_type, name, category, unit, quantity_available, is_active)
            VALUES ('raw_material', %s, %s, %s, %s, true)
            RETURNING item_id AS raw_material_id, category, name, unit, quantity_available AS available;
        """, (item_name, item_category, item_unit, amount))
        item = cur.fetchone()

        _insert_inventory_movement(
            cur,
            item_id=item["raw_material_id"],
            movement_type="raw_receipt",
            quantity_delta=amount,
            unit=item_unit,
            balance_before=Decimal("0.000"),
            balance_after=amount,
            actor_account_id=actor_account_id,
            actor_name=actor_name,
            note="Initial raw-material receipt",
        )
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="updated_raw_inventory", entity_type="inventory_items", entity_id=item["raw_material_id"])
    return clean_row(item)


def add_raw_inventory_quantity(
    raw_material_id: int,
    quantity: object,
    actor_account_id: int | None = None,
) -> dict:
    amount = parse_inventory_decimal(quantity, "Quantity", "0.001")
    if amount <= 0:
        raise ValueError("Quantity must be greater than zero.")

    with get_transaction_cursor() as cur:
        cur.execute("""
            SELECT item_id, name, unit, quantity_available
            FROM inventory_items
            WHERE item_id = %s
              AND item_type = 'raw_material'
              AND is_active = true
            FOR UPDATE;
        """, (raw_material_id,))
        item = cur.fetchone()
        if item is None:
            raise ValueError("Choose a valid raw inventory item.")

        cur.execute("""
            UPDATE inventory_items
            SET quantity_available = quantity_available + %s
            WHERE item_id = %s
            RETURNING item_id AS raw_material_id, category, name, unit, quantity_available AS available;
        """, (amount, raw_material_id))
        updated_item = cur.fetchone()

        actor_name = _inventory_actor_name(cur, actor_account_id)
        before = Decimal(item["quantity_available"])
        after = Decimal(updated_item["available"])
        _insert_inventory_movement(
            cur,
            item_id=raw_material_id,
            movement_type="raw_receipt",
            quantity_delta=amount,
            unit=item["unit"],
            balance_before=before,
            balance_after=after,
            actor_account_id=actor_account_id,
            actor_name=actor_name,
            note="Raw-material quantity added",
        )
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="added_raw_inventory_quantity", entity_type="inventory_items", entity_id=raw_material_id)
    return clean_row(updated_item)



