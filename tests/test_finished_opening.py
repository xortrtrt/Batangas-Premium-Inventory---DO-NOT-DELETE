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
    add_product_batch, add_raw_inventory_item, dispatch_stock, list_inventory_movements, list_products,
)
from app.security import hash_password
from tools.migrate_database import migrate_database


def scalar(dsn, query, params=()):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()[0]


@pytest.fixture
def opening_stock(inventory_db):
    dsn, actor = inventory_db
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO inventory_items(item_type,name,category,unit)
                VALUES ('finished_product','Opening Tocino','Pork','pack') RETURNING item_id""")
            product = cursor.fetchone()[0]
    return dsn, actor, product


def record(stock, **changes):
    _, actor, product = stock
    details = dict(product_id=product, batch_code="OPEN-001", quantity="12", expiry_date=business_today()+timedelta(days=30),
                   source_type="opening_balance", actor_account_id=actor, opening_note="Initial physical count",
                   opening_reference=str(uuid4()))
    details.update(changes)
    return add_product_batch(**details)


def test_opening_is_audited_additive_and_dispatchable_without_recipe(opening_stock):
    dsn, actor, product = opening_stock
    material = add_raw_inventory_item("Pork", "meat", "kg", "10", actor)["raw_material_id"]
    record(opening_stock)
    record(opening_stock, batch_code="OPEN-002", quantity="3")
    assert scalar(dsn, "SELECT SUM(quantity_available) FROM inventory_batches") == 15
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
    assert scalar(dsn, "SELECT count(*) FROM product_recipes") == 0
    movements = list_inventory_movements(category="opening")
    assert len(movements) == 2
    finished = [row for row in movements if row["entity"] == "Opening Tocino"]
    assert len(finished) == 2
    assert all(row["actor_account_id"] == actor and row["note"] == "Initial physical count" for row in finished)
    assert all(row["balance_before"] == 0 and row["balance_after"] == row["quantity_delta"] for row in finished)
    assert next(p for p in list_products() if p["product_id"] == product)["available"] == 15
    dispatch_stock(product, "13", "Stock released", str(uuid4()), actor)
    assert scalar(dsn, "SELECT SUM(quantity_available) FROM inventory_batches") == 2
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
    migrate_database(dsn)  # Repeat migration preserves data.
    assert scalar(dsn, "SELECT SUM(quantity_available) FROM inventory_batches") == 2


@pytest.mark.parametrize("changes", [
    {"quantity": "0"}, {"quantity": "-1"}, {"quantity": "1.5"}, {"quantity": "NaN"},
    {"quantity": "1000000000"}, {"opening_note": " "}, {"opening_note": "x"*501},
    {"opening_reference": "bad"}, {"actor_account_id": None}, {"actor_account_id": 999999},
    {"expiry_date": business_today()-timedelta(days=1)}, {"batch_code": " "}, {"batch_code": "x"*101},
    {"product_id": 999999},
])
def test_invalid_opening_never_changes_stock(opening_stock, changes):
    dsn, _, _ = opening_stock
    with pytest.raises(ValueError):
        record(opening_stock, **changes)
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 0
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == 0


def test_opening_rejects_inactive_and_raw_material_targets(opening_stock):
    dsn, actor, product = opening_stock
    raw = add_raw_inventory_item("Pork", "meat", "kg", "1", actor)["raw_material_id"]
    with pytest.raises(ValueError):
        record(opening_stock, product_id=raw)
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE inventory_items SET is_active=false WHERE item_id=%s", (product,))
    with pytest.raises(ValueError):
        record(opening_stock)
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 0


def test_duplicate_submission_and_changed_payload(opening_stock):
    dsn, actor, product = opening_stock
    reference = str(uuid4())
    first = record(opening_stock, opening_reference=reference)
    dispatch_stock(product, "2", "Dispatched", str(uuid4()), actor)
    again = record(opening_stock, opening_reference=reference)
    assert again["already_recorded"] and again["product_batch_id"] == first["product_batch_id"]
    with pytest.raises(ValueError, match="different details"):
        record(opening_stock, opening_reference=reference, quantity="13")
    with pytest.raises(ValueError, match="Batch code already exists"):
        record(opening_stock)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches") == 10


def test_concurrent_identical_submission_is_recorded_once(opening_stock):
    dsn, _, _ = opening_stock
    reference = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: record(opening_stock, opening_reference=reference), range(2)))
    assert sorted(r["already_recorded"] for r in results) == [False, True]
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 1
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == 1


def test_http_opening_auth_csrf_and_real_actor(opening_stock):
    dsn, actor, product = opening_stock
    endpoint = "/portal/inventory/finished-products/opening-balance"
    client = TestClient(create_app())
    form = dict(product_id=product, batch_code="HTTP-OPEN", quantity="5", expiry_date=str(business_today()),
                note="Starting count", submission_reference=str(uuid4()), actor_account_id="999999")
    assert client.post(endpoint, data=form).status_code == 403
    page = client.get("/login")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    assert client.post(endpoint, data={**form, "csrf_token": token}, follow_redirects=False).status_code == 303
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 0
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts SET password_hash=%s WHERE account_id=%s", (hash_password("Opening-Test-123!"), actor))
    client.post("/login", data={"email": "inventory@test.invalid", "password": "Opening-Test-123!",
                               "consent": "yes", "csrf_token": token})
    page = client.get("/portal/inventory/inventory?modal=opening-balance")
    assert 'id="inventory-modal-opening-balance"' in page.text
    assert "Add opening balance" in client.get("/portal/inventory/finished-products").text
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    assert client.post(endpoint, data=form).status_code == 403
    response = client.post(endpoint, data={**form, "csrf_token": token})
    assert response.status_code == 200 and "Starting count" in response.text
    assert "Recorded by Test Inventory" in response.text
    assert scalar(dsn, "SELECT actor_account_id FROM inventory_movements") == actor
    assert "Opening balance" in client.get("/portal/inventory/batches").text
    response = client.post(endpoint, data={**form, "csrf_token": token})
    assert "Opening balance already recorded" in response.text
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 1
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches") == Decimal("5")
