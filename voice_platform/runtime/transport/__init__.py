"""Transport layer — abstract I/O adapters for conversation sessions."""

from voice_platform.runtime.transport.protocol import ConversationTransport
from voice_platform.runtime.transport.websocket import WebSocketTransport

__all__ = ["ConversationTransport", "WebSocketTransport"]
