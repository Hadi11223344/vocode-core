"""Deduplicate SmileCare agents and workflows in the database.

Lists active candidates newest-first. Apply mode requires exact agent/workflow
IDs to keep, then soft-deletes every other matching active record.
Dry run inside Docker: docker compose exec -T app python examples/smilecare/dedup_smilecare.py
Apply explicitly: docker compose exec -T app python examples/smilecare/dedup_smilecare.py \
    --apply --keep-agent-id 12 --keep-workflow-id 34
"""

import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from sqlalchemy import select
    from voice_platform.database import DATABASE_URL, Agent, Workflow, async_session

    parser = argparse.ArgumentParser(description="Review duplicate SmileCare records")
    parser.add_argument("--apply", action="store_true", help="Commit soft-deletes and reassignment")
    parser.add_argument("--keep-agent-id", type=int, help="Exact agent ID to retain when applying")
    parser.add_argument("--keep-workflow-id", type=int, help="Exact workflow ID to retain when applying")
    args = parser.parse_args()
    if args.apply and (args.keep_agent_id is None or args.keep_workflow_id is None):
        parser.error("--apply requires both --keep-agent-id and --keep-workflow-id")

    print(f"DATABASE_URL: {DATABASE_URL[:50]}...")
    print("Mode: APPLY" if args.apply else "Mode: DRY RUN (no changes will be committed)")

    async with async_session() as session:
        # ── Dedup agents ──────────────────────────────────────────
        result = await session.execute(
            select(Agent)
            .where(Agent.name.ilike("%SmileCare%"))
            .where(Agent.is_active == True)
            .order_by(Agent.id.desc())
        )
        agents = result.scalars().all()
        if args.apply and not any(agent.id == args.keep_agent_id for agent in agents):
            parser.error(f"Agent #{args.keep_agent_id} is not an active SmileCare candidate")

        if not agents:
            print("No active SmileCare agents found.")
        elif len(agents) == 1:
            print(f"Only 1 active SmileCare agent (#{agents[0].id}): '{agents[0].name}' — no dedup needed.")
        else:
            keep = next(
                (agent for agent in agents if agent.id == args.keep_agent_id),
                agents[0],
            )
            print(f"Keeping agent #{keep.id}: '{keep.name}'")
            duplicate_agents = [agent for agent in agents if agent.id != keep.id]
            dup_ids = [agent.id for agent in duplicate_agents]
            print(f"Soft-deleting {len(dup_ids)} duplicate agent(s): {dup_ids}")
            for a in duplicate_agents:
                print(f"  - #{a.id}: '{a.name}'")
                if args.apply:
                    a.is_active = False
            if args.apply:
                print(f"Marked {len(dup_ids)} agent(s) for soft deletion.")

        # ── Dedup workflows ───────────────────────────────────────
        result = await session.execute(
            select(Workflow)
            .where(Workflow.name.ilike("%SmileCare%"))
            .where(Workflow.is_active == True)
            .order_by(Workflow.id.desc())
        )
        workflows = result.scalars().all()
        if args.apply and not any(workflow.id == args.keep_workflow_id for workflow in workflows):
            parser.error(f"Workflow #{args.keep_workflow_id} is not an active SmileCare candidate")

        if not workflows:
            print("No active SmileCare workflows found.")
        elif len(workflows) == 1:
            print(f"Only 1 active SmileCare workflow (#{workflows[0].id}): '{workflows[0].name}' — no dedup needed.")
        else:
            keep = next(
                (workflow for workflow in workflows if workflow.id == args.keep_workflow_id),
                workflows[0],
            )
            print(f"\nKeeping workflow #{keep.id}: '{keep.name}'")
            duplicate_workflows = [workflow for workflow in workflows if workflow.id != keep.id]
            dup_ids = [workflow.id for workflow in duplicate_workflows]
            print(f"Soft-deleting {len(dup_ids)} duplicate workflow(s): {dup_ids}")
            for w in duplicate_workflows:
                print(f"  - #{w.id}: '{w.name}'")
                if args.apply:
                    w.is_active = False
            if args.apply:
                print(f"Marked {len(dup_ids)} workflow(s) for soft deletion.")

        # ── Reassign kept workflow to kept agent (if needed) ───────
        if agents and workflows:
            keep_agent = next(
                (agent for agent in agents if agent.id == args.keep_agent_id),
                agents[0],
            )
            keep_wf = next(
                (workflow for workflow in workflows if workflow.id == args.keep_workflow_id),
                workflows[0],
            )
            if args.apply and keep_wf.agent_id != keep_agent.id:
                print(f"\nReassigning workflow #{keep_wf.id} to agent #{keep_agent.id}")
                keep_wf.agent_id = keep_agent.id
            if args.apply and keep_wf.graph_json:
                keep_agent.graph_json = keep_wf.graph_json
                keep_agent.mode = "conversational_flow"
            if args.apply:
                await session.commit()
                print("Kept workflow and agent are synchronized.")

        if not args.apply:
            await session.rollback()
            print("DRY RUN complete. Re-run with --apply only after reviewing the IDs above.")


if __name__ == "__main__":
    asyncio.run(main())
