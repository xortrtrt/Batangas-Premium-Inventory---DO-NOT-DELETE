from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import web
from app.audit_context import begin_audit_context, end_audit_context
from app.portals import inventory as inventory_portal
from app.portals import shared as shared_portal
from app.routers import auth, system
from app.security_controls import csrf_token, enforce_csrf
from app.web_sessions import DatabaseSessionMiddleware

from contextlib import asynccontextmanager

BASE_DIR = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    from starlette.concurrency import run_in_threadpool
    from tools.init_db import init_database
    from app import database
    try:
        await run_in_threadpool(init_database)
    except Exception:
        logging.getLogger("uvicorn.error").exception("Inventory database initialization failed; startup refused.")
        raise
    try:
        yield
    finally:
        if database.pool is not None:
            database.pool.closeall()
            database.pool = None

class CachedStaticFiles(StaticFiles):
    """Give versioned local dependencies a long-lived browser cache."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        normalized_path = path.lstrip("/\\").replace("\\", "/")
        if response.status_code == 200 and normalized_path.startswith(("fonts/", "vendor/")):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

def create_app() -> FastAPI:
    application = FastAPI(
        title="MeatTrack Inventory Portal",
        version="1.0.0",
        dependencies=[Depends(enforce_csrf)],
        lifespan=lifespan,
    )
    application.add_middleware(DatabaseSessionMiddleware)
    application.mount(
        "/static",
        CachedStaticFiles(directory=BASE_DIR / "static"),
        name="static",
    )
    web.configure_templates(csrf_token)

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        audit_tokens = begin_audit_context(request)
        try:
            response = await call_next(request)
        finally:
            end_audit_context(audit_tokens)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; font-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return response

    @application.exception_handler(404)
    async def not_found(request: Request, exc: HTTPException):
        accept = request.headers.get("accept", "")
        if request.url.path.startswith("/api/") or (
            "application/json" in accept and "text/html" not in accept
        ):
            return JSONResponse(
                {"detail": getattr(exc, "detail", "Not Found")},
                status_code=404,
            )
        return web.templates.TemplateResponse(
            request,
            "404.html",
            {"request": request},
            status_code=404,
        )

    # Register routers
    for route_module in (system, auth):
        application.include_router(route_module.router)
    for portal_router in (inventory_portal.router, shared_portal.router):
        application.include_router(portal_router)

    return application
