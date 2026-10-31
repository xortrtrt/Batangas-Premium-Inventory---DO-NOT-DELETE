"""Fixed and customized packages composed of existing finished-product packs."""
from decimal import Decimal
from uuid import UUID

from app.inventory_measurements import parse_whole_packs
from .._shared import clean_row, fetch_all, fetch_one, get_transaction_cursor, _add_log_cursor
from .movements import _inventory_actor_name


MAX_PACKS = Decimal("999999999")


def _packs(value, label):
    if len(str(value).strip()) > 12:
        raise ValueError(f"{label} must not exceed {MAX_PACKS}.")
    result = parse_whole_packs(value, label)
    if result > MAX_PACKS:
        raise ValueError(f"{label} must not exceed {MAX_PACKS}.")
    return result


def _components(product_ids, quantities) -> dict[int, Decimal]:
    if len(product_ids) != len(quantities):
        raise ValueError("Package content rows are incomplete.")
    result = {}
    seen = set()
    for raw_id, raw_quantity in zip(product_ids, quantities):
        try:
            product_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError("Choose valid finished products.") from None
        if product_id in seen:
            raise ValueError("Each finished product can appear only once.")
        seen.add(product_id)
        if str(raw_quantity).strip() in {"", "0"}:
            continue
        result[product_id] = _packs(raw_quantity, "Packs per package")
    return result


