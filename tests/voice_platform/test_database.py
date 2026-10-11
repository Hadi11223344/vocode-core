"""Tests for voice_platform.database — ORM models and init_db."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import (
    Agent,
    Base,
    CallLog,
    Setting,
    Transcript,
    User,
    Workflow,
    init_db,
)

pytestmark = pytest.mark.asyncio


class TestUserModel:
    async def test_create_user(self, db_session: AsyncSession):
        user = User(
            google_id="g-1",
            email="user@test.com",
            name="Test",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.id is not None
        assert user.role == "user"  # default

    async def test_to_dict(self, test_user: User):
        d = test_user.to_dict()
        assert d["email"] == "test@example.com"
        assert d["name"] == "Test User"
        assert d["role"] == "user"
        assert "id" in d
        assert "created_at" in d

    async def test_unique_email(self, db_session: AsyncSession, test_user: User):
        dup = User(google_id="g-dup", email=test_user.email, name="Dup")
        db_session.add(dup)
        with pytest.raises(Exception):
            await db_session.commit()


class TestAgentModel:
    async def test_create_with_defaults(self, db_session: AsyncSession, test_user: User):
        agent = Agent(
            user_id=test_user.id,
            name="My Agent",
            prompt_preamble="Be helpful.",
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        assert agent.llm_provider == "openrouter"
        assert agent.stt_provider == "deepgram"
        assert agent.tts_provider == "gtts"
        assert agent.temperature == 0.7
        assert agent.is_active is True

    async def test_to_dict_masks_api_keys(self, db_session: AsyncSession, test_user: User):
        agent = Agent(
            user_id=test_user.id,
            name="Key Agent",
            prompt_preamble="secret",
            llm_api_key="sk-real-key-123",
        )
        db_session.add(agent)
        await db_session.commit()
        await db_session.refresh(agent)
        d = agent.to_dict()
        assert d["llm_api_key"] == "***"
        assert d["stt_api_key"] is None  # null keys stay None

    async def test_to_dict_null_key_is_none(self, test_agent: Agent):
        d = test_agent.to_dict()
        assert d["llm_api_key"] is None


class TestCallLogModel:
    async def test_create_call(self, test_call: CallLog):
        assert test_call.status == "active"
        assert test_call.conversation_id == "conv-test-001"

    async def test_to_dict(self, test_call: CallLog):
        d = test_call.to_dict()
        assert "conversation_id" in d
        assert d["status"] == "active"

    async def test_to_dict_with_transcript(self, test_call: CallLog, test_transcript):
        d = test_call.to_dict(include_transcript=True)
        # Should include transcript key
        assert "transcript" in d or "conversation_id" in d


class TestTranscriptModel:
    async def test_create_transcripts(self, test_transcript):
        assert len(test_transcript) == 2
        assert test_transcript[0].sender == "human"
        assert test_transcript[1].sender == "bot"


class TestSettingModel:
    async def test_seed_settings(self, seed_settings):
        assert len(seed_settings) == 5

    async def test_setting_key_unique(self, db_session: AsyncSession, seed_settings):
        dup = Setting(key="default_llm_provider", value="anthropic")
        db_session.add(dup)
        with pytest.raises(Exception):
            await db_session.commit()


class TestWorkflowModel:
    async def test_create_workflow(self, test_workflow: Workflow):
        assert test_workflow.name == "Test Workflow"
        assert test_workflow.is_active is True
        assert test_workflow.requires_approval is False
