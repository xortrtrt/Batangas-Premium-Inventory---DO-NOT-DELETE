from __future__ import annotations

from .._shared import (
    BATCH_SORTS,
    INVENTORY_ITEM_SORTS,
    MOVEMENT_SORTS,
    PRODUCT_SORTS,
    clean_row,
    fetch_all,
    fetch_one,
    safe_sort_sql,
)


MOVEMENT_CATEGORY_TYPES = {
    "deductions": ("raw_deduction",),
    "opening": ("opening_balance",),
    "receipts": ("raw_receipt", "direct_finished_receipt"),
    "production": ("production_consumption", "production_output"),
    "dispatch": ("stock_dispatch", "sale_fulfillment"),
}


def inventory_item_filter(category: str) -> tuple[str, str]:
    raw = (category or "").strip()
    if ":" in raw:
        item_type, item_category = raw.split(":", 1)
        if item_type in {"raw_material", "finished_product"}:
            return item_type, item_category.strip().replace("_", " ")
    if raw in {"raw_material", "finished_product"}:
        return raw, ""
    return "", raw.replace("_", " ")


def list_inventory_items(q: str = "", category: str = "", page: int | None = None, page_size: int = 10, sort: str = "", raw_material_active: bool = True, exclude_packages: bool = False) -> list[dict]:
    where = ["ii.item_type IN ('raw_material', 'finished_product')", "(ii.item_type <> 'raw_material' OR ii.is_active = %s)"]
    params: list[object] = [raw_material_active]
    if exclude_packages:
        where.append("ii.category IS DISTINCT FROM 'Package'")
    q = q.strip()
    item_type, item_category = inventory_item_filter(category)
    if q:
        where.append("(ii.name ILIKE %s OR ii.category ILIKE %s OR ii.unit ILIKE %s)")
        search = f"%{q}%"
        params.extend([search, search, search])
    if item_type:
        where.append("ii.item_type = %s")
        params.append(item_type)
    if item_category:
        where.append("LOWER(ii.category) = LOWER(%s)")
        params.append(item_category)
    paging_sql = ""
    if page is not None:
        paging_sql = " LIMIT %s OFFSET %s"
        params.extend([page_size, (page - 1) * page_size])
    order_sql = safe_sort_sql(sort, INVENTORY_ITEM_SORTS, "CASE ii.item_type WHEN 'raw_material' THEN 1 ELSE 2 END, ii.category, ii.name")
    return clean_row(fetch_all("""
        SELECT ii.item_id, ii.item_type,
               CASE ii.item_type
                   WHEN 'raw_material' THEN 'Raw material'
                   WHEN 'finished_product' THEN 'Finished product'
               END AS item_type_label,
               ii.category, ii.name, ii.unit,
               EXISTS(SELECT 1 FROM inventory_product_images pi WHERE pi.product_item_id=ii.item_id) has_image,
               (SELECT s.mode FROM inventory_package_settings s WHERE s.package_item_id=ii.item_id) package_mode,
               ii.is_active,
               CASE
                   WHEN ii.item_type = 'raw_material' THEN ii.quantity_available
                   ELSE COALESCE(SUM(ib.quantity_available) FILTER (
                       WHERE ib.quality_status = 'approved'
                         AND ib.expiry_date >= CURRENT_DATE
                   ), 0)
               END AS available
        FROM inventory_items ii
        LEFT JOIN inventory_batches ib ON ib.item_id = ii.item_id
        WHERE {where_sql}
        GROUP BY ii.item_id, ii.item_type, ii.category, ii.name, ii.unit,
                 ii.quantity_available, ii.is_active
        ORDER BY {order_sql}
        {paging_sql};
    """.format(where_sql=" AND ".join(where), order_sql=order_sql, paging_sql=paging_sql), tuple(params) or None))


