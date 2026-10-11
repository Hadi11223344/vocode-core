"""
Voice Platform — Auth API Routes
==================================

Endpoints for Google OAuth2 authentication.

Routes:
    POST /api/auth/google  — Exchange Google ID token for platform JWT
    GET  /api/auth/me      — Get current user's profile
    PUT  /api/auth/profile  — Update current user's profile
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status  # Routing + error handling
from pydantic import BaseModel  # Request/response schema validation
from sqlalchemy import func, select  # Database query building
from sqlalchemy.ext.asyncio import AsyncSession  # Async DB session

from voice_platform.auth import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    verify_google_token,
)
from voice_platform.config import settings
from voice_platform.database import User, get_db  # User model + DB dependency
from voice_platform.middleware.auth_middleware import get_current_user  # Auth dependency
from voice_platform.rate_limit import limiter

# Create the router with prefix and tag (groups endpoints in Swagger docs)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# ── Request/Response Schemas ───────────────────────────────────────────
# Pydantic models define the shape of request bodies and responses.
# FastAPI uses these for automatic validation and documentation.

class GoogleAuthRequest(BaseModel):
    """Request body for Google sign-in."""
    id_token: str  # The JWT from Google's Sign-In SDK


class AuthResponse(BaseModel):
    """Response after successful authentication."""
    access_token: str  # Our platform's JWT
    refresh_token: str  # Long-lived token for session persistence
    token_type: str = "bearer"  # Always "bearer" per OAuth2 convention
    user: dict  # User profile data


class DevLoginRequest(BaseModel):
    """Request body for dev/testing login (no Google required)."""
    email: str = "dev@voia.local"
    name: str = "Dev User"


class ProfileUpdateRequest(BaseModel):
    """Request body for updating user profile."""
    name: str | None = None  # New display name (optional)


# ── Routes ─────────────────────────────────────────────────────────────

@router.post("/dev-login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def dev_login(
    request: Request,
    body: DevLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Development-only login endpoint — bypasses Google OAuth.
    
    Creates or finds a user by email and returns a JWT immediately.
    This is only for local development and testing.
    DO NOT use in production.
    """
    # Safety: explicit opt-in only.
    if not settings.allow_dev_login:
        raise HTTPException(
            status_code=403,
            detail="Dev login disabled. Set ALLOW_DEV_LOGIN=true for local development.",
        )
    
    # Find or create user
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        # Check if first user → admin
        count_result = await db.execute(select(func.count(User.id)))
        user_count = count_result.scalar()
        role = "admin" if user_count == 0 else "user"
        
        user = User(
            google_id=f"dev-{body.email}",
            email=body.email,
            name=body.name,
            picture_url=None,
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    access_token = create_access_token(
        user_id=user.id,  # type: ignore[arg-type]
        email=user.email,  # type: ignore[arg-type]
        role=user.role,  # type: ignore[arg-type]
    )
    refresh_token = create_refresh_token(user_id=user.id)  # type: ignore[arg-type]

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user.to_dict(),
    )


@router.post("/google", response_model=AuthResponse)
@limiter.limit("10/minute")
async def google_auth(
    request: Request,
    body: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange a Google OAuth2 ID token for a platform access token.
    
    This is the main authentication endpoint. The frontend calls this
    after the user signs in with Google.
    
    Flow:
        1. Verify the Google ID token (signature, expiry, audience)
        2. Extract user info (email, name, picture, google_id)
        3. Check if user already exists in our database
        4. If new user: create account (first user gets admin role)
        5. If existing user: update name/picture if changed
        6. Generate our JWT and return it
    
    Args:
        body: Contains the Google ID token
        db: Database session (injected by FastAPI)
        
    Returns:
        AuthResponse with our JWT and user profile
        
    Raises:
        400: If Google token is invalid or email not verified
    """
    # Step 1: Verify the Google token with Google's servers
    try:
        google_info = verify_google_token(body.id_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    # Step 2: Extract user info from the verified token
    google_id = google_info["sub"]         # Google's unique user ID
    email = google_info.get("email", "")   # User's email
    name = google_info.get("name", email)  # Display name (fallback to email)
    picture = google_info.get("picture")   # Profile picture URL

    # Reject tokens that do not carry a verified email identity.
    # This prevents creating local accounts from unverified Google identities.
    if not email or not google_info.get("email_verified", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account email must be verified",
        )
    
    # Step 3: Check if this Google user already has an account
    result = await db.execute(
        select(User).where(User.google_id == google_id)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        # Step 4a: New user — create their account
        
        # Check if this is the very first user (they become admin)
        count_result = await db.execute(select(func.count(User.id)))
        user_count = count_result.scalar()
        role = "admin" if user_count == 0 else "user"  # First user = admin
        
        # Create the user record
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            picture_url=picture,
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)  # Reload to get the auto-generated id

        # Seed demo data for first-time users (FYP demo ready)
        from voice_platform.seed import seed_demo_data
        await seed_demo_data(user.id, db)

    else:
        # Step 4b: Existing user — update their info if it changed
        # (Google users can change their name/picture)
        user.name = name  # type: ignore[assignment]
        user.picture_url = picture  # type: ignore[assignment]
        await db.commit()
    
    # Step 5: Generate our platform's JWT
    access_token = create_access_token(
        user_id=user.id,  # type: ignore[arg-type]
        email=user.email,  # type: ignore[arg-type]
        role=user.role,  # type: ignore[arg-type]
    )
    refresh_token = create_refresh_token(user_id=user.id)  # type: ignore[arg-type]

    # Step 6: Return the token and user profile
    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user.to_dict(),
    )


@router.get("/me")
@limiter.limit("60/minute")
async def get_profile(
    request: Request,
    user: User = Depends(get_current_user),
):
    """
    Get the current authenticated user's profile.
    
    Requires a valid Bearer token in the Authorization header.
    The get_current_user dependency handles token verification.
    
    Returns:
        User profile dictionary
    """
    return {"user": user.to_dict()}


@router.post("/refresh")
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange a refresh token for a new access token.

    The frontend calls this when the access token is about to expire
    or has expired, using the long-lived refresh token obtained at login.
    """
    refresh = body.get("refresh_token")
    if not refresh:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="refresh_token required")

    try:
        payload = decode_refresh_token(refresh)
        user_id = int(payload["sub"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token(
        user_id=user.id,  # type: ignore[arg-type]
        email=user.email,  # type: ignore[arg-type]
        role=user.role,  # type: ignore[arg-type]
    )
    new_refresh_token = create_refresh_token(user_id=user.id)  # type: ignore[arg-type]

    return AuthResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        user=user.to_dict(),
    )


@router.put("/profile")
@limiter.limit("30/minute")
async def update_profile(
    request: Request,
    body: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update the current user's profile.
    
    Currently supports updating the display name.
    Can be extended to support preferences, notification settings, etc.
    """
    if body.name is not None:
        user.name = body.name  # type: ignore[assignment]
    
    await db.commit()
    await db.refresh(user)
    return {"user": user.to_dict()}
