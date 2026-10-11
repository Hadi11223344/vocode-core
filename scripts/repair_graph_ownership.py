#!/usr/bin/env python3
"""Repair canonical workflow ownership and missing-input branch contracts.

The Workflow graph is treated as canonical. The command repairs recoverable
``on_missing`` contracts, mirrors that exact revision onto the linked Agent,
and sets both ownership foreign keys in one database transaction.

Usage:
    python scripts/repair_graph_ownership.py --workflow-id 11
    python scripts/repair_graph_ownership.py --workflow-id 11 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from voice_platform.database import Agent, Workflow, async_session
from voice_platform.graph_contracts import (
    add_missing_input_fallback_edges,
    canonical_content_hash,
    edge_branch_key,
    required_input_branch_violations,
)


def _parse_graph(raw: str | dict | None, *, owner: str) -> dict:
    if isinstance(raw, dict):
        graph = raw
    elif isinstance(raw, str):
        try:
            graph = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{owner} graph is not valid JSON") from exc
    else:
        raise ValueError(f"{owner} has no graph")
    if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise ValueError(f"{owner} graph must contain nodes and edges arrays")
    return graph


def _edge_signature(edge: dict) -> tuple[str, str, str]:
    return (
        str(edge.get("source") or ""),
        str(edge.get("target") or ""),
        edge_branch_key(edge),
    )


def _assert_safe_convergence(agent_graph: dict, repaired_workflow_graph: dict) -> None:
    """Reject convergence if the live graph contains unrelated editor changes."""
    agent_without_edges = {key: value for key, value in agent_graph.items() if key != "edges"}
    workflow_without_edges = {
        key: value for key, value in repaired_workflow_graph.items() if key != "edges"
    }
    if agent_without_edges != workflow_without_edges:
        raise ValueError(
            "Agent and Workflow differ outside edges; refusing to choose a revision automatically"
        )

    repaired_signatures = {
        _edge_signature(edge)
        for edge in repaired_workflow_graph["edges"]
        if isinstance(edge, dict)
    }
    live_only = [
        edge
        for edge in agent_graph["edges"]
        if isinstance(edge, dict) and _edge_signature(edge) not in repaired_signatures
    ]
    if live_only:
        raise ValueError(
            "Agent has live-only edges unrelated to contract repair; refusing to overwrite them"
        )


def _write_backup(workflow: Workflow, agent: Agent, workflow_graph: dict, agent_graph: dict) -> Path:
    backup_dir = PROJECT_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"graph_ownership_wf{workflow.id}_agent{agent.id}_{timestamp}.json"
    payload = {
        "timestamp": timestamp,
        "workflow_id": workflow.id,
        "agent_id": agent.id,
        "workflow_graph_hash": canonical_content_hash(workflow_graph, length=64),
        "agent_graph_hash": canonical_content_hash(agent_graph, length=64),
        "workflow_graph": workflow_graph,
        "agent_graph": agent_graph,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


async def repair(workflow_id: int, *, apply: bool) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Workflow).where(Workflow.id == workflow_id).with_for_update()
        )
        workflow = result.scalar_one_or_none()
        if workflow is None:
            raise ValueError(f"Workflow #{workflow_id} was not found")
        if workflow.agent_id is None:
            raise ValueError(f"Workflow #{workflow_id} has no assigned agent")

        agent = await db.get(Agent, workflow.agent_id, with_for_update=True)
        if agent is None:
            raise ValueError(f"Agent #{workflow.agent_id} was not found")
        if agent.user_id != workflow.user_id:
            raise ValueError("Workflow and Agent owners do not match")

        workflow_graph = _parse_graph(workflow.graph_json, owner=f"Workflow #{workflow.id}")
        agent_graph = _parse_graph(agent.graph_json, owner=f"Agent #{agent.id}")
        repaired_graph, repairs = add_missing_input_fallback_edges(workflow_graph)
        violations = required_input_branch_violations(repaired_graph)
        if violations:
            nodes = ", ".join(item["node_id"] for item in violations)
            raise ValueError(
                f"Nodes still lack a recoverable on_missing contract: {nodes}"
            )

        _assert_safe_convergence(agent_graph, repaired_graph)

        old_workflow_hash = canonical_content_hash(workflow_graph)
        old_agent_hash = canonical_content_hash(agent_graph)
        new_hash = canonical_content_hash(repaired_graph)
        print(f"Workflow #{workflow.id} -> Agent #{agent.id}")
        print(f"  workflow hash: {old_workflow_hash}")
        print(f"  agent hash:    {old_agent_hash}")
        print(f"  canonical:     {new_hash}")
        print(f"  repairs:       {len(repairs)}")
        for item in repairs:
            print(f"    {item['node_id']}:on_missing -> {item['target']}")

        if not apply:
            print("  status:        DRY RUN")
            return

        backup_path = _write_backup(
            workflow, agent, workflow_graph=workflow_graph, agent_graph=agent_graph
        )
        serialized = json.dumps(repaired_graph, ensure_ascii=False)
        workflow.graph_json = serialized
        agent.graph_json = serialized
        workflow.agent_id = agent.id
        agent.workflow_id = workflow.id
        agent.mode = "conversational_flow"
        agent.transition_flexibility = workflow.transition_flexibility or "flex"

        await db.flush()
        if agent.workflow_id != workflow.id or agent.graph_json != workflow.graph_json:
            await db.rollback()
            raise RuntimeError("Post-write ownership verification failed")
        await db.commit()
        print(f"  backup:        {os.path.relpath(backup_path, PROJECT_ROOT)}")
        print("  status:        COMMITTED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(repair(args.workflow_id, apply=args.apply))


if __name__ == "__main__":
    main()