def count_inventory_items(q: str = "", category: str = "", raw_material_active: bool = True, exclude_packages: bool = False) -> int:
    where = ["ii.item_type IN ('raw_material', 'finished_product')", "(ii.item_type <> 'raw_material' OR ii.is_active = %s)"]
    params: list[object] = [raw_material_active]
    if exclude_packages:
        where.append("ii.category IS DISTINCT FROM 'Package'")
    q = q.strip()
    item_type, item_category = inventory_item_filter(category)
    if q:
        where.append("(ii.name ILIKE %s OR ii.category ILIKE %s OR ii.unit ILIKE %s)")
        search = f"%{q}%"
        params.extend([search, search, search])
    if item_type:
        where.append("ii.item_type = %s")
        params.append(item_type)
    if item_category:
        where.append("LOWER(ii.category) = LOWER(%s)")
        params.append(item_category)
    row = fetch_one(f"""
        SELECT COUNT(*) AS total
        FROM inventory_items ii
        WHERE {" AND ".join(where)};
    """, tuple(params) or None)
    return int(row["total"])


def list_inventory_batches(q: str = "", category: str = "", page: int | None = None, page_size: int = 10, sort: str = "") -> list[dict]:
    where = ["ii.item_type = 'finished_product'", "ib.removed_at IS NULL"]
    params: list[object] = []
    q = q.strip()
    category = category.strip()
    if q:
        where.append("(ib.batch_code ILIKE %s OR ii.name ILIKE %s OR ib.source_type ILIKE %s)")
        search = f"%{q}%"
        params.extend([search, search, search])
    if category:
        where.append("ii.category = %s")
        params.append(category)
    paging_sql = ""
    if page is not None:
        paging_sql = " LIMIT %s OFFSET %s"
        params.extend([page_size, (page - 1) * page_size])
    order_sql = safe_sort_sql(sort, BATCH_SORTS, BATCH_SORTS["newest"])
    return clean_row(fetch_all("""
        SELECT ib.batch_id, ib.item_id, ii.item_type,
               CASE ii.item_type
                   WHEN 'raw_material' THEN 'Raw material'
                   WHEN 'finished_product' THEN 'Finished product'
               END AS item_type_label,
               ii.name AS item_name, ii.category, ib.batch_code, ib.source_type,
               ib.quantity_received, ib.quantity_available, ib.unit,
               ib.received_date, ib.expiry_date, ib.quality_status,
               ib.expiry_date - CURRENT_DATE AS days_until_expiry
        FROM inventory_batches ib
        JOIN inventory_items ii ON ii.item_id = ib.item_id
        WHERE {where_sql}
        ORDER BY {order_sql}
        {paging_sql};
    """.format(where_sql=" AND ".join(where), order_sql=order_sql, paging_sql=paging_sql), tuple(params) or None))


def count_inventory_batches(q: str = "", category: str = "") -> int:
    where = ["ii.item_type = 'finished_product'", "ib.removed_at IS NULL"]
    params: list[object] = []
    q = q.strip()
    category = category.strip()
    if q:
        where.append("(ib.batch_code ILIKE %s OR ii.name ILIKE %s OR ib.source_type ILIKE %s)")
        search = f"%{q}%"
        params.extend([search, search, search])
    if category:
        where.append("ii.category = %s")
        params.append(category)
    row = fetch_one(f"""
        SELECT COUNT(*) AS total
        FROM inventory_batches ib
        JOIN inventory_items ii ON ii.item_id = ib.item_id
        WHERE {" AND ".join(where)};
    """, tuple(params) or None)
    return int(row["total"])


