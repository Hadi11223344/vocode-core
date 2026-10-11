"""
Voice Platform — Workflow Step Executor
=========================================

Executes workflow integration steps during or after calls.

A workflow has a list of steps stored as JSON in `steps_json`.
Each step specifies an integration action to perform, such as:
- Create a calendar event
- Append a row to a spreadsheet
- Read/search spreadsheet data

Step Schema:
    {
        "step_number": 1,
        "integration_id": 3,
        "action": "create_event",
        "params": {
            "summary": "{{caller_name}} - Follow up call",
            "start": "{{next_business_day}}T10:00:00",
            "description": "Auto-scheduled from call"
        }
    }

Template Variables:
    Params support {{variable}} templates that are resolved at execution
    time from the call context (caller info, transcript, agent responses).
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.config import settings
from voice_platform.database import Agent, Integration, UserApiKey
from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginContext,
    PluginExecutionRequest,
)
from voice_platform.integrations.plugins.registry import (
    PluginRegistry,
    build_default_plugin_registry,
)
from voice_platform.runtime.flow.conditions import ConditionEvaluator


class WorkflowExecutor:
    """
    Executes workflow steps using the appropriate integration clients.

    Usage:
        executor = WorkflowExecutor(db_session, user_id, plugin_registry=registry, agent_id=7)
        results = await executor.execute_steps(steps, context)
    """

    def __init__(
        self,
        session: AsyncSession,
        user_id: int,
        plugin_registry: PluginRegistry,
        agent_id: Optional[int] = None,
        agent_timezone: Optional[str] = None,
        integration_overrides: Optional[Dict[str, Any]] = None,
        condition_evaluator: Optional[ConditionEvaluator] = None,
        extraction_service: Optional[Any] = None,
        generation_service: Optional[Any] = None,
        tool_runtime: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
    ):
        self._session = session
        self._user_id = user_id
        self._agent_id = agent_id
        self._agent_timezone = agent_timezone
        self._integration_overrides: Dict[str, int] = {}
        if integration_overrides:
            for k, v in integration_overrides.items():
                try:
                    self._integration_overrides[str(k)] = int(v)
                except (TypeError, ValueError):
                    pass
        self._registry = plugin_registry
        self._conditions = condition_evaluator or ConditionEvaluator()
        self._extraction_service = extraction_service
        self._generation_service = generation_service
        self._tool_runtime = tool_runtime
        self._tool_registry = tool_registry
        self._integration_resolver = None  # lazily built by _ensure_tool_runtime

    # TODO(M8): FlowRuntime becomes ToolRuntime owner. Remove ToolRuntime construction from WorkflowExecutor.
    def _ensure_tool_runtime(self):
        """Lazily build ToolRuntime + ToolRegistry + IntegrationResolver if not injected."""
        if self._tool_runtime is None:
            from voice_platform.runtime.tools import (
                IntegrationResolver,
                ToolAdapter,
                ToolRuntime,
                build_default_tool_registry,
            )
            if self._tool_registry is None:
                self._tool_registry = build_default_tool_registry()
            self._integration_resolver = IntegrationResolver(
                self._session, self._user_id
            )
            adapter = ToolAdapter(self._registry)
            self._tool_runtime = ToolRuntime(
                adapter=adapter,
                resolver=self._integration_resolver,
            )
        return self._tool_runtime

    def _ensure_generation_service(self):
        """Lazily build LLMGenerationService if not injected."""
        if self._generation_service is None:
            from voice_platform.runtime.llm.factory import AgentLLMFactory
            from voice_platform.runtime.services.llm import LLMGenerationService
            factory = AgentLLMFactory(self._session)
            self._generation_service = LLMGenerationService(factory)
        return self._generation_service

    def _ensure_extraction_service(self):
        """Lazily build ExtractionService if not injected."""
        if self._extraction_service is None:
            from voice_platform.runtime.services.extraction import ExtractionService
            gen = self._ensure_generation_service()
            self._extraction_service = ExtractionService(gen)
        return self._extraction_service

    # TODO(M7): Remove compatibility shim after nodes.py migration.
    # pragma: no cover
    async def _load_agent_extraction_prompts(self):
        """Compatibility shim — delegates to ExtractionService.ensure_prompts_loaded."""
        if not self._agent_id:
            return
        svc = self._ensure_extraction_service()
        await svc.ensure_prompts_loaded(self._session, self._agent_id)

    # TODO(M7): Remove compatibility shim after nodes.py migration.
    # pragma: no cover
    async def _llm_extract_batch(
        self, transcript: str, variable_names: list[str], last_agent_question: str = ""
    ) -> Dict[str, str]:
        """Compatibility shim — delegates to ExtractionService.extract_batch."""
        svc = self._ensure_extraction_service()
        return await svc.extract_batch(
            agent_id=self._agent_id,
            user_id=self._user_id,
            transcript=transcript,
            variable_names=variable_names,
            last_agent_question=last_agent_question,
            agent_timezone=self._agent_timezone,
        )

    async def _resolve_integration_config(
        self,
        integration_id: Optional[int],
        service_type: Optional[str],
        config: dict,
    ) -> tuple[Optional[str], Optional[str], Optional[str], dict]:
        """Unified integration resolution — delegates to IntegrationResolver.

        Compat shim: keeps the old tuple return shape for existing callers.
        TODO(M8): Remove after all callers use IntegrationResolver directly.
        """
        from voice_platform.runtime.tools.resolver import IntegrationResolver

        resolver = self._integration_resolver
        if resolver is None:
            resolver = IntegrationResolver(self._session, self._user_id)
            self._integration_resolver = resolver

        resolved = await resolver.resolve(
            integration_id=integration_id,
            service_type=service_type,
            overrides=self._integration_overrides,
            agent_timezone=self._agent_timezone,
        )
        if resolved is None:
            return (None, None, None, {})
        cfg = dict(resolved.configuration.config)
        return (
            resolved.configuration.service_type,
            resolved.configuration.api_key,
            resolved.configuration.api_secret,
            cfg,
        )

    async def execute_workflow(
        self,
        *,
        steps: Optional[list[dict]] = None,
        graph: Optional[dict] = None,
        context: Optional[dict] = None,
        transition_flexibility: str = "strict",
    ) -> dict:
        """
        Execute a workflow definition using graph-first semantics.

        If a graph is present, execute the graph runtime.
        Otherwise, execute legacy step-list runtime.
        """
        context = context or {}
        if graph and isinstance(graph, dict):
            results = await self.execute_graph(
                graph, context, transition_flexibility=transition_flexibility
            )
            return {
                "mode": "graph",
                "results": results,
            }

        results = await self.execute_steps(steps or [], context)
        return {
            "mode": "steps",
            "results": results,
        }
    
    async def execute_steps(
        self,
        steps: list[dict],
        context: dict = None,
    ) -> list[dict]:
        """
        Execute a list of workflow steps sequentially.
        
        Args:
            steps: List of step dicts from Workflow.steps_json
            context: Call context for template variable resolution
                     e.g. {"caller_name": "John", "caller_phone": "+1234567890"}
        
        Returns:
            List of step results with status and details
        """
        context = context or {}
        results = []
        
        for step in steps:
            step_num = step.get("step_number", 0)
            integration_id = step.get("integration_id")
            action = step.get("action")
            params = step.get("params", {})
            node_type = step.get("type")  # Used by execute_single_step
            
            logger.info(f"Executing workflow step {step_num}: {action} (integration={integration_id})")
            
            try:
                # Resolve template variables in params
                resolved_params = self._resolve_templates(params, context)
                
                # Steps without an integration_id use direct execution
                if not integration_id:
                    direct_type = node_type or action or ""
                    result = await self.execute_direct_action(
                        direct_type, action or direct_type, resolved_params, context,
                    )
                    step_status = "success" if result.get("success", True) else "error"
                    step_result = {
                        "step_number": step_num,
                        "action": action,
                        "status": step_status,
                        "result": result,
                    }
                    if step_status == "error":
                        step_result["error"] = result.get("error", "Direct action failed")
                    results.append(step_result)
                    context[f"step_{step_num}_result"] = result
                    continue
                
                # Load the integration via unified resolver
                svc_type, api_key_value, api_secret_value, cfg = await self._resolve_integration_config(
                    integration_id, None, {},
                )
                if not svc_type:
                    results.append({
                        "step_number": step_num,
                        "action": action,
                        "status": "error",
                        "error": f"Integration {integration_id} not found",
                    })
                    continue

                # Execute the action
                result = await self._dispatch_plugin(
                    svc_type,
                    action,
                    resolved_params,
                    api_key_value,
                    cfg,
                    api_secret=api_secret_value,
                )
                
                step_status = "success" if result.get("success", True) else "error"
                step_result = {
                    "step_number": step_num,
                    "action": action,
                    "status": step_status,
                    "result": result,
                }
                if step_status == "error":
                    step_result["error"] = result.get("error", "Integration action failed")
                results.append(step_result)
                
                # Add result to context for subsequent steps
                context[f"step_{step_num}_result"] = result
                
            except Exception as e:
                logger.error(f"Workflow step {step_num} failed: {e}")
                results.append({
                    "step_number": step_num,
                    "action": action,
                    "status": "error",
                    "error": str(e),
                })
        
        return results

    async def execute_graph(
        self,
        graph: dict,
        context: Optional[dict] = None,
        *,
        max_steps: int = 50,
        max_visits_per_node: int = 3,
        transition_flexibility: str = "strict",
        event_callback: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> list[dict]:
        """
        Execute a workflow graph (nodes + edges) with deterministic traversal.

        Branching is handled via condition node yes/no handles or edge labels.
        Cycles are constrained by max_steps and per-node visit caps.
        """
        context = context or {}
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []

        if not nodes:
            return [{"status": "error", "error": "Graph has no nodes"}]

        nodes_by_id = {
            str(node.get("id")): node
            for node in nodes
            if node.get("id") is not None
        }
        incoming_count = defaultdict(int)
        outgoing = defaultdict(list)
        for edge in edges:
            source = str(edge.get("source")) if edge.get("source") is not None else None
            target = str(edge.get("target")) if edge.get("target") is not None else None
            if not source or not target:
                continue
            outgoing[source].append(edge)
            incoming_count[target] += 1

        start_nodes = [
            node_id
            for node_id, node in nodes_by_id.items()
            if self._graph_node_type(node) == "trigger"
        ]
        if not start_nodes:
            start_nodes = [
                node_id for node_id in nodes_by_id.keys() if incoming_count[node_id] == 0
            ]
        if not start_nodes:
            return [{"status": "error", "error": "Graph has no start node"}]

        # ── Cycle detection (pre-execution safety) ─────────────
        cycle = self._detect_cycles(nodes_by_id, outgoing)
        if cycle:
            return [
                {
                    "status": "error",
                    "error": f"Graph contains a cycle: {' → '.join(cycle)}",
                    "suggestion": "Remove the loop or add a condition node to break the cycle.",
                }
            ]
        # ── END cycle detection ─────────────────────────────────

        # Deterministic order: top-to-bottom, then left-to-right.
        def _node_sort_key(node_id: str) -> tuple[float, float, str]:
            node = nodes_by_id[node_id]
            pos = node.get("position") or {}
            return (float(pos.get("y", 0)), float(pos.get("x", 0)), node_id)

        queue = sorted(start_nodes, key=_node_sort_key)
        visit_count: dict[str, int] = defaultdict(int)
        results: list[dict] = []
        processed_steps = 0

        while queue and processed_steps < max_steps:
            node_id = queue.pop(0)
            node = nodes_by_id.get(node_id)
            if not node:
                continue

            visit_count[node_id] += 1
            if visit_count[node_id] > max_visits_per_node:
                results.append(
                    {
                        "node_id": node_id,
                        "node_type": self._graph_node_type(node),
                        "status": "skipped",
                        "reason": "visit_limit_exceeded",
                    }
                )
                continue

            processed_steps += 1
            node_label = (node.get("data") or {}).get("label", node_id)
            if event_callback:
                await event_callback({
                    "event": "node_start",
                    "node_id": node_id,
                    "node_type": self._graph_node_type(node),
                    "label": node_label,
                })
            import time as _time
            _node_start = _time.time()
            node_result = await self._execute_graph_node(node, context, event_callback=event_callback)
            _node_duration_ms = round((_time.time() - _node_start) * 1000, 1)
            node_result["duration_ms"] = _node_duration_ms
            results.append(node_result)
            if event_callback:
                await event_callback({
                    "event": "node_result",
                    "node_id": node_id,
                    "node_type": self._graph_node_type(node),
                    "label": node_label,
                    "status": node_result.get("status", "unknown"),
                    "result": node_result.get("result"),
                    "duration_ms": _node_duration_ms,
                    "error": node_result.get("error"),
                })

            if node_result.get("status") == "blocking":
                # Conversation node (Issue 11): pause graph execution and
                # return results so far. The caller (inbound handler / playground)
                # should inject the conversation prompt into the LLM and resume
                # the graph after the conversation completes.
                # Store the conversation prompt as result so downstream condition
                # nodes can access it via result.<field>.
                conv_output = {"prompt": node_result.get("prompt", ""), "status": "blocking"}
                context[f"node_{node_id}_result"] = conv_output
                context["last_result"] = conv_output
                context["result"] = conv_output
                logger.info(
                    f"Graph execution paused at conversation node '{node_id}'. "
                    f"Prompt: {node_result.get('prompt', '')[:100]}"
                )
                break

            if node_result.get("status") != "success":
                # Stop this path on node execution error.
                continue

            output = node_result.get("result")
            context[f"node_{node_id}_result"] = output
            node_type = self._graph_node_type(node)
            if node_type != "condition":
                context["last_result"] = output
                context["result"] = output
            if node_type in {"end", "end_call"}:
                continue

            next_edges = outgoing.get(node_id, [])
            if not next_edges:
                continue

            if node_type == "condition":
                condition_met = bool((output or {}).get("condition_met"))
                next_edges = self._select_condition_edges(next_edges, condition_met)
                if event_callback:
                    await event_callback({
                        "event": "condition_branch",
                        "node_id": node_id,
                        "condition_met": condition_met,
                    })

            # ── Phase 3: Flex Mode ───────────────────────────────────────
            # When transition_flexibility='flex' and multiple outgoing edges exist,
            # use the LLM to choose the most relevant next step based on context.
            if (
                transition_flexibility == "flex"
                and len(next_edges) > 1
                and node_type != "condition"
            ):
                chosen = await self._flex_route(next_edges, nodes_by_id, context)
                if chosen:
                    next_edges = [chosen]
            # ── END Flex Mode ───────────────────────────────────────────

            next_ids = [
                str(edge.get("target"))
                for edge in sorted(next_edges, key=lambda e: str(e.get("id", "")))
                if edge.get("target") is not None
            ]

            for _edge in sorted(next_edges, key=lambda e: str(e.get("id", ""))):
                _tgt = str(_edge.get("target")) if _edge.get("target") is not None else None
                if _tgt and _tgt in nodes_by_id and event_callback:
                    await event_callback({
                        "event": "edge_traversed",
                        "source": node_id,
                        "target": _tgt,
                        "label": str(_edge.get("label", "")),
                    })

            for target_id in next_ids:
                if target_id in nodes_by_id:
                    queue.append(target_id)

        if processed_steps >= max_steps and queue:
            results.append(
                {
                    "status": "error",
                    "error": "Graph execution aborted: max_steps exceeded",
                    "max_steps": max_steps,
                }
            )

        if event_callback:
            await event_callback({
                "event": "flow_end",
                "total_nodes": processed_steps,
            })

        return results

    @staticmethod
    def _graph_node_type(node: dict) -> str:
        data = node.get("data") or {}
        node_type = data.get("nodeType") or node.get("type") or "action"
        return str(node_type)

    @staticmethod
    def _detect_cycles(
        nodes_by_id: dict[str, dict],
        outgoing: dict[str, list[dict]],
    ) -> list[str] | None:
        """
        Detect cycles in a directed graph using DFS.

        Returns:
            List of node IDs forming a cycle, or None if acyclic.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node_id: WHITE for node_id in nodes_by_id}
        parent = {}

        def _dfs(node_id: str) -> list[str] | None:
            color[node_id] = GRAY
            for edge in outgoing.get(node_id, []):
                target = str(edge.get("target"))
                if target not in nodes_by_id:
                    continue
                if color.get(target, WHITE) == GRAY:
                    # Found a cycle — reconstruct path
                    cycle = [target]
                    current = node_id
                    while current != target:
                        cycle.append(current)
                        current = parent.get(current, target)
                    cycle.append(target)
                    cycle.reverse()
                    return cycle
                if color.get(target, WHITE) == WHITE:
                    parent[target] = node_id
                    result = _dfs(target)
                    if result:
                        return result
            color[node_id] = BLACK
            return None

        for node_id in nodes_by_id:
            if color[node_id] == WHITE:
                result = _dfs(node_id)
                if result:
                    return result
        return None

    # ── LLM-based Flex Routing ──────────────────────────────────────

    async def _flex_route(
        self,
        edges: list[dict],
        nodes_by_id: dict[str, dict],
        context: dict,
    ) -> dict | None:
        """
        Use LLM to pick the best outgoing edge when in flex mode.

        Builds a simple prompt with edge labels/targets and returns
        the edge the LLM thinks is most appropriate.
        """
        # Build edge descriptions
        edge_options = []
        for edge in edges:
            target_id = str(edge.get("target", ""))
            target_node = nodes_by_id.get(target_id)
            label = str(edge.get("label", "")).strip() or "continue"
            node_label = (
                (target_node.get("data") or {}).get("label", "")
                if target_node
                else ""
            )
            edge_options.append({
                "id": edge.get("id", ""),
                "label": label,
                "target_label": node_label,
                "edge": edge,
            })

        options_text = "\n".join(
            f"{i + 1}. [{opt['label']}] → {opt['target_label'] or 'next step'}"
            for i, opt in enumerate(edge_options)
        )

        transcript = context.get("transcript", "")
        last_result = context.get("last_result", {})
        result_summary = str(last_result)[:500] if last_result else ""

        prompt = (
            f"Conversation transcript:\n{transcript}\n\n"
            f"Last step result: {result_summary}\n\n"
            f"Available next steps:\n{options_text}\n\n"
            f"Which next step is most appropriate? "
            f"Respond with ONLY the number (1-{len(edge_options)})."
        )

        system = (
            "You are a conversation flow router. "
            "Pick the most logical next step. "
            "Reply with ONLY a single number."
        )

        raw = await self._ensure_generation_service().generate(
            agent_id=self._agent_id,
            user_id=self._user_id,
            system_prompt=system,
            user_prompt=prompt,
            max_tokens=10,
            temperature=0.0,
        )
        if raw is None:
            logger.debug("Flex routing: LLM unavailable, falling back to first edge")
            return edge_options[0]["edge"] if edge_options else None

        # Extract first digit
        digits = [c for c in raw if c.isdigit()]
        if digits:
            idx = int(digits[0]) - 1
            if 0 <= idx < len(edge_options):
                chosen = edge_options[idx]["edge"]
                logger.debug(f"Flex route chose edge {idx + 1}: {chosen.get('label', '')}")
                return chosen

        logger.warning(f"Flex routing: no digit in LLM response '{raw}', falling back")
        return edge_options[0]["edge"] if edge_options else None

    @staticmethod
    def _select_condition_edges(edges: list[dict], condition_met: bool) -> list[dict]:
        branch_aliases = {"yes", "true"} if condition_met else {"no", "false"}
        preferred = []
        for edge in edges:
            source_handle = str(edge.get("sourceHandle") or "").strip().lower()
            label = str(edge.get("label") or "").strip().lower()
            if source_handle in branch_aliases or label in branch_aliases:
                preferred.append(edge)
        if not preferred:
            logger.warning(
                f"Condition node has no '{'yes' if condition_met else 'no'}' branch edge. "
                f"Halting this branch — add a '{'yes' if condition_met else 'no'}' labeled edge."
            )
            return []
        return preferred

    async def _load_integration_by_service_type(self, service_type: str) -> Optional[Integration]:
        result = await self._session.execute(
            select(Integration).where(
                Integration.service_type == service_type,
                Integration.user_id == self._user_id,
                Integration.is_active == True,
            ).order_by(Integration.id.asc())
        )
        return result.scalars().first()

    async def _execute_graph_node(
        self,
        node: dict,
        context: dict,
        *,
        event_callback: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> dict:
        node_id = str(node.get("id"))
        node_type = self._graph_node_type(node)
        data = node.get("data") or {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        params_from_data = data.get("params") if isinstance(data.get("params"), dict) else {}

        # Merge config and explicit params map; explicit params take precedence.
        # This avoids empty params_from_data (falsy) shadowing a populated config.
        params = {**(config or {}), **(params_from_data or {})}
        action = data.get("action") or config.get("action") or node_type

        integration_id = data.get("integrationId") or data.get("integration_id")
        # D1: Fall back to config for template-imported action nodes
        if not integration_id:
            integration_id = config.get("integration_id") or config.get("integrationId")
        try:
            integration_id = int(integration_id) if integration_id not in (None, "") else None
        except (TypeError, ValueError):
            integration_id = None

        service_type = None
        known_service_types = {
            "google_calendar", "google_sheets", "google_drive", "google_drive_mcp",
            "sms", "email", "knowledge_base",
            "cal_com", "calendly", "salesforce", "pipedrive", "gohighlevel", "hubspot",
            "stripe", "shopify", "zendesk", "freshdesk", "intercom", "notion",
            "airtable", "jira", "linear", "webhook", "zapier", "slack", "make",
            "discord", "microsoft_teams", "whatsapp_cloud", "telegram_bot", "sendgrid",
        }
        if node_type in known_service_types:
            service_type = node_type
        elif node_type == "send_email":
            # React Flow uses the caller-facing node type while the plugin
            # registry and Integration rows use the canonical service alias.
            service_type = "email"
        elif node_type == "action":
            inferred = config.get("integration_type")
            if isinstance(inferred, str) and inferred in known_service_types:
                service_type = inferred

        try:
            # ── MCP Tool / Custom API ─────────────────────────────────────
            # These nodes carry all their config inside node.data.config and do
            # NOT need a pre-connected Integration row in the database.
            if node_type == "mcp_tool":
                try:
                    result = await self._dispatch_plugin(
                        "mcp_tool",
                        config.get("tool_name") or params.get("tool_name") or "",
                        params,
                        api_key=None,
                        config=config,
                        context=context,
                    )
                    if isinstance(result, dict):
                        context[f"node_{node_id}_result"] = result.get("result", result)
                        context["last_result"] = result.get("result", result)
                    node_status = "success" if result.get("success", True) else "error"
                    node_result = {
                        "node_id": node_id,
                        "node_type": node_type,
                        "action": config.get("tool_name") or params.get("tool_name") or "",
                        "status": node_status,
                        "result": result,
                    }
                    if node_status == "error":
                        node_result["error"] = result.get("error", "MCP tool failed")
                    return node_result
                except Exception as mcp_err:
                    logger.error(f"MCP tool node failed ({node_id}): {mcp_err}")
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": "error",
                        "error": str(mcp_err)[:500],
                    }

            if node_type == "custom_api":
                try:
                    return await self._execute_custom_api_node(
                        node_id, params, config, context
                    )
                except Exception as api_err:
                    logger.error(
                        f"Custom API node failed ({node_id}): {api_err}"
                    )
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": "error",
                        "error": str(api_err)[:500],
                    }
            # ═══ NEW: Phase 3 Node Types ════════════════════════════════════════

            # ── Note Node ──
            if node_type == "note":
                note_content = self._resolve_templates(
                    config.get("content", ""), context
                )
                context["_last_note"] = note_content
                logger.debug(f"Note node ({node_id}): stored {len(note_content)} chars")
                return {
                    "node_id": node_id,
                    "node_type": node_type,
                    "status": "success",
                    "result": {"note": note_content[:200]},
                }

            # ── Code Node ──
            if node_type == "code":
                if not settings.enable_sandboxed_code_nodes:
                    logger.warning(f"Code node {node_id} skipped: sandboxed code execution is disabled")
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": "error",
                        "error": "Sandboxed code execution is disabled. Set ENABLE_SANDBOXED_CODE_NODES=1 to enable (not recommended without a real sandbox).",
                    }

                code_text = config.get("code", "")
                language = config.get("language", "python")
                try:
                    result = self._execute_sandboxed_code(code_text, language, context)
                    if isinstance(result, dict):
                        context.update(result)
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": "success",
                        "result": result,
                    }
                except Exception as code_err:
                    logger.warning(f"Code node failed ({node_id}): {code_err}")
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": "error",
                        "error": str(code_err)[:500],
                    }

            # ── Subagent Node ──
            if node_type == "subagent":
                subagent_id = config.get("subagent_id", "")
                prompt = self._resolve_templates(config.get("prompt", ""), context)
                timeout = config.get("timeout", 60)
                try:
                    from sqlalchemy import select

                    from voice_platform.database import Agent
                    agent_result = await self._session.execute(
                        select(Agent).where(
                            (Agent.id == int(subagent_id))
                            | (Agent.name.ilike(f"%{subagent_id}%"))
                        )
                    )
                    subagent = agent_result.scalar_one_or_none()
                    if not subagent:
                        return {
                            "node_id": node_id,
                            "node_type": node_type,
                            "status": "error",
                            "error": f"Subagent '{subagent_id}' not found",
                        }
                    # In a real implementation, this would start a sub-call.
                    # For now, we simulate by returning the prompt as the result.
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": "success",
                        "result": {
                            "subagent_id": subagent.id,
                            "subagent_name": subagent.name,
                            "delegation_prompt": prompt,
                            "simulated": True,
                        },
                    }
                except Exception as sub_err:
                    logger.warning(f"Subagent node failed ({node_id}): {sub_err}")
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": "error",
                        "error": str(sub_err)[:500],
                    }

            # ── Extract Variable Node ──
            if node_type == "extract_variable":
                var_name = config.get("variable_name", "")
                extract_prompt = self._resolve_templates(
                    config.get("prompt", ""), context
                )
                required = config.get("required", False)
                transcript = context.get("transcript", "")
                try:
                    svc = self._ensure_extraction_service()
                    svc.configure(
                        agent_id=self._agent_id,
                        user_id=self._user_id,
                        agent_timezone=self._agent_timezone,
                    )
                    extraction = await svc.extract_variable(
                        transcript, extract_prompt, var_name
                    )
                    if extraction:
                        context[var_name] = extraction
                        logger.debug(
                            f"Extracted {var_name}='{extraction}' from node {node_id}"
                        )
                        return {
                            "node_id": node_id,
                            "node_type": node_type,
                            "status": "success",
                            "result": {var_name: extraction},
                        }
                    elif required:
                        return {
                            "node_id": node_id,
                            "node_type": node_type,
                            "status": "error",
                            "error": f"Required variable '{var_name}' could not be extracted",
                        }
                    else:
                        return {
                            "node_id": node_id,
                            "node_type": node_type,
                            "status": "success",
                            "result": {var_name: None},
                        }
                except Exception as ex_err:
                    logger.warning(f"Extract variable failed ({node_id}): {ex_err}")
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "status": "error",
                        "error": str(ex_err)[:500],
                    }

            # ── END Phase 3 Node Types ────────────────────────────────────────
            # ── END NEW ────────────────────────────────────────────────────────

            # MEDIUM-2: Check agent-level integration overrides first, before node's integration_id
            if service_type:
                override_id = self._integration_overrides.get(service_type)
                if override_id:
                    integration_id = override_id

            if integration_id:
                step = {
                    "step_number": 1,
                    "integration_id": integration_id,
                    "action": action,
                    "params": params,
                    "type": node_type,
                }
                step_result = await self.execute_single_step(step, context)
                return {
                    "node_id": node_id,
                    "node_type": node_type,
                    "action": action,
                    "status": "success",
                    "result": step_result,
                }

            if service_type:
                # Unified integration resolution via _resolve_integration_config
                resolved_params = self._resolve_templates(params, context)
                svc_type, api_key_value, api_secret_value, cfg = await self._resolve_integration_config(
                    integration_id, service_type, {},
                )
                if not svc_type:
                    # Platform SMTP fallback for send_email when no email Integration
                    # row exists (same path as execute_direct_action / in-call tools).
                    if service_type == "email" or node_type == "send_email":
                        action_params = resolved_params.get("params")
                        if not isinstance(action_params, dict):
                            action_params = resolved_params
                        logger.info(
                            "send_email: no email integration for user %s — "
                            "using platform SMTP fallback",
                            self._user_id,
                        )
                        direct_result = await self.execute_direct_action(
                            "send_email",
                            "send_email",
                            action_params,
                            context,
                        )
                        node_status = (
                            "success" if direct_result.get("success", True) else "error"
                        )
                        node_result = {
                            "node_id": node_id,
                            "node_type": node_type,
                            "action": action,
                            "status": node_status,
                            "result": direct_result,
                        }
                        if node_status == "error":
                            node_result["error"] = direct_result.get(
                                "error", "Email delivery failed"
                            )
                        return node_result
                    return {
                        "node_id": node_id,
                        "node_type": node_type,
                        "action": action,
                        "status": "error",
                        "error": f"No active integration configured for service '{service_type}'",
                    }

                # Action node parameters are nested inside config.params for graph
                # nodes; unwrap them before passing to the integration handler.
                action_params = resolved_params.get("params")
                if not isinstance(action_params, dict):
                    action_params = resolved_params
                result = await self._dispatch_plugin(
                    svc_type,
                    str(action),
                    action_params,
                    api_key_value,
                    cfg,
                    context=context,
                    api_secret=api_secret_value,
                )
                node_status = "success" if result.get("success", True) else "error"
                node_result = {
                    "node_id": node_id,
                    "node_type": node_type,
                    "action": action,
                    "status": node_status,
                    "result": result,
                }
                if node_status == "error":
                    node_result["error"] = result.get("error", "Integration action failed")
                return node_result

            direct_result = await self.execute_direct_action(node_type, str(action), params, context)
            # Propagate "blocking" status from conversation nodes (Issue 11)
            if direct_result.get("status") == "blocking":
                return {
                    "node_id": node_id,
                    "node_type": node_type,
                    "action": action,
                    "status": "blocking",
                    "result": direct_result,
                    "prompt": direct_result.get("prompt", ""),
                }
            node_status = "success" if direct_result.get("success", True) else "error"
            out = {
                "node_id": node_id,
                "node_type": node_type,
                "action": action,
                "status": node_status,
                "result": direct_result,
            }
            if node_status == "error":
                out["error"] = direct_result.get("error", "Direct action failed")
            return out
        except Exception as e:
            logger.error(f"Graph node execution failed ({node_id}/{node_type}): {e}")
            return {
                "node_id": node_id,
                "node_type": node_type,
                "action": action,
                "status": "error",
                "error": str(e),
            }

    # ── NEW: Custom API Node Handler ───────────────────────────────────────
    async def _execute_custom_api_node(
        self,
        node_id: str,
        params: dict,
        config: dict,
        context: dict,
    ) -> dict:
        """
        Execute a custom_api workflow node.

        Makes a generic HTTP request using the existing WebhookClient so
        SSRF protection, retries, and response parsing are all inherited.
        Supports response_mappings (JSONPath) to extract values into context.
        """
        # Lazy import — reuses the battle-tested WebhookClient
        from voice_platform.integrations.webhook_client import WebhookClient

        url: str = (
            config.get("url") or params.get("url") or ""
        ).strip()
        method: str = (
            config.get("method") or params.get("method") or "GET"
        ).upper()

        # Headers and body may arrive as JSON strings (textarea input)
        headers_raw = config.get("headers") or params.get("headers") or {}
        body_raw = config.get("body") or params.get("body") or {}

        if isinstance(headers_raw, str):
            try:
                headers_raw = json.loads(headers_raw)
            except json.JSONDecodeError:
                headers_raw = {}

        if isinstance(body_raw, str):
            try:
                body_raw = json.loads(body_raw)
            except json.JSONDecodeError:
                # Treat as raw string payload
                body_raw = {"raw": body_raw}

        # Resolve {{variable}} templates in URL, headers, and body
        resolved_url_wrap = self._resolve_templates({"url": url}, context)
        url = resolved_url_wrap.get("url", url)
        headers_resolved = self._resolve_templates(headers_raw, context)
        body_resolved = self._resolve_templates(body_raw, context)

        logger.info(f"Executing custom_api node {node_id}: {method} {url}")

        # ── BUG-B5 fix: Resolve auth header for authenticated APIs ──────
        auth_header = (
            config.get("auth_header")
            or params.get("auth_header")
            or None
        )
        if not auth_header and config.get("api_key_id"):
            raw_key = await self._load_api_key(int(config["api_key_id"]))
            if raw_key:
                auth_header = f"Bearer {raw_key}"
        # ── END BUG-B5 fix ─────────────────────────────────────────────

        client = WebhookClient({"timeout": 30})
        result = await client.request(
            url=url,
            method=method,
            headers=headers_resolved if headers_resolved else None,
            body=body_resolved if body_resolved else None,
            auth_header=auth_header,
        )

        # Apply optional JSONPath response_mappings → inject into context
        mappings_raw = config.get("response_mappings") or params.get("response_mappings")
        if mappings_raw:
            if isinstance(mappings_raw, str):
                try:
                    mappings_raw = json.loads(mappings_raw)
                except json.JSONDecodeError:
                    mappings_raw = {}
            if isinstance(mappings_raw, dict) and mappings_raw:
                extracted = WebhookClient.extract_response_data(result, mappings_raw)
                result["extracted"] = extracted
                # Push extracted values into graph context for downstream nodes
                context.update({k: v for k, v in extracted.items() if v is not None})
                logger.debug(
                    f"custom_api node {node_id} extracted: {list(extracted.keys())}"
                )

        context[f"node_{node_id}_result"] = result
        context["last_result"] = result

        node_status = "success" if result.get("success", True) else "error"
        node_result = {
            "node_id": node_id,
            "node_type": "custom_api",
            "action": f"{method} {url}",
            "status": node_status,
            "result": result,
        }
        if node_status == "error":
            node_result["error"] = result.get("error", "Custom API request failed")
        return node_result

    # ── END NEW HANDLERS ───────────────────────────────────────────────────
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
    
    async def _load_api_key(self, api_key_id: Optional[int]) -> Optional[str]:
        """Load an API key value by ID (decrypted). Calls _load_api_key_and_secret internally."""
        key, _ = await self._load_api_key_and_secret(api_key_id)
        return key

    async def _load_api_secret(self, api_key_id: Optional[int]) -> Optional[str]:
        """Load an API secret value by ID (decrypted). Calls _load_api_key_and_secret internally."""
        _, secret = await self._load_api_key_and_secret(api_key_id)
        return secret

    async def _load_api_key_and_secret(
        self, api_key_id: Optional[int]
    ) -> tuple[Optional[str], Optional[str]]:
        """
        FIX C-6: Load BOTH api_key and api_secret in a SINGLE DB query.

        Previously, _load_api_key and _load_api_secret each issued a separate
        SELECT against user_api_keys for the same api_key_id.  Two round-trips
        are wasted work and open a (tiny) window for inconsistency if the row
        changes between the two reads.

        Returns (decrypted_key, decrypted_secret).  Either may be None.
        """
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
    
    def _resolve_templates(self, params: dict, context: dict) -> dict:
        """
        Resolve {{variable}} templates in step params.
        
        Supported template variables:
            {{caller_name}}       — Caller's name (if known)
            {{caller_phone}}      — Caller's phone number
            {{call_date}}         — Date of the call (YYYY-MM-DD)
            {{call_time}}         — Time of the call (HH:MM)
            {{now}}               — Current ISO datetime
            {{next_business_day}} — Next weekday date
            {{transcript}}        — Full call transcript
            {{step_N_result}}     — Result from step N
        """
        # Add default template values in the agent's business timezone.
        from zoneinfo import ZoneInfo

        try:
            current_timezone = ZoneInfo(self._agent_timezone) if self._agent_timezone else timezone.utc
        except Exception:
            current_timezone = timezone.utc
        now = datetime.now(current_timezone)
        defaults = {
            "now": now.isoformat(),
            "call_date": now.strftime("%Y-%m-%d"),
            "call_time": now.strftime("%H:%M"),
            "next_business_day": self._next_business_day(now).strftime("%Y-%m-%d"),
        }
        full_context = {**defaults, **context}
        
        template_pattern = re.compile(r"\{\{([^}]+)\}\}")

        def _context_lookup(var_name: str):
            if var_name in full_context:
                return full_context[var_name]
            if "." in var_name:
                current: Any = full_context
                for part in var_name.split("."):
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        return None
                return current
            return None

        def _resolve_value(value, depth: int = 0):
            if isinstance(value, str):
                current = value
                # Multi-pass resolution to support nested templates in context values,
                # e.g. context["greeting"] = "Hello {{caller_name}}".
                for _ in range(5):
                    # Preserve non-string types when the entire value is one template.
                    whole = re.fullmatch(r"\{\{\s*([^}]+?)\s*\}\}", current)
                    if whole:
                        resolved = _context_lookup(whole.group(1).strip())
                        if resolved is None:
                            return current
                        if isinstance(resolved, str) and depth < 5 and "{{" in resolved:
                            current = resolved
                            continue
                        return resolved

                    changed = False

                    def _replace(match):
                        nonlocal changed
                        var_name = match.group(1).strip()
                        resolved = _context_lookup(var_name)
                        if resolved is None:
                            return match.group(0)
                        changed = True
                        return str(resolved)

                    updated = template_pattern.sub(_replace, current)
                    current = updated
                    if not changed or "{{" not in current:
                        break
                return current
            if isinstance(value, dict):
                return {k: _resolve_value(v, depth + 1) for k, v in value.items()}
            if isinstance(value, list):
                return [_resolve_value(v, depth + 1) for v in value]
            return value

        return _resolve_value(params)
    
    async def _dispatch_plugin(
        self,
        service_type: str,
        action: str,
        params: dict,
        api_key: Optional[str],
        config: dict,
        *,
        context: Optional[dict] = None,
        api_secret: Optional[str] = None,
    ) -> dict:
        """Dispatch an action to the plugin registered for this service type.

        When integration config is NOT pre-resolved (api_key is None and config
        is empty), delegates to ToolRuntime which resolves via IntegrationResolver.
        When integration config IS pre-resolved, uses direct plugin dispatch to
        avoid double resolution.
        TODO(M8): Remove direct plugin dispatch after full migration.
        """
        # If integration was pre-resolved by caller, use direct plugin dispatch
        if api_key is not None or (config and len(config) > 0):
            if not self._registry.supports(service_type):
                logger.warning(f"No plugin registered for service type: {service_type}")
                return {
                    "success": False,
                    "error": f"Unknown service type: {service_type}",
                }
            plugin = self._registry.get(service_type)
            request = PluginExecutionRequest(
                action=action,
                params=params,
                integration=IntegrationConfiguration(
                    service_type=service_type,
                    api_key=api_key,
                    api_secret=api_secret,
                    config=config,
                    user_id=self._user_id,
                    agent_timezone=self._agent_timezone,
                ),
                context=PluginContext(
                    variables=context or {},
                    user_id=self._user_id,
                ) if context else None,
            )
            result = await plugin.execute(request)
            return result.to_dict()

        # Integration not pre-resolved — delegate to ToolRuntime
        import uuid as _uuid

        from voice_platform.runtime.tools.types import (
            ToolCaller,
            ToolCallerType,
            ToolDefinition,
            ToolExecutionRequest,
        )

        if not self._registry.supports(service_type):
            logger.warning(f"No plugin registered for service type: {service_type}")
            return {
                "success": False,
                "error": f"Unknown service type: {service_type}",
            }

        runtime = self._ensure_tool_runtime()
        definition = ToolDefinition(
            name=f"{service_type}.{action}",
            description="",
            schema={},
            service_type=service_type,
            action=action,
        )
        request = ToolExecutionRequest(
            arguments=params,
            caller=ToolCaller(
                caller_type=ToolCallerType.FLOW,
                user_id=self._user_id,
                conversation_id=str(context.get("conversation_id", "")) if context else "",
            ),
            execution_id=str(_uuid.uuid4()),
            integration_overrides=self._integration_overrides,
            agent_timezone=self._agent_timezone,
        )
        result = await runtime.execute(definition, request)
        return result.to_dict()
    
    # ── Direct Execution (no integration required) ──────────────────
    async def execute_direct_action(
        self,
        node_type: str,
        action: str,
        params: dict,
        context: dict = None,
    ) -> dict:
        """
        Execute actions that don't require an integration record.
        Used for node types like webhook, delay, condition, transfer_call.
        """
        context = context or {}
        resolved_params = self._resolve_templates(params, context)

        if node_type in {"trigger", "end", "end_call", "voicemail_detect"}:
            return {
                "success": True,
                "node_type": node_type,
                "note": "control-flow node; no external execution required",
            }

        # Conversation nodes are NOT instant no-ops — they represent a step
        # where the agent must converse with the caller before proceeding.
        # Return a blocking result so the graph executor pauses here instead
        # of immediately firing the next action node (Issue 11).
        if node_type == "conversation":
            prompt = resolved_params.get("prompt") or resolved_params.get("message") or ""
            return {
                "success": True,
                "node_type": node_type,
                "status": "blocking",
                "prompt": prompt,
                "note": "conversation node — pause graph and let the LLM converse before proceeding",
            }
        
        if node_type == "webhook" or node_type == "api_request":
            return await self._dispatch_plugin(
                "webhook", "request", dict(resolved_params),
                api_key=resolved_params.get("auth_header") or resolved_params.get("authorization"),
                config=resolved_params,
                context=context,
            )
        elif node_type == "delay":
            import asyncio
            delay_secs = int(resolved_params.get("delay_seconds", 0))
            delay_secs = min(delay_secs, 300)  # Cap at 5 minutes
            await asyncio.sleep(delay_secs)
            return {"success": True, "delayed_seconds": delay_secs}
        elif node_type == "condition":
            expression = resolved_params.get("expression") or resolved_params.get("condition", "")
            result = self._conditions.evaluate(expression, context)
            return {"success": True, "condition_met": result, "expression": expression}
        elif node_type == "llm_process":
            # LLM processing is handled by the main pipeline
            return {
                "success": True,
                "note": "LLM processing is handled by the conversation pipeline",
                "prompt": resolved_params.get("prompt", ""),
            }
        elif node_type == "notification":
            # Log as notification (could be extended to push notifications)
            logger.info(f"📢 Notification: {resolved_params.get('message', '')}")
            return {
                "success": True,
                "message": resolved_params.get("message", ""),
                "channel": resolved_params.get("channel", "log"),
            }
        elif node_type == "transfer_call":
            return await self._dispatch_plugin(
                "transfer_call", "transfer_call", dict(resolved_params),
                api_key=None, config={}, context=context,
            )
        elif node_type == "send_sms":
            from voice_platform.config import settings
            if settings.twilio_account_sid and settings.twilio_auth_token:
                return await self._dispatch_plugin(
                    "sms", "send_sms", dict(resolved_params),
                    api_key=settings.twilio_auth_token,
                    config={
                        "account_sid": settings.twilio_account_sid,
                        "from_number": settings.twilio_phone_number or "",
                    },
                    context=context,
                )
            return {"success": False, "error": "Twilio credentials not configured"}
        elif node_type == "send_email":
            from voice_platform.config import settings as _settings
            if _settings.smtp_host and _settings.smtp_password:
                return await self._dispatch_plugin(
                    "email", "send_email", dict(resolved_params),
                    api_key=_settings.smtp_password,
                    config={
                        "smtp_host": _settings.smtp_host,
                        "smtp_port": _settings.smtp_port,
                        "smtp_user": _settings.smtp_user,
                        "from_email": _settings.smtp_from_email or _settings.smtp_user,
                        "from_name": _settings.smtp_from_name,
                        "use_tls": _settings.smtp_use_tls,
                    },
                    context=context,
                )
            return {
                "success": False,
                "error": "Email requires an email integration to be configured",
            }
        else:
            return {"success": False, "error": f"Unknown direct action: {node_type}"}
    

    async def execute_single_step(
        self,
        step: dict,
        context: dict = None,
    ) -> dict:
        """
        Execute a single workflow step and return its result dict.
        
        Used by PlatformToolAction for in-call function calling where
        only one action needs to run at a time.
        
        Args:
            step: Step dict with keys: type/integration_id, action, params
            context: Call context for template variable resolution
        
        Returns:
            Result dict from the action execution
        """
        context = context or {}
        results = await self.execute_steps([step], context)
        if results and results[0].get("status") == "success":
            return results[0].get("result", {})
        elif results:
            raise RuntimeError(results[0].get("error", "Step execution failed"))
        return {}

    # ── Phase 3: Sandboxed Code Execution ───────────────────────────
    @staticmethod
    def _execute_sandboxed_code(
        code: str, language: str, context: dict
    ) -> dict:
        """
        Execute user-provided code in a restricted sandbox.

        Only pure computation is allowed — no file, network, or subprocess access.
        The code receives `context` as a read-only dict and must return a dict.
        """
        import ast
        import datetime as _dt
        import json as _json
        import math
        import random as _random
        import re as _re

        # Whitelist of safe builtins
        safe_globals = {
            "__builtins__": {
                "abs": abs, "all": all, "any": any, "bool": bool,
                "dict": dict, "float": float, "int": int, "len": len,
                "list": list, "max": max, "min": min, "range": range,
                "round": round, "set": set, "str": str, "sum": sum,
                "tuple": tuple, "type": type, "zip": zip,
                "Exception": Exception, "ValueError": ValueError,
            },
            "math": math,
            "re": _re,
            "json": _json,
            "datetime": _dt,
            "random": _random,
        }

        # Parse and validate AST — reject dangerous constructs
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (
                ast.Import, ast.ImportFrom, ast.With, ast.AsyncWith,
                ast.Try, ast.ExceptHandler, ast.Raise, ast.Delete,
                ast.Global, ast.Nonlocal, ast.ClassDef,
                ast.Attribute,
            )):
                raise ValueError(f"Disallowed construct: {type(node).__name__}")
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in (
                    "open", "exec", "eval", "compile", "__import__",
                    "input", "print", "exit", "quit",
                ):
                    raise ValueError(f"Disallowed function call: {func.id}")

        sandbox_locals: dict = {}
        exec(compile(tree, "<sandbox>", "exec"), safe_globals, sandbox_locals)

        # Look for a `main` function or return the last expression
        if "main" in sandbox_locals and callable(sandbox_locals["main"]):
            result = sandbox_locals["main"](dict(context))
        else:
            result = sandbox_locals.get("result", sandbox_locals)

        if not isinstance(result, dict):
            result = {"output": result}
        return result

    @staticmethod
    def _next_business_day(from_date):
        """Get the next weekday (Mon-Fri) after the given date."""
        next_day = from_date + timedelta(days=1)
        while next_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
            next_day += timedelta(days=1)
        return next_day
