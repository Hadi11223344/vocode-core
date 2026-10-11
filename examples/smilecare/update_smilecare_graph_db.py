"""Deprecated SmileCare bulk migration retained only for historical reference.

Changes:
- condition_3 "Yes" edge target changes from action_2 to conversation_3
- conversation_4 prompt updated to ask for a different day/time if alternatives don't work
"""

import asyncio
import json
import os
import sys

import asyncpg

OLD_EDGE = {"source": "condition_3", "target": "action_2", "label": "Yes"}
NEW_EDGE = {"source": "condition_3", "target": "conversation_3", "label": "Yes"}

OLD_PROMPT = "That time slot isn't available, I'm sorry. Let me suggest a few alternatives. Our sessions are morning (10 AM - 1 PM), afternoon (2 PM - 5 PM), and evening (6 PM - 9 PM). I have openings tomorrow morning at 10:30 or 11:15, and in the afternoon at 2:30 or 3:45. Would any of those work for you? If not, we could try a different day. Remember, we're also open Sundays from 2 PM to 8 PM. During Ramadan, our hours are 4 PM to 11 PM."
NEW_PROMPT = "That time slot isn't available, I'm sorry. Let me suggest a few alternatives. Our sessions are morning (10 AM - 1 PM), afternoon (2 PM - 5 PM), and evening (6 PM - 9 PM). I have openings tomorrow morning at 10:30 or 11:15, and in the afternoon at 2:30 or 3:45. Would any of those work for you? If not, just let me know a different day or time and I'll check availability right away. Remember, we're also open Sundays from 2 PM to 8 PM. During Ramadan, our hours are 4 PM to 11 PM."


def update_graph(graph: dict) -> dict:
    """Return a new graph dict with the cycle fix applied, or None if no changes."""
    changed = False
    for edge in graph.get("edges", []):
        if edge == OLD_EDGE:
            edge["target"] = "conversation_3"
            changed = True

    for node in graph.get("nodes", []):
        data = node.get("data") or {}
        config = data.get("config") or {}
        prompt = config.get("prompt")
        if prompt == OLD_PROMPT:
            config["prompt"] = NEW_PROMPT
            changed = True

    return graph if changed else None


async def main():
    print(
        "This bulk updater is disabled because it matches many records and can "
        "overwrite repaired graphs. Use examples/smilecare/update_smilecare_workflow.py "
        "--workflow-id <ID> [--apply] instead."
    )
    sys.exit(2)

    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)

    updated_agents = 0
    updated_workflows = 0

    # Agents
    rows = await conn.fetch(
        "SELECT id, graph_json FROM agents WHERE template_id ILIKE '%smilecare%' OR graph_json ILIKE '%smilecare%'"
    )
    for row in rows:
        if not row["graph_json"]:
            continue
        try:
            graph = json.loads(row["graph_json"])
        except json.JSONDecodeError:
            continue
        new_graph = update_graph(graph)
        if new_graph is not None:
            await conn.execute(
                "UPDATE agents SET graph_json = $1, updated_at = NOW() WHERE id = $2",
                json.dumps(new_graph), row["id"]
            )
            updated_agents += 1

    # Workflows
    rows = await conn.fetch(
        "SELECT id, graph_json FROM workflows WHERE graph_json ILIKE '%smilecare%'"
    )
    for row in rows:
        if not row["graph_json"]:
            continue
        try:
            graph = json.loads(row["graph_json"])
        except json.JSONDecodeError:
            continue
        new_graph = update_graph(graph)
        if new_graph is not None:
            await conn.execute(
                "UPDATE workflows SET graph_json = $1, updated_at = NOW() WHERE id = $2",
                json.dumps(new_graph), row["id"]
            )
            updated_workflows += 1

    await conn.close()
    print(f"Updated {updated_agents} agents and {updated_workflows} workflows.")
    sys.exit(0 if (updated_agents or updated_workflows) else 0)


if __name__ == "__main__":
    asyncio.run(main())
