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
    if pin == settings.admin_pin:
        role = "admin"
    elif pin == settings.accounting_pin:
        role = "accounting"
    elif pin == settings.operations_pin:
        role = "operations"
    elif pin == settings.field_pin:
        role = "field"

    if not role:
        # Brute-force delay: 10,000 attempts × 1s ≈ 2.7 hours via Ngrok
        import asyncio
        await asyncio.sleep(1)
        # Redirect back to login page with inline error flag
        safe_redirect = redirect_url if redirect_url.startswith("/") else "/"
        return RedirectResponse(
            url=f"/login?redirect_url={safe_redirect}&error=1",
            status_code=303,
        )

    token = create_access_token(role)

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
