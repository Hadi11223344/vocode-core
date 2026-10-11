"""
Compiler: React Flow JSON → LangGraph StateGraph.

Reads the graph JSON (nodes + edges) produced by the React Flow frontend
and builds a LangGraph StateGraph with:
- Nodes mapped to handler functions
- Edges mapped to direct or conditional connections
- Slot filling loops for conversation nodes
- Entry point set to the trigger node
"""

import hashlib
import time
from typing import Any, Callable, Dict, List, Optional

from langgraph.errors import GraphInterrupt
from langgraph.graph import END, StateGraph
from loguru import logger

from voice_platform.flow.nodes import create_node_handlers
from voice_platform.flow.state import FlowState, make_initial_state
from voice_platform.flow.tracer import Tracer, get_tracer
from voice_platform.graph_contracts import canonical_content_hash, edge_branch_key


class UnknownBranchError(Exception):
    """Raised when last_result.branch doesn't match any configured edge.

    Uses HMAC-SHA256 fingerprint to avoid leaking raw branch labels in logs,
    tracebacks, or diagnostics.
    """

    def __init__(self, node_id: str, branch_key: str):
        self._node_id = node_id
        self._branch_key = branch_key
        self._fingerprint = hashlib.sha256(
            f"{node_id}:{branch_key}".encode()
        ).hexdigest()[:12]
        super().__init__("UNKNOWN_BRANCH")

    def __str__(self) -> str:
        return f"UnknownBranchError(fingerprint={self._fingerprint})"


def _node_type(node: dict) -> str:
    data = node.get("data") or {}
    return str(data.get("nodeType") or node.get("type") or "action")


def _node_id(node: dict) -> str:
    return str(node.get("id", ""))


def _build_adjacency(graph: dict) -> tuple[dict[str, dict], dict[str, list]]:
    """Parse graph into nodes_by_id and outgoing edge maps."""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    nodes_by_id = {
        str(n.get("id")): n for n in nodes if n.get("id") is not None
    }

    outgoing: dict[str, list] = {}
    for n_id in nodes_by_id:
        outgoing[n_id] = []
    for edge in edges:
        src = str(edge.get("source")) if edge.get("source") is not None else None
        tgt = str(edge.get("target")) if edge.get("target") is not None else None
        if src and tgt and src in outgoing:
            # Ignore outgoing edges from terminal nodes (end / end_call).
            # These edges are a common source of unintended true cycles and
            # terminal nodes should never route further.
            if _node_type(nodes_by_id[src]) in ("end", "end_call"):
                logger.warning(
                    f"Ignoring outgoing edge from terminal node '{src}' to '{tgt}' — "
                    "end/end_call nodes should not have outgoing edges."
                )
                continue
            outgoing[src].append(edge)

    return nodes_by_id, outgoing


def _edge_branch_label(edge: dict) -> str:
    """Return the branch label for an edge from its sourceHandle or label."""
    return edge_branch_key(edge)


def _build_branch_targets(
    node_id: str, edges: list, nodes_by_id: dict[str, dict]
) -> tuple[list[str], dict[str, str]]:
    """Build ordered target list and branch-label -> target map for a node.

    Trigger nodes are skipped. Labels are normalized and the first target for a
    given label wins.
    """
    targets: list[str] = []
    branch_map: dict[str, str] = {}
    seen: set[str] = set()

    for edge in edges:
        tgt = str(edge.get("target")) if edge.get("target") is not None else None
        if not tgt or tgt not in nodes_by_id:
            continue
        # Never route into a trigger node
        if _node_type(nodes_by_id[tgt]) == "trigger":
            continue
        if tgt not in seen:
            seen.add(tgt)
            targets.append(tgt)
        label = _edge_branch_label(edge)
        if label and label not in branch_map:
            branch_map[label] = tgt

    return targets, branch_map


