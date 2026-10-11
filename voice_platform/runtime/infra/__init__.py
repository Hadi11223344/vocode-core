"""Infrastructure abstractions — protocols for DB, cache, events, tracing, plugins."""

from voice_platform.integrations.plugins.registry import EmptyPluginRegistry, PluginRegistry
from voice_platform.runtime.events.event_bus import EventBus, NoOpEventBus
from voice_platform.runtime.infra.cache import Cache
from voice_platform.runtime.infra.db import DatabaseSession
from voice_platform.runtime.tracing.tracer import NoOpTracer, Tracer

__all__ = [
    "Cache",
    "DatabaseSession",
    "EventBus",
    "NoOpEventBus",
    "PluginRegistry",
    "EmptyPluginRegistry",
    "Tracer",
    "NoOpTracer",
]
