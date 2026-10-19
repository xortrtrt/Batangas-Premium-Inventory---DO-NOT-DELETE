from __future__ import annotations

roles = {
    "inventory": {
        "label": "Inventory Portal",
        "account_type": "team_leader",
        "name": "Inventory Manager",
        "email": "inventory@batangaspremium.test",
        "default_section": "dashboard",
    },
    "team-leader": {
        "label": "Inventory Portal",
        "account_type": "team_leader",
        "name": "Inventory Manager",
        "email": "inventory@batangaspremium.test",
        "default_section": "dashboard",
    },
    "owner": {
        "label": "Inventory Portal",
        "account_type": "owner",
        "name": "Admin",
        "email": "admin@batangaspremium.test",
        "default_section": "dashboard",
    },
}

team_leader_role_labels = {
    "inventory": "Inventory Manager",
}

INVENTORY_NAV = [
    ("dashboard", "Dashboard", "layout-dashboard"),
    ("inventory", "Inventory Workspace", "boxes"),
    ("raw-materials", "Raw Materials", "beef"),
    ("finished-products", "Finished Products", "package-search"),
    ("batches", "Product Batches", "package-check"),
    ("logs", "Inventory Logs", "scroll-text"),
    ("profile", "Profile", "user-cog"),
]

portal_nav = {
    "inventory": INVENTORY_NAV,
    "team-leader": INVENTORY_NAV,
    "owner": INVENTORY_NAV,
}

team_leader_nav_by_role = {
    "inventory": INVENTORY_NAV,
}

portal_secondary_sections = {
    "inventory": {
        "notifications": ("Notifications", "bell"),
    },
    "team-leader": {
        "notifications": ("Notifications", "bell"),
    },
    "owner": {
        "notifications": ("Notifications", "bell"),
    },
}

owner_nav_groups = (
    ("Inventory Operations", ("dashboard", "inventory", "raw-materials", "finished-products", "batches", "logs")),
    ("Account", ("profile",)),
)

def portal_nav_for(role_key: str, team_leader_role: str | None = None) -> list[tuple[str, str, str]]:
    return INVENTORY_NAV

def default_section_for(role_key: str, team_leader_role: str | None = None) -> str:
    return "dashboard"

__all__ = [
    'default_section_for',
    'owner_nav_groups',
    'portal_nav',
    'portal_nav_for',
    'portal_secondary_sections',
    'roles',
    'team_leader_nav_by_role',
    'team_leader_role_labels',
]
