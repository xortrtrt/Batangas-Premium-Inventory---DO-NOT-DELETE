from __future__ import annotations

from typing import Any

from ._shared import fetch_all, fetch_one

SETTING_DEFAULTS: dict[str, Any] = {
    "inventory.near_expiry_days": 7,
    "inventory.critical_expiry_days": 2,
    "notifications.owner_critical_alerts": True,
    "business.name": "MeatTrack Inventory",
    "business.contact_email": "",
    "business.contact_phone": "",
}

def list_business_settings() -> dict[str, Any]:
    rows = fetch_all("SELECT setting_key, setting_value FROM business_settings ORDER BY setting_key;")
    values = dict(SETTING_DEFAULTS)
    values.update({row["setting_key"]: row["setting_value"] for row in rows})
    return values

def business_setting(key: str) -> Any:
    row = fetch_one("SELECT setting_value FROM business_settings WHERE setting_key = %s;", (key,))
    return row["setting_value"] if row else SETTING_DEFAULTS.get(key)

__all__ = [
    'SETTING_DEFAULTS',
    'business_setting',
    'list_business_settings',
]
