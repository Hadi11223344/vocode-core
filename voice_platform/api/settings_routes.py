"""
Voice Platform — Settings API Routes
=======================================

Admin-only endpoints for platform-wide configuration.

Settings are stored as key-value pairs in the database.
Default settings are seeded on first startup (see database.py init_db).

Routes:
    GET /api/settings      — Get all platform settings
    PUT /api/settings      — Update a setting (admin only)
"""

from fastapi import APIRouter, Depends, HTTPException  # Routing + errors
from pydantic import BaseModel  # Request validation
from sqlalchemy import select  # Database queries
from sqlalchemy.ext.asyncio import AsyncSession  # Async DB session

from voice_platform.database import Setting, User, get_db
from voice_platform.middleware.auth_middleware import get_current_user, require_admin

# Create router
router = APIRouter(prefix="/api/settings", tags=["Settings"])


# Keys that non-admin users should not see
_SENSITIVE_KEYS = {"encryption_key", "jwt_secret", "twilio_auth_token", "deepgram_api_key"}

# Keys that admins are allowed to set (whitelist)
_ALLOWED_KEYS = {
    "default_llm_provider",
    "default_llm_model",
    "default_voice",
    "max_call_duration",
    "enable_recording",
    "enable_transcription",
    "platform_greeting",
    "platform_name",
}


class UpdateSettingRequest(BaseModel):
    """Request body for updating a single setting."""
    key: str    # Setting key (e.g. 'default_llm_model')
    value: str  # New value (e.g. 'gpt-4o')


@router.get("")
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all platform settings.
    
    Returns all key-value settings as a dictionary.
    Available to all authenticated users (not just admins),
    so the frontend can read defaults.
    
    Returns:
        Dictionary of all settings (key → value)
    """
    result = await db.execute(select(Setting).order_by(Setting.key))
    settings = result.scalars().all()
    
    # Filter out sensitive keys for non-admin users
    is_admin = getattr(user, "role", None) == "admin"
    return {
        "settings": {
            s.key: s.value
            for s in settings
            if is_admin or s.key not in _SENSITIVE_KEYS
        }
    }


@router.put("")
async def update_setting(
    request: UpdateSettingRequest,
    user: User = Depends(require_admin),  # Admin only!
    db: AsyncSession = Depends(get_db),
):
    """
    Update a platform setting (admin only).
    
    Creates the setting if it doesn't exist, updates if it does.
    This is an "upsert" operation.
    
    Only users with role='admin' can access this endpoint.
    The require_admin dependency enforces this.
    
    Args:
        request: Key and new value
        user: Admin user (enforced by require_admin)
        db: Database session
        
    Returns:
        Updated settings dictionary
    """
    # Validate key against whitelist
    if request.key not in _ALLOWED_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Setting key '{request.key}' is not in the allowed list: {sorted(_ALLOWED_KEYS)}",
        )
    
    # Check if setting already exists
    result = await db.execute(
        select(Setting).where(Setting.key == request.key)
    )
    setting = result.scalar_one_or_none()
    
    if setting is None:
        # Create new setting
        setting = Setting(key=request.key, value=request.value)
        db.add(setting)
    else:
        # Update existing setting
        setting.value = request.value
    
    await db.commit()
    
    return {"message": f"Setting '{request.key}' updated", "key": request.key, "value": request.value}
