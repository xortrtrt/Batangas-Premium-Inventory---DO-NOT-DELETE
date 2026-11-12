"""Product/date-scoped manual batch numbers, atomic writes, and migration safety."""
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
    add_product_batch, add_raw_inventory_item, create_product_with_recipe,
    dispatch_stock, produce_product,
)
from app.security import hash_password
from app.repositories.inventory import products as product_repository
from tools.migrate_database import migrate_database


def scalar(dsn, query, params=()):
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()[0]


@pytest.fixture
def batch_stock(inventory_db):
    dsn, actor = inventory_db
    material = add_raw_inventory_item("Pork", "meat", "kg", "20", actor)["raw_material_id"]
    products = [create_product_with_recipe(name, "Pork", [material], ["500"], ["g"], actor)["product_id"]
                for name in ("Tocino", "Sausage")]
    return dsn, actor, material, products


def record(stock, source, product=None, code="Batch-001", day=None, reference=None):
    _, actor, _, products = stock
    product = products[0] if product is None else product
    expiry = business_today() + timedelta(days=30)
    if source == "production":
        return produce_product(product, code, "2", expiry, actor, batch_date=day)
    kwargs = {}
    if source == "opening_balance":
        kwargs = {"opening_note": "Physical starting count", "opening_reference": reference or str(uuid4())}
    return add_product_batch(product, code, "2", expiry, source, actor, batch_date=day, **kwargs)


@pytest.mark.parametrize("source", ["direct_received", "opening_balance", "production"])
def test_same_number_across_products_and_days_keeps_stock_separate(batch_stock, source):
    dsn, actor, material, products = batch_stock
    today = business_today()
    first = record(batch_stock, source, code=" Batch-001 ", day=today - timedelta(days=1))
    other = record(batch_stock, source, product=products[1], day=today - timedelta(days=1))
    later = record(batch_stock, source, day=today)
    assert first["batch_code"] == "Batch-001"
    assert len({b["product_batch_id"] for b in (first, other, later)}) == 3
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches WHERE received_date=%s", (today,)) == 3
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == (
        Decimal("17") if source == "production" else Decimal("20"))
    dispatch_stock(products[0], "3", "Dispatch Tocino only", str(uuid4()), actor)
    assert scalar(dsn, "SELECT SUM(quantity_available) FROM inventory_batches WHERE item_id=%s", (products[0],)) == 1
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches WHERE batch_id=%s", (other["product_batch_id"],)) == 2


@pytest.mark.parametrize("source", ["direct_received", "opening_balance", "production"])
@pytest.mark.parametrize("duplicate_source", ["direct_received", "opening_balance", "production"])
def test_same_product_day_duplicate_is_rejected_across_all_entry_flows(batch_stock, source, duplicate_source):
    dsn, _, material, _ = batch_stock
    record(batch_stock, source)
    balance = scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,))
    movements = scalar(dsn, "SELECT count(*) FROM inventory_movements")
    with pytest.raises(ValueError, match="already exists for this product and batch date"):
        record(batch_stock, duplicate_source, code=" batch-001 ")
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 1
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == movements
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == balance


@pytest.mark.parametrize("source", ["direct_received", "opening_balance", "production"])
def test_manual_text_codes_preserve_leading_zeros_case_and_spaces(batch_stock, source):
    for code in ("001", "a", "Nov11  Bundle-A", "x" * 100):
        assert record(batch_stock, source, code=code)["batch_code"] == code


@pytest.mark.parametrize("source", ["direct_received", "opening_balance", "production"])
@pytest.mark.parametrize("changes", [{"code": " "}, {"code": "x" * 101}, {"day": "2026-01-01"}])
def test_invalid_identity_never_changes_stock(batch_stock, source, changes):
    dsn, _, material, _ = batch_stock
    with pytest.raises(ValueError):
        record(batch_stock, source, **changes)
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 0
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 20


@pytest.mark.parametrize("source", ["direct_received", "opening_balance", "production"])
def test_future_batch_date_is_rejected(batch_stock, source):
    with pytest.raises(ValueError, match="today or an earlier date"):
        record(batch_stock, source, day=business_today() + timedelta(days=1))


@pytest.mark.parametrize("source", ["direct_received", "opening_balance", "production"])
def test_default_date_allows_number_to_be_reused_next_business_day(batch_stock, source, monkeypatch):
    first = record(batch_stock, source)
    tomorrow = business_today() + timedelta(days=1)
    monkeypatch.setattr(product_repository, "business_today", lambda: tomorrow)
    second = record(batch_stock, source)
    assert second["batch_date"] == tomorrow
    assert second["product_batch_id"] != first["product_batch_id"]


