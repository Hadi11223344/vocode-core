from __future__ import annotations

import asyncio
import hashlib
import json

from loguru import logger

from vocode.streaming.action.abstract_factory import AbstractActionFactory
from vocode.streaming.action.default_factory import DefaultActionFactory
from vocode.streaming.agent.base_agent import ActionResultAgentInput, AgentInput
from vocode.streaming.models.actions import ActionInput, ActionOutput
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.utils.state_manager import (
    AbstractConversationStateManager,
    TwilioPhoneConversationStateManager,
    VonagePhoneConversationStateManager,
)
from vocode.streaming.utils.worker import (
    AbstractWorker,
    InterruptibleEvent,
    InterruptibleEventFactory,
    InterruptibleWorker,
)

_ACTION_TIMEOUT_SECONDS = 30.0


class ActionsWorker(InterruptibleWorker):
    consumer: AbstractWorker[InterruptibleEvent[ActionResultAgentInput]]

    def __init__(
        self,
        action_factory: AbstractActionFactory,
        interruptible_event_factory: InterruptibleEventFactory = InterruptibleEventFactory(),
    ):
        super().__init__(
            interruptible_event_factory=interruptible_event_factory,
        )
        self.action_factory = action_factory
        self._tool_result_cache: dict[str, ActionOutput] = {}

    def attach_conversation_state_manager(
        self, conversation_state_manager: AbstractConversationStateManager
    ):
        self.conversation_state_manager = conversation_state_manager

    def _build_result_event(self, action_input: ActionInput, action_output: ActionOutput, is_quiet: bool) -> InterruptibleEvent:
        return self.interruptible_event_factory.create_interruptible_event(
            ActionResultAgentInput(
                conversation_id=action_input.conversation_id,
                action_input=action_input,
                action_output=action_output,
                vonage_uuid=(
                    self.conversation_state_manager.get_vonage_uuid()
                    if isinstance(
                        self.conversation_state_manager, VonagePhoneConversationStateManager
                    )
                    else None
                ),
                twilio_sid=(
                    self.conversation_state_manager.get_twilio_sid()
                    if isinstance(
                        self.conversation_state_manager, TwilioPhoneConversationStateManager
                    )
                    else None
                ),
                is_quiet=is_quiet,
            ),
            is_interruptible=False,
        )

    async def process(self, item: InterruptibleEvent[ActionInput]):
        action_input = item.payload
        action = self.action_factory.create_action(action_input.action_config)
        action.attach_conversation_state_manager(self.conversation_state_manager)

        # Tool result caching: check if we already executed this exact action
        cache_key = self._cache_key(action_input)
        if cache_key and cache_key in self._tool_result_cache:
            cached_output = self._tool_result_cache[cache_key]
            logger.debug(f"Tool cache hit for {action_input.action_config.type} (key={cache_key[:12]})")
            self.consumer.consume_nonblocking(
                self._build_result_event(action_input, cached_output, is_quiet=action.quiet)
            )
            return

        try:
            action_output = await asyncio.wait_for(
                action.run(action_input),
                timeout=_ACTION_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            # INT-1: Synthesize a cancelled ActionOutput so the transcript
            # gets a matching ActionFinish instead of an orphan ActionStart.
            cancelled_output = ActionOutput(
                action_type=action_input.action_config.type,
                canned_response=BaseMessage(text="The action was cancelled."),
                response=BaseMessage(text="cancelled"),  # type: ignore[arg-type]
            )
            self.consumer.consume_nonblocking(
                self._build_result_event(action_input, cancelled_output, is_quiet=True)
            )
            return
        except asyncio.TimeoutError:
            # Fix A: Tool execution timed out — return a user-facing message
            logger.warning(
                f"Action {action_input.action_config.type} timed out after {_ACTION_TIMEOUT_SECONDS}s "
                f"(conversation_id={action_input.conversation_id})"
            )
            timeout_output = ActionOutput(
                action_type=action_input.action_config.type,
                canned_response=BaseMessage(
                    text="I'm sorry, it's taking longer than expected to look that up. "
                         "Let me continue our conversation."
                ),
                response=BaseMessage(text="timeout"),  # type: ignore[arg-type]
            )
            self.consumer.consume_nonblocking(
                self._build_result_event(action_input, timeout_output, is_quiet=False)
            )
            return
        # Cache successful result for this conversation
        if cache_key:
            self._tool_result_cache[cache_key] = action_output
        self.consumer.consume_nonblocking(
            self._build_result_event(action_input, action_output, is_quiet=action.quiet)
        )

    def _cache_key(self, action_input: ActionInput) -> str:
        """Build a cache key from action type + params. Returns empty string if params can't be serialized."""
        try:
            params_json = action_input.action_input.params.json() if hasattr(action_input.action_input, 'params') and action_input.action_input.params else ""
            key_str = f"{action_input.action_config.type}:{params_json}"
            return hashlib.md5(key_str.encode()).hexdigest()
        except Exception:
            return ""
