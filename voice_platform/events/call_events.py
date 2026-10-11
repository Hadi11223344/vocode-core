"""
Voice Platform — Persistent Events Manager
=============================================

Extends vocode's EventsManager to persist call events to the database.

vocode's event system works like this:
    1. During a call, components publish events to the EventsManager queue
    2. EventsManager.start() runs an async loop pulling events from the queue
    3. For each event, handle_event() is called
    4. The base class handle_event() does nothing — we override it

Our PersistentEventsManager adds:
    - TranscriptEvent → INSERT into transcripts table
    - PhoneCallEndedEvent → UPDATE call_logs (status, duration, ended_at)
    - RecordingEvent → UPDATE call_logs (recording_url)
    - ActionEvent → INSERT into action_logs table

This replaces the old in-memory-only PlatformEventsManager.
"""

import asyncio  # For background task creation
import json  # For serializing action params/results
import time  # For current timestamps
from datetime import datetime, timezone  # For ended_at timestamp
from typing import Any, Dict, List, Optional, Set, Tuple  # Type hints

from loguru import logger  # Structured logging
from sqlalchemy import select  # Database queries
from sqlalchemy.ext.asyncio import AsyncSession  # Async DB session type

from vocode.streaming.models.events import ActionEvent  # Fired when an action executes
from vocode.streaming.models.events import Event  # Base event class
from vocode.streaming.models.events import EventType  # Event type enum
from vocode.streaming.models.events import PhoneCallConnectedEvent  # Fired when call connects
from vocode.streaming.models.events import PhoneCallDidNotConnectEvent  # Fired when call fails
from vocode.streaming.models.events import PhoneCallEndedEvent  # Fired when call ends
from vocode.streaming.models.events import RecordingEvent  # Fired when recording is available
from vocode.streaming.models.transcript import TranscriptCompleteEvent  # Full transcript
from vocode.streaming.models.transcript import TranscriptEvent  # Human/bot message event
from vocode.streaming.utils.events_manager import EventsManager  # Base class we extend
from voice_platform.cache import RedisCache
from voice_platform.database import ActionLog  # Action log DB model
from voice_platform.database import Agent  # Agent mode determines in-call flow ownership
from voice_platform.database import CallLog  # Call log DB model
from voice_platform.database import Workflow  # Workflow model for trigger matching
from voice_platform.database import async_session  # Session factory for creating new DB sessions
from voice_platform.database import (
    Transcript as TranscriptRow,  # Transcript DB model (aliased to avoid name clash)
)
from voice_platform.utils import normalize_trigger_phrases


def _resolve_caller_name(call_log: CallLog, transcript_text: str) -> str:
    """Try to resolve the caller's name from analysis or transcript, fall back to 'Caller'."""
    # Try analysis_json for extracted caller name
    if call_log.analysis_json:
        try:
            analysis = json.loads(call_log.analysis_json)
            name = (
                analysis.get("caller_name")
                or analysis.get("customer_name")
                or analysis.get("contact_name")
            )
            if name and isinstance(name, str) and name.strip():
                return name.strip()
        except (json.JSONDecodeError, TypeError):
            pass
    return "Caller"


def _safe_create_task(coro, name: str = ""):
    """Create a fire-and-forget task that logs exceptions instead of silently dropping them."""
    async def _wrapper():
        try:
            await coro
        except Exception as e:
            logger.error(f"Background task '{name}' failed: {type(e).__name__}: {e}")
    return asyncio.create_task(_wrapper())


