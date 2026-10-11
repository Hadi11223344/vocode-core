"""Deprecated — imports from integrations.plugins.registry.

This module will be removed in a future cleanup. Update imports to:
    from voice_platform.integrations.plugins.registry import PluginRegistry, EmptyPluginRegistry
"""

from voice_platform.integrations.plugins.registry import EmptyPluginRegistry, PluginRegistry

__all__ = ["PluginRegistry", "EmptyPluginRegistry"]
