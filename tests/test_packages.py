from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
import psycopg2
from fastapi.testclient import TestClient

from app import database, repositories, web_sessions
from app.application import create_app
from app.business_time import business_today
from app.repositories.inventory import (
    add_product_batch, add_raw_inventory_item, create_product_with_recipe, dispatch_package,
    dispatch_stock, list_inventory_items, list_products, package_workspace, produce_product,
    save_package_contents,
    count_inventory_movements, list_inventory_movements,
)


@pytest.fixture
def package_stock(inventory_db):
    _, actor = inventory_db
    raw = add_raw_inventory_item("Meat", "meat", "kg", "20", actor)["raw_material_id"]
    first = create_product_with_recipe("Beef product", "Beef", [raw], ["1"], ["kg"], actor)["product_id"]
    second = create_product_with_recipe("Pork product", "Pork", [raw], ["1"], ["kg"], actor)["product_id"]
    with database.get_transaction_cursor() as cur:
        cur.execute("""INSERT INTO inventory_items(item_type,name,category,unit)
            VALUES('finished_product','Trial Package','Package','pack') RETURNING item_id""")
        package = cur.fetchone()["item_id"]
    today = business_today()
    add_product_batch(first, "BEEF-EARLY", "3", today+timedelta(days=2), actor_account_id=actor)
    add_product_batch(first, "BEEF-LATER", "7", today+timedelta(days=20), actor_account_id=actor)
    add_product_batch(second, "PORK-ONLY", "10", today+timedelta(days=20), actor_account_id=actor)
    return actor, package, first, second


def test_standard_package_fefo_snapshot_and_no_double_count(package_stock):
    actor, package, first, second = package_stock
    save_package_contents(package, "standard", [first, second], ["2", "1"], 1, actor, confirmed=True)
    assert package_workspace(package)["package_capacity"] == 5
    ref = str(uuid4())
    assert not dispatch_package(package, "2", "Delivery", ref, [], [], 2, actor)["already_recorded"]
    assert dispatch_package(package, "2", "Delivery", ref, [], [], 2, actor)["already_recorded"]
    batches = database.fetch_all("SELECT batch_code,quantity_available FROM inventory_batches ORDER BY batch_id")
    assert [b["quantity_available"] for b in batches] == [0, 6, 8]
    movements = database.fetch_all("SELECT * FROM inventory_movements WHERE dispatch_id=%s ORDER BY movement_id", (ref,))
    assert len(movements) == 3 and sum(-m["quantity_delta"] for m in movements) == 6
    assert {m["item_id"] for m in movements} == {first, second}
    assert database.fetch_one("SELECT count(*) n FROM inventory_batches WHERE item_id=%s", (package,))["n"] == 0
    assert all(p["product_id"] != package for p in list_products(include_packages=False))
    assert list_inventory_items(category="finished_product:Package")[0]["package_mode"] == "standard"
    with pytest.raises(ValueError, match="cannot be changed"):
        save_package_contents(package, "standard", [first], ["3"], 2, actor, confirmed=True)
    history = package_workspace(package)["package_history"][0]
    assert history["package_mode"] == "standard" and len(history["contents"]) == 2


def test_custom_package_and_atomic_insufficient_stock(package_stock):
    actor, package, first, second = package_stock
    with pytest.raises(ValueError, match="Not enough"):
        dispatch_package(package, "2", "Insufficient", str(uuid4()), [first, second], ["1", "6"], 1, actor, dispatch_mode="customized")
    assert database.fetch_one("SELECT SUM(quantity_available) n FROM inventory_batches")["n"] == 20
    assert database.fetch_one("SELECT count(*) n FROM inventory_dispatches")["n"] == 0
    ref = str(uuid4())
    dispatch_package(package, "2", "Customized", ref, [first, second], ["1", "3"], 1, actor, dispatch_mode="customized")
    assert package_workspace(package)["package_history"][0]["quantity"] == 2
    with pytest.raises(ValueError, match="different details"):
        dispatch_package(package, "2", "Customized", ref, [first, second], ["2", "3"], 1, actor, dispatch_mode="customized")


def test_packages_cannot_be_produced_received_or_dispatched_as_single_packs(package_stock):
    actor, package, first, second = package_stock
    with pytest.raises(ValueError):
        add_product_batch(package, "BAD-PACKAGE", "1", business_today()+timedelta(days=10), actor_account_id=actor)
    with pytest.raises(ValueError):
        produce_product(package, "BAD-PACKAGE", "1", business_today()+timedelta(days=10), actor)
    with pytest.raises(ValueError):
        dispatch_stock(package, "1", "Wrong workflow", str(uuid4()), actor)
    with pytest.raises(ValueError, match="active individual"):
        save_package_contents(package, "standard", [package], ["1"], 1, actor, confirmed=True)
    with pytest.raises(ValueError, match="at least one"):
        save_package_contents(package, "standard", [], [], 1, actor, confirmed=True)
    save_package_contents(package, "standard", [first], ["1"], 1, actor, confirmed=True)
    with pytest.raises(ValueError, match="settings changed"):
        dispatch_package(package, "1", "Stale", str(uuid4()), [], [], 1, actor)


