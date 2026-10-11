"""MVP Quick-Win — runtime identity, phone routing fail-closed, graph SoT."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.diagnostics import (
    ERROR_REGISTRY,
    FailureInjection,
    build_runtime_identity,
    build_safe_error_event,
)
from voice_platform.telephony.inbound_handler import (
    PhoneAgentRoutingError,
    _validate_assigned_agent,
)


REQUIRED_PHONE_CODES = [
    "PHONE_AGENT_NOT_ASSIGNED",
    "PHONE_AGENT_NOT_FOUND",
    "PHONE_AGENT_DISABLED",
    "PHONE_AGENT_MODE_UNSUPPORTED",
    "PHONE_AGENT_CONFIG_INVALID",
]

REQUIRED_STT_CODES = [
    "STT_TIMEOUT",
    "STT_EMPTY_FINAL",
    "STT_PROVIDER_UNAVAILABLE",
    "STT_STREAM_DISCONNECTED",
    "DUPLICATE_FINAL_TRANSCRIPT",
]

REQUIRED_TTS_CODES = [
    "TTS_PROVIDER_UNAVAILABLE",
    "TTS_EMISSION_FAILED",
    "TTS_CANCEL_FAILED",
    "STALE_TTS_RESPONSE_DROPPED",
]


class TestErrorRegistryMVP:
    def test_phone_error_codes_registered(self):
        for code in REQUIRED_PHONE_CODES:
            assert code in ERROR_REGISTRY

    def test_stt_error_codes_registered(self):
        for code in REQUIRED_STT_CODES:
            assert code in ERROR_REGISTRY

    def test_tts_error_codes_registered(self):
        for code in REQUIRED_TTS_CODES:
            assert code in ERROR_REGISTRY


class TestRuntimeIdentity:
    def test_identity_has_required_fields(self):
        identity = build_runtime_identity(
            agent_id=10,
            agent_name="UMT Outreach & Sales",
            agent_mode="single_prompt",
            execution_channel="playground",
            conversation_id="conv-1",
            prompt_preamble="You are Bilal",
            model_provider="openrouter",
            stt_provider="deepgram",
            tts_provider="deepgram",
        )
        required = {
            "agent_id",
            "agent_name",
            "agent_mode",
            "execution_channel",
            "conversation_id",
            "call_id",
            "websocket_connection_id",
            "thread_id",
            "prompt_version_or_hash",
            "graph_hash",
            "executor_instance_id",
            "model_provider",
            "stt_provider",
            "tts_provider",
            "phone_number_id",
        }
        assert required.issubset(set(identity.keys()))
        assert identity["agent_id"] == "10"
        assert identity["execution_channel"] == "playground"
        assert identity["prompt_version_or_hash"]
        assert identity["executor_instance_id"]

    def test_identity_hashes_prompt_and_graph_without_raw_content(self):
        graph = {"nodes": [{"id": "n1"}], "edges": []}
        identity = build_runtime_identity(
            agent_id=14,
            agent_name="SmileCare",
            agent_mode="conversational_flow",
            execution_channel="telephony",
            conversation_id="c1",
            call_id="CA123",
            prompt_preamble="SECRET_PROMPT_CONTENT_XYZ",
            graph=graph,
        )
        blob = json.dumps(identity)
        assert "SECRET_PROMPT_CONTENT_XYZ" not in blob
        assert '"nodes"' not in blob
        assert identity["graph_hash"]
        assert identity["prompt_version_or_hash"]

    def test_identity_no_pii_fields(self):
        identity = build_runtime_identity(
            agent_id=1,
            agent_mode="single_prompt",
            execution_channel="telephony",
            conversation_id="c1",
        )
        forbidden = {"phone", "email", "transcript", "prompt", "api_key", "token"}
        assert forbidden.isdisjoint(set(identity.keys()))


class TestSafeErrorEventMVP:
    def test_includes_mvp_manual_fields(self):
        ev = build_safe_error_event(
            "PHONE_AGENT_DISABLED",
            agent_id="10",
            execution_channel="telephony",
            conversation_id="c1",
            call_id="CA1",
            tool="append_sheet",
            side_effect_attempted=True,
            side_effect_may_have_succeeded=False,
        )
        assert ev["execution_channel"] == "telephony"
        assert ev["call_id"] == "CA1"
        assert ev["tool"] == "append_sheet"
        assert ev["side_effect_attempted"] is True
        assert ev["side_effect_may_have_succeeded"] is False
        assert "manual_action_required" in ev
        assert ev["manual_action_required"] is True


class TestFailureInjectionMVP:
    def test_telephony_flags_exist_and_reset(self):
        FailureInjection.reset()
        fi = FailureInjection.instance()
        for flag in (
            "stt_timeout",
            "stt_empty_final",
            "stt_duplicate_final",
            "tts_failure",
            "provider_disconnect",
            "duplicate_completion_callback",
            "disconnect_after_booking",
            "lead_save_failure",
            "patient_lookup_failure",
            "sheets_missing_tab",
            "checkpoint_resume_failure",
        ):
            assert flag in fi.to_dict()
            fi.set(flag, True)
            assert fi.is_active(flag)
        FailureInjection.reset()
        assert not fi.any_active()


@pytest.mark.asyncio
class TestPhoneAgentValidation:
    async def test_not_assigned(self):
        session = MagicMock()
        with pytest.raises(PhoneAgentRoutingError) as exc:
            await _validate_assigned_agent(session, None)
        assert exc.value.error_code == "PHONE_AGENT_NOT_ASSIGNED"

    async def test_not_found(self):
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result
        with pytest.raises(PhoneAgentRoutingError) as exc:
            await _validate_assigned_agent(session, 999)
        assert exc.value.error_code == "PHONE_AGENT_NOT_FOUND"

    async def test_disabled(self):
        session = AsyncMock()
        agent = SimpleNamespace(
            id=9,
            is_active=False,
            mode="single_prompt",
            prompt_preamble="hi",
            graph=None,
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = agent
        session.execute.return_value = result
        with pytest.raises(PhoneAgentRoutingError) as exc:
            await _validate_assigned_agent(session, 9)
        assert exc.value.error_code == "PHONE_AGENT_DISABLED"

    async def test_flow_missing_graph(self):
        session = AsyncMock()
        agent = SimpleNamespace(
            id=14,
            is_active=True,
            mode="conversational_flow",
            prompt_preamble="hi",
            graph=None,
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = agent
        session.execute.return_value = result
        with pytest.raises(PhoneAgentRoutingError) as exc:
            await _validate_assigned_agent(session, 14)
        assert exc.value.error_code == "PHONE_AGENT_CONFIG_INVALID"

    async def test_valid_single_prompt(self):
        session = AsyncMock()
        agent = SimpleNamespace(
            id=10,
            is_active=True,
            mode="single_prompt",
            prompt_preamble="You are Bilal",
            graph=None,
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = agent
        session.execute.return_value = result
        out = await _validate_assigned_agent(session, 10)
        assert out.id == 10


class TestPlaygroundGraphSourceOfTruth:
    @pytest.mark.asyncio
    async def test_flow_runtime_uses_agent_graph_property(self):
        from voice_platform.runtime.session.factory import ConversationSessionFactory

        graph = {"nodes": [{"id": "a", "type": "conversation"}], "edges": []}
        agent = SimpleNamespace(
            id=14,
            mode="conversational_flow",
            graph_json=None,  # column empty — only property has graph
            graph=graph,
            name="SmileCare",
            prompt_preamble="x",
        )
        factory = ConversationSessionFactory(service_container=MagicMock())

        with patch(
            "voice_platform.runtime.session.adapters.playground_conversation._build_playground_conversation",
            new=AsyncMock(return_value=MagicMock()),
        ), patch(
            "voice_platform.flow.executor.LangGraphFlowExecutor"
        ) as mock_exec:
            mock_exec.return_value = MagicMock(_event_callback_failed=False)
            await factory._build_flow_runtime(agent, user_id=1)
            kwargs = mock_exec.call_args.kwargs
            assert kwargs["graph"] == graph
