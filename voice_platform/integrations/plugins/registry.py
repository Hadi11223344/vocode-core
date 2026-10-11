"""PluginRegistry — Protocol, DefaultPluginRegistry, and build_default_plugin_registry().

The registry maps service type aliases (e.g. "google_calendar", "hubspot")
to IntegrationPlugin instances. Registration is declarative via the PLUGINS
tuple — adding a new plugin requires only one line there.

Registry lifecycle: register → validate → freeze. After freeze(), no further
registration is allowed. This enforces immutability at runtime rather than
relying on convention.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from voice_platform.integrations.plugins.base import IntegrationPlugin


class UnknownPluginError(LookupError):
    """Raised when get() is called for an unregistered service type."""


class DuplicatePluginError(Exception):
    """Raised when register() is called with an already-registered alias."""


class RegistryFrozenError(Exception):
    """Raised when register() is called after freeze()."""


class EmptyPluginRegistry:
    """Default empty plugin registry. All queries return empty/raise.

    Used in tests and telephony path where no real registry is available.
    Implements the PluginRegistry protocol but with no plugins registered.
    """

    def register(self, alias: str, plugin: IntegrationPlugin) -> None:
        pass

    def get(self, alias: str) -> IntegrationPlugin:
        raise UnknownPluginError(f"No plugin registered for service type: {alias}")

    def supports(self, alias: str) -> bool:
        return False

    def aliases(self) -> Sequence[str]:
        return ()

    def plugins(self) -> Sequence[IntegrationPlugin]:
        return ()

    def validate(self) -> None:
        pass

    def freeze(self) -> None:
        pass


@runtime_checkable
class PluginRegistry(Protocol):
    """Protocol for integration plugin discovery and introspection."""

    def register(self, alias: str, plugin: IntegrationPlugin) -> None:
        """Register a plugin under a service type alias."""
        ...

    def get(self, alias: str) -> IntegrationPlugin:
        """Get the plugin for a service type alias. Raises UnknownPluginError if not found."""
        ...

    def supports(self, alias: str) -> bool:
        """Check if a service type alias is registered."""
        ...

    def aliases(self) -> Sequence[str]:
        """Return all registered service type aliases."""
        ...

    def plugins(self) -> Sequence[IntegrationPlugin]:
        """Return all unique plugin instances."""
        ...

    def validate(self) -> None:
        """Validate internal consistency. Raises on misconfiguration."""
        ...

    def freeze(self) -> None:
        """Freeze the registry — no further registration allowed. Idempotent."""
        ...


class DefaultPluginRegistry:
    """Concrete registry — dict keyed by service type alias string."""

    def __init__(self) -> None:
        self._by_alias: dict[str, IntegrationPlugin] = {}
        self._frozen: bool = False

    def register(self, alias: str, plugin: IntegrationPlugin) -> None:
        if self._frozen:
            raise RegistryFrozenError(
                f"Cannot register alias '{alias}' — registry is frozen"
            )
        if alias in self._by_alias:
            raise DuplicatePluginError(
                f"Alias '{alias}' is already registered"
            )
        self._by_alias[alias] = plugin

    def get(self, alias: str) -> IntegrationPlugin:
        if alias not in self._by_alias:
            raise UnknownPluginError(f"No plugin registered for service type: {alias}")
        return self._by_alias[alias]

    def supports(self, alias: str) -> bool:
        return alias in self._by_alias

    def aliases(self) -> Sequence[str]:
        return tuple(self._by_alias.keys())

    def plugins(self) -> Sequence[IntegrationPlugin]:
        seen: list[IntegrationPlugin] = []
        for p in self._by_alias.values():
            if p not in seen:
                seen.append(p)
        return tuple(seen)

    def validate(self) -> None:
        """Sanity check internal consistency."""
        if not self._by_alias:
            raise ValueError("Plugin registry is empty")

        for alias, plugin in self._by_alias.items():
            if not alias or not isinstance(alias, str):
                raise ValueError(f"Invalid alias: {alias!r}")

            if not hasattr(plugin, "kinds") or not plugin.kinds:
                raise ValueError(
                    f"Plugin for alias '{alias}' has no kinds"
                )

        # Duplicate alias check — redundant with register() but catches
        # manual dict manipulation
        if len(self._by_alias) != len(set(self._by_alias.keys())):
            raise ValueError("Duplicate aliases detected in registry")

    def freeze(self) -> None:
        """Mark registry as read-only. Idempotent — repeated calls are harmless."""
        if self._frozen:
            return
        self._frozen = True


# ── Declarative plugin list ──────────────────────────────────────────
# Adding a new integration = create plugin class + add to PLUGINS tuple.
# No other changes needed — build_default_plugin_registry() handles the rest.

PLUGINS: tuple[type[IntegrationPlugin], ...] = ()


def build_default_plugin_registry() -> PluginRegistry:
    """Build a registry with all standard plugins registered by their kinds aliases.

    Does NOT call validate() or freeze() — that is ServiceContainer's responsibility.

    Usage:
        registry = build_default_plugin_registry()
        plugin = registry.get("google_calendar")
    """
    from voice_platform.integrations.plugins.calcom import CalComPlugin
    from voice_platform.integrations.plugins.calendar import CalendarPlugin
    from voice_platform.integrations.plugins.calendly import CalendlyPlugin
    from voice_platform.integrations.plugins.crm import CRMPlugin
    from voice_platform.integrations.plugins.drive import DrivePlugin
    from voice_platform.integrations.plugins.ecommerce import EcommercePlugin
    from voice_platform.integrations.plugins.email import EmailPlugin
    from voice_platform.integrations.plugins.knowledge import KnowledgePlugin
    from voice_platform.integrations.plugins.mcp import MCPPlugin
    from voice_platform.integrations.plugins.messaging import MessagingPlugin
    from voice_platform.integrations.plugins.payments import PaymentsPlugin
    from voice_platform.integrations.plugins.productivity import ProductivityPlugin
    from voice_platform.integrations.plugins.project import ProjectPlugin
    from voice_platform.integrations.plugins.sheets import SheetsPlugin
    from voice_platform.integrations.plugins.sms import SMSPlugin
    from voice_platform.integrations.plugins.support import SupportPlugin
    from voice_platform.integrations.plugins.transfer import TransferPlugin
    from voice_platform.integrations.plugins.webhook import WebhookPlugin

    all_plugins: tuple[type[IntegrationPlugin], ...] = (
        CalendarPlugin,
        SheetsPlugin,
        EmailPlugin,
        WebhookPlugin,
        SMSPlugin,
        TransferPlugin,
        MCPPlugin,
        CalComPlugin,
        CalendlyPlugin,
        CRMPlugin,
        PaymentsPlugin,
        EcommercePlugin,
        SupportPlugin,
        ProductivityPlugin,
        ProjectPlugin,
        DrivePlugin,
        KnowledgePlugin,
        MessagingPlugin,
    )

    registry = DefaultPluginRegistry()
    for cls in all_plugins:
        plugin = cls()
        for alias in plugin.kinds:
            registry.register(alias, plugin)
    return registry
