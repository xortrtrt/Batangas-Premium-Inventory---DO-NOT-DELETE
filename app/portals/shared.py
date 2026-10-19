from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from app import repositories as data
from app import portal_config
from app import portal_dependencies
from app import uploads as uploads_module
from app import web
from app.capabilities import portal_section_capability, require_capability

router = APIRouter()

PORTAL_TEMPLATES = {
    "inventory": "portals/inventory.html",
    "team-leader": "portals/team_leader.html",
    "owner": "portals/inventory.html",
}

PORTAL_SECTION_LOADERS = {}

NOTIFICATION_CATEGORIES = (
    ("account", "Accounts"),
    ("inventory", "Inventory"),
)

def templates():
    return web.templates

def redirect_to(path: str) -> RedirectResponse:
    return web.redirect_to(path)

def session_account_id(request: Request) -> int | None:
    return portal_dependencies.session_account_id(request)

def session_team_leader_role(request: Request) -> str | None:
    return portal_dependencies.session_team_leader_role(request)

def require_portal_session(request: Request, role_key: str = "inventory") -> RedirectResponse | None:
    return portal_dependencies.require_portal_session(request, role_key)

def require_team_leader_role(request: Request, required_role: str) -> RedirectResponse | None:
    return None

def require_email(email: str) -> str:
    return web.require_email(email)

def require_date_range(period_start: date, period_end: date) -> None:
    web.require_date_range(period_start, period_end)

async def save_profile_image_upload(account_id: int, upload: UploadFile) -> str:
    return await uploads_module.save_profile_image_upload(account_id, upload)

def remove_profile_image_file(relative_path: str | None) -> None:
    uploads_module.remove_profile_image_file(relative_path)

def safe_portal_path(role_key: str, section: str, message: str = "", error: str = "", **extra_params: str) -> str:
    return portal_dependencies.safe_portal_path(role_key, section, message=message, error=error, **extra_params)

def path_with_query(path: str, **params: str) -> str:
    return web.path_with_query(path, **params)

def positive_int(value: str | None, default: int = 1, maximum: int = 50) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        return default
    return max(1, min(parsed, maximum))

def portal_filters(request: Request) -> dict:
    return {
        "q": request.query_params.get("q", "").strip(),
        "status": request.query_params.get("status", "").strip(),
        "type": request.query_params.get("type", "").strip(),
        "sort": request.query_params.get("sort", "").strip(),
        "page": positive_int(request.query_params.get("page")),
    }

def paged(items: list[dict], total: int, page: int, page_size: int = 10, **filters: str) -> dict:
    return {
        "items": items,
        "pagination": data.pagination_meta(total, page, page_size),
        "filters": filters,
    }

def product_page(request: Request, page_size: int = 12, active_only: bool = False) -> dict:
    filters = portal_filters(request)
    items = data.list_products(
        q=filters["q"],
        category=filters["type"],
        page=filters["page"],
        page_size=page_size,
        sort=filters["sort"],
        active_only=active_only,
    )
    total = data.count_products(q=filters["q"], category=filters["type"], active_only=active_only)
    return paged(items, total, filters["page"], page_size, q=filters["q"], type=filters["type"], sort=filters["sort"])

def notifications_context(request: Request, page_size: int = 15) -> dict:
    account_id = session_account_id(request)
    role_key = str(request.path_params.get("role_key") or request.session.get("role_key") or "inventory")
    requested_status = request.query_params.get("status", "").strip().lower()
    status = requested_status if requested_status in {"unread", "read"} else ""
    requested_category = request.query_params.get("type", "").strip().lower()
    category_values = {value for value, _label in NOTIFICATION_CATEGORIES}
    category = requested_category if requested_category in category_values else ""
    page_number = positive_int(request.query_params.get("page"))
    items = data.list_notification_history(
        account_id,
        status=status,
        category=category,
        page=page_number,
        page_size=page_size,
    )
    total = data.count_notification_history(account_id, status=status, category=category)
    return {
        "notifications_page": paged(
            items,
            total,
            page_number,
            page_size,
            status=status,
            type=category,
        ),
        "notification_categories": NOTIFICATION_CATEGORIES,
    }

def portal_nav_for_request(role_key: str, request: Request) -> list[tuple[str, str, str]]:
    return portal_config.portal_nav_for(role_key, session_team_leader_role(request))

def portal_role_for_request(role_key: str, request: Request) -> dict:
    base = portal_config.roles.get(role_key) or portal_config.roles["inventory"]
    role = dict(base)
    account_name = request.session.get("account_name")
    account_email = request.session.get("account_email")
    if account_name:
        role["name"] = account_name
    if account_email:
        role["email"] = account_email
    role["profile_image_path"] = request.session.get("profile_image_path") or ""
    role["profile_image_position_x"] = request.session.get("profile_image_position_x", 50)
    role["profile_image_position_y"] = request.session.get("profile_image_position_y", 50)
    role["profile_image_scale"] = request.session.get("profile_image_scale", 1)
    role["label"] = "Inventory Portal"
    role["team_leader_role"] = "inventory"
    return role

def portal_section_context(role_key: str, section: str, request: Request) -> dict:
    loader = PORTAL_SECTION_LOADERS.get((role_key, section)) or PORTAL_SECTION_LOADERS.get(("inventory", section))
    if not loader:
        raise HTTPException(status_code=404)
    context = loader(request)
    products = context.get("products", [])
    if products:
        selected_product = products[0]
        requested_product_id = request.query_params.get("product_id")
        if requested_product_id:
            try:
                product_id = int(requested_product_id)
            except ValueError:
                product_id = None
            selected_product = next(
                (product for product in products if product["product_id"] == product_id),
                selected_product,
            )
        context["selected_product"] = selected_product
    return context

