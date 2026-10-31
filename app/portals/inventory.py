from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from app.web import path_with_query

from app import repositories as data
from app.portals import shared

router = APIRouter()


@router.post("/portal/inventory/packages/{package_id}/settings")
async def package_settings(request: Request, package_id: int):
    guard = await run_in_threadpool(shared.require_portal_session, request)
    if guard:
        return guard
    form = await request.form()
    try:
        await run_in_threadpool(data.save_package_contents, package_id, str(form.get("mode", "")),
            form.getlist("product_id[]"), form.getlist("packs[]"), int(str(form.get("revision", "0"))),
            shared.session_account_id(request), str(form.get("confirmed", "")) == "yes")
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "package-details", product_id=str(package_id), error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "package-details", product_id=str(package_id), message="Package settings saved."))


@router.post("/portal/inventory/packages/{package_id}/dispatch")
async def package_dispatch(request: Request, package_id: int):
    guard = await run_in_threadpool(shared.require_portal_session, request)
    if guard:
        return guard
    form = await request.form()
    try:
        result = await run_in_threadpool(data.dispatch_package, package_id, str(form.get("quantity", "")),
            str(form.get("note", "")), str(form.get("submission_reference", "")),
            form.getlist("product_id[]"), form.getlist("packs[]"), int(str(form.get("revision", "0"))),
            shared.session_account_id(request), str(form.get("dispatch_mode", "")))
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "package-details", product_id=str(package_id), error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "package-details", product_id=str(package_id),
        message="Package dispatch already recorded." if result["already_recorded"] else "Package dispatched. Finished-product stock deducted."))


@router.post("/portal/inventory/products/{product_id}/batches/{batch_id}/remove")
def remove_batch(
    request: Request, product_id: int, batch_id: int,
    reason: Annotated[str, Form()], expected_quantity: Annotated[str, Form()],
    confirmed: Annotated[str, Form()] = "",
):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        removed = data.remove_product_batch(product_id, batch_id, reason, confirmed == "yes",
                                            expected_quantity, shared.session_account_id(request))
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path(
            "inventory", "product-details", product_id=str(product_id), error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path(
        "inventory", "product-details", product_id=str(product_id),
        message="Batch removed. Stock history is preserved." if removed else "Batch was already removed."))


@router.post("/portal/inventory/finished-products/opening-balance")
@router.post("/portal/team-leader/finished-products/opening-balance")
def finished_opening_balance(
    request: Request,
    product_id: Annotated[int, Form()],
    batch_code: Annotated[str, Form()],
    quantity: Annotated[str, Form()],
    expiry_date: Annotated[date, Form()],
    note: Annotated[str, Form()],
    submission_reference: Annotated[str, Form()],
):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        result = data.add_product_batch(
            product_id, batch_code, quantity, expiry_date, source_type="opening_balance",
            actor_account_id=shared.session_account_id(request), opening_note=note,
            opening_reference=submission_reference,
        )
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", modal="opening-balance", error=str(exc)))
    message = "Opening balance already recorded." if result["already_recorded"] else "Finished goods opening balance recorded."
    return shared.redirect_to(shared.safe_portal_path("inventory", "logs", type="opening", message=message))


@router.post("/portal/inventory/raw-materials/{raw_material_id}/remove")
@router.post("/portal/team-leader/raw-materials/{raw_material_id}/remove")
def remove_material(request: Request, raw_material_id: int, confirmed: Annotated[str, Form()] = ""):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        data.remove_raw_material(raw_material_id, confirmed == "yes", shared.session_account_id(request))
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "raw-materials", error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "raw-materials",
                                                     message="Raw material removed from active inventory. Stock history is preserved."))


