"""Export inventory definitions from an isolated restoration, never a live import."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


def export_catalog(source_url: str, meattrack_root: Path, output: Path, backup: Path) -> dict:
    # Read only the original image-name mapping, without importing the full app.
    tree = ast.parse((meattrack_root / "app/web.py").read_text(encoding="utf-8"))
    images = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PRODUCT_IMAGE_FILENAMES" for target in statement.targets
        ):
            images = ast.literal_eval(statement.value)
    images["bacon"] = "bacon_smoked.jpg"
    with psycopg2.connect(source_url) as conn:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT item_id AS source_id, item_type, name, description, category, unit,
                base_price::text, pack_size::text, pack_size_unit, pack_content_status, is_active
                FROM inventory_items ORDER BY item_type, name""")
            items = [dict(row) for row in cur.fetchall()]
            cur.execute("""SELECT product_item_id AS product_source_id, material_item_id AS material_source_id,
                quantity_required::text, unit FROM product_recipes ORDER BY product_item_id, material_item_id""")
            recipes = [dict(row) for row in cur.fetchall()]
    for item in items:
        item["image"] = None
        if item["item_type"] == "finished_product":
            key = re.sub(r"[^a-z0-9]+", " ", item["name"].lower()).strip()
            filename = images.get(key)
            if filename and (meattrack_root / "app/static/img" / filename).is_file():
                destination = output.parent.parent / "app/static/img" / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(meattrack_root / "app/static/img" / filename, destination)
                item["image"] = filename
    manifest = {
        "version": 1,
        "source_backup": backup.name,
        "source_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "items": items,
        "recipes": recipes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meattrack-root", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("catalog/meattrack-20261017-v1.json"))
    args = parser.parse_args()
    manifest = export_catalog(os.environ["CATALOG_SOURCE_URL"], args.meattrack_root, args.output, args.backup)
    print(f"Exported {len(manifest['items'])} item definitions and {len(manifest['recipes'])} recipe rows.")
