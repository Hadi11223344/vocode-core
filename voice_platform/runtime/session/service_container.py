"""ServiceContainer — application-scoped owner of long-lived infrastructure services.

Construction validates all services — if __init__ succeeds, the app is valid.
Minimal: only PluginRegistry for M8. Expand only when another service
genuinely becomes application-scoped.
"""

from __future__ import annotations

from voice_platform.integrations.plugins.registry import (
    PluginRegistry,
    build_default_plugin_registry,
)


class ServiceContainer:
    """Application-scoped owner of long-lived infrastructure services.

    Constructed once during application startup (FastAPI lifespan).
    If construction succeeds, all services are valid and frozen.
    Only the lifespan handler touches app.state; all other code
    receives ServiceContainer or sub-services via dependency injection.
    """

    def __init__(self) -> None:
        self._plugin_registry = self._build_plugin_registry()

    def _build_plugin_registry(self) -> PluginRegistry:
        registry = build_default_plugin_registry()
        registry.validate()
        registry.freeze()
        return registry

    @property
    def plugin_registry(self) -> PluginRegistry:
        return self._plugin_registry