@router.post("/portal/inventory/raw-materials/deduct")
@router.post("/portal/team-leader/raw-materials/deduct")
def deduct_material(
    request: Request,
    raw_material_id: Annotated[int, Form()],
    quantity: Annotated[str, Form()],
    note: Annotated[str, Form()],
    submission_reference: Annotated[str, Form()],
):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        result = data.deduct_raw_material(raw_material_id, quantity, note, submission_reference,
                                          shared.session_account_id(request))
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", modal="deduct-material", error=str(exc)))
    message = "Raw-material deduction already recorded." if result["already_recorded"] else "Raw-material stock deducted successfully."
    return shared.redirect_to(shared.safe_portal_path("inventory", "logs", type="deductions", message=message))


@router.post("/portal/inventory/raw-materials/{raw_material_id}/reactivate")
@router.post("/portal/team-leader/raw-materials/{raw_material_id}/reactivate")
def reactivate_material(request: Request, raw_material_id: int):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        data.reactivate_raw_material(raw_material_id, shared.session_account_id(request))
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "raw-materials", type="archived", error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "raw-materials", message="Raw material reactivated with its saved stock balance."))


@router.post("/portal/inventory/dispatch")
def dispatch_inventory(
    request: Request,
    product_id: int = Form(...),
    quantity: str = Form(...),
    note: str = Form(...),
    submission_reference: str = Form(...),
):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        result = data.dispatch_stock(product_id, quantity, note, submission_reference,
                                     shared.session_account_id(request))
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", error=str(exc)))
    message = "Dispatch already recorded." if result["already_recorded"] else "Stock dispatched successfully."
    return shared.redirect_to(shared.safe_portal_path("inventory", "logs", message=message))

def logs_page(request: Request, page_size: int = 10, inventory_only: bool = True) -> dict:
    filters = shared.portal_filters(request)
    movement_category = filters["type"] if filters["type"] in {"opening", "receipts", "production", "dispatch", "deductions"} else ""
    if inventory_only:
        items = data.list_inventory_movements(
            q=filters["q"],
            category=movement_category,
            page=filters["page"],
            page_size=page_size,
            sort=filters["sort"],
        )
        total = data.count_inventory_movements(q=filters["q"], category=movement_category)
    else:
        items = data.list_activity_logs(q=filters["q"], page=filters["page"], page_size=page_size, inventory_only=False, sort=filters["sort"])
        total = data.count_activity_logs(q=filters["q"], inventory_only=False)
    page = shared.paged(
        items,
        total,
        filters["page"],
        page_size,
        q=filters["q"],
        type=movement_category if inventory_only else "",
        sort=filters["sort"],
    )
    page["inventory_movements"] = inventory_only
    current_page = page["pagination"]["page"]
    total_pages = page["pagination"]["total_pages"]
    first_page = max(1, min(current_page - 2, total_pages - 4))
    page["pagination"]["page_numbers"] = list(range(first_page, min(total_pages, first_page + 4) + 1))
    return page

def finished_inventory_products_page(request: Request, page_size: int = 8) -> dict:
    filters = shared.portal_filters(request)
    category = f"finished_product:{filters['type']}" if filters["type"] else "finished_product"
    packages_only = filters["type"] == "Package"
    total = data.count_inventory_items(q=filters["q"], category=category, exclude_packages=not packages_only)
    page_number = 1 if packages_only else data.pagination_meta(total, filters["page"], page_size)["page"]
    items = data.list_inventory_items(q=filters["q"], category=category,
        page=None if packages_only else page_number, page_size=page_size,
        sort=filters["sort"], exclude_packages=not packages_only)
    return shared.paged(items, total, page_number, max(total,1) if packages_only else page_size,
                        q=filters["q"], type=filters["type"], sort=filters["sort"])