def _routing_branch_key(state: FlowState) -> str:
    """Return the normalized branch key from last_result.branch only.

    Never reads result.branch — that field is accumulated and may contain
    stale values from previous node executions.
    """
    last_result = state.get("last_result") or {}
    branch = last_result.get("branch")
    return str(branch).strip().lower() if branch else ""


def _state_snapshot(state: dict) -> dict:
    """Return a compact state view for redacted Tracer diagnostics."""
    slots = state.get("_slots") or {}
    return {
        "current_node": state.get("current_node", ""),
        "previous_node": state.get("previous_node", ""),
        "extracted_vars": dict(state.get("extracted_vars") or {}),
        "result": dict(state.get("result") or {}),
        "last_result": dict(state.get("last_result") or {}),
        "slots": {
            str(name): {
                "status": data.get("status"),
                "value": data.get("value"),
                "ask_count": data.get("ask_count", 0),
            }
            for name, data in slots.items()
            if isinstance(data, dict)
        },
        "slots_missing": list(state.get("_slots_missing") or []),
        "retry_count": state.get("retry_count", 0),
    }


def _preview_state_after(state: dict, update: dict) -> dict:
    """Preview reducer-relevant node updates for diagnostics only."""
    preview = dict(state)
    for merge_key in ("extracted_vars", "result"):
        existing = state.get(merge_key) or {}
        incoming = update.get(merge_key) or {}
        if isinstance(existing, dict) and isinstance(incoming, dict):
            preview[merge_key] = {**existing, **incoming}
    preview.update({
        key: value
        for key, value in update.items()
        if key not in {"extracted_vars", "result", "messages", "trace_events"}
    })
    return _state_snapshot(preview)


def _find_start_nodes(nodes_by_id: dict, outgoing: dict) -> List[str]:
    """Find trigger nodes or nodes with no incoming edges."""
    incoming = {n_id: 0 for n_id in nodes_by_id}
    for edges in outgoing.values():
        for edge in edges:
            tgt = str(edge.get("target")) if edge.get("target") is not None else None
            if tgt in incoming:
                incoming[tgt] += 1

    triggers = [
        n_id for n_id, node in nodes_by_id.items()
        if _node_type(node) == "trigger"
    ]
    if triggers:
        return triggers
    return [n_id for n_id, count in incoming.items() if count == 0]


