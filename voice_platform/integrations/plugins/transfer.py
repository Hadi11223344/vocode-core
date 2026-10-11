"""TransferPlugin — telephony call transfer integration.

Telephony transfer is an integration, not a control-flow node.
The executor's execute_direct_action() delegates transfer_call here.
"""

from __future__ import annotations

from typing import Any, Callable

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class TransferPlugin:
    """Call transfer integration plugin."""

    kinds = ("transfer_call",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        params = dict(request.params)

        if request.action == "transfer_call":
            result = {
                "success": True,
                "transfer_to": params.get("transfer_number") or params.get("transfer_to", ""),
                "transfer_type": params.get("transfer_type", "cold"),
                "summary": params.get("summary", ""),
                "note": "Call transfer must be executed by the telephony layer",
            }
            return PluginResult(success=True, output=result)

        return PluginResult(success=False, error=f"Unknown transfer action: {request.action}")