@pytest.mark.parametrize("source", ["direct_received", "opening_balance", "production"])
def test_concurrent_duplicate_creates_one_batch_and_one_stock_increase(batch_stock, source):
    dsn, _, material, _ = batch_stock

    def attempt(_):
        try:
            record(batch_stock, source)
            return "saved"
        except ValueError as exc:
            assert "already exists for this product and batch date" in str(exc)
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["duplicate", "saved"]
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 1
    assert scalar(dsn, "SELECT SUM(quantity_available) FROM inventory_batches") == 2
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == (
        19 if source == "production" else 20)


def test_opening_replay_cannot_change_batch_date(batch_stock):
    dsn, _, _, _ = batch_stock
    reference = str(uuid4())
    day = business_today() - timedelta(days=1)
    first = record(batch_stock, "opening_balance", day=day, reference=reference)
    replay = record(batch_stock, "opening_balance", day=day, reference=reference)
    assert replay["already_recorded"] and replay["product_batch_id"] == first["product_batch_id"]
    with pytest.raises(ValueError, match="different details"):
        record(batch_stock, "opening_balance", day=business_today(), reference=reference)
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 1


def test_database_constraint_enforces_product_date_identity_and_migration_preserves_history(batch_stock):
    dsn, _, _, products = batch_stock
    batch = record(batch_stock, "direct_received")
    with pytest.raises(psycopg2.errors.UniqueViolation):
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO inventory_batches
                    (item_id,batch_code,batch_date,quantity_received,quantity_available,unit,received_date,expiry_date)
                    VALUES (%s,' batch-001 ',%s,1,1,'pack',%s,%s)""",
                            (products[0], business_today(), business_today(), business_today()))
    # Reconstruct the immediately preceding schema with a real receipt/history.
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP INDEX inventory_batches_product_date_code_unique")
            cur.execute("ALTER TABLE inventory_batches DROP COLUMN batch_date")
            cur.execute("ALTER TABLE inventory_batches ADD CONSTRAINT inventory_batches_batch_code_key UNIQUE (batch_code)")
            cur.execute("DELETE FROM inventory_schema_migrations WHERE version='012_product_batch_dates.sql'")
            cur.execute("UPDATE inventory_batches SET received_date=%s WHERE batch_id=%s",
                        (business_today() - timedelta(days=4), batch["product_batch_id"]))
            cur.execute("SELECT row_to_json(m) FROM inventory_movements m ORDER BY movement_id")
            history = cur.fetchall()
    migrate_database(dsn)
    migrate_database(dsn)
    assert scalar(dsn, "SELECT batch_date=received_date AND quantity_available=2 FROM inventory_batches WHERE batch_id=%s",
                  (batch["product_batch_id"],))
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT row_to_json(m) FROM inventory_movements m ORDER BY movement_id")
            assert cur.fetchall() == history


@pytest.mark.parametrize("endpoint", ["production", "batches", "finished-products/opening-balance"])
def test_http_accepts_same_batch_number_for_other_products_and_dates(batch_stock, endpoint):
    dsn, actor, _, products = batch_stock
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET password_hash=%s WHERE account_id=%s", (hash_password("Batch-Test-123!"), actor))
    client = TestClient(create_app())
    try:
        page = client.get("/login")
        token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
        client.post("/login", data={"email": "inventory@test.invalid", "password": "Batch-Test-123!",
                                   "consent": "yes", "csrf_token": token})
        workspace = client.get("/portal/inventory/inventory")
        assert 'name="batch_date"' in workspace.text
        assert 'type="text" required name="batch_code" maxlength="100"' in workspace.text
        token = re.search(r'name="csrf-token" content="([^"]+)"', workspace.text).group(1)
        day = business_today() - timedelta(days=1)
        form = {"product_id": products[0], "batch_code": "001", "batch_date": str(day), "quantity": "2",
                "expiry_date": str(business_today() + timedelta(days=30)), "csrf_token": token,
                "note": "Initial count", "submission_reference": str(uuid4())}
        url = f"/portal/inventory/{endpoint}"
        assert client.post(url, data=form).status_code == 200
        assert client.post(url, data={**form, "product_id": products[1], "submission_reference": str(uuid4())}).status_code == 200
        assert client.post(url, data={**form, "batch_date": str(business_today()), "submission_reference": str(uuid4())}).status_code == 200
        response = client.post(url, data={**form, "submission_reference": str(uuid4())})
        assert "already exists for this product and batch date" in response.text
        assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 3
        batches = client.get("/portal/inventory/batches").text
        assert "Batch date" in batches and "001" in batches
        assert client.get(f"/portal/inventory/product-details?product_id={products[0]}").status_code == 200
    finally:
        client.close()
