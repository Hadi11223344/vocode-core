"""Remove all outgoing edges from terminal (end/end_call) nodes in DB graph_json records."""

import asyncio
import json
import sys

import asyncpg


def is_terminal_node(node: dict) -> bool:
    """Check if a node is terminal (end or end_call)."""
    data = node.get("data") or {}
    node_type = data.get("nodeType") or node.get("type") or ""
    return node_type in ("end", "end_call")


def strip_terminal_outgoing_edges(graph: dict) -> tuple[dict, int]:
    """Return graph with terminal-node outgoing edges removed, and count removed."""
    removed = 0
    if not isinstance(graph, dict):
        return graph, removed

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    terminal_ids = {n.get("id") for n in nodes if is_terminal_node(n)}

    new_edges = []
    for edge in edges:
        src = edge.get("source")
        if src in terminal_ids:
            removed += 1
            continue
        new_edges.append(edge)

    graph["edges"] = new_edges
    return graph, removed


async def main():
    dsn = "postgresql://voia:voia_password@localhost:5433/voia"
    conn = await asyncpg.connect(dsn)

    total_removed = 0
    updated_records = 0

    for source, table in [("agents", "agents"), ("workflows", "workflows")]:
        rows = await conn.fetch(f"SELECT id, graph_json FROM {table} WHERE graph_json IS NOT NULL AND graph_json != ''")
        for row in rows:
            try:
                graph = json.loads(row["graph_json"])
            except json.JSONDecodeError:
                continue

            new_graph, removed = strip_terminal_outgoing_edges(graph)
            if removed > 0:
                await conn.execute(
                    f"UPDATE {table} SET graph_json = $1, updated_at = NOW() WHERE id = $2",
                    json.dumps(new_graph), row["id"]
                )
                total_removed += removed
                updated_records += 1
                print(f"{source[:-1]} id={row['id']}: removed {removed} terminal outgoing edge(s)")

    await conn.close()
    print(f"Updated {updated_records} records, removed {total_removed} edges total.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
