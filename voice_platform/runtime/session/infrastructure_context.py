"""InfrastructureContext — immutable infrastructure dependencies.

Contains only Protocol abstractions (DatabaseSession, Cache, EventBus, Tracer,
PluginRegistry, CredentialProvider). No SQLAlchemy or Redis imports.
Secrets are resolved by CredentialProvider at LLM client creation time,
not stored in the execution context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from voice_platform.integrations.plugins.registry import PluginRegistry
from voice_platform.runtime.events.event_bus import EventBus
from voice_platform.runtime.infra.cache import Cache
from voice_platform.runtime.infra.db import DatabaseSession
from voice_platform.runtime.llm.credential_provider import CredentialProvider
from voice_platform.runtime.tracing.tracer import Tracer


@dataclass(frozen=True)
class InfrastructureContext:
    """Immutable infrastructure context — protocols only, no concrete classes.

    Attributes:
        db: Database session protocol.
        cache: Cache protocol.
        event_bus: Event bus protocol.
        tracer: Tracer protocol.
        plugin_registry: Plugin registry protocol.
        credential_provider: Resolves secrets at LLM client creation time.
        state_manager: Deferred — TODO: Protocol when state architecture finalized.
    """

    db: DatabaseSession
    cache: Cache
    event_bus: EventBus
    tracer: Tracer
    plugin_registry: PluginRegistry
    credential_provider: CredentialProvider | None = None
    state_manager: Any | None = None
