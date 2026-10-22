from __future__ import annotations

from ._shared import *

def _activity_log_filters(
    q: str,
    inventory_only: bool,
    actor_role: str,
    module: str,
    action: str,
    outcome: str,
    date_from: str,
    date_to: str,
) -> tuple[list[str], list[object]]:
    where = []
    params: list[object] = []
    q = q.strip()
    if inventory_only:
        where.append("al.action = ANY(%s)")
        params.append(list(INVENTORY_LOG_ACTIONS))
    if q:
        where.append("(COALESCE(a.name, 'MEATTRACK') ILIKE %s OR al.action ILIKE %s OR al.entity_type ILIKE %s)")
        search = f"%{q}%"
        params.extend([search, search, search])
    if actor_role.strip():
        where.append("al.actor_role = %s")
        params.append(actor_role.strip())
    if module.strip():
        where.append("al.entity_type = %s")
        params.append(module.strip())
    if action.strip():
        where.append("al.action = %s")
        params.append(action.strip())
    if outcome in {"success", "failure"}:
        where.append("al.outcome = %s")
        params.append(outcome)
    if date_from.strip():
        where.append("al.created_at >= %s::date")
        params.append(date_from.strip())
    if date_to.strip():
        where.append("al.created_at < %s::date + interval '1 day'")
        params.append(date_to.strip())
    return where, params

def list_activity_logs(
    q: str = "",
    page: int | None = None,
    page_size: int = 10,
    inventory_only: bool = False,
    sort: str = "",
    actor_role: str = "",
    module: str = "",
    action: str = "",
    outcome: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    where, params = _activity_log_filters(
        q, inventory_only, actor_role, module, action, outcome, date_from, date_to
    )
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    paging_sql = ""
    if page is not None:
        paging_sql = " LIMIT %s OFFSET %s"
        params.extend([page_size, (page - 1) * page_size])
    order_sql = safe_sort_sql(sort, LOG_SORTS, LOG_SORTS["newest"])
    return clean_row(fetch_all("""
        SELECT al.activity_log_id,
               COALESCE(a.name, 'MEATTRACK') AS actor,
               al.action,
               al.actor_role,
               al.outcome,
               al.request_id,
               (CASE
                    WHEN al.entity_type = 'products' THEN (SELECT name FROM inventory_items WHERE item_id = al.entity_id)
                    WHEN al.entity_type = 'raw_materials' THEN (SELECT name FROM inventory_items WHERE item_id = al.entity_id)
                    ELSE COALESCE(al.entity_type, 'System')
                END) AS entity,
               al.created_at
        FROM activity_logs al
        LEFT JOIN accounts a ON a.account_id = al.account_id
        {where_sql}
        ORDER BY {order_sql}
        {paging_sql};
    """.format(where_sql=where_sql, order_sql=order_sql, paging_sql=paging_sql), tuple(params) or None))

def count_activity_logs(
    q: str = "",
    inventory_only: bool = False,
    actor_role: str = "",
    module: str = "",
    action: str = "",
    outcome: str = "",
    date_from: str = "",
    date_to: str = "",
) -> int:
    query = """
        SELECT COUNT(*) AS total
        FROM activity_logs al
        LEFT JOIN accounts a ON a.account_id = al.account_id
    """
    where, params = _activity_log_filters(
        q, inventory_only, actor_role, module, action, outcome, date_from, date_to
    )
    if where:
        query += " WHERE " + " AND ".join(where)
    row = fetch_one(query + ";", tuple(params) or None)
    return int(row["total"]) if row else 0

def current_metrics() -> dict:
    row = fetch_one("""
        SELECT
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE status = 'open'
            ) AS open_alerts,
            COALESCE((
                SELECT SUM(ib.quantity_available)
                FROM inventory_batches ib
                JOIN inventory_items ii ON ii.item_id = ib.item_id
                WHERE ii.item_type = 'finished_product'
                  AND ib.quality_status = 'approved'
                  AND (ib.expiry_date IS NULL OR ib.expiry_date >= CURRENT_DATE)
            ), 0) AS total_available;
    """)

    return {
        "open_alerts": int(row["open_alerts"]) if row else 0,
        "total_available": float(row["total_available"]) if row else 0.0,
    }

def inventory_product_movement_analytics(days: int = 30, limit: int = 8) -> list[dict]:
    clean_days = max(1, min(int(days), 365))
    clean_limit = max(1, min(int(limit), 20))
    return clean_row(fetch_all("""
        SELECT p.item_id AS product_id,
               p.name,
               p.category,
               p.unit,
               COALESCE(stock.total_available, 0) AS total_available,
               COALESCE(product_in.total_in, 0) AS total_in,
               COALESCE(product_out.total_out, 0) AS total_out
        FROM inventory_items p
        LEFT JOIN (
            SELECT item_id, SUM(quantity_available) AS total_available
            FROM inventory_batches
            WHERE quality_status = 'approved'
              AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
            GROUP BY item_id
        ) stock ON stock.item_id = p.item_id
        LEFT JOIN (
            SELECT item_id, SUM(quantity_received) AS total_in
            FROM inventory_batches
            WHERE received_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
            GROUP BY item_id
        ) product_in ON product_in.item_id = p.item_id
        LEFT JOIN (
            SELECT item_id, ABS(SUM(quantity_delta)) AS total_out
            FROM inventory_movements
            WHERE quantity_delta < 0
              AND created_at >= CURRENT_DATE - (%s * INTERVAL '1 day')
            GROUP BY item_id
        ) product_out ON product_out.item_id = p.item_id
        WHERE p.item_type = 'finished_product'
          AND p.is_active = true
          AND (COALESCE(product_in.total_in, 0) > 0 OR COALESCE(product_out.total_out, 0) > 0)
        ORDER BY (COALESCE(product_in.total_in, 0) + COALESCE(product_out.total_out, 0)) DESC,
                 p.name
        LIMIT %s;
    """, (clean_days, clean_days, clean_limit)))

__all__ = [
    'count_activity_logs',
    'current_metrics',
    'inventory_product_movement_analytics',
    'list_activity_logs',
]
