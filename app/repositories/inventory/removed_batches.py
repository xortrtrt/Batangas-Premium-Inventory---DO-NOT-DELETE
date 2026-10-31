"""Archived batch records, separate from active stock."""
from .._shared import clean_row, fetch_all, fetch_one, pagination_meta


def removed_batches_page(q: str = "", page: int = 1, product_id: int | None = None) -> dict | None:
    product = None
    if product_id is not None:
        product = fetch_one("""SELECT item_id,name FROM inventory_items
            WHERE item_id=%s AND item_type='finished_product';""", (product_id,))
        if product is None:
            return None
    where = ["b.removed_at IS NOT NULL", "i.item_type='finished_product'"]
    params = []
    if product_id is not None:
        where.append("b.item_id=%s")
        params.append(product_id)
    if q.strip():
        where.append("""(b.batch_code ILIKE %s OR i.name ILIKE %s OR b.removal_reason ILIKE %s
            OR a.name ILIKE %s OR a.username ILIKE %s)""")
        params.extend([f"%{q.strip()}%"] * 5)
    source = """FROM inventory_batches b JOIN inventory_items i ON i.item_id=b.item_id
        JOIN accounts a ON a.account_id=b.removed_by_account_id WHERE """ + " AND ".join(where)
    total = fetch_one("SELECT COUNT(*) total " + source, tuple(params))["total"]
    pagination = pagination_meta(int(total), page, 10)
    items = fetch_all("""SELECT b.batch_id,b.item_id,b.batch_code,b.source_type,b.quantity_received,
        b.received_date,b.expiry_date,b.removal_reason,b.removed_at,i.name product_name,
        COALESCE(NULLIF(a.username,''),a.name) removed_by,
        COALESCE((SELECT -m.quantity_delta FROM inventory_movements m
            WHERE m.affected_batch_id=b.batch_id AND m.movement_type='owner_correction'
            AND m.created_at=b.removed_at AND m.actor_account_id=b.removed_by_account_id
            AND m.note LIKE 'Batch removed:%%' ORDER BY m.movement_id DESC LIMIT 1),0) quantity_removed
        """ + source + " ORDER BY b.removed_at DESC,b.batch_id DESC LIMIT 10 OFFSET %s",
        tuple([*params, (pagination["page"] - 1) * 10]))
    return clean_row({"items": items, "pagination": pagination, "q": q.strip(), "product": product})
