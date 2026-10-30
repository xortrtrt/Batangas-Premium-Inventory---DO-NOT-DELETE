from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import re
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg2
import pytest

from app.application import create_app
from app.business_time import business_today
from app.repositories.inventory import (
    add_raw_inventory_item, add_raw_inventory_quantity, create_product_with_recipe,
    count_inventory_movements, deduct_raw_material, list_inventory_movements, produce_product,
)
from app.security import hash_password


def test_stock_display_retains_third_decimal():
    from app.web import stock_quantity
    assert stock_quantity(Decimal("0.001")) == "0.001"
    assert stock_quantity(9.999) == "9.999"
    assert stock_quantity(Decimal("10")) == "10"
    assert stock_quantity(Decimal("9.750")) == "9.75"
    assert stock_quantity(Decimal("0")) == "0.00"


@pytest.mark.parametrize("unit", ["kg", "g", "ml"])
def test_zero_quantity_material_stays_listed_with_two_decimal_zero(inventory_db, unit):
    from app.repositories.inventory import list_raw_materials, list_inventory_items
    dsn, actor = inventory_db
    material = add_raw_inventory_item("Zero stock supply", "raw_material", unit, "1", actor)["raw_material_id"]
    deduct_raw_material(material, "1", "Used up", str(uuid4()), actor)
    assert any(item["raw_material_id"] == material and item["available"] == 0 for item in list_raw_materials())
    assert any(item["item_id"] == material for item in list_inventory_items(category="raw_material"))
    assert scalar(dsn, "SELECT is_active FROM inventory_items WHERE item_id=%s", (material,))
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts SET password_hash=%s WHERE account_id=%s", (hash_password("Zero-Stock-Test-123!"), actor))
    client = TestClient(create_app())
    page = client.get("/login")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    client.post("/login", data={"email": "inventory@test.invalid", "password": "Zero-Stock-Test-123!", "consent": "yes", "csrf_token": token})
    page = client.get("/portal/inventory/raw-materials")
    assert "Zero Stock Supply" in page.text and f'0.00 <small>{unit}</small>' in page.text


def scalar(dsn, query, params=()):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()[0]


@pytest.fixture
def raw_stock(inventory_db):
    dsn, actor = inventory_db
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts SET username='BPadmin1' WHERE account_id=%s", (actor,))
    material = add_raw_inventory_item("Pork", "meat", "kg", "10", actor)
    return dsn, actor, material["raw_material_id"]


def test_deduction_balance_reason_actor_and_search(raw_stock):
    dsn, actor, material = raw_stock
    reference = str(uuid4())
    result = deduct_raw_material(material, "0.125", "  Spoiled stock  ", reference, actor)
    assert not result["already_recorded"]
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == Decimal("9.875")
    rows = list_inventory_movements(q="BPadmin1", category="deductions")
    assert count_inventory_movements(category="deductions") == len(rows) == 1
    row = rows[0]
    assert row["quantity_delta"] == -0.125 and row["balance_before"] == 10 and row["balance_after"] == 9.875
    assert row["actor_account_id"] == actor and row["actor_name"] == "BPadmin1"
    assert str(row["raw_deduction_reference"]) == reference and row["note"] == "Spoiled stock"
    assert row["unit"] == "kg"
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 0


@pytest.mark.parametrize("unit", ["g", "ml"])
def test_deductions_use_material_stock_unit(inventory_db, unit):
    dsn, actor = inventory_db
    material = add_raw_inventory_item("Test supply", "raw_material", unit, "2", actor)["raw_material_id"]
    deduct_raw_material(material, "0.001", "Wastage", str(uuid4()), actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == Decimal("1.999")
    assert list_inventory_movements(category="deductions")[0]["unit"] == unit


def test_receipt_and_deduction_do_not_lose_updates(raw_stock):
    dsn, actor, material = raw_stock

    def run(operation):
        if operation == "receipt":
            add_raw_inventory_quantity(material, "2", actor)
        else:
            deduct_raw_material(material, "3", "Wastage", str(uuid4()), actor)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ("receipt", "deduction")))
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 9
    assert scalar(dsn, "SELECT sum(quantity_delta) FROM inventory_movements WHERE item_id=%s", (material,)) == 9


