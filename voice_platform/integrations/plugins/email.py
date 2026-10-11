"""EmailPlugin — Email (SMTP) integration."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class EmailPlugin:
    """Email integration plugin."""

    kinds = ("email",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    def _build_client(self, integration: IntegrationConfiguration) -> Any:
        from voice_platform.integrations.email_client import EmailClient
        return EmailClient(integration.api_key or "", dict(integration.config))

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        action = request.action
        params = dict(request.params)

        client = (
            self._client_factory(integration)
            if self._client_factory
            else self._build_client(integration)
        )

        try:
            if action == "send_email":
                # Local/manual failure injection only — impossible in normal production.
                try:
                    from voice_platform.diagnostics import FailureInjection

                    fi = FailureInjection.instance()
                    if fi.is_enabled() and fi.is_active("email_failure"):
                        return PluginResult(
                            success=False,
                            error="Injected email failure (manual test mode)",
                            output={
                                "email_sent": False,
                                "error_code": "EMAIL_SEND_FAILED",
                            },
                        )
                except Exception:
                    pass

                result = await client.send_email(
                    to=params.get("to", ""),
                    subject=params.get("subject", ""),
                    body=params.get("body", ""),
                    html_body=params.get("html_body"),
                    cc=params.get("cc"),
                    attachments=params.get("attachments"),
                )
                if isinstance(result, dict) and result.get("success") is False:
                    return PluginResult(
                        success=False,
                        error=str(result.get("error") or "Email delivery failed"),
                    )
                output = dict(result) if isinstance(result, dict) else {"output": result}
                output["email_sent"] = True
                return PluginResult(success=True, output=output)
            else:
                return PluginResult(success=False, error=f"Unknown email action: {action}")
        except Exception as e:
            logger.error(f"Email action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
