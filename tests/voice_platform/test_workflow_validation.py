"""Phase 7: Backend graph validation tests for the flow compiler."""

import pytest

from voice_platform.flow.compiler import (
    _build_adjacency,
    _detect_cycles,
    _find_start_nodes,
    compile_flow,
)


def test_build_adjacency_ignores_terminal_outgoing_edges():
    """Outgoing edges from end/end_call nodes should be discarded."""
    graph = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "end", "data": {"nodeType": "end"}},
            {"id": "n1", "data": {"nodeType": "conversation"}},
        ],
        "edges": [
            {"source": "trigger", "target": "n1"},
            {"source": "end", "target": "n1"},  # should be ignored
        ],
    }
    nodes_by_id, outgoing = _build_adjacency(graph)
    assert "n1" in [e["target"] for e in outgoing["trigger"]]
    assert outgoing["end"] == []


def test_find_start_nodes_prefers_trigger():
    """_find_start_nodes should return trigger nodes when present."""
    graph = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "n1", "data": {"nodeType": "conversation"}},
        ],
        "edges": [
            {"source": "n1", "target": "trigger"},  # trigger has incoming edge
            {"source": "trigger", "target": "n1"},
        ],
    }
    nodes_by_id, outgoing = _build_adjacency(graph)
    starts = _find_start_nodes(nodes_by_id, outgoing)
    assert starts == ["trigger"]


def test_detect_cycles_true_cycle_rejected():
    """A cycle with no condition node should be reported as a true cycle."""
    graph = {
        "nodes": [
            {"id": "a", "data": {"nodeType": "conversation"}},
            {"id": "b", "data": {"nodeType": "conversation"}},
        ],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ],
    }
    nodes_by_id, outgoing = _build_adjacency(graph)
    true_cycles, conditional = _detect_cycles(nodes_by_id, outgoing)
    assert true_cycles
    assert not conditional


def test_detect_cycles_bounded_conditional_cycle_allowed():
    """A condition cycle is allowed only when its retry counter is bounded."""
    graph = {
        "nodes": [
            {"id": "a", "data": {"nodeType": "conversation"}},
            {
                "id": "b",
                "data": {
                    "nodeType": "condition",
                    "config": {"expression": "_slot_retry_count < 2"},
                },
            },
        ],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ],
    }
    nodes_by_id, outgoing = _build_adjacency(graph)
    true_cycles, conditional = _detect_cycles(nodes_by_id, outgoing)
    assert not true_cycles
    assert conditional


def test_detect_cycles_unbounded_condition_is_rejected():
    graph = {
        "nodes": [
            {"id": "a", "data": {"nodeType": "conversation"}},
            {"id": "b", "data": {"nodeType": "condition", "config": {"expression": "available == false"}}},
        ],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ],
    }
    nodes_by_id, outgoing = _build_adjacency(graph)

    true_cycles, conditional = _detect_cycles(nodes_by_id, outgoing)

    assert true_cycles
    assert not conditional


def _dummy_handlers():
    async def noop(_state, _config):
        return {}
    return {
        "action": noop,
        "conversation": noop,
        "condition": noop,
        "trigger": noop,
        "end": noop,
    }


def test_compile_flow_rejects_true_cycle():
    """compile_flow should raise ValueError for a graph with a true cycle."""
    graph = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "a", "data": {"nodeType": "conversation"}},
            {"id": "b", "data": {"nodeType": "conversation"}},
        ],
        "edges": [
            {"source": "trigger", "target": "a"},
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ],
    }
    with pytest.raises(ValueError, match="true cycles"):
        compile_flow(graph, node_handlers={})


def test_compile_flow_allows_bounded_conditional_cycle():
    """compile_flow should accept a cycle with an explicit retry bound."""
    graph = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "a", "data": {"nodeType": "conversation"}},
            {
                "id": "b",
                "data": {
                    "nodeType": "condition",
                    "config": {"expression": "_slot_retry_count < 2"},
                },
            },
        ],
        "edges": [
            {"source": "trigger", "target": "a"},
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ],
    }
    compiled = compile_flow(graph, node_handlers=_dummy_handlers())
    assert compiled is not None
