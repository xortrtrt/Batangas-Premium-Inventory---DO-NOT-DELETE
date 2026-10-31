from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import database, repositories, web_sessions
from app.application import create_app
from app.business_time import business_today
from app.repositories.inventory import (
    add_product_batch, add_raw_inventory_item, count_inventory_batches, create_product_with_recipe,
    dispatch_stock, list_inventory_batches, product_stock_details, remove_product_batch, removed_batches_page,
)


@pytest.fixture
def batch_stock(inventory_db):
    _, actor = inventory_db
    raw = add_raw_inventory_item("Meat", "meat", "kg", "20", actor)["raw_material_id"]
    product = create_product_with_recipe("Test product", "Pork", [raw], ["1"], ["kg"], actor)["product_id"]
    batch = add_product_batch(product, "REMOVE-TEST", "10", business_today()+timedelta(days=2),
                              actor_account_id=actor)["product_batch_id"]
    return actor, product, batch


def test_remove_preserves_history_deducts_once_and_hides_batch(batch_stock):
    actor, product, batch = batch_stock
    assert remove_product_batch(product, batch, "Damaged packaging", True, "10", actor)
    assert not remove_product_batch(product, batch, "Damaged packaging", True, "10", actor)
    row = database.fetch_one("SELECT * FROM inventory_batches WHERE batch_id=%s", (batch,))
    assert row["removed_at"] and row["removed_by_account_id"] == actor
    assert row["quantity_available"] == 0 and row["quantity_received"] == 10
    assert row["removal_reason"] == "Damaged packaging"
    movements = database.fetch_all("SELECT * FROM inventory_movements WHERE affected_batch_id=%s ORDER BY movement_id", (batch,))
    assert len(movements) == 2 and movements[0]["quantity_delta"] == 10
    assert movements[1]["quantity_delta"] == -10 and movements[1]["actor_account_id"] == actor
    assert "Damaged packaging" in movements[1]["note"]
    assert product_stock_details(product)["totals"]["batch_count"] == 0
    assert product_stock_details(product)["movement_pagination"]["total"] == 2
    assert count_inventory_batches() == 0 and list_inventory_batches() == []
    archive = removed_batches_page(product_id=product)
    assert archive["pagination"]["total"] == 1
    assert archive["items"][0]["quantity_removed"] == 10
    assert archive["items"][0]["removal_reason"] == "Damaged packaging"
    assert removed_batches_page(q="Damaged")["pagination"]["total"] == 1
    assert removed_batches_page(q="Not a matching batch")["items"] == []
    assert removed_batches_page(product_id=999999) is None
    assert database.fetch_one("SELECT COUNT(*) total FROM alerts WHERE product_batch_id=%s AND status='open'", (batch,))["total"] == 0
    with pytest.raises(ValueError, match="Not enough"):
        dispatch_stock(product, "1", "Must not dispatch removed stock", str(uuid4()), actor)


def test_empty_batch_removal_keeps_dispatch_and_does_not_create_zero_movement(batch_stock):
    actor, product, batch = batch_stock
    dispatch_stock(product, "10", "Fully dispatched", str(uuid4()), actor)
    assert remove_product_batch(product, batch, "Archive empty batch", True, "0", actor)
    assert removed_batches_page()["items"][0]["quantity_removed"] == 0
    assert database.fetch_one("SELECT COUNT(*) total FROM inventory_movements WHERE affected_batch_id=%s", (batch,))["total"] == 2