def raw_materials_inventory_page(request: Request, page_size: int = 10) -> dict:
    filters = shared.portal_filters(request)
    show_removed = filters["type"] == "archived"
    material_category = filters["type"] if filters["type"] in data.raw_material_categories else ""
    category = f"raw_material:{material_category}" if material_category else "raw_material"
    items = data.list_inventory_items(q=filters["q"], category=category, page=filters["page"], page_size=page_size, sort=filters["sort"], raw_material_active=not show_removed)
    total = data.count_inventory_items(q=filters["q"], category=category, raw_material_active=not show_removed)
    page = shared.paged(
        items,
        total,
        filters["page"],
        page_size,
        q=filters["q"],
        type="archived" if show_removed else material_category,
        sort=filters["sort"],
    )
    current_page = page["pagination"]["page"]
    total_pages = page["pagination"]["total_pages"]
    first_page = max(1, min(current_page - 2, total_pages - 4))
    page["pagination"]["page_numbers"] = list(range(first_page, min(total_pages, first_page + 4) + 1))
    return page

def raw_materials_inventory_context(request: Request) -> dict:
    raw_materials_page = raw_materials_inventory_page(request)
    items = raw_materials_page["items"]
    maximum_available = max((float(item.get("available") or 0) for item in items), default=0)
    raw_items = [
        {
            **item,
            "stock_percent": round((float(item.get("available") or 0) / maximum_available) * 100)
            if maximum_available
            else 0,
        }
        for item in items
    ]
    return {
        "raw_materials_page": raw_materials_page,
        "raw_items": raw_items,
        "raw_material_tabs": (
            ("", "Active materials"),
            ("meat", "Meat"),
            ("raw_material", "Other supplies"),
            ("archived", "Removed materials"),
        ),
    }

def finished_products_inventory_context(request: Request) -> dict:
    products_page = finished_inventory_products_page(request)
    finished_products = [
        product
        for product in products_page["items"]
        if str(product.get("category") or "").strip().lower() != "package"
    ]
    product_packages = data.list_inventory_items(q=products_page["filters"]["q"],
        category="finished_product:Package", sort=products_page["filters"]["sort"]) if not products_page["filters"]["type"] else [
        product for product in products_page["items"] if product.get("category") == "Package"
    ]
    return {
        "inventory_items_page": products_page,
        "inventory_products_page": products_page,
        "finished_products": finished_products,
        "finished_product_packages": product_packages,
        "catalog_total": products_page["pagination"]["total"] + (len(product_packages) if not products_page["filters"]["type"] else 0),
        "inventory_item_tabs": [
            {"label": "All products", "value": ""},
            *[
                {"label": category, "value": category}
                for category in data.product_categories
            ],
            {"label": "Packages", "value": "Package"},
        ],
    }

def inventory_batches_page(request: Request, page_size: int = 10) -> dict:
    filters = shared.portal_filters(request)
    categories = [*data.product_categories, "Package"]
    category = filters["type"] if filters["type"] in categories else ""
    items = data.list_inventory_batches(
        q=filters["q"],
        category=category,
        page=filters["page"],
        page_size=page_size,
        sort=filters["sort"],
    )
    total = data.count_inventory_batches(q=filters["q"], category=category)
    page = shared.paged(
        items,
        total,
        filters["page"],
        page_size,
        q=filters["q"],
        type=category,
        sort=filters["sort"],
    )
    current_page = page["pagination"]["page"]
    total_pages = page["pagination"]["total_pages"]
    first_page = max(1, min(current_page - 2, total_pages - 4))
    page["pagination"]["page_numbers"] = list(range(first_page, min(total_pages, first_page + 4) + 1))
    return page

def profile_context(request: Request) -> dict:
    account_id = shared.session_account_id(request)
    account = data.account_portal_profile(account_id) if account_id is not None else None
    return {
        "account_profile": account,
    }

def dashboard_context(request: Request) -> dict:
    return {
        "team_leader_role": "inventory",
        "metrics": data.current_metrics(),
        "products": data.list_products(include_packages=False),
        "movement_analytics": data.inventory_product_movement_analytics(days=30, limit=8),
    }

