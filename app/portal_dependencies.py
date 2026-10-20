from __future__ import annotations

from fastapi import Request
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from app.business_time import business_now
from app.repositories import accounts
from app.web import path_with_query, redirect_to

def session_account_id(request: Request) -> int | None:
    value = request.session.get("account_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

def session_team_leader_role(request: Request) -> str | None:
    return "inventory"

def safe_portal_path(
    role_key: str,
    section: str,
    message: str = "",
    error: str = "",
    **extra_params: str,
) -> str:
    params = {key: value for key, value in extra_params.items() if value}
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    return path_with_query(f"/portal/inventory/{section}", **params)

def require_team_leader_role(request: Request, required_role: str) -> RedirectResponse | None:
    return None

def require_portal_session(request: Request, role_key: str = "inventory") -> RedirectResponse | None:
    if role_key not in {"inventory", "team-leader", "owner"}:
        raise HTTPException(status_code=404)
    expires_at = request.session.get("portal_expires_at")
    try:
        expired = int(str(expires_at)) <= int(business_now().timestamp())
    except (TypeError, ValueError):
        expired = True
    account_id = session_account_id(request)
    if not expired and account_id:
        account = accounts.active_session_account(account_id)
        if account:
            request.session["profile_image_path"] = account.get("profile_image_path") or ""
            request.session["profile_image_position_x"] = account.get("profile_image_position_x", 50)
            request.session["profile_image_position_y"] = account.get("profile_image_position_y", 50)
            request.session["profile_image_scale"] = account.get("profile_image_scale", 1)
            return None
    if request.session.get("account_id"):
        request.session.clear()
    return redirect_to(path_with_query("/login", error="Please sign in to access the inventory system."))

__all__ = [
    "require_portal_session",
    "require_team_leader_role",
    "safe_portal_path",
    "session_account_id",
    "session_team_leader_role",
]