@router.get("/portal")
async def portal_root(request: Request):
    return redirect_to("/portal/inventory/dashboard")

@router.get("/portal/{role_key}")
async def portal_default(request: Request, role_key: str):
    guard = require_portal_session(request, role_key)
    if guard:
        return guard
    return redirect_to(f"/portal/{role_key}/dashboard")

@router.get("/portal/{role_key}/{section}")
async def portal(request: Request, role_key: str, section: str, message: str = "", error: str = ""):
    guard = require_portal_session(request, role_key)
    if guard:
        return guard

    nav = portal_nav_for_request(role_key, request)
    nav_sections = {item[0]: item for item in nav}
    secondary_section = portal_config.portal_secondary_sections.get(role_key, {}).get(section)
    if section not in nav_sections and secondary_section is None:
        raise HTTPException(status_code=404)

    section_title = nav_sections[section][1] if section in nav_sections else (secondary_section[0] if secondary_section else section.title())

    context = {
        "request": request,
        "role_key": role_key,
        "portal_css_key": "inventory",
        "portal_body_roles": "role-team-leader leader-role-inventory",
        "role": portal_role_for_request(role_key, request),
        "nav": nav,
        "section": section,
        "section_title": section_title,
        "message": message,
        "error": error,
        "unread_notifications": data.unread_notification_count(role_key, request.session.get("account_id")),
    }
    context.update(portal_section_context(role_key, section, request))
    template_name = PORTAL_TEMPLATES.get(role_key, "portals/inventory.html")
    return templates().TemplateResponse(request, template_name, context)

@router.post("/portal/{role_key}/notifications/read")
async def portal_notifications_read(request: Request, role_key: str):
    guard = require_portal_session(request, role_key)
    if guard:
        return guard
    data.mark_notifications_read(role_key, request.session.get("account_id"))
    section = request.query_params.get("section") or "dashboard"
    return redirect_to(safe_portal_path(role_key, section))

@router.post("/portal/{role_key}/notifications/{notification_id}/open")
async def portal_notification_open(request: Request, role_key: str, notification_id: int):
    guard = require_portal_session(request, role_key)
    if guard:
        return guard
    notification = data.mark_notification_read(session_account_id(request), notification_id)
    if not notification:
        raise HTTPException(status_code=404)
    target_url = notification.get("target_url") or f"/portal/{role_key}/dashboard"
    return redirect_to(target_url)

@router.post("/portal/{role_key}/profile/picture")
async def portal_profile_picture(
    request: Request,
    role_key: str,
    profile_picture: UploadFile = File(...),
    profile_image_position_x: str = Form("50"),
    profile_image_position_y: str = Form("50"),
    profile_image_scale: str = Form("1"),
):
    guard = require_portal_session(request, role_key)
    if guard:
        return guard
    account_id = session_account_id(request)
    if account_id is None:
        return redirect_to(safe_portal_path(role_key, "profile", error="Your session expired. Please sign in again."))
    previous_path = request.session.get("profile_image_path")
    saved_path = None
    try:
        saved_path = await save_profile_image_upload(account_id, profile_picture)
        account = data.update_account_profile_image(
            account_id,
            saved_path,
            position_x=profile_image_position_x,
            position_y=profile_image_position_y,
            scale=profile_image_scale,
        )
    except ValueError as exc:
        remove_profile_image_file(saved_path)
        return redirect_to(safe_portal_path(role_key, "profile", error=str(exc)))
    request.session["profile_image_path"] = account.get("profile_image_path") or ""
    request.session["profile_image_position_x"] = account.get("profile_image_position_x", 50)
    request.session["profile_image_position_y"] = account.get("profile_image_position_y", 50)
    request.session["profile_image_scale"] = account.get("profile_image_scale", 1)
    remove_profile_image_file(previous_path if previous_path != saved_path else None)
    return redirect_to(safe_portal_path(role_key, "profile", message="Profile picture updated."))

@router.post("/portal/{role_key}/profile/picture/remove")
async def portal_profile_picture_remove(request: Request, role_key: str):
    guard = require_portal_session(request, role_key)
    if guard:
        return guard
    account_id = session_account_id(request)
    if account_id is None:
        return redirect_to(safe_portal_path(role_key, "profile", error="Your session expired. Please sign in again."))
    previous_path = request.session.get("profile_image_path")
    try:
        data.update_account_profile_image(account_id, None)
    except ValueError as exc:
        return redirect_to(safe_portal_path(role_key, "profile", error=str(exc)))
    request.session["profile_image_path"] = ""
    request.session["profile_image_position_x"] = 50
    request.session["profile_image_position_y"] = 50
    request.session["profile_image_scale"] = 1
    remove_profile_image_file(previous_path)
    return redirect_to(safe_portal_path(role_key, "profile", message="Profile picture removed."))

@router.post("/portal/{role_key}/profile/password")
async def portal_profile_password(
    request: Request,
    role_key: str,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    guard = require_portal_session(request, role_key)
    if guard:
        return guard
    account_id = session_account_id(request)
    if account_id is None:
        return redirect_to(safe_portal_path(role_key, "profile", error="Your session expired. Please sign in again."))
    try:
        if new_password != confirm_password:
            raise ValueError("New password and confirmation do not match.")
        data.change_account_password_direct(account_id, current_password, new_password)
    except ValueError as exc:
        return redirect_to(safe_portal_path(role_key, "profile", error=str(exc)))
    return redirect_to(safe_portal_path(role_key, "profile", message="Password updated successfully."))
