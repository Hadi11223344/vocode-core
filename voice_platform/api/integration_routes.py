"""
Voice Platform — Integrations API Routes
==========================================

CRUD for managing user integrations (Google Calendar, Google Sheets, Google Drive MCP).

Users connect their services from the frontend, then reference them
in workflows. During calls, the workflow engine executes steps
using these integrations.

Routes:
    GET    /api/integrations           — List user's integrations
    POST   /api/integrations           — Create new integration
    GET    /api/integrations/types      — List supported integration types
    GET    /api/integrations/{id}       — Get integration details
    PUT    /api/integrations/{id}       — Update integration
    DELETE /api/integrations/{id}       — Delete integration
    POST   /api/integrations/{id}/test  — Test connectivity
"""

import json
from typing import Any, Dict, List, Optional, cast

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.api.integration_guides import INTEGRATION_GUIDES
from voice_platform.config import settings
from voice_platform.database import (
    VALID_INTEGRATION_TYPES,
    GoogleOAuthToken,
    Integration,
    User,
    UserApiKey,
    get_db,
)
from voice_platform.encryption import decrypt, encrypt
from voice_platform.middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])


# ── Request Schemas ────────────────────────────────────────────────────

class CreateIntegrationRequest(BaseModel):
    service_type: str = Field(..., description="google_calendar, google_sheets, or google_drive_mcp")
    name: str = Field(..., min_length=1, max_length=255, description="Display name (e.g. 'Work Calendar')")
    api_key_id: Optional[int] = Field(None, description="ID of UserApiKey to use for auth")
    config: Optional[dict] = Field(None, description="Service-specific config")


class UpdateIntegrationRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    api_key_id: Optional[int] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None


# ── Routes ─────────────────────────────────────────────────────────────

_INTEGRATION_TYPE_DEFS = [
    {
        "id": "webhook",
        "name": "Custom Webhook",
        "icon": "globe",
        "category": "developer",
        "description": "Make HTTP requests to any REST API during calls",
        "config_schema": {
            "base_url": {"type": "string", "description": "Base URL for API requests (optional)"},
            "default_headers": {"type": "object", "description": "Default headers sent with every request (JSON format)"},
            "timeout": {"type": "integer", "default": 30, "description": "Request timeout in seconds"},
        },
        "capabilities": ["get", "post", "put", "patch", "delete"],
    },
    {
        "id": "mcp",
        "name": "MCP Server",
        "icon": "server",
        "category": "developer",
        "description": "Connect a Model Context Protocol server to dynamically expose tools",
        "config_schema": {
            "server_url": {"type": "string", "required": True, "description": "The MCP Server endpoint URL"},
        },
        "capabilities": ["dynamic_tools"],
    },
    {
        "id": "custom_api",
        "name": "Custom API Node",
        "icon": "code",
        "category": "developer",
        "description": "Used internally by Custom API nodes to authenticate external requests",
        "config_schema": {},
        "capabilities": ["api_request"],
    },
    {
        "id": "google_calendar",
        "name": "Google Calendar",
        "icon": "calendar",
        "category": "productivity",
        "description": "Create and manage Google Calendar events from workflows",
        "config_schema": {
            "calendar_id": {"type": "string", "default": "primary", "description": "Google Calendar ID (use 'primary' for default)"},
            "timezone": {"type": "string", "default": "UTC", "description": "Timezone for events (e.g. America/New_York)"},
        },
        "capabilities": ["create_event", "list_events", "update_event", "delete_event"],
    },
    {
        "id": "google_sheets",
        "name": "Google Sheets",
        "icon": "spreadsheet",
        "category": "productivity",
        "description": "Read and write Google Sheets data from workflows",
        "config_schema": {
            "spreadsheet_id": {"type": "string", "required": True, "description": "Google Sheets spreadsheet ID"},
            "sheet_name": {"type": "string", "default": "Sheet1", "description": "Sheet tab name"},
        },
        "capabilities": ["read_rows", "append_row", "update_cell"],
    },
    {
        "id": "google_drive_mcp",
        "name": "Google Drive (MCP)",
        "icon": "hard-drive",
        "category": "productivity",
        "description": "Search, read, and list files in Google Drive using the REST API v3",
        "config_schema": {
            "server_url": {"type": "string", "default": "https://drivemcp.googleapis.com/mcp/v1", "description": "Google Drive MCP server URL (auto-filled)"},
        },
        "capabilities": ["list_files", "search_files", "read_file_content", "get_file_metadata"],
    },
    {
        "id": "whatsapp_cloud",
        "name": "WhatsApp Cloud API",
        "icon": "message-circle",
        "category": "communication",
        "description": "Send WhatsApp messages and templates from workflows",
        "config_schema": {
            "phone_number_id": {"type": "string", "required": True, "description": "WhatsApp Business Phone Number ID"},
            "business_account_id": {"type": "string", "required": False, "description": "WhatsApp Business Account ID (optional)"},
        },
        "capabilities": ["send_message", "send_template"],
    },
    {
        "id": "telegram_bot",
        "name": "Telegram Bot",
        "icon": "send",
        "category": "communication",
        "description": "Send Telegram messages via a bot for notifications and alerts",
        "config_schema": {},
        "capabilities": ["send_message"],
    },
    {
        "id": "sms",
        "name": "SMS (Twilio)",
        "icon": "smartphone",
        "category": "communication",
        "description": "Send SMS messages via Twilio from workflows",
        "config_schema": {
            "account_sid": {"type": "string", "required": True, "description": "Twilio Account SID"},
            "from_number": {"type": "string", "required": True, "description": "Twilio phone number to send from"},
        },
        "capabilities": ["send_sms"],
    },
    {
        "id": "email",
        "name": "Email (SMTP)",
        "icon": "mail",
        "category": "communication",
        "description": "Send emails via SMTP from workflows",
        "config_schema": {
            "smtp_host": {"type": "string", "required": True, "description": "SMTP server hostname"},
            "smtp_port": {"type": "integer", "default": 587, "description": "SMTP server port"},
            "smtp_user": {"type": "string", "required": True, "description": "SMTP username"},
            "from_email": {"type": "string", "required": True, "description": "From email address"},
            "from_name": {"type": "string", "description": "From display name"},
            "use_tls": {"type": "boolean", "default": True, "description": "Use TLS encryption"},
        },
        "capabilities": ["send_email"],
    },
]