def test_package_concurrent_dispatch_does_not_oversell(package_stock):
    actor, package, first, second = package_stock
    save_package_contents(package, "standard", [first], ["6"], 1, actor, confirmed=True)
    def dispatch():
        try:
            dispatch_package(package, "1", "Concurrent", str(uuid4()), [], [], 2, actor)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: dispatch(), range(2))) == [False, True]


def test_package_page_renders_and_routes_enforce_csrf_and_actor(package_stock, monkeypatch):
    from app.portals import shared
    actor, package, first, second = package_stock
    monkeypatch.setattr(web_sessions, "_load_session", lambda *a: {})
    monkeypatch.setattr(web_sessions, "_persist_session", lambda *a: None)
    monkeypatch.setattr(web_sessions, "_delete_session", lambda *a: None)
    monkeypatch.setattr(shared, "require_portal_session", lambda *a: None)
    monkeypatch.setattr(shared, "session_account_id", lambda *a: actor)
    monkeypatch.setattr(repositories, "unread_notification_count", lambda *a: 0)
    client = TestClient(create_app())
    response = client.get(f"/portal/inventory/package-details?product_id={package}")
    assert response.status_code == 200 and 'value="standard"' in response.text
    assert 'value="customized"' in response.text
    assert "Set the standard contents" in response.text
    assert client.post(f"/portal/inventory/packages/{package}/settings", data={}).status_code == 403
    assert client.get(f"/portal/inventory/package-details?product_id={first}").status_code == 404
    save_package_contents(package, "standard", [first], ["1"], 1, actor, confirmed=True)
    response = client.get(f"/portal/inventory/package-details?product_id={package}")
    assert response.status_code == 200 and "Standard contents are saved and locked" in response.text
    assert 'id="dispatch-' in response.text


def test_explicit_test_reset_preserves_package_definition(package_stock, inventory_db, tmp_path):
    from tools.reset_inventory import reset_inventory
    actor, package, first, second = package_stock
    save_package_contents(package, "standard", [first], ["2"], 1, actor, confirmed=True)
    dispatch_package(package, "1", "Before test reset", str(uuid4()), [], [], 2, actor)
    backup = tmp_path / "test-backup.dump"
    backup.write_bytes(b"PGDMP" + b"test-only-backup-header" * 4)
    credentials = [{"username": f"BPadmin{i}", "password": f"Reset-Package-{i}-Unique!"} for i in range(1,5)]
    reset_inventory(inventory_db[0], apply=True, backup=backup, credentials=credentials)
    workspace = package_workspace(package)
    assert workspace["package_contents"][0]["quantity_per_package"] == 2
    assert workspace["package_capacity"] == 0 and workspace["package_history"] == []


def test_standard_is_immutable_and_custom_dispatch_is_one_time(package_stock):
    actor, package, first, second = package_stock
    with pytest.raises(ValueError, match="Confirm"):
        save_package_contents(package, "standard", [first], ["2"], 1, actor)
    save_package_contents(package, "standard", [first], ["2"], 1, actor, confirmed=True)
    for query, args in [
        ("UPDATE inventory_package_components SET quantity_per_package=3 WHERE package_item_id=%s", (package,)),
        ("DELETE FROM inventory_package_components WHERE package_item_id=%s", (package,)),
        ("INSERT INTO inventory_package_components VALUES(%s,%s,1)", (package,second)),
        ("UPDATE inventory_package_settings SET standard_locked_at=NULL WHERE package_item_id=%s", (package,)),
    ]:
        with pytest.raises(psycopg2.Error, match="cannot be changed"):
            with database.get_transaction_cursor() as cur:
                cur.execute(query,args)
    reference = str(uuid4())
    dispatch_package(package, "1", "One-time selection", reference, [second], ["3"], 2, actor, dispatch_mode="customized")
    assert package_workspace(package)["package_contents"][0]["quantity_per_package"] == 2
    assert package_workspace(package)["package_contents"][0]["item_id"] == first
    with pytest.raises(ValueError, match="different details"):
        dispatch_package(package, "1", "One-time selection", reference, [], [], 2, actor, dispatch_mode="standard")
    with pytest.raises(ValueError, match="at least one"):
        dispatch_package(package, "1", "No contents retained", str(uuid4()), [], [], 2, actor, dispatch_mode="customized")
    dispatch_package(package, "1", "Use locked standard", str(uuid4()), [], [], 2, actor, dispatch_mode="standard")
    assert package_workspace(package)["package_history"][0]["package_mode"] == "standard"


