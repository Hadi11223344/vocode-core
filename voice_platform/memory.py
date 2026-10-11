"""
Voice Platform — Cross-Call Memory (Phase B: delegates to MemoryService)

This module is a thin backward-compatibility wrapper. The actual logic
lives in voice_platform.runtime.services.memory.MemoryService, which
returns structured ConversationMemory objects instead of prompt strings.

The inbound handler still uses get_caller_history_summary() which returns
a formatted string. This wrapper converts the structured ConversationMemory
back to a string until the inbound handler is fully migrated to use
ExecutionContext + PromptRenderer.
"""

from typing import Optional

from loguru import logger
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import CallLog
from voice_platform.database import Transcript as TranscriptRow
from voice_platform.database import async_session
from voice_platform.runtime.services.memory import ConversationMemory, MemoryService

# ── Configuration ──────────────────────────────────────────────────────
MAX_PAST_CALLS = 2
MAX_MESSAGES_PER_CALL = 6
MAX_SUMMARY_CHARS = 1000

_memory_service = MemoryService()


def _format_memory_string(memory: ConversationMemory, from_phone: str) -> str:
    """Convert structured ConversationMemory to the legacy prompt string format."""
    if not memory.previous_calls:
        return ""

    summary_parts = ["\n=== PREVIOUS INTERACTION HISTORY ==="]
    if memory.summary:
        summary_parts.append(memory.summary)

    for i, call in enumerate(memory.previous_calls, 1):
        summary_parts.append(f"\nCall {i} ({call.call_date}, duration: {call.duration}):")
        for msg in call.messages:
            summary_parts.append(f"  {msg}")

    summary_parts.append(
        "\nUse this context to personalize your responses. "
        "Reference previous topics if relevant."
    )
    summary_parts.append("===================================\n")

    summary = "\n".join(summary_parts)

    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS] + "\n... (history truncated)\n"

    return summary


async def get_caller_history_summary(from_phone: str) -> str:
    """Build a conversation history summary for a returning caller.

    Delegates to MemoryService.get_history() and converts the structured
    ConversationMemory to a formatted string for backward compatibility.

    Args:
        from_phone: The caller's phone number (e.g. "+923390044169")

    Returns:
        A formatted summary string, or empty string if no history exists.
    """
    try:
        async with async_session() as session:
            memory = await _memory_service.get_history(session, from_phone)
            return _format_memory_string(memory, from_phone)
    except Exception as e:
        logger.error(f"Error building caller history: {e}", exc_info=True)
        return ""

