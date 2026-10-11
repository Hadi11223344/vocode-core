"""Message middleware pipeline — async, immutable, context-aware.

PII redaction is middleware, not infrastructure. Future middlewares:
ProfanityFilter, SafetyLayer, AuditLogger, PromptCompressor, ContextTrimmer.

Middleware receives MiddlewareContext (provider, model, conversation_id,
agent_id, metadata) enabling provider-specific behavior.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from vocode.streaming.utils.pii_redaction import redact_pii_from_messages


@dataclass
class MiddlewareContext:
    """Context passed to every middleware."""
    provider: str
    model: str
    conversation_id: str | None = None
    agent_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MessageMiddleware(ABC):
    """Async middleware interface.

    Sync middleware can simply return immediately — no I/O needed.
    Async middleware (DLP, audit logging, Redis compression) won't force an API break.
    """

    @abstractmethod
    async def process(self, messages: list[dict], context: MiddlewareContext) -> list[dict]:
        """Process messages and return the (possibly modified) list."""
        ...


class PIIRedactor(MessageMiddleware):
    """Redact PII from user messages using vocode's redact_pii_from_messages."""

    async def process(self, messages: list[dict], context: MiddlewareContext) -> list[dict]:
        return redact_pii_from_messages(messages)


class MessagePipeline:
    """Immutable ordered middleware chain applied before LLM calls.

    Constructed once, no mutation after. Thread-safe.
    """

    def __init__(self, middlewares: list[MessageMiddleware] | None = None):
        self._middlewares: tuple[MessageMiddleware, ...] = tuple(middlewares) if middlewares else ()

    @property
    def middlewares(self) -> tuple[MessageMiddleware, ...]:
        return self._middlewares

    async def process(self, messages: list[dict], context: MiddlewareContext) -> list[dict]:
        for mw in self._middlewares:
            messages = await mw.process(messages, context)
        return messages
