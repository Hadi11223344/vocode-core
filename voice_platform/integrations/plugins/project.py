"""ProjectPlugin — project management integrations (Jira, Linear)."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class ProjectPlugin:
    """Project management integration plugin (Jira, Linear)."""

    kinds = ("jira", "linear")

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        service_type = integration.service_type
        action = request.action
        params = dict(request.params)
        config = dict(integration.config)
        api_key = integration.api_key

        try:
            from voice_platform.integrations.webhook_client import WebhookClient

            if service_type == "jira":
                base_url = config.get("base_url", "")
                client = WebhookClient({"base_url": base_url})
                headers = {"Content-Type": "application/json"}
                if api_key:
                    import base64 as _b64
                    user_email = config.get("user_email", "")
                    token = f"{user_email}:{api_key}".encode()
                    headers["Authorization"] = f"Basic {_b64.b64encode(token).decode()}"

                action_map = {
                    "create_issue": ("POST", "/rest/api/3/issue", params),
                    "update_issue": ("PUT", f"/rest/api/3/issue/{params.get('issue_key', '')}", params),
                    "search_issues": ("GET", f"/rest/api/3/search?jql={params.get('jql', '')}", None),
                    "add_comment": ("POST", f"/rest/api/3/issue/{params.get('issue_key', '')}/comment",
                                   {"body": params.get("comment", "")}),
                    "transition_issue": ("POST", f"/rest/api/3/issue/{params.get('issue_key', '')}/transitions",
                                        {"transition": {"id": params.get("transition_id", "")}}),
                }
            else:  # linear
                base_url = "https://api.linear.app/graphql"
                client = WebhookClient({"base_url": base_url})
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = api_key

                action_map = {
                    "create_issue": ("POST", "", {"query": "mutation { issueCreate(input: {title: \"%s\", description: \"%s\", teamId: \"%s\"}) { success issue { id } } }" % (params.get("title", ""), params.get("description", ""), params.get("team_id", ""))}),
                    "update_issue": ("POST", "", {"query": "mutation { issueUpdate(id: \"%s\", input: {title: \"%s\", description: \"%s\"}) { success } }" % (params.get("issue_id", ""), params.get("title", ""), params.get("description", ""))}),
                    "search_issues": ("POST", "", {"query": "{ issues(filter: {title: {contains: \"%s\"}}) { nodes { id title state { name } } } }" % params.get("query", "")}),
                    "add_comment": ("POST", "", {"query": "mutation { commentCreate(input: {issueId: \"%s\", body: \"%s\"}) { success } }" % (params.get("issue_id", ""), params.get("comment", ""))}),
                }

            if action not in action_map:
                return PluginResult(success=False, error=f"Unknown {service_type} action: {action}")

            method, url, body = action_map[action]
            result = await client.request(url=url, method=method, headers=headers, body=body)
            return PluginResult(success=True, output=result)
        except Exception as e:
            logger.error(f"Project action {service_type}/{action} failed: {e}")
            return PluginResult(success=False, error=str(e))