async def _auto_generate_call_summary(call_log_id: int, user_id: int):
    """Auto-generate post-call summary + analysis after a call ends.

    Competitor parity: Retell and Bland auto-generate summaries on every call.
    This runs async, doesn't block call ending, and is idempotent (skips if
    analysis_json already exists).

    Uses Deepgram Audio Intelligence API when a recording URL is available
    (purpose-built for speech analysis — sentiment, summarization, topics, intents).
    Falls back to LLM-based analysis on transcript text if no recording.
    """
    try:
        from voice_platform.config import settings
        from voice_platform.integrations.deepgram_intelligence import analyze_call_recording
        from voice_platform.runtime.observability.analysis import (
            build_transcript_text as _build_transcript_text,
        )
        from voice_platform.runtime.observability.analysis import (
            run_llm_analysis as _run_llm_analysis,
        )

        async with async_session() as session:
            # Check idempotency — skip if already analyzed
            call_log = await session.get(CallLog, call_log_id)
            if not call_log or getattr(call_log, 'analysis_json', None):
                return

            # Determine analysis provider preference from agent config
            analysis_provider = "auto"
            if call_log.agent_id:
                from voice_platform.database import Agent
                agent = await session.get(Agent, call_log.agent_id)
                if agent:
                    analysis_provider = getattr(agent, 'analysis_provider', 'auto') or 'auto'

            # ── Try Deepgram Audio Intelligence first (if recording available) ──
            recording_url = getattr(call_log, 'recording_url', None)
            use_deepgram = recording_url and analysis_provider in ("auto", "deepgram")
            if use_deepgram:
                logger.info(f"🎙️ Using Deepgram Audio Intelligence for call {call_log_id}")
                analysis = await analyze_call_recording(
                    recording_url, api_key=settings.deepgram_api_key
                )
                if analysis:
                    call_log.analysis_json = json.dumps(analysis)
                    await session.commit()
                    logger.info(
                        f"📋 Deepgram analysis for call {call_log_id}: "
                        f"sentiment={analysis.get('sentiment', 'unknown')}, "
                        f"resolution={analysis.get('resolution_status', 'unknown')}, "
                        f"intents={len(analysis.get('intents', []))}"
                    )
                    return
                logger.warning(
                    f"Deepgram Audio Intelligence failed for call {call_log_id}, "
                    f"falling back to LLM analysis"
                )

            # ── Fallback: LLM-based analysis on transcript text ──
            transcript_text = await _build_transcript_text(session, call_log_id)
            if not transcript_text or len(transcript_text.strip()) < 20:
                logger.debug(f"Auto-summary skipped for call {call_log_id}: transcript too short")
                return

            analysis = await _run_llm_analysis(transcript_text, user_id)
            if analysis:
                call_log.analysis_json = json.dumps(analysis)
                await session.commit()
                logger.info(
                    f"📋 Auto-generated summary for call {call_log_id}: "
                    f"sentiment={analysis.get('sentiment', 'unknown')}, "
                    f"resolution={analysis.get('resolution_status', 'unknown')}"
                )
    except Exception as e:
        logger.error(f"Auto call summary failed for call {call_log_id}: {type(e).__name__}: {e}")