def test_archive_records_remaining_quantity_and_renders_authenticated_view(batch_stock, monkeypatch):
    from app.portals import shared
    actor, product, batch = batch_stock
    dispatch_stock(product, "4", "Previously dispatched", str(uuid4()), actor)
    remove_product_batch(product, batch, "Archive remaining packs", True, "6", actor)
    assert removed_batches_page()["items"][0]["quantity_removed"] == 6
    assert removed_batches_page(page=999)["pagination"]["page"] == 1
    monkeypatch.setattr(web_sessions, "_load_session", lambda *a: {})
    monkeypatch.setattr(web_sessions, "_persist_session", lambda *a: None)
    monkeypatch.setattr(web_sessions, "_delete_session", lambda *a: None)
    client = TestClient(create_app())
    url = f"/portal/inventory/removed-batches?product_id={product}"
    monkeypatch.setattr(shared, "require_portal_session", lambda *a: shared.redirect_to("/login"))
    assert client.get(url, follow_redirects=False).headers["location"] == "/login"
    monkeypatch.setattr(shared, "require_portal_session", lambda *a: None)
    monkeypatch.setattr(repositories, "unread_notification_count", lambda *a: 0)
    response = client.get(url)
    assert response.status_code == 200
    assert "REMOVE-TEST" in response.text and "Archive remaining packs" in response.text
    assert "View stock history" in response.text and "Test Inventory" in response.text
    assert "No removed batches" in client.get(url+"&q=no-match").text
    assert client.get("/portal/inventory/removed-batches?product_id=bad").status_code == 404


@pytest.mark.parametrize("changes", [
    {"reason": " "}, {"reason": "x"*501}, {"confirmed": False},
    {"expected_quantity": "9"}, {"actor_account_id": 999999},
    {"batch_id": 999999}, {"product_id": 999999},
])
def test_invalid_removal_leaves_stock_unchanged(batch_stock, changes):
    actor, product, batch = batch_stock
    args = dict(product_id=product, batch_id=batch, reason="Remove batch", confirmed=True,
                expected_quantity="10", actor_account_id=actor)
    with pytest.raises(ValueError):
        remove_product_batch(**{**args, **changes})
    row = database.fetch_one("SELECT quantity_available,removed_at FROM inventory_batches WHERE batch_id=%s", (batch,))
    assert row["quantity_available"] == 10 and row["removed_at"] is None


def test_removal_and_dispatch_serialize_with_stale_stock_protection(batch_stock):
    actor, product, batch = batch_stock
    def remove():
        try:
            remove_product_batch(product, batch, "Remove batch", True, "10", actor)
            return "removed"
        except ValueError:
            return "stale"
    def dispatch():
        try:
            dispatch_stock(product, "5", "Dispatch packs", str(uuid4()), actor)
            return "dispatched"
        except ValueError:
            return "unavailable"
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(remove), executor.submit(dispatch)]
        results = [f.result() for f in futures]
    assert results in (["removed", "unavailable"], ["stale", "dispatched"])
    row = database.fetch_one("SELECT quantity_available FROM inventory_batches WHERE batch_id=%s", (batch,))
    assert row["quantity_available"] in (0, 5)


def test_remove_http_auth_csrf_and_server_actor(monkeypatch):
    from app.portals import shared
    client = TestClient(create_app())
    monkeypatch.setattr(web_sessions, "_load_session", lambda *a: {})
    monkeypatch.setattr(web_sessions, "_persist_session", lambda *a: None)
    monkeypatch.setattr(web_sessions, "_delete_session", lambda *a: None)
    endpoint = "/portal/inventory/products/1/batches/2/remove"
    form = dict(reason="Damaged packaging", expected_quantity="10", confirmed="yes", actor_account_id="999")
    assert client.post(endpoint, data=form).status_code == 403
    # Override the dependency only for testing the route's independent session guard.
    from app.security_controls import enforce_csrf
    client.app.dependency_overrides[enforce_csrf] = lambda: None
    monkeypatch.setattr(shared, "require_portal_session", lambda *a: shared.redirect_to("/login"))
    assert client.post(endpoint, data=form, follow_redirects=False).headers["location"] == "/login"
    monkeypatch.setattr(shared, "require_portal_session", lambda *a: None)
    monkeypatch.setattr(shared, "session_account_id", lambda *a: 7)
    calls = []
    monkeypatch.setattr(repositories, "remove_product_batch", lambda *a: calls.append(a) or True)
    response = client.post(endpoint, data=form, follow_redirects=False)
    assert response.status_code == 303 and "product_id=1" in response.headers["location"]
    assert calls == [(1, 2, "Damaged packaging", True, "10", 7)]
