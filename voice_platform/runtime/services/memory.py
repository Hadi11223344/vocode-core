"""MemoryService — retrieves cross-call memory. Does NOT render prompts.

Returns structured ConversationMemory (domain objects) instead of prompt strings.
PromptRenderer is responsible for converting ConversationMemory into prompt text.

Extraction logic moved from voice_platform/memory.get_caller_history_summary().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import CallLog
from voice_platform.database import Transcript as TranscriptRow


MAX_PAST_CALLS = 2
MAX_MESSAGES_PER_CALL = 6


@dataclass(frozen=True)
class CallSummary:
    """Summary of a single past call."""

    call_date: str
    duration: str
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationMemory:
    """Structured cross-call memory — not a prompt string."""

    summary: str | None = None
    previous_calls: tuple[CallSummary, ...] = ()


class MemoryService:
    """Retrieves cross-call memory for returning callers.

    Does NOT render prompts. Returns ConversationMemory for PromptRenderer to consume.
    """

    async def get_history(
        self,
        db: AsyncSession,
        phone: str,
    ) -> ConversationMemory:
        """Build conversation memory for a returning caller.

        Args:
            db: Async database session.
            phone: The caller's phone number.

        Returns:
            ConversationMemory with summary and previous calls, or empty if no history.
        """
        if not phone:
            return ConversationMemory()

        try:
            result = await db.execute(
                select(CallLog)
                .where(
                    or_(
                        CallLog.from_phone == phone,
                        CallLog.to_phone == phone,
                    ),
                    CallLog.status.in_(["completed", "active"]),
                )
                .order_by(desc(CallLog.started_at))
                .limit(MAX_PAST_CALLS)
            )
            past_calls = result.scalars().all()

            if not past_calls:
                return ConversationMemory()

            call_summaries: list[CallSummary] = []
            for call in reversed(past_calls):
                transcript_result = await db.execute(
                    select(TranscriptRow)
                    .where(TranscriptRow.call_log_id == call.id)
                    .order_by(TranscriptRow.timestamp.asc())
                    .limit(MAX_MESSAGES_PER_CALL)
                )
                messages = transcript_result.scalars().all()

                if not messages:
                    continue

                call_date = call.started_at.strftime("%Y-%m-%d %H:%M") if call.started_at else "unknown"
                duration = f"{call.duration_secs:.0f}s" if call.duration_secs else "unknown"

                msg_lines: list[str] = []
                for msg in messages:
                    speaker = "Human" if msg.sender == "human" else "Bot"
                    text = msg.message[:150] + "..." if len(msg.message) > 150 else msg.message
                    msg_lines.append(f"{speaker}: {text}")

                call_summaries.append(CallSummary(
                    call_date=call_date,
                    duration=duration,
                    messages=tuple(msg_lines),
                ))

            if not call_summaries:
                return ConversationMemory()

            summary = f"The contact ({phone}) has interacted {len(past_calls)} time(s) before."

            return ConversationMemory(
                summary=summary,
                previous_calls=tuple(call_summaries),
            )

        except Exception as e:
            logger.error(f"Error building caller history: {e}", exc_info=True)
            return ConversationMemory()
