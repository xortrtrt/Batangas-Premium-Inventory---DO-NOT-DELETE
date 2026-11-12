from app import portal_config


def test_inventory_navigation_order_and_labels():
    assert [item[:2] for item in portal_config.INVENTORY_NAV] == [
        ("dashboard", "Dashboard"),
        ("inventory", "Inventory Workspace"),
        ("raw-materials", "Raw Materials"),
        ("finished-products", "Finished Products"),
        ("batches", "Product Batches"),
        ("logs", "Inventory movements"),
        ("supplies-manage", "Supplies Workspace"),
        ("supplies", "Packaging & Supplies"),
        ("supplies-movements", "Supply movements"),
        ("profile", "Profile"),
    ]


def test_inventory_navigation_groups_preserve_the_full_navigation_order():
    groups = portal_config.portal_nav_groups_for("inventory")

    assert [group["label"] for group in groups] == [None, "Product Goods", "Supplies", None]
    assert [item[0] for group in groups for item in group["items"]] == [
        item[0] for item in portal_config.INVENTORY_NAV
    ]