def list_products(
    q: str = "",
    category: str = "",
    page: int | None = None,
    page_size: int = 12,
    sort: str = "",
    active_only: bool = False,
    include_packages: bool = True,
) -> list[dict]:
    where_extra = []
    params: list[object] = []
    q = q.strip()
    category = category.strip()
    if q:
        where_extra.append("(p.name ILIKE %s OR p.description ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if category:
        where_extra.append("p.category = %s")
        params.append(category)
    if active_only:
        where_extra.append("p.is_active = true")
    if not include_packages:
        where_extra.append("p.category IS DISTINCT FROM 'Package'")
    paging_sql = ""
    if page is not None:
        paging_sql = " LIMIT %s OFFSET %s"
        params.extend([page_size, (page - 1) * page_size])
    order_sql = safe_sort_sql(sort, PRODUCT_SORTS, "p.item_id")
    return clean_row(fetch_all("""
        SELECT p.item_id AS product_id, p.name, p.description, p.unit, p.is_active,
               p.category,
               (
                   SELECT COUNT(*)
                   FROM product_recipes pr
                   JOIN inventory_items rm ON rm.item_id = pr.material_item_id
                   WHERE pr.product_item_id = p.item_id
                     AND rm.item_type = 'raw_material'
               ) AS recipe_count,
               COALESCE(SUM(pb.quantity_available) FILTER (
                   WHERE pb.quality_status = 'approved'
                     AND (pb.expiry_date IS NULL OR pb.expiry_date >= CURRENT_DATE)
               ), 0) AS available
        FROM inventory_items p
        LEFT JOIN inventory_batches pb ON pb.item_id = p.item_id
        WHERE p.item_type = 'finished_product'
          {where_extra}
        GROUP BY p.item_id, p.name, p.description, p.unit, p.is_active, p.category
        ORDER BY {order_sql}
        {paging_sql};
    """.format(
        where_extra=("AND " + " AND ".join(where_extra)) if where_extra else "",
        order_sql=order_sql,
        paging_sql=paging_sql,
    ), tuple(params) or None))


def count_products(q: str = "", category: str = "", active_only: bool = False, include_packages: bool = True) -> int:
    query = """
        SELECT COUNT(*) AS total
        FROM inventory_items p
        WHERE p.item_type = 'finished_product'
    """
    params: list[object] = []
    q = q.strip()
    category = category.strip()
    if q:
        query += " AND (p.name ILIKE %s OR p.description ILIKE %s)"
        params.extend([f"%{q}%", f"%{q}%"])
    if category:
        query += " AND p.category = %s"
        params.append(category)
    if active_only:
        query += " AND p.is_active = true"
    if not include_packages:
        query += " AND p.category IS DISTINCT FROM 'Package'"
    row = fetch_one(query + ";", tuple(params) or None)
    return int(row["total"])


def list_raw_materials() -> list[dict]:
    return clean_row(fetch_all("""
        SELECT item_id AS raw_material_id, category, name, unit,
               quantity_available AS available
        FROM inventory_items
        WHERE item_type = 'raw_material'
          AND is_active = true
        ORDER BY category, name;
    """))


def list_product_recipes(product_ids: list[int] | None = None) -> list[dict]:
    where = [
        "p.item_type = 'finished_product'",
        "rm.item_type = 'raw_material'",
    ]
    params: list[object] = []
    if product_ids is not None:
        scoped_product_ids = [int(product_id) for product_id in product_ids]
        if not scoped_product_ids:
            return []
        where.append("pr.product_item_id = ANY(%s)")
        params.append(scoped_product_ids)

    return clean_row(fetch_all(f"""
        SELECT pr.recipe_id, pr.product_item_id AS product_id, p.name AS product_name,
               pr.material_item_id AS raw_material_id, rm.name AS raw_material_name,
               rm.category AS raw_material_category,
               pr.quantity_required, pr.unit
        FROM product_recipes pr
        JOIN inventory_items p ON p.item_id = pr.product_item_id
        JOIN inventory_items rm ON rm.item_id = pr.material_item_id
        WHERE {" AND ".join(where)}
        ORDER BY p.name, rm.category, rm.name;
    """, tuple(params) or None))


def list_alerts() -> list[dict]:
    return clean_row(fetch_all("""
        SELECT al.alert_id, al.alert_type, al.severity, al.message, al.status, al.triggered_at,
               (CASE
                    WHEN al.product_batch_id IS NOT NULL THEN (
                        SELECT p.name || ' batch ' || pb.batch_code
                        FROM inventory_batches pb
                        JOIN inventory_items p ON p.item_id = pb.item_id
                        WHERE pb.batch_id = al.product_batch_id
                    )
                    WHEN al.product_id IS NOT NULL THEN (SELECT name FROM inventory_items WHERE item_id = al.product_id)
                    WHEN al.raw_material_id IS NOT NULL THEN (SELECT name FROM inventory_items WHERE item_id = al.raw_material_id)
                    ELSE 'System Alert'
                END) AS subject
        FROM alerts al
        ORDER BY al.alert_id DESC;
    """))


# The ledger keeps component stock movements intact, but presents a package
# dispatch as one event before searching, counting, sorting, or paginating.
INVENTORY_LOG_EVENTS = """
    WITH log_events AS (
        SELECT im.movement_id, im.movement_type, ii.name AS entity,
               im.quantity_delta, im.unit, im.balance_before, im.balance_after,
               im.actor_account_id, im.actor_name, im.note, im.dispatch_id,
               im.raw_deduction_reference, im.created_at,
               NULL::text AS package_mode, NULL::json AS package_contents,
               NULL::text AS package_search
        FROM inventory_movements im
        JOIN inventory_items ii ON ii.item_id=im.item_id
        WHERE NOT EXISTS (SELECT 1 FROM inventory_package_dispatch_details h
                          WHERE h.dispatch_id=im.dispatch_id)
        UNION ALL
        SELECT actor.movement_id, 'stock_dispatch', h.package_name,
               -d.quantity, 'package', NULL::numeric, NULL::numeric,
               d.actor_account_id, actor.actor_name, d.note, d.dispatch_id,
               NULL::uuid, d.created_at, h.package_mode,
               (SELECT json_agg(json_build_object(
                   'name', l.product_name, 'quantity_per_package', l.quantity_per_package,
                   'total_packs', l.total_packs) ORDER BY l.product_name,l.product_item_id)
                FROM inventory_package_dispatch_lines l WHERE l.dispatch_id=d.dispatch_id),
               (SELECT string_agg(l.product_name,' ') FROM inventory_package_dispatch_lines l
                WHERE l.dispatch_id=d.dispatch_id)
        FROM inventory_dispatches d
        JOIN inventory_package_dispatch_details h USING(dispatch_id)
        JOIN LATERAL (
            SELECT m.movement_id,m.actor_name FROM inventory_movements m
            WHERE m.dispatch_id=d.dispatch_id ORDER BY m.movement_id LIMIT 1
        ) actor ON true
    )
"""


def _inventory_log_filter(q, category):
    where = []
    params = []
    if q.strip():
        where.append("""(im.movement_type ILIKE %s OR im.entity ILIKE %s
            OR im.actor_name ILIKE %s OR im.package_search ILIKE %s)""")
        params.extend([f"%{q.strip()}%"] * 4)
    if category.strip() in MOVEMENT_CATEGORY_TYPES:
        where.append("im.movement_type = ANY(%s)")
        params.append(list(MOVEMENT_CATEGORY_TYPES[category.strip()]))
    return (f"WHERE {' AND '.join(where)}" if where else ""), params


def list_inventory_movements(
    q: str = "",
    category: str = "",
    page: int | None = None,
    page_size: int = 10,
    sort: str = "",
) -> list[dict]:
    where_sql, params = _inventory_log_filter(q, category)
    paging_sql = ""
    if page is not None:
        paging_sql = " LIMIT %s OFFSET %s"
        params.extend([page_size, (page - 1) * page_size])
    order_sql = safe_sort_sql(sort, MOVEMENT_SORTS, MOVEMENT_SORTS["newest"])
    return clean_row(fetch_all(INVENTORY_LOG_EVENTS + f"""
        SELECT im.movement_id,
               im.movement_type AS action,
               im.entity,
               im.quantity_delta,
               im.unit,
               im.balance_before,
               im.balance_after,
               im.actor_account_id,
               im.actor_name,
               im.note,
               im.dispatch_id,
               im.raw_deduction_reference,
               im.created_at,
               im.package_mode,
               im.package_contents
        FROM log_events im
        {where_sql}
        ORDER BY {order_sql}
        {paging_sql};
    """, tuple(params) or None))


def count_inventory_movements(q: str = "", category: str = "") -> int:
    where_sql, params = _inventory_log_filter(q, category)
    row = fetch_one(INVENTORY_LOG_EVENTS + f"""
        SELECT COUNT(*) AS total
        FROM log_events im
        {where_sql};
    """, tuple(params) or None)
    return int(row["total"])



