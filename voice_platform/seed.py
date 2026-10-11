"""
Voice Platform — Demo Data Seeder
====================================

Creates sample agents, knowledge base, and workflow for new users
so the dashboard looks alive on first login (FYP demo ready).

Called from auth routes after the first user signs up.
"""

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Agent, KnowledgeBase, Workflow


async def seed_demo_data(user_id: int, db: AsyncSession) -> None:
    """
    Create demo data for a newly registered user.

    Creates:
        1. "Customer Support" agent (single prompt mode)
        2. "Appointment Scheduler" agent (single prompt mode)
        3. Sample knowledge base with FAQ content
        4. Sample workflow for appointment booking
    """
    from sqlalchemy import select, func

    # Only seed if user has zero agents
    agent_count = (
        await db.execute(select(func.count(Agent.id)).where(Agent.user_id == user_id))
    ).scalar() or 0
    if agent_count > 0:
        logger.debug(f"User {user_id} already has agents — skipping demo seed")
        return

    logger.info(f"SEED: Creating demo data for user {user_id}")

    # ── Demo Agent 1: Customer Support ────────────────────────────
    support_agent = Agent(
        user_id=user_id,
        name="Demo: Customer Support",
        prompt_preamble=(
            "You are a friendly and professional customer support agent. "
            "Your goal is to help callers resolve their issues quickly and efficiently. "
            "Listen carefully to their problem, ask clarifying questions when needed, "
            "and provide clear solutions. If you cannot resolve the issue, offer to "
            "escalate to a human agent. Always maintain a calm and empathetic tone."
        ),
        initial_message="Thank you for calling! My name is Alex, how can I help you today?",
        llm_provider="groq",
        llm_model="llama-3.3-70b-versatile",
        stt_provider="deepgram",
        stt_language="en-US",
        tts_provider="deepgram",
        tts_voice_id="aura-asteria-en",
        temperature=0.5,
        max_tokens=256,
        end_on_goodbye=True,
        interrupt_sensitivity="high",
        filler_audio_enabled=True,
        is_active=True,
        mode="single_prompt",
    )
    db.add(support_agent)
    await db.flush()  # Get agent.id

    # ── Demo Agent 2: Appointment Scheduler ──────────────────────
    scheduler_agent = Agent(
        user_id=user_id,
        name="Demo: Appointment Scheduler",
        prompt_preamble=(
            "You are a professional appointment scheduling assistant. "
            "Help callers book, reschedule, or cancel appointments. "
            "Collect their name, preferred date and time, reason for the appointment, "
            "and contact information. Confirm all details before finalizing. "
            "Be efficient and organized while maintaining a warm, helpful tone."
        ),
        initial_message="Hello! I'd be happy to help you schedule an appointment. What date works for you?",
        llm_provider="groq",
        llm_model="llama-3.3-70b-versatile",
        stt_provider="deepgram",
        stt_language="en-US",
        tts_provider="deepgram",
        tts_voice_id="aura-athena-en",
        temperature=0.3,
        max_tokens=200,
        end_on_goodbye=True,
        interrupt_sensitivity="high",
        filler_audio_enabled=False,
        is_active=True,
        mode="single_prompt",
    )
    db.add(scheduler_agent)
    await db.flush()

    # ── Demo Knowledge Base ───────────────────────────────────────
    kb_content = """# Company FAQ

## What are your business hours?
We are open Monday through Friday, 9:00 AM to 6:00 PM EST. Weekend appointments are available by request.

## How do I schedule an appointment?
You can schedule by calling this number, visiting our website, or using our mobile app. Same-day appointments may be available depending on availability.

## What is your cancellation policy?
We ask for 24 hours notice for cancellations. Late cancellations may incur a fee of $50.

## Do you offer virtual consultations?
Yes! We offer video consultations via Zoom and Google Meet. Virtual appointments can be scheduled just like in-person visits.

## How can I reach a human agent?
Say "transfer to human" or "speak to a representative" at any time, and I will connect you immediately.

## What payment methods do you accept?
We accept all major credit cards, debit cards, HSA/FSA cards, and bank transfers. Payment is due at the time of service.
"""

    from voice_platform.integrations.knowledge_base import KnowledgeBaseClient

    chunks = KnowledgeBaseClient.chunk_text(kb_content, chunk_size=500, overlap=50)
    import json as _json
    kb = KnowledgeBase(
        user_id=user_id,
        name="Demo: Company FAQ",
        description="Frequently asked questions for customer support",
        source_type="text",
        content=kb_content,
        chunks_json=_json.dumps(chunks),
        chunk_size=500,
        max_chunks_per_query=3,
        agent_ids_json=_json.dumps([support_agent.id]),
        is_active=True,
    )
    db.add(kb)
    await db.flush()

    # Link the KB to the support agent
    support_agent.knowledge_base_id = kb.id

    # ── Demo Workflow ─────────────────────────────────────────────
    workflow = Workflow(
        user_id=user_id,
        name="Demo: Appointment Booking Flow",
        description="Multi-step flow for booking, rescheduling, or canceling appointments",
        trigger_phrases=_json.dumps([
            "book appointment", "schedule", "make appointment",
            "reschedule", "cancel appointment", "change my appointment"
        ]),
        agent_id=scheduler_agent.id,
        steps_json=_json.dumps([
            {
                "step": 1,
                "action": "collect_info",
                "fields": ["name", "phone", "preferred_date", "reason"],
                "prompt": "Great! I'll help you book an appointment. What's your name and preferred date?"
            },
            {
                "step": 2,
                "action": "confirm_details",
                "prompt": "Let me confirm: you'd like an appointment on {preferred_date} for {reason}. Is that correct?"
            },
            {
                "step": 3,
                "action": "finalize",
                "prompt": "Perfect! Your appointment is confirmed. You'll receive a confirmation text shortly."
            }
        ]),
        is_active=True,
    )
    db.add(workflow)

    await db.commit()
    logger.info(f"SEED: Created 2 demo agents, 1 KB, 1 workflow for user {user_id}")
