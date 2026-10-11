"""CredentialProvider — resolves secrets at LLM client creation time.

Secrets flow: CredentialProvider → LLMFactory → LLMClient

They do NOT flow through ExecutionContext or RuntimeConfig.
This replaces the temporary _TemporaryProviderCredentials from M4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class CredentialProvider(Protocol):
    """Resolves provider credentials (API keys, base URLs) on demand.

    Implementations may fetch from environment, DB, vault, etc.
    The credential provider is the ONLY component that handles secrets.
    LLMFactory calls it; nothing else should.
    """

    def get_api_key(self, provider: str, user_id: int | None = None) -> str | None:
        """Resolve the API key for a given provider and optional user context."""
        ...

    def get_base_url(self, provider: str, user_id: int | None = None) -> str | None:
        """Resolve an optional base URL override for a given provider."""
        ...


@dataclass(frozen=True)
class ResolvedCredentials:
    """Immutable resolved credentials — returned by SimpleCredentialProvider."""

    api_key: str | None = None
    base_url: str | None = None


class SimpleCredentialProvider:
    """Simple in-memory credential provider for testing and basic deployments.

    For production, use a DB-backed or vault-backed implementation.
    """

    def __init__(
        self,
        api_keys: dict[str, str] | None = None,
        base_urls: dict[str, str] | None = None,
    ) -> None:
        self._api_keys = api_keys or {}
        self._base_urls = base_urls or {}

    def get_api_key(self, provider: str, user_id: int | None = None) -> str | None:
        return self._api_keys.get(provider)

    def get_base_url(self, provider: str, user_id: int | None = None) -> str | None:
        return self._base_urls.get(provider)

    def resolve(self, provider: str, user_id: int | None = None) -> ResolvedCredentials:
        """Resolve both api_key and base_url in one call."""
        return ResolvedCredentials(
            api_key=self.get_api_key(provider, user_id),
            base_url=self.get_base_url(provider, user_id),
        )
