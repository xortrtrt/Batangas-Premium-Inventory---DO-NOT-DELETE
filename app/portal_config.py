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
    ("logs", "Inventory movements", "scroll-text"),
    ("supplies-manage", "Supplies Workspace", "package-plus"),
    ("supplies", "Packaging & Supplies", "boxes"),
    ("supplies-movements", "Supply movements", "arrow-left-right"),
    ("profile", "Profile", "user-cog"),
]

INVENTORY_NAV_GROUPS = (
    (None, ("dashboard",)),
    ("Product Goods", ("inventory", "raw-materials", "finished-products", "batches", "logs")),
    ("Supplies", ("supplies-manage", "supplies", "supplies-movements")),
    (None, ("profile",)),
)

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
        "product-details": ("Product details", "package-search"),
        "package-details": ("Package details", "gift"),
        "removed-batches": ("Removed batches", "archive"),
    },
    "team-leader": {
        "notifications": ("Notifications", "bell"),
        "product-details": ("Product details", "package-search"),
        "package-details": ("Package details", "gift"),
        "removed-batches": ("Removed batches", "archive"),
    },
    "owner": {
        "notifications": ("Notifications", "bell"),
        "product-details": ("Product details", "package-search"),
        "package-details": ("Package details", "gift"),
        "removed-batches": ("Removed batches", "archive"),
    },
}

owner_nav_groups = INVENTORY_NAV_GROUPS

def portal_nav_for(role_key: str, team_leader_role: str | None = None) -> list[tuple[str, str, str]]:
    return INVENTORY_NAV

def portal_nav_groups_for(role_key: str, team_leader_role: str | None = None) -> list[dict]:
    nav_items = {slug: (slug, label, icon) for slug, label, icon in portal_nav_for(role_key, team_leader_role)}
    return [
        {
            "label": label,
            "items": [nav_items[slug] for slug in slugs],
        }
        for label, slugs in INVENTORY_NAV_GROUPS
    ]

def default_section_for(role_key: str, team_leader_role: str | None = None) -> str:
    return "dashboard"

__all__ = [
    'default_section_for',
    'owner_nav_groups',
    'portal_nav',
    'portal_nav_for',
    'portal_nav_groups_for',
    'portal_secondary_sections',
    'roles',
    'team_leader_nav_by_role',
    'team_leader_role_labels',
]
