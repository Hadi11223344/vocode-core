"""Exception hierarchy for the unified LLM client stack.

Adapters translate SDK exceptions into these runtime exceptions.
No SDK exception types leak upstream.
"""


class ProviderError(Exception):
    """Base for all provider-translated errors."""


class AuthenticationError(ProviderError):
    """401/403 — terminal, no retry."""


class RateLimitError(ProviderError):
    """429 — retryable."""

    def __init__(self, message: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailableError(ProviderError):
    """5xx — retryable."""


class InvalidToolCall(ProviderError):
    """Provider rejected tool format or returned malformed tool call."""


class UnsupportedCapability(ProviderError):
    """Requested feature not supported by provider (e.g. tools on Ollama streaming)."""
