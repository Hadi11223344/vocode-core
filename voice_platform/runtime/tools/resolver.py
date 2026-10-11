"""IntegrationResolver — resolves integration config, credentials, and overrides from DB.

Extracts _resolve_integration_config, _load_integration,
_load_api_key_and_secret from WorkflowExecutor. Named 'Resolver' because
it resolves overrides + DB + credentials into ResolvedIntegration.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Mapping, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Integration, UserApiKey
from voice_platform.integrations.plugins.base import IntegrationConfiguration
from voice_platform.runtime.tools.types import ResolvedIntegration


class IntegrationResolver:
    """Resolves integration config, credentials, and overrides from DB."""

    def __init__(self, session: AsyncSession, user_id: int) -> None:
        self._session = session
        self._user_id = user_id

    async def resolve(
        self,
        integration_id: Optional[int],
        service_type: Optional[str],
        overrides: Mapping[str, int] | None = None,
        agent_timezone: Optional[str] = None,
    ) -> Optional[ResolvedIntegration]:
        """Returns ResolvedIntegration or None if not found."""
        if overrides is None:
            overrides = {}
        # 1. Check agent-level integration overrides
        if service_type:
            override_id = overrides.get(service_type)
            if override_id:
                integration_id = override_id

        # 2. Load integration by ID
        integration: Optional[Integration] = None
        if integration_id:
            integration = await self._load_integration(integration_id)

        # 3. Fall back to service_type lookup
        if not integration and service_type:
            integration = await self._load_integration_by_service_type(service_type)

        if not integration:
            return None

        # 4. Parse integration config JSON
        cfg: dict = {}
        if integration.config_json:
            try:
                cfg = json.loads(integration.config_json)
            except json.JSONDecodeError:
                cfg = {}

        # 5. Load API key and secret (single query)
        api_key_value, api_secret_value = await self._load_api_key_and_secret(
            integration.api_key_id
        )

        # 6. Legacy config fallback
        if not api_key_value:
            api_key_value = cfg.get("api_key") or cfg.get("auth_token")
        if not api_secret_value:
            api_secret_value = cfg.get("webhook_url")

        # 7. Inject webhook URL for webhook-based integrations
        if api_secret_value and integration.service_type in (
            "slack", "discord", "microsoft_teams", "zapier", "make", "webhook",
        ):
            cfg["webhook_url"] = api_secret_value

        # 8. Build IntegrationConfiguration + ResolvedIntegration
        configuration = IntegrationConfiguration(
            service_type=integration.service_type,
            api_key=api_key_value,
            api_secret=api_secret_value,
            config=MappingProxyType(cfg) if cfg else MappingProxyType({}),
            user_id=self._user_id,
            agent_timezone=agent_timezone,
        )

        display_name = cfg.get("display_name", "") or getattr(integration, "name", "") or ""
        provider = cfg.get("provider", "") or integration.service_type

        return ResolvedIntegration(
            configuration=configuration,
            integration_id=integration.id,
            display_name=display_name,
            provider=provider,
            metadata=MappingProxyType({}),
        )

    async def _load_integration(self, integration_id: int) -> Optional[Integration]:
        """Load an integration by ID, verifying it belongs to the user."""
        if not integration_id:
            return None
        result = await self._session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.user_id == self._user_id,
                Integration.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def _load_integration_by_service_type(
        self, service_type: str
    ) -> Optional[Integration]:
        result = await self._session.execute(
            select(Integration).where(
                Integration.service_type == service_type,
                Integration.user_id == self._user_id,
                Integration.is_active == True,
            ).order_by(Integration.id.asc())
        )
        return result.scalars().first()

    async def _load_api_key_and_secret(
        self, api_key_id: Optional[int]
    ) -> tuple[Optional[str], Optional[str]]:
        """Load BOTH api_key and api_secret in a SINGLE DB query."""
        if not api_key_id:
            return None, None
        from voice_platform.encryption import decrypt

        result = await self._session.execute(
            select(UserApiKey).where(
                UserApiKey.id == api_key_id,
                UserApiKey.user_id == self._user_id,
                UserApiKey.is_active == True,
            )
        )
        key_row = result.scalar_one_or_none()
        if not key_row:
            return None, None
        api_key = decrypt(key_row.api_key) if key_row.api_key else None
        api_secret = decrypt(key_row.api_secret) if key_row.api_secret else None
        return api_key, api_secret
