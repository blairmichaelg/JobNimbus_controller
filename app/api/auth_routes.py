"""
Auth Router: PIN-to-JWT

Issues HttpOnly cookies upon successful PIN validation.
Replaces the old token-based backdoors.
"""

from fastapi import APIRouter, Form, Response, HTTPException
from fastapi.responses import RedirectResponse
from app.config import get_settings
from app.api.auth import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login")
async def login(response: Response, pin: str = Form(...), redirect_url: str = Form("/")):
    settings = get_settings()
    
    # Map PINs to roles
    role = None
    if pin == settings.admin_pin:
        role = "admin"
    elif pin == settings.accounting_pin:
        role = "accounting"
    elif hasattr(settings, "operations_pin") and pin == settings.operations_pin:
        role = "operations"
    elif hasattr(settings, "field_pin") and pin == settings.field_pin:
        role = "field"
        
    # Default fallback if the env vars are missing
    if not role:
        if pin == "9999": role = "admin"
        elif pin == "8888": role = "accounting"
        elif pin == "7777": role = "operations"
        elif pin == "1111": role = "field"

    if not role:
        # If it's an API request, return 401
        # If it's a browser form submission, we might want to redirect,
        # but 401 is standard. We'll raise 401.
        raise HTTPException(status_code=401, detail="Invalid PIN")

    token = create_access_token(role)
    
    # We want to redirect back to the page that requested login
    res = RedirectResponse(url=redirect_url, status_code=303)
    res.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=True if settings.app_env == "prod" else False,
        samesite="lax",
        max_age=12 * 3600
    )
    return res

@router.get("/logout")
async def logout():
    res = RedirectResponse(url="/login", status_code=303)
    res.delete_cookie("auth_token")
    return res