def test_all_three_package_cards_have_no_pagination(package_stock, monkeypatch):
    from app.portals import shared
    with database.get_transaction_cursor() as cur:
        cur.execute("""INSERT INTO inventory_items(item_type,name,category,unit) VALUES
            ('finished_product','Area Distributor''s Package','Package','pack'),
            ('finished_product','Resellers Package','Package','pack')""")
    monkeypatch.setattr(web_sessions, "_load_session", lambda *a: {})
    monkeypatch.setattr(web_sessions, "_persist_session", lambda *a: None)
    monkeypatch.setattr(web_sessions, "_delete_session", lambda *a: None)
    monkeypatch.setattr(shared, "require_portal_session", lambda *a: None)
    monkeypatch.setattr(repositories, "unread_notification_count", lambda *a: 0)
    client = TestClient(create_app())
    for endpoint in ("/portal/inventory/finished-products?type=Package&page=99",
                     "/portal/inventory/finished-products/products?type=Package&page=99"):
        response = client.get(endpoint)
        assert response.status_code == 200
        assert all(name in response.text for name in ("Trial Package", "Resellers Package", "Area Distributor"))
        assert 'data-inventory-products-pagination' not in response.text


def test_inventory_logs_group_package_dispatch_before_search_and_pagination(package_stock):
    actor, package, first, second = package_stock
    save_package_contents(package, 'standard', [first, second], ['2', '1'], 1, actor, confirmed=True)
    standard_ref, custom_ref = str(uuid4()), str(uuid4())
    dispatch_package(package, '2', 'Standard delivery', standard_ref, [], [], 2, actor)
    dispatch_package(package, '1', 'Custom delivery', custom_ref, [second], ['2'], 2, actor, dispatch_mode='customized')
    dispatch_stock(first, '1', 'Individual delivery', str(uuid4()), actor)
    rows = list_inventory_movements(category='dispatch')
    assert count_inventory_movements(category='dispatch') == len(rows) == 3
    package_rows = [r for r in rows if r['package_mode']]
    assert len(package_rows) == 2
    standard = next(r for r in package_rows if str(r['dispatch_id']) == standard_ref)
    assert standard['entity'] == 'Trial Package'
    assert standard['quantity_delta'] == -2 and standard['unit'] == 'package'
    assert standard['balance_before'] is None and standard['balance_after'] is None
    assert standard['package_contents'] == [
        {'name': 'Beef Product', 'quantity_per_package': 2, 'total_packs': 4},
        {'name': 'Pork Product', 'quantity_per_package': 1, 'total_packs': 2},
    ]
    assert count_inventory_movements(q='Trial Package', category='dispatch') == 2
    assert count_inventory_movements(q='Pork product', category='dispatch') == 2
    assert len(list_inventory_movements(q='Pork product', category='dispatch')) == 2
    for sort in ('', 'oldest', 'actor_asc'):
        paged = [list_inventory_movements(category='dispatch', page=p, page_size=1, sort=sort)[0] for p in (1, 2, 3)]
        assert len({str(r['dispatch_id']) for r in paged}) == 3
    with database.get_transaction_cursor() as cur:
        cur.execute("UPDATE inventory_items SET name='Renamed package' WHERE item_id=%s", (package,))
        cur.execute("UPDATE inventory_items SET name='Renamed beef' WHERE item_id=%s", (first,))
    assert list_inventory_movements(q='Trial Package', category='dispatch')[0]['entity'] == 'Trial Package'
    assert count_inventory_movements(q='Beef product', category='dispatch') == 1


def test_package_log_expands_saved_contents(package_stock, monkeypatch):
    from app.portals import shared
    actor, package, first, second = package_stock
    dispatch_package(package, '2', 'One-time delivery', str(uuid4()), [first, second], ['2', '1'], 1, actor, dispatch_mode='customized')
    monkeypatch.setattr(web_sessions, '_load_session', lambda *a: {})
    monkeypatch.setattr(web_sessions, '_persist_session', lambda *a: None)
    monkeypatch.setattr(web_sessions, '_delete_session', lambda *a: None)
    monkeypatch.setattr(shared, 'require_portal_session', lambda *a: None)
    monkeypatch.setattr(repositories, 'unread_notification_count', lambda *a: 0)
    client = TestClient(create_app())
    response = client.get('/portal/inventory/logs?type=dispatch')
    assert response.status_code == 200
    assert response.text.count('class="movement-row movement-row--out"') == 1
    assert '<strong>Trial Package</strong>' in response.text
    assert 'Package dispatch · Customized' in response.text
    assert '<details class="package-log-contents">' in response.text
    assert 'View package contents' in response.text
    assert 'Packs per package' in response.text and 'Total packs dispatched' in response.text
    assert 'Beef Product' in response.text and 'Pork Product' in response.text
