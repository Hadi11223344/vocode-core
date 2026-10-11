"""ExecutionContext — immutable composition root for a conversation.

Composed of three sub-contexts:
  - ConversationContext: identity (who, which agent, channel)
  - RuntimeConfig: runtime configuration (model, prompt, tools, enrichment)
  - InfrastructureContext: injected infrastructure abstractions

ExecutionContext is constructed ONLY by ExecutionContextBuilder.
All consumers treat it as immutable input.
"""

from __future__ import annotations

from dataclasses import dataclass

from voice_platform.runtime.session.conversation_context import ConversationContext
from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
from voice_platform.runtime.session.runtime_config import RuntimeConfig


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable composition root for a conversation.

    Attributes:
        conversation: Conversation identity (who, agent, channel).
        runtime: Runtime configuration (model, prompt, tools, enrichment).
        infrastructure: Injected infrastructure abstractions (db, cache, events).
    """

    conversation: ConversationContext
    runtime: RuntimeConfig
    infrastructure: InfrastructureContext