def _build_integration_types() -> list[dict]:
    """Return all integration type definitions enriched with guide data."""
    types = [dict(t) for t in _INTEGRATION_TYPE_DEFS]
    for t in types:
        guide = INTEGRATION_GUIDES.get(t["id"], {})
        if guide:
            t["setup_guide"] = guide.get("setup_guide", {})
            t["api_key_help"] = guide.get("api_key_help", "")
            t["agent_usage"] = guide.get("agent_usage", {})
            field_overrides = guide.get("field_overrides", {})
            for field_name, overrides in field_overrides.items():
                if field_name in t.get("config_schema", {}):
                    t["config_schema"][field_name].update(overrides)
    return types


@router.get("/types")
async def list_integration_types():
    """List all supported integration types with config schemas."""
    return {"types": _build_integration_types()}


@router.get("/types/{type_id}")
async def get_integration_type(
    type_id: str,
    user: User = Depends(get_current_user),
):
    """Return a single integration type with full setup_guide and agent_usage."""
    type_def = None
    for t in _build_integration_types():
        if t["id"] == type_id:
            type_def = t
            break

    if not type_def:
        raise HTTPException(404, "Integration type not found")

    return {"type": type_def}


@router.get("")
async def list_integrations(
    active_only: bool = Query(False, description="Only return active integrations"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all integrations for the current user."""
    stmt = (
        select(Integration)
        .where(Integration.user_id == user.id)
        .order_by(Integration.created_at.desc())
    )
    if active_only:
        stmt = stmt.where(Integration.is_active == True)
    result = await db.execute(stmt)
    integrations = result.scalars().all()
    return {"integrations": [i.to_dict() for i in integrations]}


@router.get("/check")
async def check_integration_exists(
    service_type: str = Query(..., description="Service type to check"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if the user already has an integration of the given type."""
    if service_type not in VALID_INTEGRATION_TYPES:
        raise HTTPException(400, f"Invalid service type. Must be one of: {VALID_INTEGRATION_TYPES}")

    result = await db.execute(
        select(Integration)
        .where(
            Integration.user_id == user.id,
            Integration.service_type == service_type,
        )
        .order_by(Integration.created_at.desc())
    )
    integration = result.scalars().first()
    return {
        "exists": integration is not None,
        "integration": integration.to_dict() if integration else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_integration(
    request: CreateIntegrationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new integration."""
    if request.service_type not in VALID_INTEGRATION_TYPES:
        raise HTTPException(400, f"Invalid service type. Must be one of: {VALID_INTEGRATION_TYPES}")
    
    # Validate api_key_id belongs to user if provided
    if request.api_key_id:
        result = await db.execute(
            select(UserApiKey).where(
                UserApiKey.id == request.api_key_id,
                UserApiKey.user_id == user.id,
            )
        )
        api_key = result.scalar_one_or_none()
        if not api_key:
            raise HTTPException(404, "API key not found")
        # Validate key service matches integration type
        if api_key.service != request.service_type:
            raise HTTPException(
                400,
                f"API key service '{api_key.service}' does not match "
                f"integration type '{request.service_type}'"
            )
    
    # Validate Google Sheets config has spreadsheet_id
    if request.service_type == "google_sheets":
        if not request.config or not request.config.get("spreadsheet_id"):
            raise HTTPException(400, "Google Sheets integration requires 'spreadsheet_id' in config")

    # Inject default server_url for Google Drive MCP if not provided
    if request.service_type == "google_drive_mcp" and request.config:
        if not request.config.get("server_url"):
            request.config["server_url"] = "https://drivemcp.googleapis.com/mcp/v1"

    # If config contains api_key and no api_key_id was provided,
    # auto-create an encrypted UserApiKey so the credential is stored securely.
    # Also extract secret fields (auth_token, webhook_url) so they aren't
    # stored as plaintext in config_json.
    api_key_id = request.api_key_id
    config_for_storage = dict(request.config) if request.config else {}
    
    # Determine the primary secret: api_key, or auth_token for SMS
    raw_key = config_for_storage.pop("api_key", None)
    if not raw_key and request.service_type == "sms":
        raw_key = config_for_storage.pop("auth_token", None)
    
    # Also extract other secret config fields and store encrypted in api_secret
    raw_secret = None
    for secret_field in ("auth_token", "webhook_url"):
        if secret_field in config_for_storage:
            # For SMS, auth_token is already consumed above as raw_key
            if secret_field == "auth_token" and request.service_type == "sms":
                continue
            raw_secret = config_for_storage.pop(secret_field)
            break
    
    if not api_key_id and raw_key:
        new_key = UserApiKey(
            user_id=user.id,
            service=request.service_type,
            api_key=encrypt(raw_key),
            api_secret=encrypt(raw_secret) if raw_secret else None,
            label=f"Auto: {request.name}",
            is_active=True,
        )
        db.add(new_key)
        await db.flush()  # get the new_key.id
        api_key_id = new_key.id
    
    config_json = json.dumps(config_for_storage) if config_for_storage else None
    
    integration = Integration(
        user_id=user.id,
        service_type=request.service_type,
        name=request.name,
        api_key_id=api_key_id,
        config_json=config_json,
    )
    db.add(integration)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_user_integration" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"You already have a '{request.service_type}' integration. "
                    f"Delete the existing one first, or update it instead."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while creating integration.",
        )
    await db.refresh(integration)

    return {"integration": integration.to_dict()}


@router.get("/{integration_id}")
async def get_integration(
    integration_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific integration."""
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.user_id == user.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(404, "Integration not found")
    return {"integration": integration.to_dict()}


@router.put("/{integration_id}")
async def update_integration(
    integration_id: int,
    request: UpdateIntegrationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing integration."""
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.user_id == user.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(404, "Integration not found")
    
    update_data = request.model_dump(exclude_unset=True)
    
    # Handle config separately — extract secrets into encrypted UserApiKey
    if "config" in update_data and update_data["config"]:
        config_dict = dict(update_data.pop("config"))
        
        # Extract primary key (api_key, or auth_token for SMS)
        raw_key = config_dict.pop("api_key", None)
        if not raw_key and integration.service_type == "sms":
            raw_key = config_dict.pop("auth_token", None)
        
        # Extract secondary secret (webhook_url, auth_token for non-SMS)
        raw_secret = None
        for secret_field in ("auth_token", "webhook_url"):
            if secret_field in config_dict:
                if secret_field == "auth_token" and integration.service_type == "sms":
                    continue
                raw_secret = config_dict.pop(secret_field)
                break
        
        if raw_key:
            # Update existing linked key or create a new one
            if integration.api_key_id:
                key_result = await db.execute(
                    select(UserApiKey).where(UserApiKey.id == integration.api_key_id)
                )
                existing_key = key_result.scalar_one_or_none()
                if existing_key:
                    existing_key.api_key = encrypt(raw_key)
                    if raw_secret:
                        existing_key.api_secret = encrypt(raw_secret)
                else:
                    new_key = UserApiKey(
                        user_id=user.id,
                        service=integration.service_type,
                        api_key=encrypt(raw_key),
                        api_secret=encrypt(raw_secret) if raw_secret else None,
                        label=f"Auto: {integration.name}",
                        is_active=True,
                    )
                    db.add(new_key)
                    await db.flush()
                    update_data["api_key_id"] = new_key.id
            else:
                new_key = UserApiKey(
                    user_id=user.id,
                    service=integration.service_type,
                    api_key=encrypt(raw_key),
                    api_secret=encrypt(raw_secret) if raw_secret else None,
                    label=f"Auto: {integration.name}",
                    is_active=True,
                )
                db.add(new_key)
                await db.flush()
                update_data["api_key_id"] = new_key.id
        update_data["config_json"] = json.dumps(config_dict) if config_dict else None
    elif "config" in update_data:
        update_data.pop("config")
        update_data["config_json"] = None
    
    # Validate api_key_id if being updated
    if "api_key_id" in update_data and update_data["api_key_id"]:
        result = await db.execute(
            select(UserApiKey).where(
                UserApiKey.id == update_data["api_key_id"],
                UserApiKey.user_id == user.id,
            )
        )
        key_row = result.scalar_one_or_none()
        if not key_row:
            raise HTTPException(404, "API key not found")
        key_service = str(cast(Any, key_row).service)
        integration_service = str(cast(Any, integration).service_type)
        if key_service != integration_service:
            raise HTTPException(
                400,
                f"API key service '{key_service}' does not match "
                f"integration type '{integration_service}'",
            )
    
    for field, value in update_data.items():
        setattr(integration, field, value)
    
    await db.commit()
    await db.refresh(integration)
    return {"integration": integration.to_dict()}


@router.delete("/{integration_id}")
async def delete_integration(
    integration_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an integration."""
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.user_id == user.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(404, "Integration not found")
    
    integration.is_active = False

    # FIX M-7: Cascade deactivation to the linked UserApiKey.
    # Previously, the auto-created encrypted key remained active after the
    # integration was soft-deleted, leaving orphaned secrets in the DB.
    # We only deactivate "Auto:" keys created by this integration; manually
    # linked keys (api_key_id set by the user explicitly) are left active
    # because the user may have other integrations sharing the same key.
    if integration.api_key_id:
        key_result = await db.execute(
            select(UserApiKey).where(
                UserApiKey.id == integration.api_key_id,
                UserApiKey.user_id == user.id,
            )
        )
        linked_key = key_result.scalar_one_or_none()
        if linked_key and (linked_key.label or "").startswith("Auto:"):
            linked_key.is_active = False
            logger.info(
                f"Deactivated auto-created UserApiKey #{linked_key.id} "
                f"({linked_key.service}) linked to integration '{integration.name}'"
            )

    await db.commit()
    return {"message": f"Integration '{integration.name}' deactivated"}


@router.patch("/{integration_id}/reactivate")
async def reactivate_integration(
    integration_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a previously deactivated integration."""
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.user_id == user.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(404, "Integration not found")

    integration.is_active = True

    # Reactivate linked auto-created UserApiKey if it was deactivated
    if integration.api_key_id:
        key_result = await db.execute(
            select(UserApiKey).where(
                UserApiKey.id == integration.api_key_id,
                UserApiKey.user_id == user.id,
            )
        )
        linked_key = key_result.scalar_one_or_none()
        if linked_key and (linked_key.label or "").startswith("Auto:"):
            linked_key.is_active = True
            logger.info(
                f"Reactivated auto-created UserApiKey #{linked_key.id} "
                f"({linked_key.service}) linked to integration '{integration.name}'"
            )

    await db.commit()
    await db.refresh(integration)
    return {"integration": integration.to_dict()}


@router.post("/{integration_id}/test")
async def test_integration(
    integration_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Test connectivity for an integration.
    Attempts a basic operation to verify credentials and config are valid.
    """
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.user_id == user.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(404, "Integration not found")
    
    # Load the API key and secret — FIX M-6: single query for both values.
    # The original code issued two separate SELECTs against user_api_keys
    # for the same api_key_id (one for api_key, one for api_secret), which
    # is wasteful and can return stale/inconsistent data.
    api_key_value = None
    api_secret_value = None
    if integration.api_key_id:
        key_result = await db.execute(
            select(UserApiKey).where(UserApiKey.id == integration.api_key_id)
        )
        key_row = key_result.scalar_one_or_none()
        if key_row:
            api_key_value = decrypt(key_row.api_key)
            if key_row.api_secret:
                api_secret_value = decrypt(key_row.api_secret)

    # Load integration config from config_json column
    config = {}
    if integration.config_json:
        try:
            config = json.loads(integration.config_json)
        except json.JSONDecodeError:
            logger.warning(f"Integration {integration.id} has invalid config_json, ignoring")

    # Fall back to credentials stored in config (legacy integrations)
    if not api_key_value:
        api_key_value = config.get("api_key") or config.get("auth_token")
    if not api_secret_value:
        api_secret_value = config.get("webhook_url")
    
    try:
        if integration.service_type == "google_calendar":
            try:
                from voice_platform.integrations.google_calendar import GoogleCalendarClient
                client = GoogleCalendarClient(api_key_value, config, user_id=user.id)
                result = await client.test_connection()
                return {"status": "connected", "details": result}
            except ImportError as e:
                return {
                    "status": "error",
                    "message": f"Google Calendar requires google-api-python-client. Install it: pip install google-api-python-client ({e})",
                }

        elif integration.service_type == "google_sheets":
            try:
                from voice_platform.integrations.google_sheets import GoogleSheetsClient
                client = GoogleSheetsClient(api_key_value, config, user_id=user.id)
                result = await client.test_connection()
                return {"status": "connected", "details": result}
            except ImportError as e:
                return {
                    "status": "error",
                    "message": f"Google Sheets requires google-api-python-client. Install it: pip install google-api-python-client ({e})",
                }

        elif integration.service_type == "sms":
            account_sid = config.get("account_sid", "")
            auth_token = api_key_value or ""
            if not account_sid or not auth_token:
                return {"status": "error", "message": "Missing account_sid or auth_token"}
            try:
                from twilio.rest import Client as TwilioClient
                twilio = TwilioClient(account_sid, auth_token)
                account = twilio.api.accounts(account_sid).fetch()
                return {
                    "status": "connected",
                    "message": f"Twilio connected: {account.friendly_name}",
                }
            except Exception as sms_err:
                return {"status": "error", "message": f"Twilio auth failed: {sms_err}"}
        
        elif integration.service_type == "email":
            from voice_platform.integrations.email_client import EmailClient
            client = EmailClient(api_key_value, config)
            try:
                await client.test_connection()
                return {
                    "status": "connected",
                    "message": f"SMTP connected to {config.get('smtp_host', 'unknown host')}:{config.get('smtp_port', 587)}",
                }
            except Exception as email_err:
                return {"status": "error", "message": f"SMTP connection failed: {email_err}"}
        
        elif integration.service_type in ("webhook", "slack", "zapier", "hubspot"):
            target_url = api_secret_value or config.get("webhook_url") or config.get("base_url") or "No URL configured"
            masked = target_url[:30] + "..." if len(target_url) > 30 else target_url
            return {
                "status": "configured",
                "message": f"Webhook endpoint configured: {masked}",
            }
        
        elif integration.service_type == "knowledge_base":
            return {
                "status": "configured",
                "message": "Knowledge base integration ready. Upload content via KB management.",
            }
        
        elif integration.service_type == "cal_com":
            return {
                "status": "configured",
                "message": f"Cal.com configured with base URL: {config.get('base_url', 'https://api.cal.com/v1')}",
            }

        elif integration.service_type == "calendly":
            return {
                "status": "configured",
                "message": f"Calendly configured with base URL: {config.get('base_url', 'https://api.calendly.com')}",
            }

        elif integration.service_type in ("salesforce", "pipedrive", "gohighlevel"):
            target_url = config.get("instance_url") or config.get("base_url") or "default"
            return {
                "status": "configured",
                "message": f"{integration.service_type.title()} CRM configured: {target_url[:60]}",
            }

        elif integration.service_type == "stripe":
            return {
                "status": "configured",
                "message": f"Stripe configured. Currency: {config.get('currency', 'usd')}",
            }

        elif integration.service_type == "shopify":
            shop = config.get("shop_domain", "unknown")
            return {
                "status": "configured",
                "message": f"Shopify store configured: {shop}",
            }

        elif integration.service_type in ("zendesk", "freshdesk"):
            domain = config.get("subdomain") or config.get("domain") or "unknown"
            return {
                "status": "configured",
                "message": f"{integration.service_type.title()} configured: {domain}",
            }

        elif integration.service_type == "intercom":
            return {
                "status": "configured",
                "message": "Intercom configured. API key will be used for requests.",
            }

        elif integration.service_type == "whatsapp_cloud":
            from voice_platform.integrations.whatsapp_client import WhatsAppClient
            access_token = api_key_value or config.get("access_token", "")
            phone_number_id = config.get("phone_number_id", "")
            if not access_token or not phone_number_id:
                return {"status": "error", "message": "Missing access_token or phone_number_id"}
            try:
                client = WhatsAppClient(
                    access_token=access_token,
                    phone_number_id=phone_number_id,
                    business_account_id=config.get("business_account_id"),
                )
                result = await client.test_connection()
                return {
                    "status": "connected",
                    "message": f"WhatsApp connected: {result.get('display_name', phone_number_id)}",
                }
            except Exception as wa_err:
                return {"status": "error", "message": f"WhatsApp connection failed: {wa_err}"}

        elif integration.service_type == "telegram_bot":
            from voice_platform.integrations.telegram_client import TelegramClient
            bot_token = api_key_value or config.get("bot_token", "")
            if not bot_token:
                return {"status": "error", "message": "Missing bot_token"}
            client = TelegramClient(bot_token=bot_token)
            try:
                result = await client.test_connection()
                return {
                    "status": "connected",
                    "message": f"Telegram bot connected: @{result.get('bot_username', 'unknown')}",
                }
            except Exception as tg_err:
                return {"status": "error", "message": f"Telegram connection failed: {tg_err}"}
            finally:
                await client.aclose()

        elif integration.service_type in ("discord", "microsoft_teams", "make"):
            webhook = api_secret_value or config.get("webhook_url", "")
            masked = webhook[:30] + "..." if len(webhook) > 30 else webhook or "not set"
            return {
                "status": "configured",
                "message": f"{integration.service_type.replace('_', ' ').title()} webhook configured: {masked}",
            }

        elif integration.service_type == "sendgrid":
            return {
                "status": "error",
                "message": "SendGrid integration is not yet implemented. Use the 'Email (SMTP)' integration instead.",
            }

        elif integration.service_type in ("notion", "airtable"):
            return {
                "status": "configured",
                "message": f"{integration.service_type.title()} configured. Ready for database operations.",
            }

        elif integration.service_type in ("jira", "linear"):
            return {
                "status": "configured",
                "message": f"{integration.service_type.title()} configured. Ready for issue management.",
            }

        elif integration.service_type == "mcp":
            server_url = config.get("server_url", "").strip()
            if not server_url:
                return {"status": "error", "message": "MCP server URL is not configured."}
            try:
                from voice_platform.integrations.mcp_client import McpClient
                auth_token = config.get("auth_token") or None
                client = McpClient(server_url=server_url, auth_token=auth_token, timeout=15.0)
                tools = await client.list_tools()
                await client.aclose()
                tool_names = [t.get("name", "?") for t in (tools or [])]
                return {
                    "status": "ok",
                    "message": f"Connected to MCP server. {len(tool_names)} tool(s) available: {', '.join(tool_names[:5])}{'...' if len(tool_names) > 5 else ''}",
                }
            except Exception as mcp_err:
                return {"status": "error", "message": f"MCP server unreachable: {str(mcp_err)[:200]}"}

        elif integration.service_type == "custom_api":
            url = config.get("url", "").strip()
            if not url:
                return {"status": "error", "message": "Custom API URL is not configured."}
            return {
                "status": "configured",
                "message": f"Custom API configured. Endpoint: {url[:60]}{'...' if len(url) > 60 else ''}",
            }

        elif integration.service_type == "google_drive_mcp":
            # Test Google Drive by verifying OAuth and calling the real Drive API v3
            try:
                from voice_platform.integrations.google_oauth import GoogleOAuthManager
                creds = await GoogleOAuthManager.get_credentials(user.id)
                if not creds or not creds.token:
                    return {
                        "status": "error",
                        "message": "Google account not connected. Click 'Connect with Google' to authorize Drive access.",
                    }
                from voice_platform.integrations.google_drive_client import GoogleDriveClient
                drive_client = GoogleDriveClient(
                    access_token=creds.token, credentials=creds, timeout=15.0
                )
                result = await drive_client.test_connection()
                await drive_client.aclose()
                return {
                    "status": "ok",
                    "message": result["message"],
                }
            except Exception as drive_err:
                err_str = str(drive_err)
                if "has not been used in project" in err_str or "disabled" in err_str.lower():
                    return {
                        "status": "error",
                        "message": (
                            "Google Drive API is disabled in your Google Cloud project. "
                            "Enable it at: https://console.cloud.google.com/apis/library/drive.googleapis.com "
                            "Then wait 2–3 minutes and try again."
                        ),
                    }
                if "401" in err_str or "invalid authentication credentials" in err_str.lower():
                    return {
                        "status": "error",
                        "message": (
                            "Google Drive access token expired or invalid. "
                            "Please reconnect your Google account in Settings → Integrations."
                        ),
                    }
                if "403" in err_str:
                    return {
                        "status": "error",
                        "message": (
                            f"Drive API access denied (403). {err_str[:200]} "
                            "Ensure the Google Drive API is enabled in your Cloud project and the OAuth consent screen is configured."
                        ),
                    }
                return {"status": "error", "message": f"Drive test failed: {err_str[:200]}"}
        
        else:
            return {"status": "unknown", "message": f"No test available for {integration.service_type}"}
    
    except Exception as e:
        logger.error(f"Integration test failed: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/{integration_id}/agent-usage")
async def get_integration_agent_usage(
    integration_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the agent_usage documentation for a specific integration.
    Includes tools, trigger phrases, example scenarios, and parameters.
    """
    from voice_platform.api.integration_guides import INTEGRATION_GUIDES

    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.user_id == user.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(404, "Integration not found")

    guide = INTEGRATION_GUIDES.get(integration.service_type, {})
    agent_usage = guide.get("agent_usage", {})

    # Also list any agents using this integration
    from voice_platform.database import Agent
    agent_result = await db.execute(
        select(Agent).where(
            Agent.user_id == user.id,
            Agent.tools_config.isnot(None),
        )
    )
    agents = agent_result.scalars().all()
    linked_agents = []
    for a in agents:
        tools = []
        try:
            import json
            tools = json.loads(a.tools_config) if isinstance(a.tools_config, str) else a.tools_config or []
        except Exception:
            pass
        tool_ids = [t.get("tool_name") if isinstance(t, dict) else str(t) for t in tools]
        usage_tools = agent_usage.get("tools", [])
        if any(t in tool_ids for t in usage_tools):
            linked_agents.append({"id": a.id, "name": a.name})

    return {
        "integration_id": integration.id,
        "service_type": integration.service_type,
        "agent_usage": agent_usage,
        "linked_agents": linked_agents,
    }


# ── Google Drive File Browser ──────────────────────────────────────────

@router.get("/{integration_id}/drive/files")
async def list_drive_files(
    integration_id: int,
    query: Optional[str] = Query(None, description="Search query for file names"),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List files from a Google Drive integration via the real Drive API v3.

    Used by the workflow builder file browser and agent wizard.
    """
    result = await db.execute(
        select(Integration)
        .where(
            Integration.id == integration_id,
            Integration.user_id == user.id,
            Integration.service_type == "google_drive_mcp",
            Integration.is_active == True,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google Drive integration not found",
        )

    # Resolve OAuth credentials
    from voice_platform.integrations.google_oauth import GoogleOAuthManager
    creds = await GoogleOAuthManager.get_credentials(user.id)
    if not creds or not creds.token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account not connected. Please connect in Integrations settings.",
        )

    # Parse config for server URL
    config: dict = {}
    if integration.config_json:
        try:
            config = json.loads(integration.config_json)
        except Exception:
            pass
    server_url = config.get("server_url", "https://drivemcp.googleapis.com/mcp/v1")

    # Use real Google Drive API v3
    from voice_platform.integrations.google_drive_client import GoogleDriveClient
    drive_client = GoogleDriveClient(
        access_token=creds.token, credentials=creds, timeout=15.0
    )
    try:
        files = await drive_client.list_files(query=query, page_size=page_size)
        return {"files": files}
    except Exception as e:
        err_str = str(e)
        logger.warning(f"Drive file list failed: {e}")
        if "has not been used in project" in err_str or "disabled" in err_str.lower():
            return {
                "files": [],
                "error": (
                    "Google Drive API is disabled in your Cloud project. "
                    "Enable it at https://console.cloud.google.com/apis/library/drive.googleapis.com "
                    "and wait 2–3 minutes."
                ),
            }
        return {"files": [], "error": err_str[:200]}
    finally:
        await drive_client.aclose()


@router.get("/{integration_id}/drive/files/{file_id}/preview")
async def preview_drive_file(
    integration_id: int,
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Read a preview of a Google Drive file content via the real Drive API v3.
    Returns the first ~3000 characters of the file for read-only preview.
    """
    result = await db.execute(
        select(Integration)
        .where(
            Integration.id == integration_id,
            Integration.user_id == user.id,
            Integration.service_type == "google_drive_mcp",
            Integration.is_active == True,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google Drive integration not found",
        )

    # Resolve OAuth credentials
    from voice_platform.integrations.google_oauth import GoogleOAuthManager
    creds = await GoogleOAuthManager.get_credentials(user.id)
    if not creds or not creds.token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account not connected. Please connect in Integrations settings.",
        )

    # Use real Google Drive API v3 instead of MCP tool discovery
    from voice_platform.integrations.google_drive_client import GoogleDriveClient
    drive_client = GoogleDriveClient(
        access_token=creds.token, credentials=creds, timeout=15.0
    )
    try:
        content = await drive_client.read_file_content(file_id)
        return {
            "file_id": file_id,
            "preview": content[:3000],
            "truncated": len(content) > 3000,
            "total_chars": len(content),
        }
    except Exception as e:
        logger.warning(f"Drive file preview failed: {e}")
        return {
            "file_id": file_id,
            "preview": f"Failed to read file: {str(e)[:200]}",
            "error": str(e)[:200],
        }
    finally:
        await drive_client.aclose()


# ── Google OAuth 2.0 Flow ──────────────────────────────────────────────

@router.get("/google/auth")
async def google_oauth_init(
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    user: User = Depends(get_current_user),
):
    """Start Google OAuth flow. Returns the consent screen URL.

    The frontend opens this URL in a popup. After the user approves,
    Google redirects to redirect_uri with ?code=...&state=...
    """
    from voice_platform.integrations.google_oauth import GoogleOAuthManager

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            503,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
        )

    result = await GoogleOAuthManager.get_authorization_url(user.id, redirect_uri)
    return {"auth_url": result["auth_url"], "state": result["state"]}


@router.get("/google/auth/calendar")
async def google_oauth_init_calendar(
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    user: User = Depends(get_current_user),
):
    """Start Google OAuth flow for Calendar only."""
    from voice_platform.integrations.google_oauth import CALENDAR_SCOPES, GoogleOAuthManager

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            503,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
        )

    result = await GoogleOAuthManager.get_authorization_url(user.id, redirect_uri, scopes=CALENDAR_SCOPES)
    return {"auth_url": result["auth_url"], "state": result["state"], "service": "calendar"}


@router.get("/google/auth/sheets")
async def google_oauth_init_sheets(
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    user: User = Depends(get_current_user),
):
    """Start Google OAuth flow for Sheets only."""
    from voice_platform.integrations.google_oauth import SHEETS_SCOPES, GoogleOAuthManager

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            503,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
        )

    result = await GoogleOAuthManager.get_authorization_url(user.id, redirect_uri, scopes=SHEETS_SCOPES)
    return {"auth_url": result["auth_url"], "state": result["state"], "service": "sheets"}


@router.get("/google/auth/drive")
async def google_oauth_init_drive(
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    user: User = Depends(get_current_user),
):
    """Start Google OAuth flow for Drive only."""
    from voice_platform.integrations.google_oauth import DRIVE_SCOPES, GoogleOAuthManager

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            503,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
        )

    result = await GoogleOAuthManager.get_authorization_url(user.id, redirect_uri, scopes=DRIVE_SCOPES)
    return {"auth_url": result["auth_url"], "state": result["state"], "service": "drive"}


@router.post("/google/callback")
async def google_oauth_callback(
    code: str = Form(...),
    state: str = Form(...),
):
    """Handle OAuth callback from Google after user approval.

    Exchanges the authorization code for access + refresh tokens,
    encrypts them, and stores in the database.
    """
    from voice_platform.integrations.google_oauth import GoogleOAuthManager

    try:
        result = await GoogleOAuthManager.exchange_code(code, state)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/google/status")
async def google_oauth_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check whether the current user has connected Google OAuth."""
    from voice_platform.integrations.google_oauth import SCOPES, GoogleOAuthManager

    creds = await GoogleOAuthManager.get_credentials(user.id)
    granted_scopes = SCOPES
    if creds:
        token_result = await db.execute(
            select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user.id)
        )
        token_row = token_result.scalar_one_or_none()
        if token_row and token_row.scopes:
            try:
                granted_scopes = json.loads(token_row.scopes)
            except (json.JSONDecodeError, TypeError):
                pass
    return {
        "connected": creds is not None,
        "scopes": granted_scopes,
    }


@router.delete("/google/disconnect")
async def google_oauth_disconnect(
    user: User = Depends(get_current_user),
):
    """Revoke Google OAuth tokens and delete from DB."""
    from voice_platform.integrations.google_oauth import GoogleOAuthManager

    return await GoogleOAuthManager.revoke(user.id)
