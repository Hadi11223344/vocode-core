"""
Voice Platform — Authentication System
========================================

Handles Google OAuth2 authentication and JWT token management.

Flow:
    1. Frontend: User clicks "Sign in with Google"
    2. Frontend: Google JS SDK gives back an id_token (JWT signed by Google)
    3. Frontend: POST /api/auth/google  { "id_token": "eyJ..." }
    4. Backend:  This module verifies the id_token with Google's servers
    5. Backend:  Extracts user info (email, name, picture, google_id)
    6. Backend:  Creates or updates the user in our database
    7. Backend:  Generates our own JWT and returns it to frontend
    8. Frontend: Stores our JWT and sends it as Bearer token on all API calls

Dependencies:
    - google-auth: Verifies Google OAuth2 ID tokens
    - python-jose: Creates and verifies our own JWT tokens
"""

import os  # For reading environment variables
from datetime import datetime, timedelta, timezone  # For JWT expiration

from jose import JWTError, jwt  # JWT creation and verification
from loguru import logger  # Structured logging

from voice_platform.config import settings

# ── Configuration ──────────────────────────────────────────────────────
# Google OAuth client ID — used to verify that tokens came from our app
GOOGLE_CLIENT_ID = settings.google_client_id or ""

# FIX C-4: Warn loudly at module load if GOOGLE_CLIENT_ID is not set.
# Without it, verify_oauth2_token() skips the audience check, meaning
# ANY Google account token (from any app) would be accepted — a critical
# authentication bypass.
if not GOOGLE_CLIENT_ID:
    import warnings
    warnings.warn(
        "[SECURITY] GOOGLE_CLIENT_ID is not set. "
        "Google token verification cannot check the token audience, "
        "which allows ANY Google account token to authenticate. "
        "Set GOOGLE_CLIENT_ID in your .env file immediately.",
        stacklevel=2,
    )

# Secret key for signing our JWT tokens. May be replaced at startup with an
# ephemeral value when ALLOW_DEV_LOGIN is on and JWT_SECRET is unset/weak.
JWT_SECRET = settings.jwt_secret

# JWT algorithm — HS256 (symmetric HMAC)
JWT_ALGORITHM = "HS256"

# How long our access tokens are valid (short-lived)
TOKEN_EXPIRY_HOURS = 1  # 1 hour for access tokens

# Refresh tokens last much longer (30 days)
REFRESH_TOKEN_EXPIRY_DAYS = 30
REFRESH_TOKEN_SECRET = os.environ.get("REFRESH_TOKEN_SECRET", JWT_SECRET + "-refresh")


def verify_google_token(id_token: str) -> dict:
    """
    Verify a Google OAuth2 ID token and extract user information.
    
    This function contacts Google's token verification endpoint to ensure:
    1. The token was actually issued by Google
    2. The token was issued for OUR application (matching client_id)
    3. The token hasn't expired
    
    Args:
        id_token: The JWT string from Google's Sign-In SDK
        
    Returns:
        Dictionary with user info:
        {
            "sub": "1234567890",           # Google's unique user ID
            "email": "user@gmail.com",      # Email address
            "name": "John Doe",             # Display name
            "picture": "https://...",       # Profile picture URL
            "email_verified": True,         # Whether email is verified
        }
        
    Raises:
        ValueError: If the token is invalid, expired, not for our app,
                    or GOOGLE_CLIENT_ID is not configured.
    """
    # FIX C-4: Fail fast if GOOGLE_CLIENT_ID is not configured.
    # Passing an empty string to verify_oauth2_token() skips the audience
    # check entirely — any Google token would be accepted regardless of
    # which application issued it.
    if not GOOGLE_CLIENT_ID:
        raise ValueError(
            "GOOGLE_CLIENT_ID is not configured on the server. "
            "Authentication is disabled for security. "
            "Set GOOGLE_CLIENT_ID in the platform .env file."
        )

    try:
        # google.oauth2.id_token uses Google's public keys to verify the JWT
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        # verify_oauth2_token does ALL the heavy lifting:
        # - Fetches Google's public signing keys
        # - Verifies the JWT signature
        # - Checks the 'aud' claim matches our GOOGLE_CLIENT_ID
        # - Checks the token hasn't expired
        idinfo = google_id_token.verify_oauth2_token(
            id_token,                      # The token to verify
            google_requests.Request(),      # HTTP transport for fetching Google's keys
            GOOGLE_CLIENT_ID,               # Our app's client ID (must match token's 'aud')
            clock_skew_in_seconds=10,       # Tolerate small clock drift between client and server
        )
        
        logger.info(f"Google token verified for: {idinfo.get('email')}")
        return idinfo
        
    except ValueError as e:
        # Token is invalid (bad signature, expired, wrong audience, etc.)
        logger.warning(f"Google token verification failed: {e}")
        raise ValueError(f"Invalid Google token: {e}")


def create_access_token(user_id: int, email: str, role: str) -> str:
    """
    Create a JWT access token for an authenticated user.
    
    This is OUR token (not Google's). After verifying the user with Google,
    we issue our own JWT that the frontend sends on subsequent API requests.
    
    The token payload contains:
        - sub: User's database ID (as string, per JWT convention)
        - email: User's email (for quick access without DB query)
        - role: User's role ('admin' or 'user')
        - exp: Expiration timestamp
        - iat: Issued-at timestamp
    
    Args:
        user_id: The user's database primary key
        email: The user's email address
        role: The user's role ('admin' or 'user')
        
    Returns:
        Encoded JWT string (e.g. "eyJ...")
    """
    # Build the JWT payload (claims)
    payload = {
        "sub": str(user_id),   # Subject — identifies who this token belongs to
        "email": email,         # Convenience — avoids DB lookup for email
        "role": role,           # Authorization level
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),  # Expiration
        "iat": datetime.now(timezone.utc),  # Issued at
    }
    
    # Encode the payload into a signed JWT string
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    logger.debug(f"Created JWT for user_id={user_id}, role={role}")
    return token


def decode_access_token(token: str) -> dict:
    """
    Decode and verify one of our JWT access tokens.
    
    This is called by the auth middleware on every protected API request.
    It verifies:
    1. The token was signed with our JWT_SECRET
    2. The token hasn't expired
    3. The token contains valid claims
    
    Args:
        token: The JWT string from the Authorization header
        
    Returns:
        Decoded payload dictionary with 'sub', 'email', 'role'
        
    Raises:
        ValueError: If the token is invalid, expired, or tampered with
    """
    try:
        # jwt.decode verifies signature + expiration automatically
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        # Token is invalid (bad signature, expired, malformed, etc.)
        raise ValueError(f"Invalid token: {e}")


def create_refresh_token(user_id: int) -> str:
    """
    Create a long-lived refresh token for session persistence.

    Refresh tokens are stored separately and have their own secret
    to reduce blast radius if the access token secret is compromised.
    """
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, REFRESH_TOKEN_SECRET, algorithm=JWT_ALGORITHM)
    logger.debug(f"Created refresh token for user_id={user_id}")
    return token


def decode_refresh_token(token: str) -> dict:
    """Decode and verify a refresh token."""
    try:
        payload = jwt.decode(token, REFRESH_TOKEN_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise ValueError("Token is not a refresh token")
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid refresh token: {e}")
