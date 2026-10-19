from __future__ import annotations

from fastapi import HTTPException, Request

ALL_INVENTORY_CAPABILITIES = frozenset({
    "*",
    "inventory.manage",
    "inventory.view",
    "notifications.view",
    "operations.view_team",
    "profile.manage_own",
    "reports.view_inventory",
})

CAPABILITIES_BY_ROLE: dict[str, frozenset[str]] = {
    "owner": ALL_INVENTORY_CAPABILITIES,
    "admin": ALL_INVENTORY_CAPABILITIES,
    "team-leader:inventory": ALL_INVENTORY_CAPABILITIES,
    "team-leader": ALL_INVENTORY_CAPABILITIES,
    "inventory": ALL_INVENTORY_CAPABILITIES,
}

PORTAL_SECTION_CAPABILITIES = {
    "inventory": {
        "dashboard": "operations.view_team",
        "inventory": "inventory.view",
        "raw-materials": "inventory.view",
        "finished-products": "inventory.view",
        "batches": "inventory.view",
        "logs": "reports.view_inventory",
        "profile": "profile.manage_own",
        "notifications": "notifications.view",
    }
}

def capability_role_key(request: Request, role_key: str | None = None) -> str:
    return "inventory"

def has_capability(request: Request, capability: str, role_key: str | None = None) -> bool:
    return True

def require_capability(request: Request, capability: str, role_key: str | None = None) -> None:
    pass

def portal_section_capability(request: Request, role_key: str, section: str) -> str:
    return "inventory.view"

__all__ = [
    "CAPABILITIES_BY_ROLE",
    "PORTAL_SECTION_CAPABILITIES",
    "capability_role_key",
    "has_capability",
    "portal_section_capability",
    "require_capability",
]
