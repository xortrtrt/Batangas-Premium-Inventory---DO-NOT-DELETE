"""Compatibility facade for inventory persistence operations."""

from .movements import _insert_inventory_movement, _inventory_actor_name
from .dispatch import dispatch_stock
from .products import (
    add_product_batch,
    create_product_with_recipe,
    produce_product,
    update_product_pack_content,
    update_product_recipe,
    update_product_price,
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
from .raw_materials import add_raw_inventory_item, add_raw_inventory_quantity

__all__ = [
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
    "update_product_pack_content",
    "update_product_recipe",
    "produce_product",
    "add_product_batch",
    "update_product_price",
]
