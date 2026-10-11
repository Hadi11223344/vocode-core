from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vocode.streaming.streaming_conversation import StreamingConversation
from vocode.streaming.telephony.conversation.abstract_phone_conversation import (
    AbstractPhoneConversation,
)


class _PhoneConversation(AbstractPhoneConversation):
    async def attach_ws_and_start(self, ws):
        pass


@pytest.mark.asyncio
async def test_terminate_deletes_persisted_call_config():
    conversation = object.__new__(_PhoneConversation)
    conversation.id = "conversation-123"
    conversation._call_start_time = 0
    conversation._get_latency_summary = MagicMock(return_value={})
    conversation.events_manager = MagicMock()
    conversation.config_manager = MagicMock()
    conversation.config_manager.delete_config = AsyncMock()

    with patch.object(StreamingConversation, "terminate", new_callable=AsyncMock):
        await conversation.terminate()

    conversation.config_manager.delete_config.assert_awaited_once_with("conversation-123")
