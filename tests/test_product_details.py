"""Product histories must stay product-scoped, paginated, and authenticated."""
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.application import create_app
from app.business_time import business_today
from app.repositories.inventory import (
    add_product_batch, add_raw_inventory_item, create_product_with_recipe, dispatch_stock, product_stock_details,
)


def test_details_scope_balances_and_pagination(inventory_db):
    _, actor = inventory_db
    raw = add_raw_inventory_item("Meat", "meat", "kg", "20", actor)["raw_material_id"]
    first = create_product_with_recipe("First product", "Pork", [raw], ["1"], ["kg"], actor)["product_id"]
    other = create_product_with_recipe("Other product", "Pork", [raw], ["1"], ["kg"], actor)["product_id"]
    expiry = business_today() + timedelta(days=5)
    for n in range(11):
        add_product_batch(first, f"FIRST-{n:02}", "2", expiry, actor_account_id=actor)
    add_product_batch(other, "OTHER-ONLY", "99", expiry, actor_account_id=actor)
    dispatch_stock(first, "1", "Test dispatch", str(uuid4()), actor)
    detail = product_stock_details(first)
    assert detail["totals"]["physical_stock"] == 21
    assert detail["totals"]["available_stock"] == 21
    assert detail["batch_pagination"]["total"] == 11
    assert detail["movement_pagination"]["total"] == 12
    assert len(detail["batches"]) == len(detail["movements"]) == 10
    assert detail["movements"][0]["movement_type"] == "stock_dispatch"
    assert detail["movements"][0]["batch_code"] == "FIRST-00"
    assert all(b["batch_code"] != "OTHER-ONLY" for b in detail["batches"])
    last = product_stock_details(first, 999, 999)
    assert len(last["batches"]) == 1 and len(last["movements"]) == 2
    assert product_stock_details(raw) is None
    assert product_stock_details(999999) is None


def test_details_require_login_and_render_empty_product(monkeypatch):
    from app.portals import shared
    from app import repositories, web_sessions

    monkeypatch.setattr(web_sessions, "_load_session", lambda *a: {})
    monkeypatch.setattr(web_sessions, "_persist_session", lambda *a: None)
    monkeypatch.setattr(web_sessions, "_delete_session", lambda *a: None)

    client = TestClient(create_app())
    monkeypatch.setattr(shared, "require_portal_session", lambda *a: shared.redirect_to("/login"))
    endpoint = "/portal/inventory/product-details?product_id=1"
    assert client.get(endpoint, follow_redirects=False).headers["location"] == "/login"
    monkeypatch.setattr(shared, "require_portal_session", lambda *a: None)
    monkeypatch.setattr(repositories, "unread_notification_count", lambda *a: 0)
    from app.repositories._shared import pagination_meta
    empty_page = pagination_meta(0, 1, 10)
    monkeypatch.setattr(repositories, "product_stock_details", lambda *a, **kw: {
        "product": {"item_id": 1, "name": "Empty product", "category": "Pork", "is_active": True, "unit": "pack"},
        "totals": {"available_stock": 0, "physical_stock": 0, "batch_count": 0},
        "batches": [], "movements": [], "batch_pagination": empty_page, "movement_pagination": empty_page,
    })
    response = client.get(endpoint)
    assert response.status_code == 200
    assert "No batches recorded" in response.text and "No stock movements recorded" in response.text
    assert "Back to Finished Products" in response.text
    assert client.get("/portal/inventory/product-details?product_id=bad").status_code == 404
    monkeypatch.setattr(repositories, "product_stock_details", lambda *a, **kw: None)
    assert client.get(endpoint).status_code == 404