class PersistentEventsManager(EventsManager):
    """
    Database-backed events manager that persists call data.

    Inherits from vocode's EventsManager which provides:
    - An asyncio.Queue for receiving events
    - A start() method that runs the event processing loop
    - A publish_event() method for adding events to the queue

    We override handle_event() to save events to SQLite.

    Usage:
        events_manager = PersistentEventsManager()
        # Pass to TelephonyServer:
        telephony_server = TelephonyServer(..., events_manager=events_manager)
        # Start the event loop as a background task:
        asyncio.create_task(events_manager.start())
    """

    def __init__(self):
        """Initialize with subscriptions to all relevant event types."""
        super().__init__(
            subscriptions=[
                EventType.TRANSCRIPT,           # Human/bot messages
                EventType.TRANSCRIPT_COMPLETE,   # Full transcript at end
                EventType.PHONE_CALL_CONNECTED,  # Call started
                EventType.PHONE_CALL_ENDED,      # Call ended
                EventType.PHONE_CALL_DID_NOT_CONNECT,  # Call failed to connect
                EventType.RECORDING,             # Recording URL available
                EventType.ACTION,                # Action executed
            ]
        )
        # In-memory tracking for quick access (supplements DB)
        self._active_calls: Dict[str, Dict] = {}
        self._workflow_execution_guards: Set[Tuple[int, int]] = set()
        self._latency_summaries: Dict[str, Dict] = {}
        # QA-02/03: Per-conversation last message timestamps for crosstalk detection
        self._last_bot_message_time: Dict[str, float] = {}
        # Live dashboard broadcast manager (lazy import to avoid circular)
        self._live_manager = None
        logger.info("PersistentEventsManager initialized with DB persistence")

    @staticmethod
    def _parse_trigger_phrases(value: Any) -> List[str]:
        """Normalize trigger phrase storage to a clean list of strings."""
        return normalize_trigger_phrases(value)

    @staticmethod
    def _normalize_for_matching(text: str) -> str:
        lowered = (text or "").lower()
        normalized = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in lowered)
        return " ".join(normalized.split())

    @classmethod
    def _workflow_trigger_matches(cls, transcript_text: str, triggers: List[str]) -> bool:
        transcript_norm = cls._normalize_for_matching(transcript_text)
        if not transcript_norm:
            return False
        padded_transcript = f" {transcript_norm} "
        transcript_tokens = transcript_norm.split()

        def _token_sequence_in_order(haystack: List[str], needle: List[str]) -> bool:
            if not needle:
                return False
            pos = 0
            for word in needle:
                try:
                    idx = haystack.index(word, pos)
                except ValueError:
                    return False
                pos = idx + 1
            return True

        for trigger in triggers:
            trigger_norm = cls._normalize_for_matching(trigger)
            if not trigger_norm:
                continue
            if f" {trigger_norm} " in padded_transcript:
                return True
            trigger_tokens = trigger_norm.split()
            if len(trigger_tokens) >= 2 and _token_sequence_in_order(transcript_tokens, trigger_tokens):
                return True
        return False

    @staticmethod
    def _executes_inside_call(workflow: Workflow, call_log: CallLog, agent: Optional[Agent]) -> bool:
        """Return whether this workflow graph already ran through FlowAgent."""
        if not (
            agent
            and agent.mode == "conversational_flow"
            and agent.graph_json
            and workflow.graph_json
            and workflow.agent_id == call_log.agent_id
        ):
            return False
        try:
            return json.loads(agent.graph_json) == json.loads(workflow.graph_json)
        except (TypeError, json.JSONDecodeError):
            return agent.graph_json == workflow.graph_json

    async def handle_event(self, event: Event):
        """
        Process an event and persist it to the database.

        This method is called by the parent class's event loop (start())
        for every event that matches our subscriptions.

        We wrap everything in try/except so a database error
        doesn't crash the entire event processing loop.

        Args:
            event: The event to process (typed by EventType)
        """
        try:
            # Create a new database session for this event
            # Using async_session() context manager ensures proper cleanup
            async with async_session() as session:

                if isinstance(event, TranscriptEvent):
                    # ────────────────────────────────────────────────
                    # TRANSCRIPT EVENT
                    # Fired each time a human or bot says something.
                    # We save each utterance as a row in the transcripts table.
                    # ────────────────────────────────────────────────
                    await self._handle_transcript(session, event)

                elif isinstance(event, PhoneCallConnectedEvent):
                    # ────────────────────────────────────────────────
                    # PHONE CALL CONNECTED EVENT
                    # Fired when Twilio connects the call.
                    # We update the call_log status to 'active'.
                    # ────────────────────────────────────────────────
                    await self._handle_call_connected(session, event)

                elif isinstance(event, PhoneCallEndedEvent):
                    # ────────────────────────────────────────────────
                    # PHONE CALL ENDED EVENT
                    # Fired when the call disconnects.
                    # We update call_log with end time and duration.
                    # ────────────────────────────────────────────────
                    await self._handle_call_ended(session, event)

                elif isinstance(event, RecordingEvent):
                    # ────────────────────────────────────────────────
                    # RECORDING EVENT
                    # Fired when Twilio's recording is ready.
                    # We store the recording URL in call_logs.
                    # ────────────────────────────────────────────────
                    await self._handle_recording(session, event)

                elif isinstance(event, ActionEvent):
                    # ────────────────────────────────────────────────
                    # ACTION EVENT
                    # Fired when an action (transfer, external call) executes.
                    # We log the action details to action_logs.
                    # ────────────────────────────────────────────────
                    await self._handle_action(session, event)

                elif isinstance(event, PhoneCallDidNotConnectEvent):
                    # ────────────────────────────────────────────────
                    # PHONE CALL DID NOT CONNECT
                    # Fired when the call failed (SIP error, rejected, etc.)
                    # We update call_log with failed status.
                    # ────────────────────────────────────────────────
                    await self._handle_call_did_not_connect(session, event)

                elif isinstance(event, TranscriptCompleteEvent):
                    # ────────────────────────────────────────────────
                    # TRANSCRIPT COMPLETE
                    # Fired when the full conversation transcript is ready.
                    # We trigger any matching workflows post-call.
                    # ────────────────────────────────────────────────
                    await self._handle_transcript_complete(session, event)

                # Commit all changes in this session
                await session.commit()

        except Exception as e:
            # Log but don't crash — events are best-effort
            logger.error(f"Error handling event {event.type}: {e}", exc_info=True)

    @property
    def live_manager(self):
        """Lazy-load the live dashboard manager to avoid circular imports."""
        if self._live_manager is None:
            try:
                from voice_platform.events.live import live_manager
                self._live_manager = live_manager
            except ImportError:
                pass
        return self._live_manager

    async def _handle_transcript(self, session: AsyncSession, event: TranscriptEvent):
        """
        Save a transcript message to the database.

        Maps vocode's Sender enum to our string format:
        - Sender.HUMAN → "human"
        - Sender.BOT → "bot"
        - Sender.ACTION_WORKER → "action"
        - Everything else → "system"
        """
        # Find the call_log associated with this conversation
        call_log = await self._find_call_log(session, event.conversation_id)
        if call_log is None:
            logger.warning(
                f"No call_log found for conversation {event.conversation_id}, "
                f"transcript event will not be saved"
            )
            return

        # Map vocode's sender enum to our string
        sender_map = {
            "human": "human",
            "bot": "bot",
            "action_worker": "action",
            "vector_db": "system",
            "conference": "system",
        }
        sender = sender_map.get(event.sender.value, "system")

        # QA-02: Detect interruption (human speaks within 3s of bot message)
        now = datetime.now(timezone.utc).timestamp()
        if sender == "human":
            last_bot_time = self._last_bot_message_time.get(event.conversation_id)
            if last_bot_time and (now - last_bot_time) < 3.0:
                call_log.interruption_count = (call_log.interruption_count or 0) + 1  # type: ignore[assignment]
                logger.debug(f"🔴 Interruption detected on call {event.conversation_id[:8]} (count: {call_log.interruption_count})")

        # QA-03: Detect filler audio in bot messages
        if sender == "bot":
            self._last_bot_message_time[event.conversation_id] = now
            filler_phrases = {"one moment", "let me check", "just a moment", "hold on",
                              "please wait", "i'll look that up", "give me a second",
                              "um", "uh", "hmm"}
            msg_lower = event.text.lower()
            if any(fp in msg_lower for fp in filler_phrases) or len(event.text.strip()) < 25:
                call_log.filler_count = (call_log.filler_count or 0) + 1  # type: ignore[assignment]
                logger.debug(f"🔵 Filler detected on call {event.conversation_id[:8]} (count: {call_log.filler_count})")

        # Create transcript row
        transcript = TranscriptRow(
            call_log_id=call_log.id,
            sender=sender,
            message=event.text,
            timestamp=event.timestamp,
        )
        session.add(transcript)
        logger.debug(f"💬 [{sender}] ({event.conversation_id[:8]}): {event.text[:80]}...")

        # Broadcast to live dashboard WebSocket clients
        if self.live_manager and call_log.user_id:
            _safe_create_task(
                self.live_manager.broadcast_transcript(
                    user_id=call_log.user_id,
                    conversation_id=event.conversation_id,
                    sender=sender,
                    message=event.text,
                    timestamp=event.timestamp,
                ),
                name="live_broadcast_transcript",
            )

    async def _handle_call_connected(self, session: AsyncSession, event: PhoneCallConnectedEvent):
        """
        Mark a call as connected/active in the database.

        Creates the call_log row if it doesn't exist yet.
        vocode fires this when the WebSocket is established.
        """
        call_log = await self._find_call_log(session, event.conversation_id)
        if call_log:
            # Already exists → just update status
            call_log.status = "active"
        else:
            # Create a new call_log for this conversation
            # BUG-14: Include user_id, agent_id, and direction so orphan
            # CallLogs created by the events manager have proper attribution.
            call_log = CallLog(
                conversation_id=event.conversation_id,
                from_phone=getattr(event, "from_phone_number", None) or "unknown",
                to_phone=getattr(event, "to_phone_number", None) or "unknown",
                direction="inbound",
                status="active",
                started_at=datetime.now(timezone.utc),
            )
            session.add(call_log)
            await session.flush()  # Get the ID assigned

        # Track in memory for quick access
        self._active_calls[event.conversation_id] = {
            "call_log_id": call_log.id,
            "from_phone": getattr(event, "from_phone_number", None),
            "to_phone": getattr(event, "to_phone_number", None),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            f"📞 Call connected: {getattr(event, 'from_phone_number', '?')} → "
            f"{getattr(event, 'to_phone_number', '?')} "
            f"(ID: {event.conversation_id[:8]}, DB: {call_log.id})"
        )

        # GAP-03: Dispatch call_started webhook
        if call_log.agent_id:
            from voice_platform.events.webhook_dispatcher import WebhookDispatcher
            _safe_create_task(
                WebhookDispatcher.dispatch_call_started(call_log),
                name="webhook_call_started",
            )

        # Broadcast call_started to live dashboard
        if self.live_manager and call_log.user_id:
            _safe_create_task(
                self.live_manager.broadcast_call_event(
                    user_id=call_log.user_id,
                    event_type="call_started",
                    call_data={
                        "conversation_id": event.conversation_id,
                        "call_log_id": call_log.id,
                        "from_phone": getattr(event, "from_phone_number", None),
                        "to_phone": getattr(event, "to_phone_number", None),
                        "started_at": datetime.now(timezone.utc).isoformat(),
                    },
                ),
                name="live_broadcast_call_started",
            )

    async def _handle_call_ended(self, session: AsyncSession, event: PhoneCallEndedEvent):
        """
        Mark a call as completed and record duration.

        vocode provides conversation_minutes which we convert to seconds.
        """
        call_log = await self._find_call_log(session, event.conversation_id)
        if call_log:
            # R2-D4: Don't overwrite terminal states — if call was already
            # marked 'failed' or 'cancelled', keep that status.
            if call_log.status not in ("failed", "cancelled"):
                call_log.status = "completed"
            # BUG-15: Don't overwrite ended_at/duration_secs if already set —
            # the call_status webhook may have already populated these from
            # Twilio's terminal callback which is more accurate.
            if not call_log.ended_at:
                call_log.ended_at = datetime.now(timezone.utc)
            if not call_log.duration_secs:
                call_log.duration_secs = event.conversation_minutes * 60

        # Remove from in-memory active calls
        self._active_calls.pop(event.conversation_id, None)

        # Clean up per-conversation tool state to prevent memory leaks
        from voice_platform.actions.platform_tools import clear_document_cache, clear_tool_counts
        clear_tool_counts(event.conversation_id)
        clear_document_cache(event.conversation_id)

        logger.info(
            f"📞 Call ended: {event.conversation_id[:8]} "
            f"(duration: {event.conversation_minutes:.1f} min)"
        )

        # GAP-12: Persist latency metrics if available
        latency = self._latency_summaries.pop(event.conversation_id, None)
        if call_log and latency:
            call_log.first_response_ms = latency.get("first_response_ms")
            call_log.avg_turn_latency_ms = latency.get("avg_turn_latency_ms")
            call_log.llm_latency_ms = latency.get("llm_latency_ms")
            call_log.tts_latency_ms = latency.get("tts_latency_ms")
            call_log.stt_latency_ms = latency.get("stt_latency_ms")

        # Broadcast call_ended to live dashboard
        if self.live_manager and call_log and call_log.user_id:
            _safe_create_task(
                self.live_manager.broadcast_call_event(
                    user_id=call_log.user_id,
                    event_type="call_ended",
                    call_data={
                        "conversation_id": event.conversation_id,
                        "duration_secs": event.conversation_minutes * 60,
                    },
                ),
                name="live_broadcast_call_ended",
            )

        # GAP-03: Dispatch call_ended webhook with full context
        if call_log and call_log.agent_id:
            from voice_platform.events.webhook_dispatcher import WebhookDispatcher
            _safe_create_task(
                WebhookDispatcher.dispatch_call_ended(call_log),
                name="webhook_call_ended",
            )

        # Auto-generate post-call summary (competitor parity: Retell/Bland do this on every call)
        if call_log and call_log.user_id and not getattr(call_log, 'analysis_json', None):
            _safe_create_task(
                _auto_generate_call_summary(call_log.id, call_log.user_id),
                name="auto_call_summary",
            )

    async def _handle_recording(self, session: AsyncSession, event: RecordingEvent):
        """Store the recording URL from Twilio."""
        call_log = await self._find_call_log(session, event.conversation_id)
        if call_log:
            call_log.recording_url = event.recording_url
        logger.info(f"🎙️ Recording available for {event.conversation_id[:8]}")

    async def _handle_action(self, session: AsyncSession, event: ActionEvent):
        """
        Log an action execution to the database with detailed tool call tracing.

        Extracts tool_name, latency, and error information from the action
        event data for debugging and analytics.
        """
        call_log = await self._find_call_log(session, event.conversation_id)
        if call_log is None:
            return

        action_input = event.action_input if isinstance(event.action_input, dict) else {}
        action_output = event.action_output if isinstance(event.action_output, dict) else {}

        # Extract action type from the event data
        action_type = action_input.get("action_config", {}).get("type", "unknown")

        # Extract specific tool name (e.g. 'read_drive_file', 'send_email')
        tool_name = (
            action_input.get("tool_name")
            or action_input.get("action_config", {}).get("tool_name")
            or action_input.get("action_config", {}).get("parameters", {}).get("tool_name")
            or action_type
        )
        if tool_name == "unknown":
            tool_name = None

        # Compute latency from timestamps in the event data if available
        latency_ms = None
        start_ts = action_input.get("timestamp") or action_input.get("start_time")
        end_ts = action_output.get("timestamp") or action_output.get("end_time")
        if start_ts and end_ts:
            try:
                latency_ms = round((float(end_ts) - float(start_ts)) * 1000, 1)
            except (TypeError, ValueError):
                pass

        # Detect errors from the action output
        is_error = False
        error_message = None
        if action_output:
            if action_output.get("error"):
                is_error = True
                err = action_output.get("error")
                error_message = str(err) if isinstance(err, str) else json.dumps(err)[:500]
            elif action_output.get("success") is False:
                is_error = True
                error_message = action_output.get("error_message") or action_output.get("message") or "Tool call failed"
            elif action_output.get("status") in ("error", "failed"):
                is_error = True
                error_message = action_output.get("message") or action_output.get("error") or "Tool call failed"

        action_log = ActionLog(
            call_log_id=call_log.id,
            action_type=action_type,
            tool_name=tool_name,
            conversation_id=event.conversation_id,
            params_json=json.dumps(action_input, default=str) if action_input else None,
            result_json=json.dumps(action_output, default=str) if action_output else None,
            timestamp=time.time(),
            latency_ms=latency_ms,
            is_error=is_error,
            error_message=error_message,
        )
        session.add(action_log)
        await session.flush()

        if self.live_manager and call_log.user_id:
            _safe_create_task(
                self.live_manager.broadcast_action(
                    user_id=call_log.user_id,
                    conversation_id=event.conversation_id,
                    action_data=action_log.to_dict(),
                ),
                name="live_broadcast_action",
            )
        logger.info(
            f"⚡ Action logged: {action_type}"
            f" tool={tool_name or 'n/a'}"
            f" latency={latency_ms or 'n/a'}ms"
            f" error={'yes' if is_error else 'no'}"
            f" for {event.conversation_id[:8]}"
        )

    async def _find_call_log(self, session: AsyncSession, conversation_id: str) -> Optional[CallLog]:
        """
        Look up a call_log record by vocode's conversation_id.

        Returns None if not found (which can happen for calls that
        weren't initiated through our platform).
        """
        result = await session.execute(
            select(CallLog).where(CallLog.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()

    # ── New Handlers ───────────────────────────────────────────────

    async def _handle_call_did_not_connect(self, session: AsyncSession, event: PhoneCallDidNotConnectEvent):
        """
        Handle calls that failed to connect (SIP error, timeout, busy, etc).
        Updates CallLog status so it doesn't remain stuck at 'initiated'.
        """
        call_log = await self._find_call_log(session, event.conversation_id)
        if call_log:
            call_log.status = "failed"
            call_log.ended_at = datetime.now(timezone.utc)
        self._active_calls.pop(event.conversation_id, None)
        logger.warning(
            f"📞 Call did not connect: {event.conversation_id[:8]} "
            f"(status: {event.telephony_status})"
        )

    async def _handle_transcript_complete(self, session: AsyncSession, event):
        """
        Handle the end-of-call transcript — trigger matching workflows.

        This is the KEY mechanism for automated workflow execution:
        1. Get the full transcript text from the TranscriptCompleteEvent
        2. Look up the call's user_id and from_phone
        3. Find workflows with trigger phrases that match the transcript
        4. Execute matching workflows with the call context
        """
        call_log = await self._find_call_log(session, event.conversation_id)
        if not call_log or not call_log.user_id:
            return

        # Build full transcript text from the event
        transcript_text = ""
        if hasattr(event, 'transcript') and event.transcript:
            try:
                human_chunks: List[str] = []
                all_chunks: List[str] = []
                for entry in event.transcript.event_logs:
                    text = getattr(entry, "text", None)
                    if not text:
                        continue
                    all_chunks.append(text)
                    sender = getattr(entry, "sender", None)
                    sender_value = getattr(sender, "value", str(sender)).lower() if sender else ""
                    if sender_value == "human":
                        human_chunks.append(text)
                transcript_text = " ".join(human_chunks or all_chunks)
            except Exception:
                transcript_text = str(event.transcript)

        if not transcript_text:
            return

        # Find matching workflows
        try:
            result = await session.execute(
                select(Workflow).where(
                    Workflow.user_id == call_log.user_id,
                    Workflow.is_active == True,
                )
            )
            workflows = result.scalars().all()
            runtime_agent = (
                await session.get(Agent, call_log.agent_id)
                if call_log.agent_id is not None
                else None
            )

            # Idempotency: skip workflows already executed for this call.
            # We store a workflow_execution action log with workflow_id in params_json.
            action_result = await session.execute(
                select(ActionLog).where(
                    ActionLog.call_log_id == call_log.id,
                    ActionLog.action_type == "workflow_execution",
                )
            )
            already_executed_workflow_ids = set()
            for log in action_result.scalars().all():
                try:
                    payload = json.loads(log.params_json) if log.params_json else {}
                except json.JSONDecodeError:
                    payload = {}
                workflow_id = payload.get("workflow_id")
                if isinstance(workflow_id, int):
                    already_executed_workflow_ids.add(workflow_id)

            # Idempotency for approval queue entries
            from voice_platform.database import ReviewQueue
            review_result = await session.execute(
                select(ReviewQueue).where(
                    ReviewQueue.call_log_id == call_log.id,
                    ReviewQueue.action_type == "workflow_execution",
                    ReviewQueue.status == "pending",
                )
            )
            pending_review_workflow_ids = {
                review.workflow_id for review in review_result.scalars().all() if review.workflow_id
            }

            for wf in workflows:
                if self._executes_inside_call(wf, call_log, runtime_agent):
                    logger.info(
                        f"Skipping post-call replay of workflow '{wf.name}' — "
                        "its graph already executed in-call through FlowAgent"
                    )
                    continue
                if wf.id in already_executed_workflow_ids:
                    logger.info(f"Skipping workflow '{wf.name}' — already executed for this call")
                    continue

                triggers = self._parse_trigger_phrases(wf.trigger_phrases)
                matched = self._workflow_trigger_matches(transcript_text, triggers)

                if matched:
                    in_memory_key = (call_log.id, wf.id)
                    guard_key = f"workflow_guard:{call_log.id}:{wf.id}"
                    redis_locked = await RedisCache.set_nx(guard_key, True, ttl_seconds=300)
                    if redis_locked:
                        lock_acquired = True
                    else:
                        # Fallback to in-memory guard if Redis is unavailable or lock exists
                        if in_memory_key in self._workflow_execution_guards:
                            logger.info(
                                f"Skipping workflow '{wf.name}' — already being processed for this call"
                            )
                            continue
                        self._workflow_execution_guards.add(in_memory_key)
                        lock_acquired = False

                    logger.info(
                        f"🔗 Workflow '{wf.name}' triggered by transcript "
                        f"match in call {event.conversation_id[:8]}"
                    )
                    try:
                        if wf.requires_approval:
                            if wf.id in pending_review_workflow_ids:
                                logger.info(f"Workflow '{wf.name}' already has a pending approval item")
                                continue

                            steps = json.loads(wf.steps_json) if wf.steps_json else []
                            graph = json.loads(wf.graph_json) if wf.graph_json else None
                            caller_name = _resolve_caller_name(call_log, transcript_text)
                            context = {
                                "caller_name": caller_name,
                                "caller_phone": call_log.from_phone or "unknown",
                                "transcript": transcript_text[:2000],
                            }

                            # Create a review queue entry instead of executing
                            review = ReviewQueue(
                                workflow_id=wf.id,
                                call_log_id=call_log.id,
                                user_id=call_log.user_id,
                                action_type="workflow_execution",
                                action_url=wf.action_url,
                                action_params=json.dumps({
                                    "workflow_id": wf.id,
                                    "caller_phone": call_log.from_phone,
                                    "workflow_name": wf.name,
                                    "steps": steps,
                                    "graph": graph,
                                    "context": context,
                                }),
                                trigger_context=transcript_text[:500],
                                status="pending",
                            )
                            session.add(review)
                            logger.info(f"📋 Review created for workflow '{wf.name}' (requires approval)")
                        else:
                            # Execute immediately in background
                            try:
                                from voice_platform.integrations.executor import WorkflowExecutor
                                from voice_platform.integrations.plugins.registry import (
                                    build_default_plugin_registry,
                                )
                                executor = WorkflowExecutor(session, call_log.user_id, plugin_registry=build_default_plugin_registry(), agent_id=call_log.agent_id)

                                steps = json.loads(wf.steps_json) if wf.steps_json else []
                                graph = json.loads(wf.graph_json) if wf.graph_json else None
                                if not steps and not graph:
                                    logger.warning(f"Workflow '{wf.name}' has no steps/graph, skipping")
                                    continue

                                caller_name = _resolve_caller_name(call_log, transcript_text)
                                context = {
                                    "caller_name": caller_name,
                                    "caller_phone": call_log.from_phone or "unknown",
                                    "transcript": transcript_text[:2000],
                                }

                                execution = await executor.execute_workflow(
                                    steps=steps,
                                    graph=graph,
                                    context=context,
                                )
                                step_results = execution.get("results", [])
                                session.add(ActionLog(
                                    call_log_id=call_log.id,
                                    action_type="workflow_execution",
                                    params_json=json.dumps({
                                        "workflow_id": wf.id,
                                        "workflow_name": wf.name,
                                        "mode": execution.get("mode", "steps"),
                                    }),
                                    result_json=json.dumps({
                                        "success": True,
                                        "mode": execution.get("mode", "steps"),
                                        "results": step_results,
                                    }),
                                    timestamp=time.time(),
                                ))
                                logger.info(
                                    f"✅ Workflow '{wf.name}' auto-executed ({execution.get('mode', 'steps')}): "
                                    f"{len(step_results)} steps completed"
                                )
                            except Exception as e:
                                session.add(ActionLog(
                                    call_log_id=call_log.id,
                                    action_type="workflow_execution",
                                    params_json=json.dumps({"workflow_id": wf.id, "workflow_name": wf.name}),
                                    result_json=json.dumps({"success": False, "error": str(e)}),
                                    timestamp=time.time(),
                                ))
                                logger.error(f"Failed to auto-execute workflow '{wf.name}': {e}")
                    finally:
                        if lock_acquired:
                            await RedisCache.delete(guard_key)
                        else:
                            self._workflow_execution_guards.discard(in_memory_key)
        except Exception as e:
            logger.error(f"Error in transcript_complete workflow matching: {e}")

    # ── Convenience Methods for API ────────────────────────────────

    def get_active_calls(self) -> Dict[str, Dict]:
        """Get all currently active calls (from in-memory tracking)."""
        return dict(self._active_calls)

    def get_active_call_count(self) -> int:
        """Get number of currently active calls."""
        return len(self._active_calls)

    def _store_latency_summary(self, conversation_id: str, latency: dict) -> None:
        """Store latency summary for a conversation (GAP-12).

        Called by AbstractPhoneConversation.terminate() before publishing
        PhoneCallEndedEvent so the metrics can be persisted to the DB.
        """
        self._latency_summaries[conversation_id] = latency