def inventory_context(request: Request) -> dict:
    recipe_products_page = shared.product_page(request, page_size=8)
    recipe_product_ids = [product["product_id"] for product in recipe_products_page["items"]]
    return {
        "opening_reference": str(uuid4()),
        "dispatch_reference": str(uuid4()),
        "raw_deduction_reference": str(uuid4()),
        "products": data.list_products(include_packages=False),
        "recipe_products_page": recipe_products_page,
        "recipe_products": recipe_products_page["items"],
        "raw_materials": data.list_raw_materials(),
        "product_recipes": data.list_product_recipes(product_ids=recipe_product_ids),
        "raw_material_categories": data.raw_material_categories,
        "product_categories": data.product_categories,
        "stock_units": data.stock_units,
        "recipe_units": data.recipe_units,
    }

def batches_context(request: Request) -> dict:
    page = inventory_batches_page(request)
    return {
        "inventory_batches_page": page,
        "inventory_batches": page["items"],
        "batch_categories": (
            ("", "All batches"),
            *[(category, category) for category in data.product_categories],
            ("Package", "Packages"),
        ),
    }

def logs_context(request: Request) -> dict:
    page = logs_page(request, inventory_only=True)
    return {
        "activity_logs_page": page,
        "activity_logs": page["items"],
        "movement_categories": (
            ("", "All movements"),
            ("opening", "Opening"),
            ("receipts", "Receipts"),
            ("production", "Production"),
            ("dispatch", "Dispatch"),
            ("deductions", "Raw deductions"),
        ),
    }

def product_details_context(request: Request) -> dict:
    try:
        product_id = int(request.query_params.get("product_id", ""))
    except ValueError:
        raise HTTPException(status_code=404) from None
    details = data.product_stock_details(
        product_id,
        batch_page=shared.positive_int(request.query_params.get("batch_page"), maximum=1000000),
        movement_page=shared.positive_int(request.query_params.get("movement_page"), maximum=1000000),
    )
    if details is None:
        raise HTTPException(status_code=404)
    if details["product"].get("category") == "Package":
        return {**package_details_context(request), "is_package_page": True}
    return details


def package_details_context(request: Request) -> dict:
    try:
        product_id = int(request.query_params.get("product_id", ""))
    except ValueError:
        raise HTTPException(404) from None
    context = data.package_workspace(product_id)
    if context is None:
        raise HTTPException(404)
    return {**context, "package_dispatch_reference": str(uuid4())}


def removed_batches_context(request: Request) -> dict:
    raw_product = request.query_params.get("product_id", "")
    try:
        product_id = int(raw_product) if raw_product else None
    except ValueError:
        raise HTTPException(status_code=404) from None
    page = data.removed_batches_page(
        q=request.query_params.get("q", ""),
        page=shared.positive_int(request.query_params.get("page"), maximum=1000000),
        product_id=product_id,
    )
    if page is None:
        raise HTTPException(status_code=404)
    return {"removed_batches": page}


# Register loaders for both inventory and team-leader / owner roles
for role in ("inventory", "team-leader", "owner"):
    shared.PORTAL_SECTION_LOADERS[(role, "dashboard")] = dashboard_context
    shared.PORTAL_SECTION_LOADERS[(role, "inventory")] = inventory_context
    shared.PORTAL_SECTION_LOADERS[(role, "raw-materials")] = raw_materials_inventory_context
    shared.PORTAL_SECTION_LOADERS[(role, "finished-products")] = finished_products_inventory_context
    shared.PORTAL_SECTION_LOADERS[(role, "product-details")] = product_details_context
    shared.PORTAL_SECTION_LOADERS[(role, "package-details")] = package_details_context
    shared.PORTAL_SECTION_LOADERS[(role, "removed-batches")] = removed_batches_context
    shared.PORTAL_SECTION_LOADERS[(role, "batches")] = batches_context
    shared.PORTAL_SECTION_LOADERS[(role, "logs")] = logs_context
    shared.PORTAL_SECTION_LOADERS[(role, "profile")] = profile_context
    shared.PORTAL_SECTION_LOADERS[(role, "notifications")] = shared.notifications_context

