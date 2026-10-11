"""Provider transport sessions — pooled connections separated by protocol.

SDKSession holds shared AsyncOpenAI (or provider SDK) clients.
HttpSession holds shared httpx.AsyncClient for raw API calls.
ProviderSession is a facade exposing both.

Adapters receive a ProviderSession and never create SDK clients directly.
This centralizes connection pooling and prevents connection leaks.
"""

from typing import Any, Optional

import httpx
from loguru import logger

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore


class SDKSession:
    """Pooled SDK client session (AsyncOpenAI or provider-specific SDK).

    Lifecycle: long-lived, shared across requests for the same provider+credentials.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 60.0,
        **extra_kwargs: Any,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._extra_kwargs = extra_kwargs
        self._client: Optional[Any] = None

    @property
    def client(self) -> Any:
        """Lazily create and cache the SDK client."""
        if self._client is None:
            if AsyncOpenAI is None:
                raise RuntimeError("openai package not installed")
            kwargs: dict[str, Any] = {"api_key": self._api_key, "timeout": self._timeout}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            kwargs.update(self._extra_kwargs)
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                logger.debug(f"SDKSession close error: {e}")
            self._client = None


class HttpSession:
    """Pooled httpx.AsyncClient for raw API calls (e.g. Ollama /api/chat).

    Lifecycle: long-lived, shared across requests.
    """

    def __init__(self, *, timeout: float = 60.0, **extra_kwargs: Any):
        self._timeout = timeout
        self._extra_kwargs = extra_kwargs
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazily create and cache the httpx client."""
        if self._client is None:
            kwargs: dict[str, Any] = {"timeout": self._timeout}
            kwargs.update(self._extra_kwargs)
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.debug(f"HttpSession close error: {e}")
            self._client = None


class ProviderSession:
    """Facade exposing separated SDK and HTTP transport sessions.

    Adapters use whichever protocol they need. Future non-OpenAI-SDK
    providers use HttpSession only.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 60.0,
        sdk_extra: dict[str, Any] | None = None,
        http_extra: dict[str, Any] | None = None,
    ):
        self._sdk = SDKSession(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            **(sdk_extra or {}),
        )
        self._http = HttpSession(
            timeout=timeout,
            **(http_extra or {}),
        )

    @property
    def sdk_client(self) -> Any:
        """Shared AsyncOpenAI (or provider SDK) client."""
        return self._sdk.client

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Shared httpx.AsyncClient for raw API calls."""
        return self._http.client

    async def close(self) -> None:
        await self._sdk.close()
        await self._http.close()
