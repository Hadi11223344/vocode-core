from unittest.mock import AsyncMock, MagicMock

import pytest

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
)
from voice_platform.integrations.plugins.webhook import WebhookPlugin


@pytest.mark.asyncio
async def test_http_failure_is_returned_as_plugin_failure():
    client = MagicMock()
    client.request = AsyncMock(
        return_value={
            "success": False,
            "status_code": 500,
            "error": "HTTP 500: unavailable",
        }
    )
    plugin = WebhookPlugin(client_factory=lambda integration: client)
    request = PluginExecutionRequest(
        action="request",
        params={"url": "https://example.com/webhook"},
        integration=IntegrationConfiguration(service_type="webhook"),
    )

    result = await plugin.execute(request)

    assert result.success is False
    assert result.error == "HTTP 500: unavailable"
    assert result.output["status_code"] == 500
