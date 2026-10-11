"""
Voice Platform — Auth Middleware
=================================

FastAPI dependencies for protecting API routes with JWT authentication.

Usage in route handlers:
    from voice_platform.middleware.auth_middleware import get_current_user, require_admin
    
    @router.get("/protected")
    async def protected_route(user: User = Depends(get_current_user)):
        # user is guaranteed to be authenticated here
        return {"message": f"Hello {user.name}"}
    
    @router.get("/admin-only")
    async def admin_route(user: User = Depends(require_admin)):
        # user is guaranteed to be an admin here
        return {"settings": ...}
"""

from fastapi import Depends, HTTPException, WebSocket, status  # HTTP error handling
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # Bearer token extraction
from sqlalchemy import select  # Database queries
from sqlalchemy.ext.asyncio import AsyncSession  # Async DB session type

from voice_platform.auth import decode_access_token  # Our JWT decoder
from voice_platform.config import settings
from voice_platform.database import User, get_db  # User model + DB dependency

# HTTPBearer extracts the token from "Authorization: Bearer <token>" header
# auto_error=False means we handle missing tokens ourselves → return 401 instead of 403
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency that authenticates the current user.
    
    This is the primary authentication mechanism. It:
    1. Extracts the Bearer token from the Authorization header
    2. Decodes and validates our JWT (checks signature + expiration)
    3. Looks up the user in the database by the ID in the token
    4. Returns the User ORM object
    
    If any step fails, it raises HTTP 401 Unauthorized.
    
    Args:
        credentials: Automatically extracted from Authorization header by FastAPI
        db: Database session provided by FastAPI's dependency injection
        
    Returns:
        User: The authenticated user's database record
        
    Raises:
        HTTPException(401): If token is missing, invalid, expired, or user not found
    """
    # Step 1: Get the raw token string
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    
    # Step 2: Decode and verify the JWT
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])  # 'sub' claim contains user's DB id
    except (ValueError, KeyError) as e:
        # Token is invalid, expired, or missing required claims
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},  # RFC 7235 compliance
        )
    
    # Step 3: Look up the user in the database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    # Step 4: Ensure user exists (they might have been deleted after token was issued)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """
    FastAPI dependency that requires the user to have admin privileges.
    
    Chains with get_current_user — first authenticates, then checks role.
    
    Usage:
        @router.put("/settings")
        async def update_settings(user: User = Depends(require_admin)):
            ...  # Only admins reach here
    
    Args:
        user: The authenticated user (from get_current_user dependency)
        
    Returns:
        User: The authenticated admin user
        
    Raises:
        HTTPException(403): If user is not an admin
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required for this action",
        )
    return user


async def get_current_user_ws(websocket: WebSocket) -> User:
    """
    Authenticate a WebSocket connection.

    Preferred token transport (in order):
    1) Authorization header: Bearer <token>
    2) Sec-WebSocket-Protocol: bearer,<token>
    3) Query parameter: ?token=<token> (optional legacy fallback)
    
    Usage:
        @router.websocket("/ws")
        async def ws(websocket: WebSocket):
            user = await get_current_user_ws(websocket)
    
    Query-param auth is disabled by default and can be explicitly enabled via
    ALLOW_WS_QUERY_TOKEN_AUTH for backward compatibility.
    """
    from voice_platform.database import async_session as session_factory

    token = _extract_ws_token(
        websocket,
        allow_query_fallback=settings.allow_ws_query_token_auth,
    )
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid token")
    
    async with session_factory() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def _extract_ws_token(websocket: WebSocket, allow_query_fallback: bool = False) -> str | None:
    """Extract auth token from websocket request metadata."""
    headers = getattr(websocket, "headers", {}) or {}
    query_params = getattr(websocket, "query_params", {}) or {}

    auth_header = headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    protocol_header = headers.get("sec-websocket-protocol") or ""
    if protocol_header:
        parts = [p.strip() for p in protocol_header.split(",") if p.strip()]
        if len(parts) >= 2 and parts[0].lower() == "bearer" and parts[1]:
            return parts[1]

    if allow_query_fallback:
        # Legacy fallback for existing clients; avoid for new code because URLs are
        # more likely to be logged by intermediaries.
        return query_params.get("token")
    return None


def _wants_bearer_subprotocol(websocket: WebSocket) -> bool:
    """Whether the client offered "bearer" as a websocket subprotocol."""
    headers = getattr(websocket, "headers", {}) or {}
    protocol_header = headers.get("sec-websocket-protocol") or ""
    parts = [p.strip().lower() for p in protocol_header.split(",") if p.strip()]
    return bool(parts) and parts[0] == "bearer"
