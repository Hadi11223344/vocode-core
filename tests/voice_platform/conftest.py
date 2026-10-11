"""
Shared fixtures for voice_platform tests.

Provides an isolated in-memory SQLite database, pre-created users and agents,
and a configured httpx AsyncClient wired to the FastAPI app with dependency
overrides for authentication and database session.
"""

import json
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from voice_platform.database import (
    Agent,
    Base,
    CallLog,
    Integration,
    ReviewQueue,
    Setting,
    Transcript,
    User,
    UserApiKey,
    Workflow,
    get_db,
)

# ---------------------------------------------------------------------------
# In-memory async SQLite engine shared across all tests in a module
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite://"  # in-memory


@pytest_asyncio.fixture()
async def async_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    _Session = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with _Session() as session:
        yield session


# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        google_id="google-test-123",
        email="test@example.com",
        name="Test User",
        picture_url="https://example.com/pic.jpg",
        role="user",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        google_id="google-admin-456",
        email="admin@example.com",
        name="Admin User",
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def test_agent(db_session: AsyncSession, test_user: User) -> Agent:
    agent = Agent(
        user_id=test_user.id,
        name="Test Agent",
        prompt_preamble="You are a helpful assistant.",
        initial_message="Hello!",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        stt_provider="deepgram",
        tts_provider="gtts",
        temperature=0.7,
        max_tokens=2048,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest_asyncio.fixture()
async def test_call(db_session: AsyncSession, test_user: User, test_agent: Agent) -> CallLog:
    call = CallLog(
        conversation_id="conv-test-001",
        agent_id=test_agent.id,
        user_id=test_user.id,
        from_phone="+15551234567",
        to_phone="+15559876543",
        direction="inbound",
        status="active",
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)
    return call


@pytest_asyncio.fixture()
async def completed_call(db_session: AsyncSession, test_user: User, test_agent: Agent) -> CallLog:
    call = CallLog(
        conversation_id="conv-test-002",
        agent_id=test_agent.id,
        user_id=test_user.id,
        from_phone="+15551234567",
        to_phone="+15559876543",
        direction="inbound",
        status="completed",
        ended_at=datetime.now(timezone.utc),
        duration_secs=120.5,
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)
    return call


@pytest_asyncio.fixture()
async def test_transcript(db_session: AsyncSession, test_call: CallLog) -> list[Transcript]:
    transcripts = [
        Transcript(call_log_id=test_call.id, sender="human", message="Hi there", timestamp=1.0),
        Transcript(call_log_id=test_call.id, sender="bot", message="Hello! How can I help?", timestamp=2.0),
    ]
    db_session.add_all(transcripts)
    await db_session.commit()
    return transcripts


@pytest_asyncio.fixture()
async def test_workflow(db_session: AsyncSession, test_user: User, test_agent: Agent) -> Workflow:
    wf = Workflow(
        user_id=test_user.id,
        name="Test Workflow",
        description="A test workflow",
        trigger_phrases=json.dumps(["schedule appointment", "book meeting"]),
        agent_id=test_agent.id,
        action_type="webhook",
        action_url="https://example.com/webhook",
        requires_approval=False,
    )
    db_session.add(wf)
    await db_session.commit()
    await db_session.refresh(wf)
    return wf


@pytest_asyncio.fixture()
async def test_review(db_session: AsyncSession, test_user: User, test_call: CallLog) -> ReviewQueue:
    review = ReviewQueue(
        call_log_id=test_call.id,
        user_id=test_user.id,
        action_type="webhook",
        action_url="https://example.com/action",
        action_params=json.dumps({"key": "value"}),
        trigger_context="User said: schedule appointment",
        status="pending",
    )
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)
    return review


@pytest_asyncio.fixture()
async def seed_settings(db_session: AsyncSession) -> list[Setting]:
    settings = [
        Setting(key="default_llm_provider", value="openai"),
        Setting(key="default_llm_model", value="gpt-4o-mini"),
        Setting(key="default_stt_provider", value="deepgram"),
        Setting(key="default_tts_provider", value="gtts"),
        Setting(key="platform_name", value="VOIA"),
    ]
    db_session.add_all(settings)
    await db_session.commit()
    return settings


# ---------------------------------------------------------------------------
# FastAPI test client with dependency overrides
# ---------------------------------------------------------------------------
def _build_db_override(db_session: AsyncSession):
    """Return an async generator that yields the test db_session."""

    async def _override():
        yield db_session

    return _override


def _build_user_override(user: User):
    """Return a dependency that always returns the given user."""

    async def _override():
        return user

    return _override


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession, test_user: User) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient authenticated as the normal test_user."""
    # Import here to avoid top-level side-effects (dotenv loading, engine creation)
    from voice_platform.main import app
    from voice_platform.middleware.auth_middleware import get_current_user

    app.dependency_overrides[get_db] = _build_db_override(db_session)
    app.dependency_overrides[get_current_user] = _build_user_override(test_user)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def admin_client(
    db_session: AsyncSession, admin_user: User
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient authenticated as the admin_user."""
    from voice_platform.main import app
    from voice_platform.middleware.auth_middleware import get_current_user, require_admin

    app.dependency_overrides[get_db] = _build_db_override(db_session)
    app.dependency_overrides[get_current_user] = _build_user_override(admin_user)
    app.dependency_overrides[require_admin] = _build_user_override(admin_user)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
