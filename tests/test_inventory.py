from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg2
import pytest

from app.application import create_app
from app.business_time import business_today
from app.repositories import accounts
from app.repositories.inventory import (
    add_product_batch, add_raw_inventory_item, add_raw_inventory_quantity,
    create_product_with_recipe, dispatch_stock, produce_product, update_product_recipe,
)
from app.security import hash_password, verify_password
from tools import init_db
from tools.import_inventory_catalog import import_catalog, validate_manifest
from tools.migrate_database import migrate_database

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "catalog/meattrack-20261017-v1.json").read_text())


def test_production_enforces_throttling_with_legacy_render_environment():
    env = os.environ.copy()
    env.update(APP_ENV="production", AUTH_RATE_LIMIT_ENABLED="false",
               CSRF_PROTECTION_ENABLED="true", SESSION_SECRET_KEY="production-configuration-test-secret")
    result = subprocess.run(
        [sys.executable, "-c", "from app.config import AUTH_RATE_LIMIT_ENABLED; assert AUTH_RATE_LIMIT_ENABLED"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def scalar(dsn, query, params=()):
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()[0]


@pytest.fixture
def stock(inventory_db):
    dsn, actor = inventory_db
    material = add_raw_inventory_item("Pork", "meat", "kg", "10", actor)
    product = create_product_with_recipe("Test Tocino", "Pork", [material["raw_material_id"]],
                                         ["500"], ["g"], actor)
    return dsn, actor, material["raw_material_id"], product["product_id"]


def test_receipts_recipe_conversion_and_production(stock):
    dsn, actor, material, product = stock
    add_raw_inventory_quantity(material, "2.5", actor)
    produce_product(product, "PROD-001", "4", business_today() + timedelta(days=10), actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == Decimal("10.5")
    assert scalar(dsn, "SELECT quantity_required FROM product_recipes WHERE product_item_id=%s", (product,)) == Decimal("0.5")
    assert scalar(dsn, "SELECT SUM(quantity_available) FROM inventory_batches") == 4
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == 4


def test_insufficient_production_rolls_back(stock):
    dsn, actor, material, product = stock
    with pytest.raises(ValueError, match="Not enough"):
        produce_product(product, "PROD-FAIL", "21", business_today() + timedelta(days=10), actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 0


def test_dispatch_fefo_expiry_and_audit(stock):
    dsn, actor, material, product = stock
    later = add_product_batch(product, "LATER", "5", business_today() + timedelta(days=10), actor_account_id=actor)
    early = add_product_batch(product, "EARLY", "3", business_today() + timedelta(days=2), actor_account_id=actor)
    expired = add_product_batch(product, "EXPIRED", "20", business_today(), actor_account_id=actor)
    rejected = add_product_batch(product, "REJECTED", "20", business_today(), actor_account_id=actor)
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE inventory_batches SET received_date=CURRENT_DATE-2, expiry_date=CURRENT_DATE-1 WHERE batch_id=%s",
                        (expired["product_batch_id"],))
            cur.execute("UPDATE inventory_batches SET quality_status='rejected' WHERE batch_id=%s", (rejected["product_batch_id"],))
    ref = str(uuid4())
    dispatch_stock(product, "6", "Delivery to branch", ref, actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches WHERE batch_id=%s", (early["product_batch_id"],)) == 0
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches WHERE batch_id=%s", (later["product_batch_id"],)) == 2
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches WHERE batch_id=%s", (expired["product_batch_id"],)) == 20
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements WHERE dispatch_id=%s AND note=%s AND actor_account_id=%s AND balance_after=balance_before+quantity_delta",
                  (ref, "Delivery to branch", actor)) == 2
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10


def test_dispatch_insufficient_stock_is_atomic(stock):
    dsn, actor, _, product = stock
    add_product_batch(product, "SMALL", "2", business_today(), actor_account_id=actor)
    with pytest.raises(ValueError, match="Not enough"):
        dispatch_stock(product, "3", "Branch", str(uuid4()), actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches") == 2
    assert scalar(dsn, "SELECT count(*) FROM inventory_dispatches") == 0
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements WHERE movement_type='stock_dispatch'") == 0


@pytest.mark.parametrize("quantity", ["0", "-1", "1.5", "NaN", "Infinity", "1e2", "bad"])
def test_invalid_dispatch_quantities(stock, quantity):
    _, actor, _, product = stock
    with pytest.raises(ValueError):
        dispatch_stock(product, quantity, "Branch", str(uuid4()), actor)


@pytest.mark.parametrize("note,reference", [("", str(uuid4())), ("x"*501, str(uuid4())), ("Branch", "invalid")])
def test_invalid_dispatch_details(stock, note, reference):
    _, actor, _, product = stock
    with pytest.raises(ValueError):
        dispatch_stock(product, "1", note, reference, actor)


def test_duplicate_dispatch_and_changed_payload(stock):
    dsn, actor, _, product = stock
    add_product_batch(product, "BATCH", "5", business_today(), actor_account_id=actor)
    ref = str(uuid4())
    assert not dispatch_stock(product, "2", "Branch", ref, actor)["already_recorded"]
    assert dispatch_stock(product, "2", "Branch", ref, actor)["already_recorded"]
    with pytest.raises(ValueError, match="different details"):
        dispatch_stock(product, "3", "Branch", ref, actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches") == 3


@pytest.mark.parametrize("same_reference", [False, True])
def test_concurrent_dispatches(stock, same_reference):
    dsn, actor, _, product = stock
    add_product_batch(product, "CONCURRENT", "5", business_today(), actor_account_id=actor)
    ref = str(uuid4())
    def run(i):
        try:
            return dispatch_stock(product, "4", "Branch", ref if same_reference else str(uuid4()), actor)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(r is not None for r in results) == (2 if same_reference else 1)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches") == 1
    assert scalar(dsn, "SELECT count(*) FROM inventory_dispatches") == 1


def test_inventory_history_is_immutable(stock):
    dsn, _, _, _ = stock
    for statement in ("DELETE FROM inventory_movements", "UPDATE inventory_movements SET note='changed'", "TRUNCATE inventory_movements"):
        with pytest.raises(psycopg2.Error, match="immutable"):
            with psycopg2.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(statement)


def test_catalog_preview_repeat_and_preserved_stock(stock):
    dsn, actor, material, product = stock
    add_product_batch(product, "PRESERVE", "7", business_today(), actor_account_id=actor)
    before_items = scalar(dsn, "SELECT count(*) FROM inventory_items")
    preview = import_catalog(CATALOG, dsn=dsn)
    assert not preview["applied"]
    assert scalar(dsn, "SELECT count(*) FROM inventory_items") == before_items
    assert set(preview["ignored_source_fields"]) == {"base_price", "pack_size", "pack_size_unit", "pack_content_status"}
    assert len(preview["incomplete_recipes"]) == 16
    assert not preview["missing_images"]
    result = import_catalog(CATALOG, apply=True, dsn=dsn)
    assert result["applied"]
    count = scalar(dsn, "SELECT count(*) FROM inventory_items")
    again = import_catalog(CATALOG, apply=True, dsn=dsn)
    assert again["applied"] and not again["additions"] and not again["recipe_additions"]
    assert scalar(dsn, "SELECT count(*) FROM inventory_items") == count
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches") == 7
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == 2
    assert scalar(dsn, "SELECT count(*) FROM accounts") == 1


def test_catalog_into_empty_database(inventory_db):
    dsn, _ = inventory_db
    assert import_catalog(CATALOG, apply=True, dsn=dsn)["applied"]
    assert scalar(dsn, "SELECT count(*) FROM inventory_items") == 23
    assert scalar(dsn, "SELECT count(*) FROM product_recipes") == 4
    assert scalar(dsn, "SELECT SUM(quantity_available) FROM inventory_items") == 0
    assert scalar(dsn, "SELECT count(*) FROM inventory_batches") == 0


def test_catalog_conflicts_stop_every_addition(inventory_db):
    dsn, _ = inventory_db
    first = deepcopy(CATALOG)
    first["items"] = [i for i in first["items"] if i["name"] == "Chicken"]
    first["recipes"] = []
    first["items"][0]["unit"] = "g"
    import_catalog(first, apply=True, dsn=dsn)
    result = import_catalog(CATALOG, apply=True, dsn=dsn)
    assert result["conflicts"] and not result["applied"]
    assert scalar(dsn, "SELECT count(*) FROM inventory_items") == 1


def test_catalog_recipe_conflict(inventory_db):
    dsn, _ = inventory_db
    import_catalog(CATALOG, apply=True, dsn=dsn)
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE product_recipes SET quantity_required=quantity_required+1")
    assert import_catalog(CATALOG, apply=True, dsn=dsn)["conflicts"]


def test_catalog_rejects_stock_fields():
    manifest = deepcopy(CATALOG)
    manifest["items"][0]["quantity_available"] = "999"
    with pytest.raises(ValueError, match="definitions only"):
        validate_manifest(manifest)


def test_password_and_deactivation_survive_restart(inventory_db, monkeypatch):
    dsn, actor = inventory_db
    monkeypatch.setattr(init_db, "database_dsn", lambda: dsn)
    old, new = "Original-Test-123!", "Changed-Test-456!"
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET password_hash=%s WHERE account_id=%s", (hash_password(old), actor))
    accounts.change_account_password_direct(actor, old, new)
    monkeypatch.setenv("ADMIN_PASSWORD", "Ignored-Reset-123!")
    init_db.init_database()
    assert verify_password(new, scalar(dsn, "SELECT password_hash FROM accounts WHERE account_id=%s", (actor,)))
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET is_active=false WHERE account_id=%s", (actor,))
    init_db.init_database()
    assert not scalar(dsn, "SELECT is_active FROM accounts WHERE account_id=%s", (actor,))


def test_bootstrap_requires_explicit_credentials(inventory_db, monkeypatch):
    dsn, _ = inventory_db
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM accounts")
    monkeypatch.setattr(init_db, "database_dsn", lambda: dsn)
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="Set ADMIN_EMAIL"):
        init_db.init_database()
    monkeypatch.setenv("ADMIN_EMAIL", "bootstrap@test.invalid")
    monkeypatch.setenv("ADMIN_PASSWORD", "Explicit-Test-123!")
    init_db.init_database()
    init_db.init_database()
    assert scalar(dsn, "SELECT count(*) FROM accounts") == 1


@pytest.mark.parametrize("kind,role,allowed", [("owner", None, True), ("team_leader", "inventory", True),
    ("team_leader", "sales", False), ("reseller", None, False)])
def test_inventory_account_roles(kind, role, allowed):
    assert (accounts.role_key_for_account_type(kind, role) is not None) is allowed


def test_migrations_repeat_without_changing_data(stock):
    dsn, _, _, _ = stock
    before = scalar(dsn, "SELECT count(*) FROM inventory_movements")
    migrate_database(dsn)
    migrate_database(dsn)
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == before


def test_http_auth_csrf_pages_and_dispatch(stock):
    dsn, actor, _, product = stock
    add_product_batch(product, "HTTP", "5", business_today(), actor_account_id=actor)
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET password_hash=%s WHERE account_id=%s", (hash_password("Http-Test-123!"), actor))
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok", "database": "connected"}
    assert client.post("/portal/inventory/dispatch", data={}).status_code == 403
    page = client.get("/login")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    response = client.post("/login", data={"email": "inventory@test.invalid", "password": "Http-Test-123!", "csrf_token": token, "consent": "yes"})
    assert response.status_code == 200 and "Inventory control" in response.text
    for section in ("dashboard", "inventory", "raw-materials", "finished-products", "batches", "logs", "profile", "notifications"):
        assert client.get(f"/portal/inventory/{section}").status_code == 200
    assert client.get("/portal/team-leader/dashboard").status_code == 200
    assert client.get("/portal/owner/dashboard").status_code == 200
    for path in ("/portal/reseller/dashboard", "/portal/sales-supervisor/orders", "/portal/inventory/forecasts", "/api/chatbot"):
        assert client.get(path).status_code == 404
    page = client.get("/portal/inventory/inventory")
    assert 'name="base_price"' not in page.text and 'name="pack_size"' not in page.text
    catalog_page = client.get("/portal/inventory/finished-products")
    assert "Unit price" not in catalog_page.text and "Declared net content" not in catalog_page.text
    for removed in ("price", "pack-content"):
        assert client.post(f"/portal/inventory/products/{product}/{removed}", data={}).status_code == 404
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    recipe_url = f"/portal/inventory/products/{product}/recipe"
    recipe_form = {"material_item_id[]": stock[2], "quantity_required[]": "250",
                   "quantity_required_unit[]": "g", "q": "Tocino", "page": "1"}
    assert client.post(recipe_url, data=recipe_form).status_code == 403
    recipe_form["csrf_token"] = token
    saved = client.post(recipe_url, data=recipe_form)
    assert saved.status_code == 200 and "Recipe saved" in saved.text
    assert "modal=product-recipes" in str(saved.url) and "q=Tocino" in str(saved.url)
    assert 'data-recipe-editor' in saved.text and 'value="0.25"' in saved.text
    assert "Deduct Stock" in saved.text
    reference = re.search(r'name="submission_reference" value="([^"]+)"', page.text).group(1)
    form = {"product_id": product, "quantity": "2", "note": "HTTP dispatch", "submission_reference": reference,
            "csrf_token": token, "actor_account_id": "999999", "actor_name": "Forged account"}
    response = client.post("/portal/inventory/dispatch", data=form)
    assert response.status_code == 200 and "HTTP dispatch" in response.text
    assert "Recorded by Test Inventory" in response.text
    assert scalar(dsn, "SELECT actor_account_id FROM inventory_movements WHERE movement_type='stock_dispatch'") == actor
    client.post("/portal/inventory/dispatch", data=form)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches") == 3


def test_all_stock_movements_track_account_and_keep_historical_identity(stock):
    from app.repositories.inventory import list_inventory_movements, count_inventory_movements
    dsn, first_actor, material, product = stock
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET username='BPadmin1',name='Shared display name' WHERE account_id=%s", (first_actor,))
            cur.execute("""INSERT INTO accounts(account_type,name,username,password_hash,team_leader_role)
                VALUES ('owner','Shared display name','BPadmin2','unused','inventory') RETURNING account_id""")
            second_actor = cur.fetchone()[0]
    add_raw_inventory_quantity(material, "1", first_actor)
    produce_product(product, "TRACK-PROD", "2", business_today() + timedelta(days=10), second_actor)
    add_product_batch(product, "TRACK-DIRECT", "3", business_today() + timedelta(days=10), actor_account_id=first_actor)
    dispatch_stock(product, "1", "Account tracking", str(uuid4()), second_actor)
    first_rows = list_inventory_movements(q="bpADMIN1")
    assert count_inventory_movements(q="bpADMIN1") == len(first_rows) == 2
    assert {row["action"] for row in first_rows} == {"raw_receipt", "direct_finished_receipt"}
    assert all(row["actor_account_id"] == first_actor and row["actor_name"] == "BPadmin1" for row in first_rows)
    second_rows = list_inventory_movements(q="BPadmin2")
    assert count_inventory_movements(q="BPadmin2") == len(second_rows) == 3
    assert {row["action"] for row in second_rows} == {"production_consumption", "production_output", "stock_dispatch"}
    assert all(row["actor_account_id"] == second_actor and row["actor_name"] == "BPadmin2" for row in second_rows)
    assert count_inventory_movements(q="BPadmin2", category="dispatch") == 1
    assert len(list_inventory_movements(q="BPadmin2", page=2, page_size=1)) == 1
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET username='RenamedAccount',name='New display name' WHERE account_id=%s", (second_actor,))
    assert count_inventory_movements(q="BPadmin2") == 3
    assert count_inventory_movements(q="RenamedAccount") == 0


def test_health_database_failure(monkeypatch):
    from app.routers import system
    monkeypatch.setattr(system.data, "database_health", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    assert TestClient(create_app()).get("/health").status_code == 503


def test_startup_refuses_initialization_failure(monkeypatch):
    def unavailable():
        raise RuntimeError("migration unavailable")
    monkeypatch.setattr(init_db, "init_database", unavailable)
    with pytest.raises(RuntimeError, match="migration unavailable"):
        with TestClient(create_app()):
            pass


def test_changed_migration_is_rejected(inventory_db, tmp_path, monkeypatch):
    from tools import migrate_database as migration_module
    dsn, _ = inventory_db
    migrations = tmp_path / "database/migrations"
    migrations.mkdir(parents=True)
    (migrations / "001_stock_dispatch.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migration_module, "PROJECT_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="Applied inventory migration changed"):
        migration_module.migrate_database(dsn)


def test_health_checks_do_not_create_sessions(inventory_db):
    dsn, _ = inventory_db
    client = TestClient(create_app())
    for _ in range(3):
        response = client.get("/health")
        assert response.status_code == 200 and "set-cookie" not in response.headers
    assert scalar(dsn, "SELECT count(*) FROM web_sessions") == 0


def test_login_throttling(inventory_db):
    from app.security_controls import enforce_password_login, record_password_login
    from starlette.requests import Request
    request = Request({"type": "http", "headers": []})
    for _ in range(10):
        record_password_login(request, "blocked@test.invalid", False)
    with pytest.raises(ValueError, match="Too many"):
        enforce_password_login(request, "blocked@test.invalid")


def test_customize_recipe_preserves_history_and_changes_future_production(stock):
    dsn, actor, material, product = stock
    produce_product(product, "BEFORE-EDIT", "2", business_today() + timedelta(days=10), actor)
    history = scalar(dsn, "SELECT count(*) FROM inventory_movements")
    update_product_recipe(product, [material], ["250"], ["g"], actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 9
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == history
    assert scalar(dsn, "SELECT quantity_available FROM inventory_batches WHERE batch_code='BEFORE-EDIT'") == 2
    assert scalar(dsn, "SELECT quantity_required FROM product_recipes WHERE product_item_id=%s", (product,)) == Decimal("0.25")
    produce_product(product, "AFTER-EDIT", "2", business_today() + timedelta(days=10), actor)
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == Decimal("8.5")
    assert scalar(dsn, "SELECT count(*) FROM inventory_items WHERE item_type='finished_product'") == 1


@pytest.mark.parametrize("case", ["empty", "duplicate", "unit", "missing", "inactive", "incomplete", "negative"])
def test_invalid_recipe_edit_is_atomic(stock, case):
    dsn, actor, material, product = stock
    ids, quantities, units = [material], ["250"], ["g"]
    if case == "empty":
        ids, quantities, units = [], [], []
    elif case == "duplicate":
        ids, quantities, units = [material, material], ["250", "250"], ["g", "g"]
    elif case == "unit":
        units = ["ml"]
    elif case == "missing":
        ids = [999999]
    elif case == "incomplete":
        quantities = []
    elif case == "negative":
        quantities = ["-1"]
    elif case == "inactive":
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE inventory_items SET is_active=false WHERE item_id=%s", (material,))
    with pytest.raises(ValueError):
        update_product_recipe(product, ids, quantities, units, actor)
    assert scalar(dsn, "SELECT quantity_required FROM product_recipes WHERE product_item_id=%s", (product,)) == Decimal("0.5")
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10


def test_add_recipe_to_existing_product(stock):
    dsn, actor, material, product = stock
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM product_recipes WHERE product_item_id=%s", (product,))
    update_product_recipe(product, [material], ["500"], ["g"], actor)
    update_product_recipe(product, [material], ["500"], ["g"], actor)
    assert scalar(dsn, "SELECT count(*) FROM product_recipes WHERE product_item_id=%s", (product,)) == 1


def test_username_login_requires_credentials_and_entry_link_signs_out(inventory_db):
    from app.config import SESSION_COOKIE_NAME
    dsn, actor = inventory_db
    password = "Username-Test-123!"
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE accounts SET username='BPadmin', password_hash=%s WHERE account_id=%s",
                        (hash_password(password), actor))
    assert accounts.authenticate_account("bpADMIN", password)["account_id"] == actor
    assert accounts.authenticate_account("inventory@test.invalid", password) is None
    assert accounts.authenticate_account("BPadmin", "incorrect") is None
    client = TestClient(create_app())
    assert client.get("/portal/inventory/inventory").url.path == "/login"

    def sign_in():
        page = client.get("/login")
        assert 'name="username"' in page.text and 'type="email"' not in page.text
        token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
        response = client.post("/login", data={"username": "BPadmin", "password": password,
                                               "csrf_token": token, "consent": "yes"}, follow_redirects=False)
        assert response.status_code == 303
        assert "Max-Age" not in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        return client.cookies.get(SESSION_COOKIE_NAME)

    for entry in ("/", "/login"):
        old_token = sign_in()
        assert client.get("/portal/inventory/inventory").status_code == 200
        page = client.get(entry)
        assert page.url.path == "/login" and "Portal Sign In" in page.text
        replay = TestClient(create_app())
        replay.cookies.set(SESSION_COOKIE_NAME, old_token)
        assert replay.get("/portal/inventory/dashboard").url.path == "/login"
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == 0


def reset_test_credentials():
    return [{"username": f"BPadmin{i}", "password": f"Reset-Test-{i}-Unique!"} for i in range(1, 5)]


def test_catalog_reset_preserves_products_and_replaces_accounts(stock, tmp_path, monkeypatch):
    from app.repositories.reporting import inventory_product_movement_analytics
    from tools.reset_inventory import CLEAR_TABLES, reset_inventory
    dsn, actor, material, product = stock
    produce_product(product, "RESET-BATCH", "3", business_today() + timedelta(days=10), actor)
    dispatch_stock(product, "1", "Before reset", str(uuid4()), actor)
    before_name = scalar(dsn, "SELECT name FROM inventory_items WHERE item_id=%s", (product,))
    before_movements = scalar(dsn, "SELECT count(*) FROM inventory_movements")
    preview = reset_inventory(dsn)
    assert not preview["applied"] and preview["finished_products_kept"] == 1
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == before_movements
    with pytest.raises(ValueError, match="backup"):
        reset_inventory(dsn, apply=True, credentials=reset_test_credentials())
    backup = tmp_path / "test-backup.dump"
    backup.write_bytes(b"PGDMP" + b"test-backup-header" * 4)
    credentials = reset_test_credentials()
    result = reset_inventory(dsn, apply=True, backup=backup, credentials=credentials)
    assert result["accounts_created"] == [f"BPadmin{i}" for i in range(1, 5)]
    assert scalar(dsn, "SELECT count(*) FROM inventory_items") == 1
    assert scalar(dsn, "SELECT name FROM inventory_items WHERE item_id=%s", (product,)) == before_name
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (product,)) == 0
    assert scalar(dsn, "SELECT count(*) FROM accounts WHERE account_id=%s", (actor,)) == 0
    for table in CLEAR_TABLES:
        assert scalar(dsn, f"SELECT count(*) FROM {table}") == (4 if table == "accounts" else 0)
    assert inventory_product_movement_analytics() == []
    for item in credentials:
        account = accounts.authenticate_account(item["username"], item["password"])
        assert account and account["email"] is None
    monkeypatch.setattr(init_db, "database_dsn", lambda: dsn)
    init_db.init_database()
    assert scalar(dsn, "SELECT count(*) FROM accounts") == 4
    with pytest.raises(psycopg2.Error, match="immutable"):
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE inventory_movements")
    assert scalar(dsn, """SELECT count(*) FROM information_schema.columns WHERE table_schema=current_schema()
        AND table_name='inventory_items' AND column_name IN ('base_price','pack_size','pack_size_unit','pack_content_status')""") == 0


def test_reset_failure_rolls_back_data_and_history_protection(stock, tmp_path):
    from tools.reset_inventory import reset_inventory
    dsn, _, material, _ = stock
    backup = tmp_path / "test-backup.dump"
    backup.write_bytes(b"PGDMP" + b"test-backup-header" * 4)
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE FUNCTION reject_test_account() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'reset insertion blocked'; END $$;
                CREATE TRIGGER reject_test_account BEFORE INSERT ON accounts
                FOR EACH ROW EXECUTE FUNCTION reject_test_account();""")
    before = scalar(dsn, "SELECT count(*) FROM inventory_movements")
    with pytest.raises(psycopg2.Error, match="reset insertion blocked"):
        reset_inventory(dsn, apply=True, backup=backup, credentials=reset_test_credentials())
    assert scalar(dsn, "SELECT count(*) FROM accounts") == 1
    assert scalar(dsn, "SELECT quantity_available FROM inventory_items WHERE item_id=%s", (material,)) == 10
    assert scalar(dsn, "SELECT count(*) FROM inventory_movements") == before
    with pytest.raises(psycopg2.Error, match="immutable"):
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM inventory_movements")
