"""M10.5 smoke tests — verify app startup and core API endpoints respond.

These tests exercise the FastAPI application end-to-end with an in-memory
SQLite database, verifying that:
- The app starts and key routes are registered
- Core API endpoints return expected status codes
- Database models are properly initialized
- ServiceContainer is constructed without errors
- Key module imports succeed (no circular imports)
"""

import importlib
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from voice_platform.database import Base, get_db

# ── App Startup Tests ────────────────────────────────────────────────


def test_app_imports_without_error():
    """Main app module should import without circular import or syntax errors."""
    mod = importlib.import_module("voice_platform.main")
    assert hasattr(mod, "app"), "main module must expose `app`"


def test_app_has_all_routers():
    """All expected routers should be mounted on the app."""
    from voice_platform.main import app

    routes = {r.path for r in app.routes}
    # Check a representative endpoint from each router
    expected_prefixes = [
        "/api/agents",
        "/api/calls",
        "/api/keys",
        "/api/playground",
        "/api/settings",
        "/api/workflows",
        "/api/analytics",
        "/api/integrations",
        "/api/knowledge-bases",
        "/api/dashboard",
        "/health",
    ]
    for prefix in expected_prefixes:
        assert any(r.startswith(prefix) for r in routes), f"No route found for {prefix}"


def test_service_container_constructs():
    """ServiceContainer should construct without errors."""
    from voice_platform.runtime.session.service_container import ServiceContainer

    container = ServiceContainer()
    assert container.plugin_registry is not None


def test_conversation_session_factory_imports():
    """ConversationSessionFactory should import without circular dependency."""
    from voice_platform.runtime.session.factory import ConversationSessionFactory

    assert ConversationSessionFactory is not None


def test_condition_evaluator_imports():
    """ConditionEvaluator should import and be instantiable."""
    from voice_platform.runtime.flow.conditions import ConditionEvaluator

    evaluator = ConditionEvaluator()
    assert evaluator is not None


def test_key_modules_no_circular_imports():
    """Importing key modules should not trigger circular import errors."""
    modules = [
        "voice_platform.flow.nodes",
        "voice_platform.flow.compiler",
        "voice_platform.flow.executor",
        "voice_platform.runtime.llm.client",
        "voice_platform.runtime.llm.factory",
        "voice_platform.runtime.services.extraction",
        "voice_platform.runtime.services.llm",
        "voice_platform.runtime.services.knowledge",
        "voice_platform.runtime.services.memory",
        "voice_platform.runtime.session.session",
        "voice_platform.runtime.session.factory",
        "voice_platform.runtime.session.builder",
        "voice_platform.integrations.executor",
        "voice_platform.api.playground_routes",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import {mod_name}"


# ── API Endpoint Smoke Tests ─────────────────────────────────────────


TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture()
async def smoke_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def smoke_db(smoke_engine):
    _Session = sessionmaker(smoke_engine, class_=AsyncSession, expire_on_commit=False)
    async with _Session() as session:
        yield session


@pytest_asyncio.fixture()
async def smoke_client(smoke_db):
    """AsyncClient with auth bypass for smoke testing."""
    from voice_platform.database import User
    from voice_platform.main import app
    from voice_platform.middleware.auth_middleware import get_current_user

    # Create a test user
    user = User(
        google_id="smoke-test-123",
        email="smoke@test.com",
        name="Smoke Test",
        role="user",
    )
    smoke_db.add(user)
    await smoke_db.commit()
    await smoke_db.refresh(user)

    async def _db_override():
        yield smoke_db

    async def _user_override():
        return user

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_current_user] = _user_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_endpoint(smoke_client: AsyncClient):
    """Health endpoint should return 200."""
    response = await smoke_client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_agents_list(smoke_client: AsyncClient):
    """GET /api/agents should return 200."""
    response = await smoke_client.get("/api/agents")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_playground_agents_list(smoke_client: AsyncClient):
    """GET /api/playground/agents should return 200."""
    response = await smoke_client.get("/api/playground/agents")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_summary(smoke_client: AsyncClient):
    """GET /api/dashboard/stats should return 200."""
    response = await smoke_client.get("/api/dashboard/stats")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_settings_list(smoke_client: AsyncClient):
    """GET /api/settings should return 200."""
    response = await smoke_client.get("/api/settings")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_workflows_list(smoke_client: AsyncClient):
    """GET /api/workflows should return 200."""
    response = await smoke_client.get("/api/workflows")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_keys_list(smoke_client: AsyncClient):
    """GET /api/keys should return 200."""
    response = await smoke_client.get("/api/keys")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_integrations_list(smoke_client: AsyncClient):
    """GET /api/integrations should return 200."""
    response = await smoke_client.get("/api/integrations")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_kb_list(smoke_client: AsyncClient):
    """GET /api/knowledge-bases should return 200."""
    response = await smoke_client.get("/api/knowledge-bases")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_analytics_calls(smoke_client: AsyncClient):
    """GET /api/analytics/overview should return 200."""
    response = await smoke_client.get("/api/analytics/overview")
    assert response.status_code == 200
