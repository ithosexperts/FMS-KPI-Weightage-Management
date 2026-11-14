"""
One Portal SSO Authentication Router for KPI Weightage Management.
Handles /auth/launch (ticket consumer) and /logout.
"""
from __future__ import annotations

import html
import logging
from typing import Optional
from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.sso_session import (
    SESSION_COOKIE,
    SsoError,
    decode_ticket,
    make_session_cookie_value,
    replay_store,
)
from app.config import settings

logger = logging.getLogger("kpi_weightage.auth")
router = APIRouter(tags=["SSO Authentication"])


def _error_page(message: str, status_code: int = 401) -> HTMLResponse:
    body = (
        "<!DOCTYPE html><html><head><title>SSO Login Error</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<style>body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 40px; background: #f8fafc; color: #1e293b; }"
        ".card { max-width: 520px; margin: 40px auto; background: white; padding: 32px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; }"
        "h2 { color: #dc2626; margin-top: 0; }"
        "a { color: #0284c7; text-decoration: none; font-weight: 600; }"
        "</style></head><body>"
        "<div class='card'>"
        "<h2>Unable to sign in via One Portal SSO</h2>"
        f"<p>{html.escape(message)}</p>"
        "<p style='color: #64748b; font-size: 14px;'>Please close this tab and reopen KPI Weightage Management from One Portal.</p>"
        "<p style='margin-top: 24px;'><a href='/'>&larr; Continue as Guest</a></p>"
        "</div></body></html>"
    )
    return HTMLResponse(body, status_code=status_code)


@router.post("/auth/launch")
async def launch_from_one_portal(
    request: Request,
    ticket: str = Form(...),
    next: Optional[str] = Form("/"),
):
    """
    Receives an SSO launch ticket from One Portal via POST form submission.
    Decodes identity, creates a signed session cookie, and redirects into the app.
    """
    try:
        claims = decode_ticket(ticket.strip())
    except SsoError as exc:
        logger.warning(f"SSO Ticket verification failed: {exc}")
        return _error_page(str(exc), exc.status_code)
    except Exception as exc:
        logger.exception("Unexpected error decoding launch ticket: %s", exc)
        return _error_page("Invalid launch ticket.", 400)

    jti = str(claims.get("jti") or "")
    exp = int(claims.get("exp") or 0)
    if jti and not replay_store.consume(jti, exp):
        return _error_page("This launch ticket has already been used.", 401)

    employee_code = str(claims.get("employee_code") or claims.get("sub") or "").strip()
    if not employee_code:
        return _error_page("Ticket has no employee code.", 400)

    full_name = str(claims.get("full_name") or claims.get("name") or employee_code).strip()
    role_name = str(claims.get("role_name") or "").strip()
    target_database = str(claims.get("target_database") or settings.api_database or "OperationsDB").strip()
    portal_session_id = str(claims.get("portal_session_id") or "").strip()

    # Determine numeric role_id:
    role_id_claim = claims.get("role_id")
    if role_id_claim is not None and str(role_id_claim).isdigit():
        role_id = int(role_id_claim)
    elif "super" in role_name.lower() or "admin" in role_name.lower():
        role_id = 1
    elif "approver" in role_name.lower() or "hr" in role_name.lower() or "management" in role_name.lower():
        role_id = 2
    else:
        role_id = 3

    ttl = max(600, int(settings.sso_session_minutes) * 60)
    session_data = {
        "employee_code": employee_code,
        "full_name": full_name,
        "role_id": role_id,
        "role_name": role_name or ("Super Admin" if role_id == 1 else "Approver"),
        "target_database": target_database,
        "portal_session_id": portal_session_id,
    }
    cookie_value = make_session_cookie_value(session_data, ttl_seconds=ttl)

    target_next = next.strip() if next and next.strip().startswith("/") else "/"
    response = RedirectResponse(url=target_next, status_code=status.HTTP_303_SEE_OTHER)

    same_site = settings.sso_cookie_samesite.lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "none"

    is_secure = (same_site == "none") or settings.is_production

    # Set standard cross-site cookie
    response.set_cookie(
        key=SESSION_COOKIE,
        value=cookie_value,
        max_age=ttl,
        httponly=True,
        secure=is_secure,
        samesite=same_site,
        path="/",
    )

    # Set partitioned cookie for modern browsers (CHIPS) inside One Portal iframe
    if is_secure and same_site == "none":
        response.headers.append(
            "Set-Cookie",
            f"{SESSION_COOKIE}={cookie_value}; Max-Age={ttl}; Path=/; HttpOnly; Secure; SameSite=None; Partitioned",
        )

    logger.info(f"SSO login successful: {full_name} ({employee_code}), Role {role_id}, DB {target_database}")
    return response


@router.get("/logout")
@router.get("/auth/logout")
async def logout(request: Request):
    """Clears the One Portal SSO session and returns to default Guest view."""
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    # Also delete partitioned cookie
    response.headers.append(
        "Set-Cookie",
        f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=None; Partitioned",
    )
    return response
