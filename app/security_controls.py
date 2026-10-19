from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status

from app.config import APP_ENV, AUTH_RATE_LIMIT_ENABLED, CSRF_PROTECTION_ENABLED, RATE_LIMIT_HASH_KEY
from app.database import get_transaction_cursor

def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

class RateLimitExceeded(ValueError):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))

def _rate_subject(value: str) -> str:
    return hmac.new(
        RATE_LIMIT_HASH_KEY.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

def csrf_token(request: Request) -> str:
    if not CSRF_PROTECTION_ENABLED:
        return ""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token

async def enforce_csrf(request: Request) -> None:
    if not CSRF_PROTECTION_ENABLED or request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return

    supplied = request.headers.get("x-csrf-token", "")
    if not supplied:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("application/x-www-form-urlencoded") or content_type.startswith("multipart/form-data"):
            form = await request.form()
            supplied = str(form.get("csrf_token", ""))
    expected = request.session.get("csrf_token", "")
    if not expected or not supplied or not secrets.compare_digest(str(expected), supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing CSRF token.")

def _failure_count(event_type: str, subject_key: str, interval: str) -> int:
    with get_transaction_cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS count
            FROM security_events
            WHERE event_type = %s AND subject_key = %s AND succeeded = false
              AND created_at >= now() - %s::interval
            """,
            (event_type, subject_key, interval),
        )
        return int(cur.fetchone()["count"])

def enforce_limit(event_type: str, subject_key: str, limit: int, interval: str, message: str) -> None:
    if AUTH_RATE_LIMIT_ENABLED and _failure_count(event_type, subject_key, interval) >= limit:
        raise ValueError(message)

def record_event(event_type: str, subject_key: str, *, succeeded: bool = False) -> None:
    if not AUTH_RATE_LIMIT_ENABLED:
        return
    with get_transaction_cursor() as cur:
        if succeeded:
            cur.execute(
                "DELETE FROM security_events WHERE event_type = %s AND subject_key = %s AND succeeded = false",
                (event_type, subject_key),
            )
        cur.execute(
            "INSERT INTO security_events (event_type, subject_key, succeeded) VALUES (%s, %s, %s)",
            (event_type, subject_key, succeeded),
        )

def enforce_password_login(request: Request, email: str) -> None:
    enforce_limit("password_login", f"email:{email.lower()}", 10, "15 minutes", "Too many failed sign-in attempts. Try again in 15 minutes.")

def record_password_login(request: Request, email: str, succeeded: bool) -> None:
    record_event("password_login", f"email:{email.lower()}", succeeded=succeeded)

def enforce_otp_attempt(account_id: int) -> None:
    pass

def enforce_otp_resend(account_id: int) -> None:
    pass

def record_otp_resend(account_id: int) -> None:
    pass
