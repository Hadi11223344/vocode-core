"""Pure helpers for graph identity and runtime branch contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


_NON_ACTION_NODE_TYPES = {
    "condition",
    "conversation",
    "delay",
    "end",
    "end_call",
    "note",
    "slot_validator",
    "trigger",
    "voicemail_detect",
}


def canonical_content_hash(value: Any, *, length: int = 16) -> str | None:
    """Return a stable SHA-256 fingerprint without exposing source content."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    else:
        payload = str(value)
    if not payload:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def edge_branch_key(edge: dict) -> str:
    """Normalize a React Flow source handle or edge label to a runtime key."""
    raw = edge.get("sourceHandle") or edge.get("label") or ""
    normalized = re.sub(r"\s+", " ", str(raw).strip().lower())
    aliases = {
        "missing info": "on_missing",
        "missing input": "on_missing",
        "missing inputs": "on_missing",
        "on missing": "on_missing",
        "on error": "on_error",
    }
    return aliases.get(normalized, normalized)


def required_input_branch_violations(graph: dict) -> list[dict[str, Any]]:
    """Find action-like nodes that can emit ``on_missing`` without that edge."""
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    edges = graph.get("edges") if isinstance(graph, dict) else None
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return []

    branches_by_source: dict[str, list[str]] = {}
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("source") is None:
            continue
        source = str(edge["source"])
        branch = edge_branch_key(edge)
        if branch:
            branches_by_source.setdefault(source, []).append(branch)

    violations: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        data = node.get("data") or {}
        config = data.get("config") or {}
        required_inputs = config.get("required_inputs")
        node_type = str(data.get("nodeType") or node.get("type") or "action")
        if (
            node_type in _NON_ACTION_NODE_TYPES
            or not isinstance(required_inputs, list)
            or not required_inputs
        ):
            continue

        node_id = str(node["id"])
        branches = branches_by_source.get(node_id, [])
        if branches.count("on_missing") != 1:
            violations.append(
                {
                    "node_id": node_id,
                    "node_type": node_type,
                    "required_inputs": [str(item) for item in required_inputs],
                    "on_missing_edges": branches.count("on_missing"),
                }
            )
    return violations


def add_missing_input_fallback_edges(
    graph: dict,
) -> tuple[dict, list[dict[str, str]]]:
    """Clone each action's error edge as an explicit ``on_missing`` edge.

    The returned graph is a deep copy. Nodes without an error recovery edge are
    left unchanged so callers can reject them instead of guessing a safe target.
    """
    repaired = copy.deepcopy(graph)
    edges = repaired.get("edges") if isinstance(repaired, dict) else None
    if not isinstance(edges, list):
        return repaired, []

    existing_ids = {
        str(edge["id"])
        for edge in edges
        if isinstance(edge, dict) and edge.get("id") is not None
    }
    repairs: list[dict[str, str]] = []

    for violation in required_input_branch_violations(repaired):
        node_id = violation["node_id"]
        error_edge = next(
            (
                edge
                for edge in edges
                if isinstance(edge, dict)
                and str(edge.get("source")) == node_id
                and edge_branch_key(edge) in {"error", "on_error", "failure"}
                and edge.get("target") is not None
            ),
            None,
        )
        if error_edge is None:
            continue

        target = str(error_edge["target"])
        edge_id_base = f"e-{node_id}-on_missing-{target}"
        edge_id = edge_id_base
        suffix = 2
        while edge_id in existing_ids:
            edge_id = f"{edge_id_base}-{suffix}"
            suffix += 1
        existing_ids.add(edge_id)

        missing_edge = copy.deepcopy(error_edge)
        missing_edge.update(
            {
                "id": edge_id,
                "source": node_id,
                "sourceHandle": "on_missing",
                "target": target,
                "label": "Missing info",
            }
        )
        edges.append(missing_edge)
        repairs.append({"node_id": node_id, "target": target, "edge_id": edge_id})

    return repaired, repairs
