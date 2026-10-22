"""Preview or add catalog definitions; never import quantities or overwrite client records."""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.config import database_dsn
from app.inventory_measurements import parse_decimal_exact

ITEM_FIELDS = {
    "source_id", "item_type", "name", "description", "category", "unit", "base_price",
    "pack_size", "pack_size_unit", "pack_content_status", "is_active", "image",
}


def item_key(item: dict) -> tuple[str, str]:
    return item["item_type"], " ".join(item["name"].split()).casefold()


def validate_manifest(manifest: dict) -> None:
    if manifest.get("version") != 1:
        raise ValueError("Unsupported catalog version.")
    by_id, keys = {}, set()
    for item in manifest["items"]:
        if set(item) != ITEM_FIELDS:
            raise ValueError("Catalog item fields must contain definitions only; stock/account fields are forbidden.")
        if item["item_type"] not in {"raw_material", "finished_product"} or not item["name"].strip():
            raise ValueError("Catalog item type and name are required.")
        key = item_key(item)
        if key in keys or item["source_id"] in by_id:
            raise ValueError("Duplicate catalog item.")
        keys.add(key)
        by_id[item["source_id"]] = item
        if not isinstance(item["is_active"], bool):
            raise ValueError("Catalog activation status must be boolean.")
        price = parse_decimal_exact(item["base_price"], "Price", scale=2, nonnegative=True)
        if item["item_type"] == "raw_material":
            if item["unit"] not in {"kg", "g", "ml"} or price != 0 or any(
                item[field] is not None for field in ("pack_size", "pack_size_unit", "pack_content_status")
            ):
                raise ValueError(f"Invalid raw-material definition: {item['name']}")
        elif item["unit"] != "pack":
            raise ValueError("Finished products must use packs.")
        elif item["pack_content_status"] == "declared":
            parse_decimal_exact(item["pack_size"], "Pack size", scale=3, positive=True)
            if item["pack_size_unit"] not in {"kg", "g", "ml"}:
                raise ValueError("Invalid pack-size unit.")
        elif (item["pack_content_status"] != "unknown_legacy"
              or item["pack_size"] is not None or item["pack_size_unit"] is not None):
            raise ValueError("Missing pack contents must stay explicitly unknown.")
        image = item["image"]
        if image and (Path(image).name != image or "/" in image or "\\" in image):
            raise ValueError("Catalog image must be a local filename.")
    pairs = set()
    for recipe in manifest["recipes"]:
        if set(recipe) != {"product_source_id", "material_source_id", "quantity_required", "unit"}:
            raise ValueError("Unexpected recipe fields.")
        product = by_id.get(recipe["product_source_id"])
        material = by_id.get(recipe["material_source_id"])
        if (not product or not material or product["item_type"] != "finished_product"
                or material["item_type"] != "raw_material" or recipe["unit"] != material["unit"]):
            raise ValueError("Recipe links or units are invalid.")
        pair = recipe["product_source_id"], recipe["material_source_id"]
        if pair in pairs:
            raise ValueError("Duplicate recipe ingredient.")
        pairs.add(pair)
        parse_decimal_exact(recipe["quantity_required"], "Ingredient quantity", scale=3, positive=True)


def import_catalog(manifest: dict, *, apply: bool = False, dsn: str | None = None) -> dict:
    validate_manifest(manifest)
    report = {key: [] for key in ("additions", "matches", "recipe_additions", "conflicts",
                                  "missing_images", "incomplete_recipes")}
    # The archived v1 source remains intact, but these fields never enter the client database.
    report["ignored_source_fields"] = ["base_price", "pack_size", "pack_size_unit", "pack_content_status"]
    products_with_recipe = {r["product_source_id"] for r in manifest["recipes"]}
    for item in manifest["items"]:
        if item["item_type"] == "finished_product":
            if not item["image"] or not (ROOT / "app/static/img" / item["image"]).is_file():
                report["missing_images"].append(item["name"])
            if item["source_id"] not in products_with_recipe:
                report["incomplete_recipes"].append(item["name"])
    with psycopg2.connect(dsn or database_dsn()) as conn:
        conn.set_session(readonly=not apply)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if apply:
                # Protect normalized matching from simultaneous imports and catalog edits.
                cur.execute("LOCK TABLE inventory_items, product_recipes IN SHARE ROW EXCLUSIVE MODE")
            cur.execute("SELECT * FROM inventory_items")
            target = {}
            for row in cur.fetchall():
                key = item_key(row)
                if key in target:
                    report["conflicts"].append(f"Duplicate target name: {row['name']}")
                target[key] = row
            mapped = {}
            for item in manifest["items"]:
                existing = target.get(item_key(item))
                if existing:
                    fields = ("unit",)
                    for field in fields:
                        source_value = item[field]
                        if existing[field] != source_value:
                            report["conflicts"].append(f"{item['name']}: conflicting {field}")
                    mapped[item["source_id"]] = existing["item_id"]
                    report["matches"].append(item["name"])
                else:
                    report["additions"].append(item["name"])
            cur.execute("SELECT * FROM product_recipes")
            existing_recipes = {(r["product_item_id"], r["material_item_id"]): r for r in cur.fetchall()}
            source_by_id = {item["source_id"]: item for item in manifest["items"]}
            for recipe in manifest["recipes"]:
                p, m = recipe["product_source_id"], recipe["material_source_id"]
                existing = existing_recipes.get((mapped.get(p), mapped.get(m)))
                label = f"{source_by_id[p]['name']} / {source_by_id[m]['name']}"
                if existing:
                    if existing["unit"] != recipe["unit"] or existing["quantity_required"] != Decimal(recipe["quantity_required"]):
                        report["conflicts"].append(f"Conflicting recipe: {label}")
                else:
                    report["recipe_additions"].append(label)
            if apply and not report["conflicts"]:
                for item in manifest["items"]:
                    if item["source_id"] in mapped:
                        continue
                    cur.execute("""INSERT INTO inventory_items
                        (item_type, name, description, category, unit, is_active, quantity_available)
                        VALUES (%s,%s,%s,%s,%s,%s,0) RETURNING item_id""",
                        tuple(item[field] for field in ("item_type", "name", "description", "category", "unit",
                              "is_active")))
                    mapped[item["source_id"]] = cur.fetchone()["item_id"]
                for recipe in manifest["recipes"]:
                    p, m = mapped[recipe["product_source_id"]], mapped[recipe["material_source_id"]]
                    if (p, m) not in existing_recipes:
                        cur.execute("""INSERT INTO product_recipes
                            (product_item_id,material_item_id,quantity_required,unit) VALUES (%s,%s,%s,%s)""",
                            (p, m, recipe["quantity_required"], recipe["unit"]))
    report["applied"] = apply and not report["conflicts"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true", help="Add definitions; default is a read-only preview.")
    args = parser.parse_args()
    report = import_catalog(json.loads(args.manifest.read_text(encoding="utf-8")), apply=args.apply)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["conflicts"]:
        raise SystemExit(1)
