from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from app import inventory_measurements as measurements
from app.business_time import business_now, business_today
from app.config import BUSINESS_TIMEZONE
from app.database import clean_row, execute_write, fetch_all, fetch_one, get_transaction_cursor
from app.security import hash_password, password_needs_rehash, validate_password_policy, verify_password
from app.security_controls import record_event
from app.web_sessions import revoke_account_sessions

PRODUCT_SORTS = {
    "name_asc": "p.name ASC, p.item_id ASC",
    "name_desc": "p.name DESC, p.item_id DESC",
    "price_asc": "p.base_price ASC, p.name ASC",
    "price_desc": "p.base_price DESC, p.name ASC",
    "stock_desc": "available DESC, p.name ASC",
}

INVENTORY_ITEM_SORTS = {
    "name_asc": "ii.name ASC, ii.item_id ASC",
    "category_asc": "ii.category ASC, ii.name ASC",
    "stock_desc": "available DESC, ii.name ASC",
    "stock_asc": "available ASC, ii.name ASC",
}

BATCH_SORTS = {
    "newest": "ib.batch_id DESC",
    "oldest": "ib.batch_id ASC",
    "expiry_asc": "ib.expiry_date ASC NULLS LAST, ib.batch_id ASC",
    "available_desc": "ib.quantity_available DESC, ib.batch_id DESC",
    "product_asc": "ii.name ASC, ib.batch_id DESC",
}

ACCOUNT_SORTS = {
    "newest": "a.account_id DESC",
    "oldest": "a.account_id ASC",
    "name_asc": "a.name ASC, a.account_id ASC",
    "type_asc": "a.account_type ASC, a.name ASC",
    "status_asc": "a.is_active DESC, a.name ASC",
}

LOG_SORTS = {
    "newest": "al.activity_log_id DESC",
    "oldest": "al.activity_log_id ASC",
    "actor_asc": "COALESCE(a.name, 'MEATTRACK') ASC, al.activity_log_id DESC",
    "action_asc": "al.action ASC, al.activity_log_id DESC",
}

MOVEMENT_SORTS = {
    "newest": "im.movement_id DESC",
    "oldest": "im.movement_id ASC",
    "actor_asc": "im.actor_name ASC, im.movement_id DESC",
    "action_asc": "im.movement_type ASC, im.movement_id DESC",
}

UNIT_ALIASES = measurements.UNIT_ALIASES
UNIT_FACTORS = measurements.UNIT_FACTORS

raw_material_categories = ["meat", "raw_material"]
product_categories = ["Chicken", "Pork", "Beef"]

stock_units = list(measurements.STOCK_UNITS)
content_units = list(measurements.CONTENT_UNITS)
recipe_units = list(measurements.RECIPE_UNITS)

INVENTORY_LOG_ACTIONS = (
    "updated_raw_inventory",
    "added_raw_inventory_quantity",
    "created_product_recipe",
    "updated_product_recipe",
    "produced_product_batch",
    "registered_product_batch",
)

def safe_sort_sql(sort: str, allowed: dict[str, str], default_sql: str) -> str:
    """Return a whitelisted ORDER BY clause fragment."""
    return allowed.get((sort or "").strip(), default_sql)

def database_health() -> str:
    row = fetch_one("SELECT 1 AS ready")
    return "connected" if row and row["ready"] == 1 else "unavailable"

def normalize_inventory_text(value: str, label: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise ValueError(f"{label} is required.")
    return cleaned

def normalize_inventory_name(value: str, label: str = "Name") -> str:
    return normalize_inventory_text(value, label).title()

def parse_inventory_decimal(value: object, label: str, places: str) -> Decimal:
    scale = abs(Decimal(places).as_tuple().exponent)
    return measurements.parse_decimal_exact(value, label, scale=scale)

def display_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text

def parse_money(value: object, label: str = "Amount") -> Decimal:
    return measurements.parse_decimal_exact(value, label, scale=2, nonnegative=True)

def require_inventory_choice(value: object, choices: list[str], label: str) -> str:
    cleaned = normalize_inventory_text(str(value), label)
    for choice in choices:
        if cleaned.lower() == choice.lower():
            return choice
    raise ValueError(f"Choose a valid {label.lower()}.")

def canonical_inventory_unit(unit: str, label: str = "Unit") -> str:
    return measurements.canonical_unit(unit, label)

def convert_inventory_quantity(quantity: Decimal, from_unit: str, to_unit: str, item_name: str) -> Decimal:
    return measurements.convert_quantity(quantity, from_unit, to_unit, item_name)

def pagination_meta(total: int, page: int, page_size: int) -> dict:
    page_size = max(1, min(page_size, 50))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }

def _add_log_cursor(
    cur,
    *,
    actor_account_id: int | None,
    action: str,
    entity_type: str = "custom",
    entity_id: int | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO activity_logs (account_id, action, entity_type, entity_id, created_at)
        VALUES (%s, %s, %s, %s, now());
        """,
        (actor_account_id, action, entity_type, entity_id),
    )

def add_log(actor_name: str, action: str, entity_name: str, actor_account_id: int | None = None) -> None:
    with get_transaction_cursor() as cur:
        acc_id = actor_account_id
        if acc_id is None:
            cur.execute("SELECT account_id FROM accounts WHERE name = %s LIMIT 1;", (actor_name,))
            acc = cur.fetchone()
            acc_id = acc["account_id"] if acc else None
        _add_log_cursor(cur, actor_account_id=acc_id, action=action)

__all__ = [
    'hashlib', 'json', 'logging', 'secrets', 'date', 'datetime', 'timedelta', 'Decimal',
    'measurements', 'business_now', 'business_today', 'BUSINESS_TIMEZONE', 'clean_row',
    'execute_write', 'fetch_all', 'fetch_one', 'get_transaction_cursor', 'hash_password',
    'password_needs_rehash', 'validate_password_policy', 'verify_password',
    'record_event', 'revoke_account_sessions',
    'PRODUCT_SORTS', 'INVENTORY_ITEM_SORTS', 'BATCH_SORTS', 'ACCOUNT_SORTS',
    'LOG_SORTS', 'MOVEMENT_SORTS', 'UNIT_ALIASES', 'UNIT_FACTORS', 'raw_material_categories',
    'product_categories', 'stock_units', 'content_units', 'recipe_units', 'INVENTORY_LOG_ACTIONS',
    'safe_sort_sql', 'database_health', 'normalize_inventory_text', 'normalize_inventory_name',
    'parse_inventory_decimal', 'display_decimal', 'parse_money', 'require_inventory_choice',
    'canonical_inventory_unit', 'convert_inventory_quantity', 'pagination_meta',
    '_add_log_cursor', 'add_log'
]
