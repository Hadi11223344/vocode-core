"""Tests for ServiceContainer — construction validation, shared registry, immutability."""

import pytest

from voice_platform.integrations.plugins.registry import (
    DefaultPluginRegistry,
    DuplicatePluginError,
    EmptyPluginRegistry,
    RegistryFrozenError,
    UnknownPluginError,
)
from voice_platform.runtime.session.service_container import ServiceContainer


class TestServiceContainerConstruction:
    """ServiceContainer() construction validates and freezes all services."""

    def test_construction_succeeds(self):
        container = ServiceContainer()
        assert container is not None

    def test_registry_contains_expected_plugins(self):
        container = ServiceContainer()
        aliases = container.plugin_registry.aliases()
        assert len(aliases) > 0
        assert "google_calendar" in aliases
        assert "email" in aliases
        assert "sms" in aliases
        assert "webhook" in aliases

    def test_registry_is_frozen_after_construction(self):
        container = ServiceContainer()
        with pytest.raises(RegistryFrozenError):
            container.plugin_registry.register("new_alias", type("FakePlugin", (), {"kinds": ("new_alias",)})())

    def test_registry_validated_during_construction(self):
        """If construction succeeds, the registry passed validation."""
        container = ServiceContainer()
        # No exception means validate() passed
        assert container.plugin_registry is not None


class TestServiceContainerSharedRegistry:
    """Single ServiceContainer shared across callers returns same registry instance."""

    def test_shared_registry_returns_same_instance(self):
        container = ServiceContainer()
        reg1 = container.plugin_registry
        reg2 = container.plugin_registry
        assert reg1 is reg2

    def test_read_only_property(self):
        """plugin_registry is a read-only property — cannot be set."""
        container = ServiceContainer()
        with pytest.raises(AttributeError):
            container.plugin_registry = EmptyPluginRegistry()


class TestUnknownPluginError:
    """registry.get("missing") raises UnknownPluginError (inherits LookupError)."""

    def test_get_missing_raises_unknown_plugin_error(self):
        registry = DefaultPluginRegistry()
        with pytest.raises(UnknownPluginError):
            registry.get("nonexistent")

    def test_unknown_plugin_error_inherits_lookup_error(self):
        assert issubclass(UnknownPluginError, LookupError)

    def test_empty_registry_get_raises(self):
        registry = EmptyPluginRegistry()
        with pytest.raises(UnknownPluginError):
            registry.get("anything")


class TestDuplicatePluginError:
    """register() raises DuplicatePluginError on duplicate alias."""

    def test_duplicate_alias_raises(self):
        registry = DefaultPluginRegistry()

        class FakePlugin:
            kinds = ("test",)

        plugin = FakePlugin()
        registry.register("test", plugin)
        with pytest.raises(DuplicatePluginError):
            registry.register("test", plugin)


class TestRegistryFrozenError:
    """freeze() prevents further registration. Idempotent."""

    def test_register_after_freeze_raises(self):
        registry = DefaultPluginRegistry()

        class FakePlugin:
            kinds = ("test",)

        registry.register("test", FakePlugin())
        registry.freeze()
        with pytest.raises(RegistryFrozenError):
            registry.register("another", FakePlugin())

    def test_freeze_is_idempotent(self):
        registry = DefaultPluginRegistry()
        registry.freeze()
        registry.freeze()  # Should not raise


class TestValidate:
    """validate() checks internal consistency."""

    def test_empty_registry_raises(self):
        registry = DefaultPluginRegistry()
        with pytest.raises(ValueError, match="empty"):
            registry.validate()

    def test_valid_registry_passes(self):
        registry = DefaultPluginRegistry()

        class FakePlugin:
            kinds = ("test_service",)

        registry.register("test_service", FakePlugin())
        registry.validate()  # Should not raise

    def test_plugin_without_kinds_raises(self):
        registry = DefaultPluginRegistry()

        class BadPlugin:
            kinds = ()

        registry.register("bad", BadPlugin())
        with pytest.raises(ValueError, match="no kinds"):
            registry.validate()