def _detect_cycles(nodes_by_id: dict, outgoing: dict) -> tuple[List[str], List[str]]:
    """Detect cycles using DFS. Returns (true_cycles, conditional_retries)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n_id: WHITE for n_id in nodes_by_id}
    parent: Dict[str, str] = {}
    true_cycles: List[str] = []
    conditional_retries: List[str] = []

    def dfs(node_id: str) -> None:
        color[node_id] = GRAY
        for edge in outgoing.get(node_id, []):
            tgt = str(edge.get("target")) if edge.get("target") is not None else None
            if tgt and tgt in color:
                if color[tgt] == GRAY:
                    cycle_path = [tgt]
                    cur = node_id
                    while cur != tgt and cur in parent:
                        cycle_path.append(cur)
                        cur = parent[cur]
                    cycle_path.append(tgt)
                    has_slot_validator = any(
                        _node_type(nodes_by_id.get(c, {})) == "slot_validator"
                        for c in cycle_path
                    )
                    has_bounded_retry_condition = any(
                        _node_type(nodes_by_id.get(c, {})) == "condition"
                        and "_slot_retry_count" in str(
                            ((nodes_by_id.get(c, {}).get("data") or {}).get("config") or {}).get("expression", "")
                        )
                        for c in cycle_path
                    )
                    if has_slot_validator or has_bounded_retry_condition:
                        conditional_retries.append(tgt)
                    else:
                        true_cycles.append(tgt)
                elif color[tgt] == WHITE:
                    parent[tgt] = node_id
                    dfs(tgt)
        color[node_id] = BLACK

    for n_id in nodes_by_id:
        if color[n_id] == WHITE:
            dfs(n_id)
    return true_cycles, conditional_retries


# ── Builder cache ──────────────────────────────────────────────
# Cache the StateGraph builder (nodes/edges/wrappers added) by graph JSON hash.
# builder.compile(checkpointer=...) is called each time — this is cheap.
# The expensive part is _build_adjacency, _detect_cycles, add_node, add_edge.
_builder_cache: Dict[str, StateGraph] = {}


def make_branch_router(src_id: str, default: str | Any, branches: dict[str, str]):
    """Create a router that routes by last_result.branch with node_id matching.

    - If last_result.node_id matches src_id and branch is set, route to the
      matching branch target. Unknown branches raise UnknownBranchError.
    - If no branch is set, route by execution success: True → default,
      False → error branch if available, else END.
    - If node_id doesn't match, fall back to default.
    """
    def router(state: FlowState) -> str | Any:
        last_result = state.get("last_result") or {}
        if last_result.get("node_id") == src_id:
            branch_key = str(last_result.get("branch") or "").strip().lower()
            if branch_key:
                if branch_key in branches:
                    return branches[branch_key]
                if branch_key == "on_missing":
                    for err_key in ("error", "on_error", "failure"):
                        if err_key in branches:
                            logger.warning(
                                f"Legacy graph node '{src_id}' has no on_missing edge; "
                                f"using its {err_key} recovery edge."
                            )
                            return branches[err_key]
                raise UnknownBranchError(src_id, branch_key)
            if last_result.get("success") is True:
                return default
            if last_result.get("success") is False:
                for err_key in ("error", "on_error", "failure"):
                    if err_key in branches:
                        return branches[err_key]
                return END
        return default
    return router


def _build_state_graph(
    graph_json: dict,
    node_handlers: Dict[str, Callable],
) -> StateGraph:
    """Build a LangGraph StateGraph (builder) from graph JSON and handlers.

    Returns the builder (not compiled) so the caller can attach a checkpointer.
    """
    nodes_by_id, outgoing = _build_adjacency(graph_json)

    # M-11: Validate graph structure before compiling
    if not nodes_by_id:
        raise ValueError("Graph has no nodes")
    start_nodes = _find_start_nodes(nodes_by_id, outgoing)
    if not start_nodes:
        raise ValueError("Graph has no start node (trigger node with no incoming edges)")
    has_terminal = any(
        _node_type(node) in ("end", "end_call")
        for node in nodes_by_id.values()
    )
    if not has_terminal:
        logger.warning("Graph has no end/end_call node — flow may not terminate cleanly")

    # MEDIUM-11: Reject graphs with true cycles (non-conditional loops)
    true_cycles, conditional_retries = _detect_cycles(nodes_by_id, outgoing)
    if true_cycles:
        raise ValueError(
            f"Graph contains true cycles at nodes: {', '.join(true_cycles[:5])}. "
            f"Remove the cycle or use a condition node to break it."
        )
    if conditional_retries:
        logger.info(
            f"Graph has bounded retry loops at: {', '.join(conditional_retries[:5])}"
        )

    builder = StateGraph(FlowState)

    # Add all nodes to the graph
    for node_id, node in nodes_by_id.items():
        node_type = _node_type(node)

        # Map node type to handler
        if node_type == "conversation":
            handler = node_handlers["conversation"]
        elif node_type == "condition":
            handler = node_handlers["condition"]
        elif node_type == "slot_validator":
            handler = node_handlers["slot_validator"]
        elif node_type in ("trigger", "end", "end_call", "voicemail_detect", "note", "delay"):
            handler = node_handlers.get(node_type, node_handlers["action"])
        else:
            # All integration/action types
            handler = node_handlers["action"]

        # Wrap handler to set current_node before execution and emit edge transitions
        def make_wrapper(h, nid, outgoing_edges):
            async def wrapper(state: FlowState, config: dict) -> dict:
                previous_node = state.get("current_node", "")
                # Set current_node directly on the input dict so the handler sees
                # the updated state and any mutations it makes (e.g. response cache
                # writes before interrupt) are captured by the checkpointer.
                state["current_node"] = nid
                state["previous_node"] = previous_node

                # Phase 5.6: create a fresh tracer for this node execution.
                conf = config.get("configurable") or {}
                event_cb = conf.get("event_callback")
                tracer = Tracer(
                    event_callback=event_cb,
                    workflow_id=conf.get("workflow_id"),
                    conversation_id=conf.get("conversation_id"),
                    agent_id=conf.get("agent_id"),
                    thread_id=conf.get("thread_id"),
                )
                if "configurable" not in config:
                    config["configurable"] = {}
                config["configurable"]["_tracer"] = tracer

                node = state["nodes_by_id"].get(nid, {})
                node_data = node.get("data") or {}
                node_label = node_data.get("label", nid)
                node_type = _node_type(node)

                # Report the edge we are about to traverse (before handler, so
                # interrupted conversation nodes still highlight the incoming edge)
                branch_label = ""
                if previous_node and event_cb:
                    label = ""
                    for edge in outgoing_edges.get(previous_node, []):
                        if str(edge.get("target")) == nid:
                            label = str(edge.get("label") or edge.get("sourceHandle") or "")
                            branch_label = label
                            break
                    await event_cb({
                        "event": "edge_traversed",
                        "source": previous_node,
                        "target": nid,
                        "label": label,
                    })

                if previous_node:
                    await tracer.transition(
                        source=previous_node,
                        target=nid,
                        branch=branch_label or None,
                    )

                await tracer.emit(
                    "node_enter",
                    node_id=nid,
                    node_type=node_type,
                    label=node_label,
                    total_steps=state.get("total_steps", 0),
                    retry_count=state.get("retry_count", 0),
                    state_before=_state_snapshot(state),
                )

                t0 = time.time()
                try:
                    result = await h(state, config)
                except GraphInterrupt:
                    await tracer.emit(
                        "node_exit",
                        node_id=nid,
                        node_type=node_type,
                        label=node_label,
                        status="interrupted",
                        duration_ms=round((time.time() - t0) * 1000, 1),
                        total_steps=state.get("total_steps", 0),
                        retry_count=state.get("retry_count", 0),
                    )
                    raise
                except Exception as exc:
                    await tracer.emit(
                        "node_exit",
                        node_id=nid,
                        node_type=node_type,
                        label=node_label,
                        status="error",
                        error=str(exc)[:500],
                        duration_ms=round((time.time() - t0) * 1000, 1),
                        total_steps=state.get("total_steps", 0),
                        retry_count=state.get("retry_count", 0),
                    )
                    raise

                duration_ms = round((time.time() - t0) * 1000, 1)
                await tracer.emit(
                    "node_exit",
                    node_id=nid,
                    node_type=node_type,
                    label=node_label,
                    status="success",
                    duration_ms=duration_ms,
                    total_steps=state.get("total_steps", 0),
                    retry_count=state.get("retry_count", 0),
                    state_updates={
                        key: value
                        for key, value in result.items()
                        if key not in {"messages", "trace_events"}
                    },
                    state_after=_preview_state_after(state, result),
                )

                # Persist current_node so the next node can determine the edge it came from
                return {**result, "current_node": nid, "trace_events": tracer.events}
            return wrapper

        builder.add_node(node_id, make_wrapper(handler, node_id, outgoing))

    # Add edges
    start_nodes = _find_start_nodes(nodes_by_id, outgoing)

    if len(start_nodes) > 1:
        logger.warning(
            f"Graph has {len(start_nodes)} start nodes: {start_nodes}. "
            f"Using first as entry point: {start_nodes[0]}"
        )

    # Set entry point
    if start_nodes:
        builder.set_entry_point(start_nodes[0])

    for node_id, node in nodes_by_id.items():
        node_type = _node_type(node)
        edges = outgoing.get(node_id, [])

        if node_type in ("end", "end_call"):
            # Terminal nodes — no outgoing edges
            builder.add_edge(node_id, END)
            continue

        if not edges:
            # No outgoing edges — connect to END
            builder.add_edge(node_id, END)
            continue

        if node_type == "condition":
            # Condition nodes: use conditional edges based on _condition_met
            # Map edges by label/handle to yes/no branches
            yes_targets = []
            no_targets = []
            other_targets = []

            for edge in edges:
                tgt = str(edge.get("target")) if edge.get("target") else None
                if not tgt or tgt not in nodes_by_id:
                    continue
                source_handle = str(edge.get("sourceHandle") or "").strip().lower()
                label = str(edge.get("label") or "").strip().lower()

                if source_handle in ("yes", "true") or label in ("yes", "true"):
                    yes_targets.append(tgt)
                elif source_handle in ("no", "false") or label in ("no", "false"):
                    no_targets.append(tgt)
                else:
                    other_targets.append(tgt)

            # Emit edge_traversed events via a routing function
            def make_condition_router(yes_list, no_list, other_list, src_id):
                def router(state: FlowState) -> str | list[str]:
                    condition_met = state.get("_condition_met", False)
                    if condition_met and yes_list:
                        return yes_list[0]
                    elif not condition_met and no_list:
                        return no_list[0]
                    elif other_list:
                        return other_list[0]
                    elif yes_list:
                        return yes_list[0]
                    elif no_list:
                        return no_list[0]
                    # M-12: Warn when condition node falls through to END
                    logger.warning(
                        f"Condition node '{src_id}' has no matching branch — falling through to END"
                    )
                    return END
                return router

            router = make_condition_router(yes_targets, no_targets, other_targets, node_id)
            path_map = {target: target for target in (yes_targets + no_targets + other_targets)}
            builder.add_conditional_edges(
                node_id,
                router,
                path_map=path_map,
            )

        elif node_type == "slot_validator":
            # Slot validator nodes: route by result.branch (slot name, "done", "exhausted")
            # Uses the same branch-based routing as action nodes.
            targets, branch_map = _build_branch_targets(node_id, edges, nodes_by_id)
            default_target = targets[0] if targets else END

            if len(targets) <= 1 and not branch_map:
                builder.add_edge(node_id, default_target)
            else:
                def make_slot_validator_router(default: str | Any, branches: dict[str, str]):
                    def router(state: FlowState) -> str | Any:
                        branch_key = _routing_branch_key(state)
                        if branch_key and branch_key in branches:
                            return branches[branch_key]
                        return default
                    return router

                router = make_slot_validator_router(default_target, branch_map)
                path_map = {target: target for target in targets}
                builder.add_conditional_edges(
                    node_id,
                    router,
                    path_map=path_map,
                )

        elif node_type == "conversation":
            # Conversation nodes: extraction happens inside the handler after interrupt().
            # If slots are still missing, the handler returns _slots_missing and the
            # graph loops back to the same conversation node. Otherwise it routes using
            # result.branch or falls back to the primary (first) outgoing edge.
            targets, branch_map = _build_branch_targets(node_id, edges, nodes_by_id)
            default_target = targets[0] if targets else END

            def make_conversation_router(
                nid: str, default: str | Any, branches: dict[str, str]
            ):
                def router(state: FlowState) -> str | Any:
                    # Two-phase conversation node: after the generate phase returns
                    # _conversation_phase="wait", re-enter the same node to run the
                    # wait phase. After the wait phase completes, loop only if there
                    # are still missing slots with retry budget remaining.
                    if state.get("_conversation_phase") == "wait":
                        return nid
                    missing = state.get("_slots_missing", [])
                    retry = state.get("retry_count", 0)
                    _mr = state.get("max_retries", 0) or 0
                    max_retries = _mr if _mr > 0 else (len(state.get("pending_variables_to_extract", [])) or 2)
                    if missing and retry < max_retries:
                        return nid
                    branch_key = _routing_branch_key(state)
                    if branch_key and branch_key in branches:
                        return branches[branch_key]
                    return default
                return router

            router = make_conversation_router(node_id, default_target, branch_map)
            path_map = {node_id: node_id, **{target: target for target in targets}}
            builder.add_conditional_edges(
                node_id,
                router,
                path_map=path_map,
            )

        else:
            # Action, trigger, delay, note nodes: route by last_result.branch
            # when node_id matches, otherwise fall back to default.
            targets, branch_map = _build_branch_targets(node_id, edges, nodes_by_id)
            default_target = targets[0] if targets else END

            if len(targets) <= 1 and not branch_map:
                builder.add_edge(node_id, default_target)
            else:
                router = make_branch_router(node_id, default_target, branch_map)
                path_map = {target: target for target in targets}
                builder.add_conditional_edges(
                    node_id,
                    router,
                    path_map=path_map,
                )

    logger.info(
        f"Built flow graph: {len(nodes_by_id)} nodes, "
        f"entry={start_nodes[0] if start_nodes else 'none'}"
    )

    return builder


def _get_or_build_builder(graph_json: dict) -> StateGraph:
    """Get a cached StateGraph builder or build a new one.

    The builder is cached by graph JSON hash. Handlers are created internally
    via create_node_handlers() (no instance-specific deps).
    """
    graph_hash = canonical_content_hash(graph_json, length=64)
    if graph_hash is None:
        raise ValueError("Graph is empty")
    if graph_hash not in _builder_cache:
        logger.info(f"Building new flow graph builder (hash={graph_hash[:8]})")
        handlers = create_node_handlers()
        _builder_cache[graph_hash] = _build_state_graph(graph_json, handlers)
    else:
        logger.debug(f"Reusing cached flow graph builder (hash={graph_hash[:8]})")
    return _builder_cache[graph_hash]


def compile_flow(
    graph_json: dict,
    checkpointer=None,
    node_handlers: Optional[Dict[str, Callable]] = None,
) -> StateGraph:
    """Compile a React Flow graph JSON into a LangGraph StateGraph.

    Args:
        graph_json: The graph dict with "nodes" and "edges" keys
        checkpointer: Optional LangGraph checkpointer for persistence
        node_handlers: Optional dict mapping node type → async handler function.
            If None, handlers are created internally via create_node_handlers()
            and the builder is cached by graph JSON hash (production path).
            If provided, a fresh builder is created without caching (test path).

    Returns:
        Compiled LangGraph StateGraph ready for invocation
    """
    if node_handlers is not None:
        builder = _build_state_graph(graph_json, node_handlers)
    else:
        builder = _get_or_build_builder(graph_json)

    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    compiled = builder.compile(**compile_kwargs)

    logger.info(f"Compiled flow graph: {len(builder.nodes)} nodes")

    return compiled


def create_initial_state(
    graph_json: dict,
    user_id: int,
    agent_id: int,
    agent_timezone: str = "",
    caller_name: str = "",
    caller_phone: str = "",
    max_retries: int = 0,
) -> FlowState:
    """Create initial FlowState with graph structure injected."""
    nodes_by_id, outgoing = _build_adjacency(graph_json)
    return make_initial_state(
        user_id=user_id,
        agent_id=agent_id,
        agent_timezone=agent_timezone,
        caller_name=caller_name,
        caller_phone=caller_phone,
        nodes_by_id=nodes_by_id,
        outgoing=outgoing,
        max_retries=max_retries,
    )


def get_cycle_warnings(graph_json: dict) -> tuple[List[str], List[str]]:
    """Get cycle warnings for the graph. Returns (true_cycles, conditional_retries)."""
    nodes_by_id, outgoing = _build_adjacency(graph_json)
    return _detect_cycles(nodes_by_id, outgoing)
