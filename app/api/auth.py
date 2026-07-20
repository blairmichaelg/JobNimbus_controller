import jwt
import datetime
from fastapi import HTTPException, Depends, Cookie, Header
from app.config import get_settings

ALGORITHM = "HS256"

def create_access_token(
    role: str,
    rep_name: str | None = None,
    rep_id: str | None = None,
) -> str:
    settings = get_settings()
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=12)
    to_encode: dict = {"sub": role, "role": role, "exp": expire}
    if rep_name:
        to_encode["rep_name"] = rep_name
    if rep_id:
        to_encode["rep_id"] = rep_id
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> dict:
    """
    Decode a JWT and return the full payload dict.
    Raises HTTPException 401 on invalid/expired token.
    Returns at minimum: {"role": str}
    May also contain: {"rep_name": str, "rep_id": str}
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        # Support both legacy "sub" claim and new "role" claim
        role = payload.get("role") or payload.get("sub")
        if role is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        payload["role"] = role
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

async def get_current_role(
    auth_token: str | None = Cookie(None),
    x_internal_token: str | None = Header(None, alias="x-internal-token")
) -> str:
    """Returns only the role string from the JWT. Used by all role-check dependencies."""
    # Support both cookie and header for API access
    token = x_internal_token or auth_token
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    return payload["role"]

async def get_current_claims(
    auth_token: str | None = Cookie(None),
    x_internal_token: str | None = Header(None, alias="x-internal-token")
) -> dict:
    """
    Returns the full decoded JWT payload dict.
    Used by routes that need rep_name or rep_id in addition to the role.
    """
    token = x_internal_token or auth_token
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return decode_token(token)

async def verify_admin(role: str = Depends(get_current_role)):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized for admin access")
    return role

async def verify_accounting(role: str = Depends(get_current_role)):
    # Admin can access accounting
    if role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Not authorized for accounting access")
    return role

async def verify_operations(role: str = Depends(get_current_role)):
    # Admin can access ops
    if role not in ["admin", "operations"]:
        raise HTTPException(status_code=403, detail="Not authorized for operations access")
    return role

async def verify_field(role: str = Depends(get_current_role)):
    if role not in ["admin", "field"]:
        raise HTTPException(status_code=403, detail="Not authorized for field access")
    return role
