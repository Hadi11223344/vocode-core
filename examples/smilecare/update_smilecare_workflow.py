"""Update saved SmileCare Dental workflow graph_json in the database.

Usage:
    python examples/smilecare/update_smilecare_workflow.py --workflow-id 42
    python examples/smilecare/update_smilecare_workflow.py --workflow-id 42 --apply

Connects to the Postgres DB via the same DATABASE_URL used by the app,
updates one explicitly selected workflow and its linked agent. The default is
a dry run; ``--apply`` is required before any database mutation is committed.

Nodes are converted to frontend format (type='workflowNode' with data.nodeType)
so they render correctly in both the Workflow Editor and Flow Playground.
"""

import asyncio
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _convert_to_frontend_format(nodes: list) -> list:
    """Convert template-format nodes to frontend-format (workflowNode)."""
    converted = []
    for node in nodes:
        original_type = node.get("type", "workflowNode")
        data = dict(node.get("data", {}))
        if not data.get("nodeType"):
            data["nodeType"] = original_type
        converted.append({
            "id": node["id"],
            "type": "workflowNode",
            "position": node.get("position", {"x": 0, "y": 0}),
            "data": data,
        })
    return converted


def _convert_edges(edges: list) -> list:
    """Ensure persisted React Flow edges have stable IDs and branch handles."""
    return [
        {
            **edge,
            "id": edge.get("id") or f"e-{edge.get('source')}-{edge.get('target')}-{index}",
        }
        for index, edge in enumerate(edges)
    ]


async def main():
    from sqlalchemy import select

    parser = argparse.ArgumentParser(description="Replace one workflow with the current SmileCare template")
    parser.add_argument("--workflow-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Commit the replacement (default: dry run)")
    args = parser.parse_args()

    # Get templates by calling the async route handler directly
    from voice_platform.api.workflow_routes import list_workflow_templates
    from voice_platform.database import DATABASE_URL, Agent, Workflow, async_session
    template_data = await list_workflow_templates()
    templates = template_data.get("templates", [])

    # Find the SmileCare template
    template = None
    for t in templates:
        if t.get("id") == "smilecare_dental":
            template = t
            break

    if not template:
        print("ERROR: SmileCare template not found in templates")
        return

    frontend_nodes = _convert_to_frontend_format(template["nodes"])
    frontend_edges = _convert_edges(template.get("edges", []))
    template_graph = json.dumps({"nodes": frontend_nodes, "edges": frontend_edges})

    print(f"DATABASE_URL: {DATABASE_URL[:50]}...")
    print(f"Template: {len(frontend_nodes)} nodes (frontend format), {len(frontend_edges)} edges")

    async with async_session() as session:
        # Update only the explicitly selected workflow.
        result = await session.execute(
            select(Workflow).where(Workflow.id == args.workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if workflow is None:
            print(f"ERROR: Workflow #{args.workflow_id} was not found.")
            return
        print(f"  Selected workflow #{workflow.id}: '{workflow.name}'")
        workflow.graph_json = template_graph
        workflow.trigger_phrases = json.dumps(template.get("trigger_phrases", []))

        agent = await session.get(Agent, workflow.agent_id) if workflow.agent_id else None
        if agent:
            print(f"  Linked agent #{agent.id}: '{agent.name}'")
            agent.graph_json = template_graph
            agent.mode = "conversational_flow"
        else:
            print("  Workflow has no linked agent; only the workflow record would change.")

        if args.apply:
            await session.commit()
            print("Committed the workflow and linked-agent replacement atomically.")
        else:
            await session.rollback()
            print("DRY RUN: no changes committed. Re-run with --apply to replace the graph.")


if __name__ == "__main__":
    asyncio.run(main())
