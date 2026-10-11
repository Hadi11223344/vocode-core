"""Unit tests for graph identity and on_missing branch contracts."""

from voice_platform.graph_contracts import (
    add_missing_input_fallback_edges,
    canonical_content_hash,
    edge_branch_key,
    required_input_branch_violations,
)


def _action_graph(*, with_on_missing: bool = False) -> dict:
    edges = [
        {"id": "e-success", "source": "action_1", "target": "next"},
        {"id": "e-error", "source": "action_1", "sourceHandle": "error", "target": "recover", "label": "error"},
    ]
    if with_on_missing:
        edges.append(
            {
                "id": "e-missing",
                "source": "action_1",
                "sourceHandle": "on_missing",
                "target": "recover",
                "label": "Missing info",
            }
        )
    return {
        "nodes": [
            {
                "id": "action_1",
                "type": "google_sheets",
                "data": {
                    "nodeType": "google_sheets",
                    "config": {"required_inputs": ["patient_name"]},
                },
            },
            {"id": "next", "type": "end", "data": {"nodeType": "end"}},
            {"id": "recover", "type": "conversation", "data": {"nodeType": "conversation"}},
        ],
        "edges": edges,
    }


def test_edge_branch_key_aliases_missing_info_labels():
    assert edge_branch_key({"sourceHandle": "on_missing"}) == "on_missing"
    assert edge_branch_key({"label": "Missing info"}) == "on_missing"
    assert edge_branch_key({"label": "on error"}) == "on_error"


def test_required_input_branch_violations_detects_missing_edge():
    violations = required_input_branch_violations(_action_graph(with_on_missing=False))
    assert len(violations) == 1
    assert violations[0]["node_id"] == "action_1"
    assert violations[0]["on_missing_edges"] == 0


def test_required_input_branch_violations_accepts_exact_one_edge():
    assert required_input_branch_violations(_action_graph(with_on_missing=True)) == []


def test_add_missing_input_fallback_edges_clones_error_target():
    repaired, repairs = add_missing_input_fallback_edges(_action_graph(with_on_missing=False))
    assert repairs == [
        {
            "node_id": "action_1",
            "target": "recover",
            "edge_id": "e-action_1-on_missing-recover",
        }
    ]
    assert required_input_branch_violations(repaired) == []
    assert canonical_content_hash(repaired) != canonical_content_hash(
        _action_graph(with_on_missing=False)
    )