@router.get("/portal/inventory/finished-products/products")
@router.get("/portal/team-leader/finished-products/products")
async def inventory_products_partial(request: Request):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    return shared.templates().TemplateResponse(
        request, "portals/inventory/_inventory_products.html",
        {"request": request, **finished_products_inventory_context(request)},
    )

@router.post("/portal/inventory/inventory-items")
@router.post("/portal/team-leader/inventory-items")
async def add_raw_material(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    unit: str = Form(...),
    quantity: str = Form(...),
):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        data.add_raw_inventory_item(name, category, unit, quantity, actor_account_id=shared.session_account_id(request))
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", message="Raw inventory added successfully."))

@router.post("/portal/inventory/inventory-items/quantity")
@router.post("/portal/team-leader/inventory-items/quantity")
async def add_raw_material_quantity(
    request: Request,
    raw_material_id: int = Form(...),
    quantity: str = Form(...),
):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        data.add_raw_inventory_quantity(raw_material_id, quantity, actor_account_id=shared.session_account_id(request))
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", message="Raw inventory quantity added successfully."))

@router.post("/portal/inventory/products")
@router.post("/portal/team-leader/products")
async def create_product(request: Request):
    guard = shared.require_portal_session(request)
    if guard:
        return guard

    form = await request.form()
    material_item_ids = [value for value in form.getlist("material_item_id[]") if str(value).strip()]
    quantity_required = [value for value in form.getlist("quantity_required[]") if str(value).strip()]
    quantity_required_units = [value for value in form.getlist("quantity_required_unit[]") if str(value).strip()]

    try:
        data.create_product_with_recipe(
            str(form.get("name", "")),
            str(form.get("category", "")),
            material_item_ids,
            quantity_required,
            quantity_required_units,
            actor_account_id=shared.session_account_id(request),
        )
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", message="Product recipe created successfully."))

@router.post("/portal/inventory/products/{product_id}/recipe")
@router.post("/portal/team-leader/products/{product_id}/recipe")
async def save_product_recipe(request: Request, product_id: int):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    form = await request.form()
    result = {}
    try:
        await run_in_threadpool(
            data.update_product_recipe, product_id, form.getlist("material_item_id[]"),
            form.getlist("quantity_required[]"), form.getlist("quantity_required_unit[]"),
            shared.session_account_id(request),
        )
        result["message"] = "Recipe saved. Future production will use these ingredients."
    except ValueError as exc:
        result["error"] = str(exc)
    return shared.redirect_to(path_with_query(
        "/portal/inventory/inventory", modal="product-recipes", recipe_product=str(product_id),
        q=str(form.get("q", "")), page=str(form.get("page", "1")), **result,
    ))


@router.post("/portal/inventory/production")
@router.post("/portal/team-leader/production")
async def produce_batch(
    request: Request,
    product_id: int = Form(...),
    batch_code: str = Form(...),
    quantity: str = Form(...),
    expiry_date: date = Form(...),
):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        data.produce_product(
            product_id,
            batch_code,
            quantity,
            expiry_date,
            actor_account_id=shared.session_account_id(request),
        )
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "inventory", message="Product batch produced and ingredients deducted."))

@router.post("/portal/inventory/batches")
@router.post("/portal/team-leader/batches")
async def register_direct_batch(
    request: Request,
    product_id: int = Form(...),
    batch_code: str = Form(...),
    quantity: str = Form(...),
    expiry_date: date = Form(...),
):
    guard = shared.require_portal_session(request)
    if guard:
        return guard
    try:
        data.add_product_batch(
            product_id,
            batch_code,
            quantity,
            expiry_date,
            actor_account_id=shared.session_account_id(request),
        )
    except ValueError as exc:
        return shared.redirect_to(shared.safe_portal_path("inventory", "batches", error=str(exc)))
    return shared.redirect_to(shared.safe_portal_path("inventory", "batches", message="Finished product batch recorded successfully."))
