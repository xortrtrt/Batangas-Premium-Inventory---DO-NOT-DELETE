from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import portal_config
from app import repositories as data
from app import web
from app.business_time import business_now
from app.config import CONSENT_VERSION
from app.security_controls import (
    enforce_password_login,
    record_password_login,
)
from app.web_sessions import rotate_session

PORTAL_SESSION_SECONDS = 7 * 24 * 60 * 60  # 7 days session for convenience
router = APIRouter()
templates = web.templates
redirect_to = web.redirect_to
path_with_query = web.path_with_query
require_email = web.require_email

def establish_portal_session(request: Request, account: dict) -> RedirectResponse:
    request.session.clear()
    request.session["account_id"] = account["account_id"]
    request.session["role_key"] = "inventory"
    request.session["team_leader_role"] = "inventory"
    request.session["account_name"] = account["name"]
    request.session["account_email"] = account["email"]
    request.session["profile_image_path"] = account.get("profile_image_path") or ""
    request.session["profile_image_position_x"] = account.get("profile_image_position_x", 50)
    request.session["profile_image_position_y"] = account.get("profile_image_position_y", 50)
    request.session["profile_image_scale"] = account.get("profile_image_scale", 1)
    request.session["portal_expires_at"] = int(business_now().timestamp()) + PORTAL_SESSION_SECONDS
    rotate_session(request)
    data.add_log(account["name"], "login", "Inventory Portal", actor_account_id=account["account_id"])
    return redirect_to("/portal/inventory/dashboard")

@router.get("/")
async def root():
    return redirect_to("/portal/inventory/dashboard")

@router.get("/login")
def login(request: Request, message: str = "", error: str = ""):
    from app.portal_dependencies import require_portal_session
    if request.session.get("account_id") and require_portal_session(request) is None:
        return redirect_to("/portal/inventory/dashboard")
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "roles": portal_config.roles,
            "message": message,
            "error": error,
            "consent_version": CONSENT_VERSION,
        },
    )

@router.post("/login")
def submit_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    consent: str = Form(""),
):
    try:
        email = require_email(email)
        enforce_password_login(request, email)
        if consent != "yes":
            raise ValueError("Please acknowledge the inventory activity notice to continue.")
        if len(password.strip()) < 4:
            raise ValueError("Password must be at least 4 characters.")
    except ValueError as exc:
        return redirect_to(path_with_query("/login", error=str(exc)))

    account = data.authenticate_account(email, password)
    if account is None:
        record_password_login(request, email, False)
        return redirect_to(path_with_query("/login", error="Invalid email or password."))
    record_password_login(request, email, True)

    data.record_user_consent(account["account_id"], CONSENT_VERSION, "password_login")
    return establish_portal_session(request, account)

@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return redirect_to(path_with_query("/login", message="You have been signed out."))

@router.get("/logout")
async def logout_get(request: Request):
    request.session.clear()
    return redirect_to(path_with_query("/login", message="You have been signed out."))
