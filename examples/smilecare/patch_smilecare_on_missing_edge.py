#!/usr/bin/env python3
"""
Patch SmileCare graphs so action_1 emits a recoverable on_missing branch.

When a Workflow is linked via Agent.workflow_id or Workflow.agent_id, this
script updates both graphs and sets ownership so Save & Test cannot reintroduce
split-brain revisions.

Usage:
    python examples/smilecare/patch_smilecare_on_missing_edge.py --list
    python examples/smilecare/patch_smilecare_on_missing_edge.py --agent-id N --dry-run
    python examples/smilecare/patch_smilecare_on_missing_edge.py --agent-id N --apply
    python examples/smilecare/patch_smilecare_on_missing_edge.py --agent-id N --verify

Prefer scripts/repair_graph_ownership.py for full required_input contract repair.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from voice_platform.database import async_session, Agent, Workflow
from sqlalchemy import select

# ── Constants ───────────────────────────────────────────────────────────────

REQUIRED_NODES = [
    "action_1",
    "conversation_contact",
    "condition_patient_found",
    "action_2",
    "action_3",
    "condition_1",
    "end_1",
]

EDGE_TO_ADD = {
    "source": "action_1",
    "sourceHandle": "on_missing",
    "target": "conversation_contact",
    "label": "Missing info",
}

BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _graph_hash(graph: dict) -> str:
    """SHA-256 hash of canonical JSON (sorted keys, UTF-8)."""
    canonical = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_graph(agent: Agent) -> dict | None:
    """Parse agent.graph_json into a dict. Return None on failure."""
    raw = agent.graph_json
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    if isinstance(raw, dict):
        return raw
    return None


def _get_node_ids(graph: dict) -> set:
    return {n.get("id") for n in graph.get("nodes", []) if isinstance(n, dict)}


def _get_action1_on_missing_edges(graph: dict) -> list:
    """Find all edges from action_1 with sourceHandle == 'on_missing'."""
    edges = graph.get("edges", [])
    return [
        e for e in edges
        if isinstance(e, dict)
        and e.get("source") == "action_1"
        and e.get("sourceHandle") == "on_missing"
    ]


def _build_branch_map(graph: dict, node_id: str) -> dict:
    """Build the branch map the compiler would produce for a node."""
    from voice_platform.flow.compiler import _build_adjacency, _build_branch_targets
    nodes_by_id, outgoing = _build_adjacency(graph)
    edges = outgoing.get(node_id, [])
    _, branch_map = _build_branch_targets(node_id, edges, nodes_by_id)
    return branch_map


def _validate_graph(graph: dict) -> tuple[bool, str]:
    """Validate the graph has the required SmileCare structure."""
    if not isinstance(graph, dict):
        return False, "graph is not a dict"
    if not isinstance(graph.get("nodes"), list):
        return False, "nodes is not a list"
    if not isinstance(graph.get("edges"), list):
        return False, "edges is not a list"
    node_ids = _get_node_ids(graph)
    missing = [n for n in REQUIRED_NODES if n not in node_ids]
    if missing:
        return False, f"missing required nodes: {missing}"
    return True, "ok"


def _inspect_existing(graph: dict) -> tuple[str, list]:
    """Inspect existing action_1:on_missing edges. Return (status, edges)."""
    existing = _get_action1_on_missing_edges(graph)
    if len(existing) == 0:
        return "ELIGIBLE", []
    if len(existing) > 1:
        return "INVALID_GRAPH", existing
    # Exactly one
    if existing[0].get("target") == "conversation_contact":
        return "ALREADY_FIXED", existing
    return "CONFLICT", existing


def _write_backup(agent: Agent, graph: dict, original_hash: str) -> str | None:
    """Write backup file. Return path or None on failure."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(BACKUP_DIR, f"smilecare_agent_{agent.id}_{ts}.json")
        backup = {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "original_graph_hash": original_hash,
            "original_graph_json": graph,
            "timestamp": ts,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(backup, f, indent=2, ensure_ascii=False)
        return path
    except Exception as e:
        print(f"  Backup failure: {e}")
        return None


# ── Commands ────────────────────────────────────────────────────────────────


async def cmd_list():
    """List conversational_flow agents that may be SmileCare."""
    async with async_session() as db:
        result = await db.execute(
            select(Agent).where(
                Agent.mode == "conversational_flow",
                Agent.graph_json.isnot(None),
            )
        )
        agents = result.scalars().all()

    if not agents:
        print("No conversational_flow agents with graph_json found.")
        return

    print(f"Found {len(agents)} conversational_flow agent(s):\n")
    for a in agents:
        graph = _parse_graph(a)
        if graph is None:
            print(f"  Agent #{a.id}: name={a.name}, template_id={a.template_id}, "
                  f"graph=UNPARSEABLE")
            continue
        node_ids = _get_node_ids(graph)
        has_smilecare = all(n in node_ids for n in ["action_1", "condition_1", "end_1"])
        on_missing = _get_action1_on_missing_edges(graph)
        on_missing_status = (
            "present" if len(on_missing) == 1 and on_missing[0].get("target") == "conversation_contact"
            else f"CONFLICT({on_missing[0].get('target')})" if len(on_missing) == 1
            else f"DUPLICATES({len(on_missing)})" if len(on_missing) > 1
            else "absent"
        )
        print(f"  Agent #{a.id}: name={a.name}, template_id={a.template_id}, "
              f"smilecare={has_smilecare}, on_missing_edge={on_missing_status}")


async def cmd_dry_run(agent_id: int):
    """Preview the patch without writing."""
    async with async_session() as db:
        agent = await db.get(Agent, agent_id)
    if not agent:
        print(f"Status: INVALID_TARGET\n  Agent #{agent_id} not found")
        return

    print(f"Targeted agent:")
    print(f"  id: {agent.id}")
    print(f"  name: {agent.name}")
    print(f"  mode: {agent.mode}\n")

    if agent.mode != "conversational_flow":
        print(f"Status: INVALID_TARGET\n  mode is '{agent.mode}', not 'conversational_flow'")
        return

    graph = _parse_graph(agent)
    if graph is None:
        print("Status: INVALID_TARGET\n  graph_json is missing or unparseable")
        return

    valid, msg = _validate_graph(graph)
    if not valid:
        print(f"Status: INVALID_TARGET\n  {msg}")
        return

    original_hash = _graph_hash(graph)
    edges_count = len(graph.get("edges", []))
    branch_map = _build_branch_map(graph, "action_1")

    print(f"Original graph hash:\n  {original_hash}\n")
    print(f"Edge count:\n  {edges_count}\n")
    print(f"Current action_1 branch map:")
    for k, v in sorted(branch_map.items()):
        print(f"  {k}: {v}")
    print()

    status, existing = _inspect_existing(graph)
    print(f"Existing on_missing edge status: {status}\n")

    if status == "ALREADY_FIXED":
        print("No patch needed — edge already present.")
        return
    if status == "CONFLICT":
        print(f"CONFLICT: existing on_missing edge targets '{existing[0].get('target')}', "
              f"not 'conversation_contact'")
        return
    if status == "INVALID_GRAPH":
        print(f"INVALID_GRAPH: {len(existing)} on_missing edges found")
        return

    # Simulate the patch
    patched = json.loads(json.dumps(graph))
    patched["edges"].append(dict(EDGE_TO_ADD))
    new_hash = _graph_hash(patched)

    print(f"Proposed edge:")
    print(f"  {EDGE_TO_ADD['source']}:{EDGE_TO_ADD['sourceHandle']} -> {EDGE_TO_ADD['target']}\n")
    print(f"Proposed new graph hash:\n  {new_hash}\n")
    print(f"Hashes differ: {original_hash != new_hash}\n")

    # Linked workflow info
    wf_id = agent.workflow_id
    print(f"Linked workflow:")
    print(f"  workflow_id: {wf_id}")
    if wf_id:
        async with async_session() as db:
            wf = await db.get(Workflow, wf_id)
        if wf:
            wf_graph_raw = wf.graph_json
            if wf_graph_raw:
                try:
                    wf_graph = json.loads(wf_graph_raw) if isinstance(wf_graph_raw, str) else wf_graph_raw
                    wf_hash = _graph_hash(wf_graph)
                    print(f"  workflow exists: yes")
                    print(f"  workflow graph hash: {wf_hash}")
                    print(f"  matches agent original: {wf_hash == original_hash}")
                except Exception:
                    print(f"  workflow graph: UNPARSEABLE")
            else:
                print(f"  workflow graph: empty")
        else:
            print(f"  workflow exists: no")
    else:
        print(f"  (no linked workflow)")

    print(f"\nPatch would be safe: yes")
    print(f"Status: DRY_RUN_COMPLETE")


async def cmd_apply(agent_id: int):
    """Apply the patch to the database."""
    async with async_session() as db:
        agent = await db.get(Agent, agent_id)
        if not agent:
            print(f"Status: INVALID_TARGET\n  Agent #{agent_id} not found")
            return

        print(f"Targeted agent:")
        print(f"  id: {agent.id}")
        print(f"  name: {agent.name}")
        print(f"  mode: {agent.mode}\n")

        if agent.mode != "conversational_flow":
            print(f"Status: INVALID_TARGET\n  mode is '{agent.mode}'")
            return

        # Parse graph from the raw column (not the .graph property)
        raw = agent.graph_json
        if not raw:
            print("Status: INVALID_TARGET\n  graph_json is empty")
            return
        try:
            graph = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            print("Status: INVALID_TARGET\n  graph_json is unparseable")
            return

        valid, msg = _validate_graph(graph)
        if not valid:
            print(f"Status: INVALID_TARGET\n  {msg}")
            return

        original_hash = _graph_hash(graph)
        edges_before = len(graph.get("edges", []))

        status, existing = _inspect_existing(graph)
        if status == "ALREADY_FIXED":
            print(f"Status: ALREADY_FIXED\n  on_missing edge already targets conversation_contact")
            return
        if status == "CONFLICT":
            print(f"Status: CONFLICT\n  existing on_missing targets '{existing[0].get('target')}'")
            return
        if status == "INVALID_GRAPH":
            print(f"Status: INVALID_GRAPH\n  {len(existing)} on_missing edges")
            return

        # Backup
        backup_path = _write_backup(agent, graph, original_hash)
        if backup_path is None:
            print("Status: BACKUP_FAILED\n  Aborting patch — could not write backup")
            await db.rollback()
            return

        # Modify graph
        patched = json.loads(json.dumps(graph))
        patched["edges"].append(dict(EDGE_TO_ADD))
        new_hash = _graph_hash(patched)
        edges_after = len(patched["edges"])

        # Update agent.graph_json and keep the linked/assigned workflow canonical.
        serialized = json.dumps(patched, ensure_ascii=False)
        agent.graph_json = serialized

        workflow = None
        if agent.workflow_id is not None:
            workflow = await db.get(Workflow, agent.workflow_id)
        if workflow is None:
            wf_result = await db.execute(
                select(Workflow).where(Workflow.agent_id == agent.id).order_by(Workflow.id.desc())
            )
            workflow = wf_result.scalars().first()
        if workflow is not None:
            if workflow.user_id != agent.user_id:
                print("Status: CONFLICT\n  Linked workflow belongs to a different owner")
                await db.rollback()
                return
            workflow.graph_json = serialized
            workflow.agent_id = agent.id
            agent.workflow_id = workflow.id

        await db.flush()

        # Read back inside transaction to verify
        await db.refresh(agent)
        verify_raw = agent.graph_json
        try:
            verify_graph = json.loads(verify_raw) if isinstance(verify_raw, str) else verify_raw
        except Exception:
            print("Status: VERIFICATION_FAILED\n  Could not parse graph after write")
            await db.rollback()
            return

        verify_edges = _get_action1_on_missing_edges(verify_graph)
        if len(verify_edges) != 1 or verify_edges[0].get("target") != "conversation_contact":
            print(f"Status: VERIFICATION_FAILED\n  Edge not found after write")
            await db.rollback()
            return

        if workflow is not None:
            await db.refresh(workflow)
            if workflow.graph_json != agent.graph_json or agent.workflow_id != workflow.id:
                print("Status: VERIFICATION_FAILED\n  Workflow/agent ownership sync failed")
                await db.rollback()
                return

        # Commit
        await db.commit()

        print(f"Original graph hash:\n  {original_hash}\n")
        print(f"Updated graph hash:\n  {new_hash}\n")
        print(f"Edge count:\n  before: {edges_before}\n  after: {edges_after}\n")
        print(f"Edge added:\n  action_1:on_missing -> conversation_contact\n")
        print(f"Backup:\n  {backup_path}\n")

        print(f"Linked workflow:")
        print(f"  workflow_id: {agent.workflow_id}")
        if workflow is not None:
            print(f"  workflow graph hash: {_graph_hash(json.loads(workflow.graph_json))}")
            print(f"  matches updated agent hash: True")
        else:
            print(f"  (no linked workflow)")

        print(f"\nStatus:\n  COMMITTED")

async def cmd_verify(agent_id: int):
    """Verify the persisted graph contains the edge."""
    async with async_session() as db:
        agent = await db.get(Agent, agent_id)
    if not agent:
        print(f"Status: INVALID_TARGET\n  Agent #{agent_id} not found")
        return

    print(f"Targeted agent:")
    print(f"  id: {agent.id}")
    print(f"  name: {agent.name}")
    print(f"  mode: {agent.mode}\n")

    raw = agent.graph_json
    if not raw:
        print("Status: INVALID_TARGET\n  graph_json is empty")
        return
    try:
        graph = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        print("Status: INVALID_TARGET\n  graph_json is unparseable")
        return

    valid, msg = _validate_graph(graph)
    if not valid:
        print(f"Status: INVALID_TARGET\n  {msg}")
        return

    graph_hash = _graph_hash(graph)
    print(f"Graph hash:\n  {graph_hash}\n")

    on_missing_edges = _get_action1_on_missing_edges(graph)
    if len(on_missing_edges) == 0:
        print("Status: NOT_PATCHED\n  action_1:on_missing edge is absent")
        return
    if len(on_missing_edges) > 1:
        print(f"Status: INVALID_GRAPH\n  {len(on_missing_edges)} on_missing edges")
        return

    edge = on_missing_edges[0]
    if edge.get("target") != "conversation_contact":
        print(f"Status: CONFLICT\n  on_missing targets '{edge.get('target')}'")
        return

    print(f"action_1:on_missing edge:\n  {json.dumps(edge)}\n")

    branch_map = _build_branch_map(graph, "action_1")
    print(f"Compiled action_1 branch map:")
    for k, v in sorted(branch_map.items()):
        print(f"  {k}: {v}")
    print()

    print(f"Status:\n  VERIFIED")


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Patch SmileCare Agent.graph_json with action_1:on_missing edge"
    )
    parser.add_argument("--list", action="store_true", help="List candidate agents")
    parser.add_argument("--agent-id", type=int, help="Target agent ID")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--apply", action="store_true", help="Apply the patch")
    parser.add_argument("--verify", action="store_true", help="Verify the patch")
    args = parser.parse_args()

    if args.list:
        asyncio.run(cmd_list())
        return

    if not args.agent_id:
        parser.error("--agent-id is required for --dry-run, --apply, --verify")

    if args.dry_run:
        asyncio.run(cmd_dry_run(args.agent_id))
    elif args.apply:
        asyncio.run(cmd_apply(args.agent_id))
    elif args.verify:
        asyncio.run(cmd_verify(args.agent_id))
    else:
        parser.error("One of --list, --dry-run, --apply, --verify is required")


if __name__ == "__main__":
    main()
