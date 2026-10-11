"""Voice Platform — Google OAuth 2.0 Manager
===============================================

Handles the full Google OAuth 2.0 authorization code flow with PKCE
for Calendar and Sheets access.

Flow:
    1. Frontend calls /api/integrations/google/auth
    2. Backend generates PKCE verifier + state, stores in Redis/cache
    3. Backend returns Google consent screen URL
    4. User approves in popup, Google redirects to frontend callback
    5. Frontend POSTs code + state to /api/integrations/google/callback
    6. Backend exchanges code for tokens, stores encrypted in DB
    7. GoogleCalendarClient / GoogleSheetsClient retrieve tokens on use

Security:
    - PKCE prevents authorization code interception
    - State parameter prevents CSRF
    - Tokens encrypted at rest (Fernet)
    - 10-minute state expiry
"""

import asyncio
import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from loguru import logger

from voice_platform.cache import RedisCache
from voice_platform.config import settings
from voice_platform.encryption import decrypt, encrypt

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DEFAULT_GOOGLE_OAUTH_REDIRECT_URI = "http://localhost:3001/oauth/google/callback"

# Per-service scope sets — allows granular authorization per Google product
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

# Combined scopes for the unified "Connect Google" flow.
# When a user connects their Google account, they authorize all three
# services at once — Calendar, Sheets, and Drive.
SCOPES = CALENDAR_SCOPES + SHEETS_SCOPES + DRIVE_SCOPES

# OAuth state stored in Redis with 10-minute TTL for multi-instance safety


def _resolve_redirect_uri(redirect_uri: Optional[str] = None) -> str:
    """Resolve the canonical Google OAuth callback URL."""
    return settings.google_oauth_redirect_uri or redirect_uri or DEFAULT_GOOGLE_OAUTH_REDIRECT_URI


def _hash_verifier(verifier: str) -> str:
    """S256 code challenge from verifier (PKCE)."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class GoogleOAuthManager:
    """Handles Google OAuth 2.0 authorization code flow with PKCE."""

    @staticmethod
    async def get_authorization_url(
        user_id: int,
        redirect_uri: str,
        scopes: Optional[list] = None,
    ) -> dict:
        """Generate the Google consent screen URL with PKCE.

        Args:
            scopes: List of OAuth scopes to request. Defaults to all
                (Calendar + Sheets + Drive) if not provided.

        Stores PKCE verifier in Redis (10-min TTL) so multi-instance
        deployments can complete the OAuth callback on any worker.

        Returns:
            {"auth_url": str, "state": str}
        """
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        canonical_redirect_uri = _resolve_redirect_uri(redirect_uri)
        requested_scopes = scopes or SCOPES

        await RedisCache.set(
            f"oauth_state:{state}",
            {
                "user_id": user_id,
                "code_verifier": code_verifier,
                "redirect_uri": canonical_redirect_uri,
                "scopes": requested_scopes,
            },
            ttl_seconds=600,
        )

        scope_str = " ".join(requested_scopes)
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": canonical_redirect_uri,
            "response_type": "code",
            "scope": scope_str,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": _hash_verifier(code_verifier),
            "code_challenge_method": "S256",
        }
        auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
        return {"auth_url": auth_url, "state": state}

    @staticmethod
    async def exchange_code(code: str, state: str) -> dict:
        """Exchange authorization code for access + refresh tokens.

        Raises:
            ValueError: If state is invalid or expired.
        """
        cached = await RedisCache.get(f"oauth_state:{state}")
        await RedisCache.delete(f"oauth_state:{state}")
        if not cached:
            raise ValueError("Invalid or expired OAuth state")

        user_id = cached["user_id"]
        redirect_uri = _resolve_redirect_uri(cached["redirect_uri"])
        code_verifier = cached["code_verifier"]
        # Fallback to full scopes if not stored in older cache entries
        cached_scopes = cached.get("scopes", SCOPES)

        async with httpx.AsyncClient(verify=True) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "code_verifier": code_verifier,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])

        # Store encrypted tokens in DB
        from sqlalchemy import select

        from voice_platform.database import GoogleOAuthToken, async_session

        async with async_session() as session:
            # Delete existing token for this user
            existing = await session.execute(
                select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user_id)
            )
            for row in existing.scalars().all():
                await session.delete(row)

            token = GoogleOAuthToken(
                user_id=user_id,
                access_token=encrypt(data["access_token"]),
                refresh_token=encrypt(data["refresh_token"]),
                token_type=data.get("token_type", "Bearer"),
                expires_at=expires_at,
                scopes=json.dumps(data.get("scope", " ".join(cached_scopes)).split()),
            )
            session.add(token)
            await session.commit()

        logger.info(f"Google OAuth tokens stored for user {user_id}")
        return {"success": True, "expires_at": expires_at.isoformat()}

    @staticmethod
    async def get_credentials(user_id: int) -> Optional[Credentials]:
        """Get valid (possibly refreshed) OAuth credentials for a user.

        Returns None if no token exists.
        """
        from sqlalchemy import select

        from voice_platform.database import GoogleOAuthToken, async_session

        async with async_session() as session:
            result = await session.execute(
                select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user_id)
            )
            token = result.scalar_one_or_none()
            if not token:
                return None

            access_token = decrypt(token.access_token)
            refresh_token = decrypt(token.refresh_token)
            scopes = json.loads(token.scopes) if token.scopes else SCOPES

            expiry = token.expires_at
            if expiry and expiry.tzinfo is not None:
                expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)

            creds = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri=GOOGLE_TOKEN_URL,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                scopes=scopes,
                expiry=expiry,
            )

            # Auto-refresh if expired
            if creds.expired and creds.refresh_token:
                logger.info(f"Refreshing expired Google token for user {user_id}")
                await asyncio.to_thread(creds.refresh, Request())
                # Update stored access token
                token.access_token = encrypt(creds.token)
                if creds.expiry:
                    token.expires_at = creds.expiry.replace(tzinfo=timezone.utc)
                await session.commit()

            return creds

    @staticmethod
    async def revoke(user_id: int) -> dict:
        """Revoke Google OAuth tokens and delete from DB."""
        from sqlalchemy import select

        from voice_platform.database import GoogleOAuthToken, async_session

        async with async_session() as session:
            result = await session.execute(
                select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user_id)
            )
            token = result.scalar_one_or_none()
            if not token:
                return {"success": True, "message": "No token to revoke"}

            access_token = decrypt(token.access_token)
            # Revoke with Google (best-effort)
            try:
                async with httpx.AsyncClient(verify=True) as client:
                    await client.post(
                        GOOGLE_REVOKE_URL,
                        params={"token": access_token},
                    )
            except Exception as e:
                logger.warning(f"Google token revocation failed: {e}")

            await session.delete(token)
            await session.commit()

        logger.info(f"Google OAuth revoked for user {user_id}")
        return {"success": True}
