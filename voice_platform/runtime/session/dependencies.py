"""FastAPI dependency providers for ServiceContainer and ConversationSessionFactory.

Only entrypoint code touches app.state; all other code receives
ServiceContainer or sub-services via these dependency providers.
"""

from __future__ import annotations

from fastapi import Request

from voice_platform.runtime.session.factory import ConversationSessionFactory
from voice_platform.runtime.session.service_container import ServiceContainer


def get_services(request: Request) -> ServiceContainer:
    """FastAPI dependency that returns the application-scoped ServiceContainer."""
    return request.app.state.services


def get_plugin_registry(request: Request):
    """FastAPI dependency that returns the application-scoped PluginRegistry."""
    return request.app.state.services.plugin_registry


def get_session_factory(request: Request) -> ConversationSessionFactory:
    """FastAPI dependency that returns the application-scoped ConversationSessionFactory."""
    return request.app.state.session_factory
