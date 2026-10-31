"""Read-only batch and movement history for a single finished product."""
from __future__ import annotations

from .._shared import clean_row, fetch_all, fetch_one, pagination_meta
from ..settings import business_setting


def product_stock_details(product_id: int, batch_page: int = 1, movement_page: int = 1) -> dict | None:
    product = fetch_one("""SELECT item_id, name, category, unit, is_active,
        EXISTS(SELECT 1 FROM inventory_product_images pi WHERE pi.product_item_id=inventory_items.item_id) has_image
        FROM inventory_items WHERE item_id=%s AND item_type='finished_product';""", (product_id,))
    if product is None:
        return None
    near_expiry_days = int(business_setting("inventory.near_expiry_days"))
    totals = fetch_one("""SELECT COUNT(*) batch_count,
        COALESCE(SUM(quantity_available),0) physical_stock,
        COALESCE(SUM(quantity_available) FILTER (WHERE expiry_date<CURRENT_DATE),0) expired_stock,
        COALESCE(SUM(quantity_available) FILTER (WHERE quality_status='approved'
            AND expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE+%s),0) near_expiry_stock,
        COALESCE(SUM(quantity_available) FILTER (
            WHERE quality_status='approved' AND expiry_date>=CURRENT_DATE),0) available_stock
        FROM inventory_batches WHERE item_id=%s AND removed_at IS NULL;""", (near_expiry_days, product_id))
    movement_count = fetch_one(
        "SELECT COUNT(*) total FROM inventory_movements WHERE item_id=%s;", (product_id,)
    )["total"]
    batch_pagination = pagination_meta(int(totals["batch_count"]), batch_page, 10)
    movement_pagination = pagination_meta(int(movement_count), movement_page, 10)
    batches = fetch_all("""SELECT batch_id, batch_code, source_type, quantity_received,
        quantity_available, unit, received_date, expiry_date, quality_status,
        expiry_date<CURRENT_DATE AS is_expired, expiry_date-CURRENT_DATE AS days_left
        FROM inventory_batches WHERE item_id=%s AND removed_at IS NULL
        ORDER BY expiry_date ASC NULLS LAST, batch_id ASC LIMIT 10 OFFSET %s;""",
        (product_id, (batch_pagination["page"] - 1) * 10))
    movements = fetch_all("""SELECT m.movement_id, m.movement_type, m.quantity_delta, m.unit,
        m.balance_before, m.balance_after, m.actor_name, m.note, m.created_at,
        m.dispatch_id, b.batch_code
        FROM inventory_movements m LEFT JOIN inventory_batches b ON b.batch_id=m.affected_batch_id
        WHERE m.item_id=%s ORDER BY m.created_at DESC, m.movement_id DESC LIMIT 10 OFFSET %s;""",
        (product_id, (movement_pagination["page"] - 1) * 10))
    return clean_row({"product": product, "totals": totals, "batches": batches, "movements": movements,
                      "batch_pagination": batch_pagination, "movement_pagination": movement_pagination,
                      "near_expiry_days": near_expiry_days})
