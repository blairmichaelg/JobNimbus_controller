"""
Auth Router: PIN-to-JWT

Issues HttpOnly cookies upon successful PIN validation.
Replaces the old token-based backdoors.
"""

from fastapi import APIRouter, Form, Response
from fastapi.responses import RedirectResponse
from app.config import get_settings
from app.api.auth import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(response: Response, pin: str = Form(...), redirect_url: str = Form("/")):
    settings = get_settings()

    # Map PINs to roles — .env is the ONLY source of truth.
    # No hardcoded fallbacks. If a PIN env var is missing, Pydantic
    # crashes at startup, which is the correct behavior.
    role = None
    rep_name: str | None = None
    rep_id: str | None = None

    if pin == settings.admin_pin:
        role = "admin"
    elif pin == settings.accounting_pin:
        role = "accounting"
    elif pin == settings.operations_pin:
        role = "operations"
    else:
        # Dynamic field rep lookup — field_reps table is the sole
        # source of truth for field identity (Phase 9).
        # Static field_pin in config.py is RETIRED from auth.
        from app.core.database import get_field_rep_by_pin
        rep = get_field_rep_by_pin(pin)
        if rep:
            role = "field"
            rep_name = rep["name"]
            rep_id = rep["id"]

    if not role:
        # Brute-force delay: 10,000 attempts x 1s ~= 2.7 hours via Ngrok
        import asyncio
        await asyncio.sleep(1)
        # Redirect back to login page with inline error flag
        safe_redirect = redirect_url if redirect_url.startswith("/") else "/"
        return RedirectResponse(
            url=f"/login?redirect_url={safe_redirect}&error=1",
            status_code=303,
        )

    token = create_access_token(
        role,
        rep_name=rep_name if role == "field" else None,
        rep_id=rep_id if role == "field" else None,
    )

    # Redirect to the page that originally requested authentication
    res = RedirectResponse(url=redirect_url, status_code=303)
    res.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=True if settings.app_env == "prod" else False,
        samesite="lax",
        max_age=12 * 3600,
    )
    return res


@router.get("/logout")
async def logout():
    res = RedirectResponse(url="/login", status_code=303)
    res.delete_cookie("auth_token")
    return res
