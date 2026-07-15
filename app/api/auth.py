import jwt
import datetime
from fastapi import HTTPException, Depends, Cookie, Header
from app.config import get_settings

ALGORITHM = "HS256"

def create_access_token(role: str) -> str:
    settings = get_settings()
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=12)
    to_encode = {"sub": role, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        role = payload.get("sub")
        if role is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        return role
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

async def get_current_role(
    auth_token: str | None = Cookie(None),
    x_internal_token: str | None = Header(None, alias="x-internal-token")
) -> str:
    # Support both cookie and header for API access
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
