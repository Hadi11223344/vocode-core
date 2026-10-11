#!/usr/bin/env python3
"""
Patch the persisted SmileCare Agent.graph_json to fix Google Sheets range
configuration. Replaces "Patients!A:K" with "'Sheet1'!A:K" in sheets_1 and
action_1 node configs.

Usage:
    python examples/smilecare/patch_smilecare_sheets_range.py --list
    python examples/smilecare/patch_smilecare_sheets_range.py --agent-id N --dry-run
    python examples/smilecare/patch_smilecare_sheets_range.py --agent-id N --apply
    python examples/smilecare/patch_smilecare_sheets_range.py --agent-id N --verify
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from voice_platform.database import async_session, Agent
from sqlalchemy import select

OLD_RANGE = "Patients!A:K"
NEW_RANGE = "'Sheet1'!A:K"
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")


def _graph_hash(graph: dict) -> str:
    canonical = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_graph(agent: Agent) -> dict | None:
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


def _find_range_occurrences(graph: dict) -> list[dict]:
    """Find all nodes with range == OLD_RANGE in their config or params."""
    occurrences = []
    for node in graph.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "?")
        data = node.get("data") or {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        params = config.get("params") if isinstance(config.get("params"), dict) else {}

        # Check config.range
        if config.get("range") == OLD_RANGE:
            occurrences.append({"node_id": node_id, "location": "config.range", "old": OLD_RANGE})

        # Check params.range
        if params.get("range") == OLD_RANGE:
            occurrences.append({"node_id": node_id, "location": "config.params.range", "old": OLD_RANGE})

    return occurrences


def _apply_range_fix(graph: dict) -> tuple[dict, list[dict]]:
    """Replace all occurrences of OLD_RANGE with NEW_RANGE. Returns (patched_graph, changes)."""
    patched = json.loads(json.dumps(graph))
    changes = []
    for node in patched.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "?")
        data = node.get("data") or {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        params = config.get("params") if isinstance(config.get("params"), dict) else {}

        if config.get("range") == OLD_RANGE:
            config["range"] = NEW_RANGE
            changes.append({"node_id": node_id, "location": "config.range", "old": OLD_RANGE, "new": NEW_RANGE})

        if params.get("range") == OLD_RANGE:
            params["range"] = NEW_RANGE
            changes.append({"node_id": node_id, "location": "config.params.range", "old": OLD_RANGE, "new": NEW_RANGE})

    return patched, changes


def _write_backup(agent: Agent, graph: dict, original_hash: str) -> str | None:
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(BACKUP_DIR, f"smilecare_sheets_agent_{agent.id}_{ts}.json")
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


async def cmd_list():
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
            print(f"  Agent #{a.id}: name={a.name}, graph=UNPARSEABLE")
            continue
        occurrences = _find_range_occurrences(graph)
        has_old = len(occurrences) > 0
        print(f"  Agent #{a.id}: name={a.name}, has_Patients_range={has_old}, "
              f"occurrences={len(occurrences)}")


async def cmd_dry_run(agent_id: int):
    async with async_session() as db:
        agent = await db.get(Agent, agent_id)
    if not agent:
        print(f"Status: INVALID_TARGET\n  Agent #{agent_id} not found")
        return

    print(f"Targeted agent:")
    print(f"  id: {agent.id}")
    print(f"  name: {agent.name}")
    print(f"  mode: {agent.mode}\n")

    graph = _parse_graph(agent)
    if graph is None:
        print("Status: INVALID_TARGET\n  graph_json is missing or unparseable")
        return

    original_hash = _graph_hash(graph)
    occurrences = _find_range_occurrences(graph)

    print(f"Original graph hash:\n  {original_hash}\n")
    print(f"Occurrences of '{OLD_RANGE}': {len(occurrences)}")
    for occ in occurrences:
        print(f"  {occ['node_id']} / {occ['location']}")
    print()

    if not occurrences:
        # Check if already fixed
        has_new = False
        for node in graph.get("nodes", []):
            config = (node.get("data") or {}).get("config") or {}
            params = config.get("params") if isinstance(config.get("params"), dict) else {}
            if config.get("range") == NEW_RANGE or params.get("range") == NEW_RANGE:
                has_new = True
                break
        if has_new:
            print(f"Status: ALREADY_FIXED\n  Range already set to '{NEW_RANGE}'")
        else:
            print(f"Status: NO_MATCH\n  No occurrences of '{OLD_RANGE}' found")
        return

    patched, changes = _apply_range_fix(graph)
    new_hash = _graph_hash(patched)

    print(f"Proposed changes:")
    for c in changes:
        print(f"  {c['node_id']} / {c['location']}: '{c['old']}' -> '{c['new']}'")
    print()
    print(f"Proposed new graph hash:\n  {new_hash}\n")
    print(f"Hashes differ: {original_hash != new_hash}\n")
    print(f"Patch would be safe: yes")
    print(f"Status: DRY_RUN_COMPLETE")


async def cmd_apply(agent_id: int):
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

        original_hash = _graph_hash(graph)
        occurrences = _find_range_occurrences(graph)

        if not occurrences:
            has_new = False
            for node in graph.get("nodes", []):
                config = (node.get("data") or {}).get("config") or {}
                params = config.get("params") if isinstance(config.get("params"), dict) else {}
                if config.get("range") == NEW_RANGE or params.get("range") == NEW_RANGE:
                    has_new = True
                    break
            if has_new:
                print(f"Status: ALREADY_FIXED\n  Range already set to '{NEW_RANGE}'")
            else:
                print(f"Status: NO_MATCH\n  No occurrences of '{OLD_RANGE}' found")
            return

        # Backup
        backup_path = _write_backup(agent, graph, original_hash)
        if backup_path is None:
            print("Status: BACKUP_FAILED\n  Aborting patch — could not write backup")
            await db.rollback()
            return

        # Apply
        patched, changes = _apply_range_fix(graph)
        new_hash = _graph_hash(patched)

        agent.graph_json = json.dumps(patched, ensure_ascii=False)
        await db.flush()

        # Verify
        await db.refresh(agent)
        verify_raw = agent.graph_json
        try:
            verify_graph = json.loads(verify_raw) if isinstance(verify_raw, str) else verify_raw
        except Exception:
            print("Status: VERIFICATION_FAILED\n  Could not parse graph after write")
            await db.rollback()
            return

        verify_occurrences = _find_range_occurrences(verify_graph)
        if verify_occurrences:
            print(f"Status: VERIFICATION_FAILED\n  Old range still present after write")
            await db.rollback()
            return

        # Check new range is present
        has_new = False
        for node in verify_graph.get("nodes", []):
            config = (node.get("data") or {}).get("config") or {}
            params = config.get("params") if isinstance(config.get("params"), dict) else {}
            if config.get("range") == NEW_RANGE or params.get("range") == NEW_RANGE:
                has_new = True
                break
        if not has_new:
            print(f"Status: VERIFICATION_FAILED\n  New range '{NEW_RANGE}' not found after write")
            await db.rollback()
            return

        await db.commit()

        print(f"Original graph hash:\n  {original_hash}\n")
        print(f"Updated graph hash:\n  {new_hash}\n")
        print(f"Changes applied:")
        for c in changes:
            print(f"  {c['node_id']} / {c['location']}: '{c['old']}' -> '{c['new']}'")
        print()
        print(f"Backup:\n  {backup_path}\n")
        print(f"Status:\n  COMMITTED")


async def cmd_verify(agent_id: int):
    async with async_session() as db:
        agent = await db.get(Agent, agent_id)
    if not agent:
        print(f"Status: INVALID_TARGET\n  Agent #{agent_id} not found")
        return

    print(f"Targeted agent:")
    print(f"  id: {agent.id}")
    print(f"  name: {agent.name}\n")

    raw = agent.graph_json
    if not raw:
        print("Status: INVALID_TARGET\n  graph_json is empty")
        return
    try:
        graph = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        print("Status: INVALID_TARGET\n  graph_json is unparseable")
        return

    graph_hash = _graph_hash(graph)
    print(f"Graph hash:\n  {graph_hash}\n")

    old_occurrences = _find_range_occurrences(graph)
    if old_occurrences:
        print(f"Status: NOT_PATCHED\n  Found {len(old_occurrences)} occurrences of '{OLD_RANGE}'")
        for occ in old_occurrences:
            print(f"  {occ['node_id']} / {occ['location']}")
        return

    # Find new range
    new_nodes = []
    for node in graph.get("nodes", []):
        config = (node.get("data") or {}).get("config") or {}
        params = config.get("params") if isinstance(config.get("params"), dict) else {}
        if config.get("range") == NEW_RANGE or params.get("range") == NEW_RANGE:
            new_nodes.append(node.get("id"))

    if not new_nodes:
        print(f"Status: NOT_PATCHED\n  Neither '{OLD_RANGE}' nor '{NEW_RANGE}' found")
        return

    print(f"Nodes with '{NEW_RANGE}':")
    for nid in new_nodes:
        print(f"  {nid}")
    print()
    print(f"Status:\n  VERIFIED")


def main():
    parser = argparse.ArgumentParser(
        description="Patch SmileCare Agent.graph_json with corrected Sheets range"
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
