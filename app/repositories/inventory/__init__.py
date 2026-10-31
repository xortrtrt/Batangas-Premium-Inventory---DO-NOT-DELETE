"""Compatibility facade for inventory persistence operations."""

from .movements import _insert_inventory_movement, _inventory_actor_name
from .dispatch import dispatch_stock
from .details import product_stock_details
from .batch_removal import remove_product_batch
from .removed_batches import removed_batches_page
from .packages import package_workspace, save_package_contents, dispatch_package
from .products import (
    add_product_batch,
    create_product_with_recipe,
    produce_product,
    update_product_recipe,
)
from .queries import (
    count_inventory_batches,
    count_inventory_items,
    count_inventory_movements,
    count_products,
    inventory_item_filter,
    list_alerts,
    list_inventory_batches,
    list_inventory_items,
    list_inventory_movements,
    list_product_recipes,
    list_products,
    list_raw_materials,
)
from .raw_materials import add_raw_inventory_item, add_raw_inventory_quantity, deduct_raw_material, remove_raw_material, reactivate_raw_material

__all__ = [
    "product_stock_details",
    "remove_product_batch",
    "removed_batches_page",
    "package_workspace",
    "save_package_contents",
    "dispatch_package",
    "deduct_raw_material",
    "remove_raw_material",
    "reactivate_raw_material",
    "dispatch_stock",
    "inventory_item_filter",
    "list_inventory_items",
    "count_inventory_items",
    "list_inventory_batches",
    "count_inventory_batches",
    "list_products",
    "count_products",
    "list_raw_materials",
    "list_product_recipes",
    "list_alerts",
    "list_inventory_movements",
    "count_inventory_movements",
    "_inventory_actor_name",
    "_insert_inventory_movement",
    "add_raw_inventory_item",
    "add_raw_inventory_quantity",
    "create_product_with_recipe",
    "update_product_recipe",
    "produce_product",
    "add_product_batch",
]
