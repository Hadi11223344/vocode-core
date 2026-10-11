"""SheetsPlugin — Google Sheets integration."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


def _parse_csv_values(values_str: str) -> list[str]:
    import csv
    import io
    import json

    # Try JSON array first (LLMs sometimes return JSON instead of CSV)
    try:
        parsed = json.loads(values_str)
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if v is not None]
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        reader = csv.reader(io.StringIO(values_str))
        row = next(reader, [])
        return [v.strip() for v in row if v is not None]
    except Exception:
        return [v.strip() for v in values_str.split(",") if v.strip()]


_ALLOWED_FALLBACK_KEYS = frozenset({
    "name", "phone", "email", "notes", "purpose", "date", "time",
    "status", "summary", "description", "location", "attendee_email",
})


class SheetsPlugin:
    """Google Sheets integration plugin."""

    kinds = ("google_sheets",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    def _build_client(self, integration: IntegrationConfiguration, params: dict, event_callback=None) -> Any:
        from voice_platform.integrations.google_sheets import GoogleSheetsClient
        sheet_config = dict(integration.config)
        if params.get("sheet_name"):
            sheet_config["sheet_name"] = params["sheet_name"]
        return GoogleSheetsClient(
            integration.api_key, sheet_config,
            user_id=integration.user_id,
            event_callback=event_callback,
        )

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        action = request.action
        params = dict(request.params)

        client = (
            self._client_factory(integration)
            if self._client_factory
            else self._build_client(integration, params)
        )

        try:
            if action == "read_rows":
                rows = await client.read_rows(
                    cell_range=params.get("range"),
                    max_rows=int(params.get("max_rows", 100)),
                )
                return PluginResult(
                    success=True,
                    output={
                        "rows": rows,
                        "count": len(rows),
                        "found": bool(rows),
                    },
                )

            elif action == "append_row":
                values = params.get("values", [])
                if isinstance(values, str):
                    values = _parse_csv_values(values)
                if not values:
                    values = [v for k, v in params.items() if k in _ALLOWED_FALLBACK_KEYS and v]
                try:
                    result = await client.append_row(values, range=params.get("range"))
                    if isinstance(result, dict) and result.get("success") is False:
                        return PluginResult(
                            success=False,
                            error=str(result.get("error") or "Google Sheets append_row failed"),
                        )
                    output = dict(result) if isinstance(result, dict) else {"output": result}
                    output["row_appended"] = True
                    return PluginResult(success=True, output=output)
                except Exception as e:
                    from voice_platform.integrations.google_sheets import SheetsError
                    if isinstance(e, SheetsError):
                        return PluginResult(
                            success=False,
                            error=e.message_safe,
                            output={
                                "row_appended": False,
                                "error_code": e.code,
                                "error_message_safe": e.message_safe,
                            },
                        )
                    logger.error(f"Sheets append_row failed: {e}")
                    return PluginResult(
                        success=False,
                        error=str(e),
                        output={"row_appended": False, "error_code": "SHEETS_APPEND_FAILED"},
                    )

            elif action == "update_row":
                values = params.get("values", [])
                if isinstance(values, str):
                    values = _parse_csv_values(values)
                result = await client.update_row(
                    row_number=int(params["row_number"]),
                    values=values,
                )
                if isinstance(result, dict) and result.get("success") is False:
                    return PluginResult(
                        success=False,
                        error=str(result.get("error") or "Google Sheets update_row failed"),
                    )
                return PluginResult(success=True, output=result)

            elif action == "search_rows":
                matches = await client.search_rows(
                    column=params.get("column", "A"),
                    query=params.get("query", ""),
                    max_results=int(params.get("max_results", 10)),
                )
                return PluginResult(success=True, output={"matches": matches, "count": len(matches)})

            elif action == "get_headers":
                headers = await client.get_headers()
                return PluginResult(success=True, output={"headers": headers})

            else:
                return PluginResult(success=False, error=f"Unknown sheets action: {action}")
        except Exception as e:
            logger.error(f"Sheets action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