def _lock_package(cur, package_id):
    cur.execute("""SELECT i.item_id,i.name,s.mode,s.revision,s.standard_locked_at FROM inventory_items i
        JOIN inventory_package_settings s ON s.package_item_id=i.item_id
        WHERE i.item_id=%s AND i.category='Package' AND i.is_active=true
        FOR UPDATE OF i,s;""", (package_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError("Choose an active package.")
    return row


def _lock_products(cur, ids):
    cur.execute("""SELECT item_id,name,unit FROM inventory_items
        WHERE item_id=ANY(%s) AND item_type='finished_product' AND category<>'Package'
        AND is_active=true ORDER BY item_id FOR UPDATE;""", (sorted(ids),))
    rows = {r["item_id"]: r for r in cur.fetchall()}
    if len(rows) != len(ids):
        raise ValueError("Package contents must use active individual finished products.")
    return rows


def save_package_contents(package_id, mode, product_ids, quantities, expected_revision, actor_account_id, confirmed=False):
    if mode != "standard":
        raise ValueError("Customized contents are chosen for one dispatch, not saved as package settings.")
    if not confirmed:
        raise ValueError("Confirm that standard contents cannot be changed after saving.")
    contents = _components(product_ids, quantities)
    if mode == "standard" and not contents:
        raise ValueError("Select at least one finished product for a standard package.")
    with get_transaction_cursor() as cur:
        package = _lock_package(cur, package_id)
        if package["standard_locked_at"] is not None:
            raise ValueError("Standard contents are already saved and cannot be changed. Use Customize for a one-time dispatch.")
        if package["revision"] != expected_revision:
            raise ValueError("Package settings changed. Reload and review the latest contents.")
        _lock_products(cur, contents)
        cur.execute("DELETE FROM inventory_package_components WHERE package_item_id=%s", (package_id,))
        for product_id, quantity in contents.items():
            cur.execute("INSERT INTO inventory_package_components VALUES (%s,%s,%s)", (package_id, product_id, quantity))
        cur.execute("""UPDATE inventory_package_settings SET mode='standard',revision=revision+1,
            standard_locked_at=now() WHERE package_item_id=%s""", (package_id,))
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="updated_package_contents",
                        entity_type="inventory_items", entity_id=package_id)


def package_workspace(package_id):
    package = fetch_one("""SELECT i.item_id,i.name,i.is_active,s.mode,s.revision,s.standard_locked_at FROM inventory_items i
        JOIN inventory_package_settings s ON s.package_item_id=i.item_id
        WHERE i.item_id=%s AND i.category='Package';""", (package_id,))
    if package is None:
        return None
    products = fetch_all("""SELECT i.item_id,i.name,i.is_active,COALESCE(c.quantity_per_package,0) quantity_per_package,
        COALESCE((SELECT SUM(b.quantity_available) FROM inventory_batches b WHERE b.item_id=i.item_id
            AND b.removed_at IS NULL AND b.quality_status='approved' AND b.expiry_date>=CURRENT_DATE),0) available
        FROM inventory_items i LEFT JOIN inventory_package_components c
            ON c.product_item_id=i.item_id AND c.package_item_id=%s
        WHERE i.item_type='finished_product' AND i.category<>'Package' AND (i.is_active OR c.product_item_id IS NOT NULL)
        ORDER BY i.name;""", (package_id,))
    selected = [p for p in products if p["quantity_per_package"] > 0] if package["standard_locked_at"] else []
    capacity = min((int(p["available"] // p["quantity_per_package"]) if p["is_active"] else 0 for p in selected), default=0)
    history = fetch_all("""SELECT d.dispatch_id,d.quantity,d.note,d.created_at,h.package_mode,
        COALESCE(NULLIF(a.username,''),a.name) actor_name,
        (SELECT json_agg(json_build_object('name',l.product_name,'quantity',l.total_packs))
            FROM inventory_package_dispatch_lines l WHERE l.dispatch_id=d.dispatch_id) contents
        FROM inventory_dispatches d JOIN inventory_package_dispatch_details h USING(dispatch_id)
        JOIN accounts a ON a.account_id=d.actor_account_id WHERE d.product_item_id=%s
        ORDER BY d.created_at DESC,d.dispatch_id DESC LIMIT 20;""", (package_id,))
    return clean_row({"package": package, "component_products": products, "package_contents": selected,
                      "package_capacity": capacity, "package_history": history})


def dispatch_package(package_id, quantity, note, reference, product_ids, quantities, expected_revision, actor_account_id,
                     dispatch_mode="standard"):
    if dispatch_mode not in {"standard", "customized"}:
        raise ValueError("Choose Standard or Customize for this dispatch.")
    amount = _packs(quantity, "Number of packages")
    note = note.strip()
    if not note or len(note) > 500:
        raise ValueError("Enter a dispatch note of 1 to 500 characters.")
    try:
        reference = str(UUID(reference))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid dispatch reference. Reload the package.") from None
    requested = _components(product_ids, quantities)
    with get_transaction_cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"dispatch:{reference}",))
        cur.execute("SELECT * FROM inventory_dispatches WHERE dispatch_id=%s", (reference,))
        existing = cur.fetchone()
        if existing:
            cur.execute("SELECT * FROM inventory_package_dispatch_details WHERE dispatch_id=%s", (reference,))
            snapshot = cur.fetchone()
            cur.execute("SELECT product_item_id,quantity_per_package FROM inventory_package_dispatch_lines WHERE dispatch_id=%s", (reference,))
            original = {r["product_item_id"]: r["quantity_per_package"] for r in cur.fetchall()}
            if (not snapshot or existing["product_item_id"] != package_id or existing["quantity"] != amount
                    or existing["note"] != note or existing["actor_account_id"] != actor_account_id
                    or snapshot["package_revision"] != expected_revision
                    or snapshot["package_mode"] != dispatch_mode
                    or (snapshot["package_mode"] == "customized" and requested != original)):
                raise ValueError("This dispatch reference was used for different details. Reload the package.")
            return {"already_recorded": True}
        package = _lock_package(cur, package_id)
        if package["revision"] != expected_revision:
            raise ValueError("Package settings changed. Reload and review the current contents.")
        if dispatch_mode == "standard":
            if package["standard_locked_at"] is None:
                raise ValueError("Save the standard contents before dispatching a Standard package, or choose Customize.")
            cur.execute("SELECT product_item_id,quantity_per_package FROM inventory_package_components WHERE package_item_id=%s", (package_id,))
            contents = {r["product_item_id"]: r["quantity_per_package"] for r in cur.fetchall()}
        else:
            contents = requested
        if not contents:
            raise ValueError("Choose at least one finished product and its packs per package.")
        products = _lock_products(cur, contents)
        actor_name = _inventory_actor_name(cur, actor_account_id)
        allocations = []
        for product_id in sorted(contents):
            required = contents[product_id] * amount
            if required > MAX_PACKS:
                raise ValueError("The total packs exceed the supported stock limit.")
            cur.execute("""SELECT batch_id,quantity_available FROM inventory_batches
                WHERE item_id=%s AND removed_at IS NULL AND quality_status='approved'
                AND expiry_date>=CURRENT_DATE AND quantity_available>0
                ORDER BY expiry_date,batch_id FOR UPDATE;""", (product_id,))
            batches = cur.fetchall()
            available = sum((b["quantity_available"] for b in batches), Decimal(0))
            if available < required:
                raise ValueError(f"Not enough {products[product_id]['name']}. Required {required:g} packs, available {available:g}.")
            remaining = required
            for batch in batches:
                take = min(batch["quantity_available"], remaining)
                if take:
                    allocations.append((product_id,batch,take))
                remaining -= take
                if not remaining:
                    break
        cur.execute("INSERT INTO inventory_dispatches VALUES (%s,%s,%s,%s,%s,now())",
                    (reference,package_id,amount,note,actor_account_id))
        cur.execute("INSERT INTO inventory_package_dispatch_details VALUES (%s,%s,%s,%s)",
                    (reference,package["name"],dispatch_mode,package["revision"]))
        for product_id, per_package in contents.items():
            cur.execute("INSERT INTO inventory_package_dispatch_lines VALUES (%s,%s,%s,%s,%s)",
                        (reference,product_id,products[product_id]["name"],per_package,per_package*amount))
        for product_id,batch,take in allocations:
            before = batch["quantity_available"]
            cur.execute("UPDATE inventory_batches SET quantity_available=quantity_available-%s WHERE batch_id=%s", (take,batch["batch_id"]))
            cur.execute("""INSERT INTO inventory_movements
                (item_id,affected_batch_id,movement_type,quantity_delta,unit,balance_before,balance_after,
                 actor_account_id,actor_name,note,dispatch_id)
                VALUES (%s,%s,'stock_dispatch',%s,'pack',%s,%s,%s,%s,%s,%s)""",
                (product_id,batch["batch_id"],-take,before,before-take,actor_account_id,actor_name,
                 f"Package: {package['name']} ({amount:g}). {note}",reference))
            cur.execute("UPDATE alerts SET status='resolved' WHERE product_batch_id=%s AND status IN ('open','acknowledged') AND %s=0",
                        (batch["batch_id"],before-take))
        _add_log_cursor(cur, actor_account_id=actor_account_id, action="dispatched_package",
                        entity_type="inventory_items", entity_id=package_id)
    return {"already_recorded": False}
