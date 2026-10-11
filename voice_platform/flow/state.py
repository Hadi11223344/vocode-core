"""
FlowState schema for LangGraph-based flow execution.

Defines the typed state that flows through the LangGraph StateGraph,
replacing the unstructured dict used by the old FlowPlaygroundConversation.
"""

from typing import Annotated, Any, TypedDict

from langgraph.graph import add_messages


def merge_dicts(left: dict, right: dict) -> dict:
    """LangGraph reducer for dict fields — merges instead of replacing."""
    if left is None:
        left = {}
    if right is None:
        right = {}
    return {**left, **right}


_TRANSIENT_RESULT_KEYS = frozenset(
    {
        "branch",
        "error",
        "missing_inputs",
        "collected_inputs",
        "condition_met",
        "expression",
    }
)


def merge_result(left: dict, right: dict) -> dict:
    """Reducer for result dict — strips transient keys from BOTH sides.

    Unlike merge_dicts, this removes transient execution metadata (branch,
    error, status, etc.) from both the accumulated state and the incoming
    update. This prevents stale branch values from surviving across retries.
    """
    if left is None:
        left = {}
    if right is None:
        right = {}
    cleaned_left = {
        key: value
        for key, value in left.items()
        if key not in _TRANSIENT_RESULT_KEYS
    }
    cleaned_right = {
        key: value
        for key, value in right.items()
        if key not in _TRANSIENT_RESULT_KEYS
    }
    return {**cleaned_left, **cleaned_right}


def merge_lists(left: list, right: list) -> list:
    """LangGraph reducer for list fields — appends without replacing."""
    if left is None:
        left = []
    if right is None:
        right = []
    return list(left) + list(right)


class FlowState(TypedDict):
    # Flat extracted variables for {{template}} substitution
    # Uses merge_dicts reducer so node returns accumulate rather than replace
    extracted_vars: Annotated[dict[str, Any], merge_dicts]

    # Conversation messages (LangGraph add_messages reducer)
    messages: Annotated[list, add_messages]

    # Control flow
    current_node: str
    previous_node: str
    _condition_met: bool
    pending_variables_to_extract: list[str]
    _slots_missing: list[str]
    # L-9: retry_count tracks how many times the current conversation node has
    # re-asked for missing slots. Reset to 0 when proceeding to the next node.
    retry_count: int
    max_retries: int
    # L-9: _slot_retry_count is a legacy counter; _slot_retry_tracker is the
    # active per-variable tracker that limits each variable to 2 re-ask attempts.
    _slot_retry_count: int
    _slot_retry_tracker: dict
    _retry_context: str
    # Schema-driven slot tracking (Phase 5.2); underscore-prefixed to avoid
    # conflicting with M-6 guardrail that removed a public `slots` field.
    _slots: dict
    _slot_history: list[str]
    # Phase A/B: split conversation node into generate and wait phases within the
    # same graph node. "generate" runs the LLM and returns; "wait" calls interrupt.
    _conversation_phase: str
    _initial_message_sent: bool
    # Which conversation node currently owns the slot retry budget. Must be
    # persisted across generate/wait re-entries so retry_count is not reset.
    _slot_owner_node: str

    # Context (mirrors the old self.context dict)
    transcript: str
    caller_name: str
    caller_phone: str
    user_id: int
    agent_id: int
    agent_timezone: str

    # Results from action/condition nodes
    # Uses merge_result reducer so transient keys (branch, error, etc.) are
    # stripped from BOTH accumulated and incoming dicts, preventing stale
    # branch values from surviving across retries.
    last_result: dict
    result: Annotated[dict, merge_result]

    # Retry scope tracking — per-action scoped retry counters
    _active_retry_scope: str
    _slot_retry_counts: dict

    # Business outcome — authoritative truth about integration results
    business_outcome: dict

    # Graph structure (injected at compile time, read-only at runtime)
    nodes_by_id: dict
    outgoing: dict

    # Response cache for conversation nodes (persists via checkpointer)
    # Uses merge_dicts reducer so cache entries accumulate across nodes
    _response_cache: Annotated[dict, merge_dicts]

    # Event callback reference (stored as string key, resolved by executor)
    total_steps: int

    # Phase 5.6: Structured trace events emitted by handlers for observability
    trace_events: Annotated[list[dict], merge_lists]

    # Serialized SlotEngine state — persisted via checkpointer across turns.
    # Reconstructed via SlotEngine.from_dict() in slot_validator/collector handlers.
    _slot_engine: dict


def make_initial_state(
    user_id: int,
    agent_id: int,
    agent_timezone: str = "",
    caller_name: str = "",
    caller_phone: str = "",
    nodes_by_id: dict = None,
    outgoing: dict = None,
    max_retries: int = 0,
) -> FlowState:
    """Create the initial FlowState for a new flow session."""
    return FlowState(
        extracted_vars={},
        messages=[],
        current_node="",
        previous_node="",
        _condition_met=False,
        pending_variables_to_extract=[],
        _slots_missing=[],
        retry_count=0,
        max_retries=max_retries,
        _slot_retry_count=0,
        _slot_retry_tracker={},
        _retry_context="",
        _slots={},
        _slot_history=[],
        _conversation_phase="generate",
        _initial_message_sent=False,
        _slot_owner_node="",
        transcript="",
        caller_name=caller_name,
        caller_phone=caller_phone,
        user_id=user_id,
        agent_id=agent_id,
        agent_timezone=agent_timezone,
        last_result={},
        result={},
        nodes_by_id=nodes_by_id or {},
        outgoing=outgoing or {},
        _response_cache={},
        total_steps=0,
        trace_events=[],
        _slot_engine={},
        _active_retry_scope="",
        _slot_retry_counts={},
        business_outcome={
            "availability": "not_checked",
            "booking": "not_attempted",
            "email": "not_attempted",
            "patient_log": "not_attempted",
            "overall": "in_progress",
        },
    )
