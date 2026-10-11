"""
One-time migration: sync SmileCare Dental agent prompt in DB with updated template.

Updates agents named 'SmileCare Dental Receptionist' or 'SmileCare Dental Lahore'
to use the latest prompt from the agent_templates.py template.

Run inside the app container:
    python examples/smilecare/sync_smilecare_prompt.py
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import or_, select

from voice_platform.agent_templates import AGENT_TEMPLATES
from voice_platform.database import Agent, async_session


async def main():
    # Find the SmileCare template
    smilecare_template = None
    for t in AGENT_TEMPLATES:
        if t.id == "smilecare":
            smilecare_template = t
            break

    if not smilecare_template:
        print("ERROR: SmileCare template not found")
        return

    new_prompt = smilecare_template.config["prompt_preamble"]
    new_initial = smilecare_template.config["initial_message"]
    new_voicemail = smilecare_template.config.get("voicemail_message", "")

    print(f"Template prompt length: {len(new_prompt)} chars")

    async with async_session() as session:
        result = await session.execute(
            select(Agent).where(
                or_(
                    Agent.name == "SmileCare Dental Receptionist",
                    Agent.name == "SmileCare Dental Lahore",
                )
            )
        )
        agents = result.scalars().all()
        for agent in agents:
            old_len = len(agent.prompt_preamble or "")
            agent.prompt_preamble = new_prompt
            agent.initial_message = new_initial
            if hasattr(agent, "voicemail_message") and new_voicemail:
                agent.voicemail_message = new_voicemail
            print(f"  Agent {agent.id} ({agent.name}): prompt {old_len} -> {len(new_prompt)} chars")
        await session.commit()
        print(f"Updated {len(agents)} agent(s)")


if __name__ == "__main__":
    asyncio.run(main())