@pytest.mark.parametrize("quantity", ["0", "-1", "0.0001", "NaN", "Infinity", "abc", "", "1e1"])
def test_invalid_quantity_never_changes_stock(raw_stock, quantity):
    dsn, actor, material = raw_stock
    with pytest.raises(ValueError):
        deduct_raw_material(material, quantity, "Wastage", str(uuid4()), actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
    assert count_inventory_movements(category="deductions") == 0


@pytest.mark.parametrize("note", ["", "  ", "x" * 501])
def test_reason_is_required(raw_stock, note):
    _, actor, material = raw_stock
    with pytest.raises(ValueError, match="reason"):
        deduct_raw_material(material, "1", note, str(uuid4()), actor)
    assert count_inventory_movements(category="deductions") == 0


def test_insufficient_stock_and_retry_are_atomic(raw_stock):
    dsn, actor, material = raw_stock
    reference = str(uuid4())
    with pytest.raises(ValueError, match="Not enough"):
        deduct_raw_material(material, "10.001", "Wastage", reference, actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
    assert count_inventory_movements(category="deductions") == 0
    add_raw_inventory_quantity(material, "1", actor)
    deduct_raw_material(material, "10.001", "Wastage", reference, actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == Decimal("0.999")


def test_full_balance_and_duplicate_submission(raw_stock):
    dsn, actor, material = raw_stock
    reference = str(uuid4())
    deduct_raw_material(material, "10", "Damaged stock", reference, actor)
    assert deduct_raw_material(material, "10", "Damaged stock", reference, actor)["already_recorded"]
    with pytest.raises(ValueError, match="different details"):
        deduct_raw_material(material, "9", "Damaged stock", reference, actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 0
    assert count_inventory_movements(category="deductions") == 1
    with pytest.raises(psycopg2.Error, match="immutable"):
        with psycopg2.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM inventory_movements WHERE raw_deduction_reference=%s", (reference,))


@pytest.mark.parametrize("case", ["inactive", "missing", "finished_product", "invalid_reference", "missing_actor"])
def test_invalid_target_reference_or_actor(raw_stock, case):
    dsn, actor, material = raw_stock
    target, reference = material, str(uuid4())
    if case == "inactive":
        with psycopg2.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE inventory_items SET is_active=false WHERE item_id=%s", (material,))
    elif case == "missing":
        target = 999999
    elif case == "finished_product":
        target = create_product_with_recipe("Tocino", "Pork", [material], ["500"], ["g"], actor)["product_id"]
    elif case == "invalid_reference":
        reference = "invalid"
    elif case == "missing_actor":
        actor = None
    with pytest.raises(ValueError):
        deduct_raw_material(target, "1", "Wastage", reference, actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
    assert count_inventory_movements(category="deductions") == 0


@pytest.mark.parametrize("same_reference", [True, False])
def test_concurrent_deductions_cannot_overdraw(raw_stock, same_reference):
    dsn, actor, material = raw_stock
    reference = str(uuid4())

    def run(_):
        try:
            return deduct_raw_material(material, "6", "Wastage", reference if same_reference else str(uuid4()), actor)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(result is not None for result in results) == (2 if same_reference else 1)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 4
    assert count_inventory_movements(category="deductions") == 1


def test_production_and_manual_deduction_share_stock_lock(raw_stock):
    dsn, actor, material = raw_stock
    product = create_product_with_recipe("Tocino", "Pork", [material], ["500"], ["g"], actor)["product_id"]

    def run(operation):
        try:
            if operation == "production":
                produce_product(product, "CONCURRENT-PROD", "2", business_today() + timedelta(days=5), actor)
            else:
                deduct_raw_material(material, "9.5", "Wastage", str(uuid4()), actor)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(run, ("production", "deduction"))) == 1
    balance = scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,))
    assert balance in (Decimal("9"), Decimal("0.5"))
    assert scalar(dsn, "SELECT 10+sum(quantity_delta) FROM inventory_movements WHERE item_id=%s AND quantity_delta<0", (material,)) == balance


def test_http_deduction_csrf_actor_and_duplicate(raw_stock):
    dsn, actor, material = raw_stock
    password = "Local-Test-123!"
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts SET password_hash=%s WHERE account_id=%s", (hash_password(password), actor))
    client = TestClient(create_app())
    endpoint = "/portal/inventory/raw-materials/deduct"
    assert client.post(endpoint, data={}).status_code == 403
    page = client.get("/login")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    form = {"raw_material_id": material, "quantity": "0.25", "note": "Spoiled stock",
            "submission_reference": str(uuid4()), "csrf_token": token}
    assert client.post(endpoint, data=form).url.path == "/login"
    page = client.get("/login")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    client.post("/login", data={"username": "BPadmin1", "password": password, "consent": "yes", "csrf_token": token})
    page = client.get("/portal/inventory/inventory?modal=deduct-material")
    assert "Deduct raw materials" in page.text and 'data-stock-unit="kg"' in page.text
    form["csrf_token"] = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    form.update(actor_account_id="999999", actor_name="Forged actor")
    response = client.post(endpoint, data=form)
    assert response.status_code == 200 and "Raw material deduction" in response.text
    assert "Recorded by BPadmin1" in response.text and "Spoiled stock" in response.text
    assert "type=deductions" in str(response.url)
    client.post(endpoint, data=form)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == Decimal("9.75")
    assert list_inventory_movements(category="deductions")[0]["actor_account_id"] == actor
    form.update(submission_reference=str(uuid4()), quantity="20")
    error = client.post(endpoint, data=form)
    assert "Not enough" in error.text and "modal=deduct-material" in str(error.url)


def test_soft_delete_and_reactivation_preserve_balance_history_and_identity(raw_stock):
    from app.repositories.inventory import (
        remove_raw_material, reactivate_raw_material, list_inventory_items, list_raw_materials, count_inventory_items,
    )
    dsn, actor, material = raw_stock
    before = scalar(dsn, "SELECT count(*) FROM inventory_movements")
    remove_raw_material(material, True, actor)
    assert list_raw_materials() == []
    assert list_inventory_items(category="raw_material") == []
    assert count_inventory_items(category="raw_material") == 0
    removed = list_inventory_items(category="raw_material", raw_material_active=False)
    assert len(removed) == count_inventory_items(category="raw_material", raw_material_active=False) == 1
    assert removed[0]["item_id"] == material and removed[0]["available"] == 10
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == before
    with pytest.raises(ValueError, match="Reactivate"):
        add_raw_inventory_item("pOrK", "meat", "kg", "2", actor)
    with pytest.raises(ValueError):
        add_raw_inventory_quantity(material, "1", actor)
    with pytest.raises(ValueError):
        deduct_raw_material(material, "1", "Wastage", str(uuid4()), actor)
    reactivate_raw_material(material, actor)
    assert list_raw_materials()[0]["raw_material_id"] == material
    assert list_raw_materials()[0]["available"] == 10
    assert list_inventory_items(category="raw_material", raw_material_active=False) == []
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == before
    assert scalar(dsn, "SELECT count(*) FROM inventory_items") == 1
    assert scalar(dsn, "SELECT count(*) FROM activity_logs WHERE action IN ('removed_raw_material','reactivated_raw_material') AND account_id=%s", (actor,)) == 2


def test_soft_delete_requires_confirmation_and_unlinked_recipe(raw_stock):
    from app.repositories.inventory import remove_raw_material, update_product_recipe
    dsn, actor, material = raw_stock
    with pytest.raises(ValueError, match="Confirm"):
        remove_raw_material(material, False, actor)
    product = create_product_with_recipe("Tocino", "Pork", [material], ["500"], ["g"], actor)["product_id"]
    with pytest.raises(ValueError, match="recipe"):
        remove_raw_material(material, True, actor)
    assert scalar(dsn, "SELECT is_active FROM inventory_items WHERE item_id=%s", (material,))
    other = add_raw_inventory_item("Chicken", "meat", "kg", "2", actor)["raw_material_id"]
    update_product_recipe(product, [other], ["500"], ["g"], actor)
    remove_raw_material(material, True, actor)
    with pytest.raises(ValueError, match="valid"):
        create_product_with_recipe("New Tocino", "Pork", [material], ["500"], ["g"], actor)
    assert scalar(dsn, "SELECT count(*) FROM product_recipes WHERE material_item_id=%s", (material,)) == 0


def test_soft_delete_and_recipe_creation_are_serialized(raw_stock):
    from app.repositories.inventory import remove_raw_material
    dsn, actor, material = raw_stock

    def run(operation):
        try:
            if operation == "remove":
                remove_raw_material(material, True, actor)
            else:
                create_product_with_recipe("Tocino", "Pork", [material], ["500"], ["g"], actor)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(run, ("remove", "recipe"))) == 1
    active = scalar(dsn, "SELECT is_active FROM inventory_items WHERE item_id=%s", (material,))
    recipe_count = scalar(dsn, "SELECT count(*) FROM product_recipes WHERE material_item_id=%s", (material,))
    assert recipe_count == (1 if active else 0)


def test_soft_delete_and_reactivation_http(raw_stock):
    dsn, actor, material = raw_stock
    password = "Removal-Test-123!"
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts SET password_hash=%s WHERE account_id=%s", (hash_password(password), actor))
    client = TestClient(create_app())
    remove_url = f"/portal/inventory/raw-materials/{material}/remove"
    reactivate_url = f"/portal/inventory/raw-materials/{material}/reactivate"
    assert client.post(remove_url, data={}).status_code == 403
    assert client.post(reactivate_url, data={}).status_code == 403
    page = client.get("/login")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    assert client.post(remove_url, data={"confirmed": "yes", "csrf_token": token}).url.path == "/login"
    page = client.get("/login")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    client.post("/login", data={"username": "BPadmin1", "password": password, "consent": "yes", "csrf_token": token})
    page = client.get("/portal/inventory/raw-materials")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    unconfirmed = client.post(remove_url, data={"csrf_token": token})
    assert "Confirm that you want" in unconfirmed.text
    assert scalar(dsn, "SELECT is_active FROM inventory_items WHERE item_id=%s", (material,))
    result = client.post(remove_url, data={"confirmed": "yes", "csrf_token": token})
    assert result.status_code == 200 and "Stock history is preserved" in result.text
    assert 'Remove <strong>Pork</strong>?' not in result.text
    removed_page = client.get("/portal/inventory/raw-materials?type=archived&q=Pork")
    assert "Reactivate Pork" in removed_page.text and "10 <small>kg</small>" in removed_page.text
    assert "Removed raw materials" in removed_page.text
    token = re.search(r'name="csrf-token" content="([^"]+)"', removed_page.text).group(1)
    restored = client.post(reactivate_url, data={"csrf_token": token})
    assert restored.status_code == 200 and "Remove <strong>Pork</strong>?" in restored.text
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
