"""
Voice Platform — MCP Client (Streamable HTTP Transport)
=========================================================

Communicates with external MCP (Model Context Protocol) servers using
standard JSON-RPC 2.0 over HTTP (Streamable HTTP transport).

MCP Spec Reference:
  https://modelcontextprotocol.io/specification/2025-03-26/basic/transports

Architecture:
  - list_tools()   → calls tools/list RPC, returns available tool schemas
  - call_tool()    → calls tools/call RPC, executes a named tool
  - initialize()   → sends MCP handshake (optional but recommended)

SSRF Protection:
  Internal/private URLs (localhost, 10.x, 192.168.x) are blocked before
  any HTTP request is made.

Context Window Protection:
  All responses are truncated to MAX_RESPONSE_CHARS (4000) before being
  returned to the LLM. This prevents context window overflow on large payloads.

Usage:
    client = McpClient("https://mcp.example.com", auth_token="sk-...")
    tools  = await client.list_tools()
    result = await client.call_tool("get_customer", {"email": "a@b.com"})
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from voice_platform.utils.ssrf import is_safe_url as _is_safe_url

# ── Constants ──────────────────────────────────────────────────────────

# Hard cap on response size returned to the LLM.
# MCP servers can return arbitrarily large payloads; truncating protects
# the LLM context window and avoids crashing the Vocode conversation thread.
MAX_RESPONSE_CHARS = 4000


# ── McpClient ──────────────────────────────────────────────────────────

class McpClient:
    """
    HTTP-based MCP client for tool discovery and execution.

    Implements the JSON-RPC 2.0 Streamable HTTP transport used by most
    hosted MCP servers.  Tries POST to ``{server_url}/mcp`` first; if
    that returns 404, retries the root ``server_url``.

    Args:
        server_url:  Base URL of the MCP server (trailing slash stripped).
        auth_token:  Optional Bearer token for authentication.
        timeout:     Per-request timeout in seconds (default 30).
    """

    def __init__(
        self,
        server_url: str,
        auth_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._auth_token = auth_token
        self._timeout = timeout
        self._request_id: int = 0
        self._id_lock = asyncio.Lock()  # BUG-B3 fix: thread-safe counter
        self._http_client: Optional[httpx.AsyncClient] = None
        self._initialized: bool = False
        self._session_id: Optional[str] = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Close the underlying HTTP client and free connections."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def __del__(self) -> None:
        # Synchronous fallback — fire a task to close the async client.
        # Best practice is to call aclose() explicitly via async context.
        if self._http_client is not None:
            try:
                asyncio.get_event_loop().create_task(self._http_client.aclose())
            except RuntimeError:
                pass  # No running event loop

    # ── Helpers ──────────────────────────────────────────────────────

    async def _next_id(self) -> int:
        """Return a monotonically-increasing JSON-RPC request ID (thread-safe)."""
        async with self._id_lock:
            self._request_id += 1
            return self._request_id

    def _headers(self) -> Dict[str, str]:
        """Build request headers, injecting the Bearer token if present."""
        h: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._auth_token:
            # Do NOT log this token — it is a sensitive credential.
            h["Authorization"] = f"Bearer {self._auth_token}"
        if self._session_id:
            # Stateful MCP servers (e.g. Google hosted) require this header
            # on every request after initialize.
            h["Mcp-Session-Id"] = self._session_id
        return h

    # ── Core RPC ─────────────────────────────────────────────────────

    async def _rpc(self, method: str, params: Optional[Dict] = None) -> Any:
        """
        Send a JSON-RPC 2.0 request to the MCP server.

        Tries ``{server_url}/mcp`` first.  If that endpoint returns 404,
        falls back to the bare ``server_url``.

        Raises:
            RuntimeError: On network timeout, HTTP error, or JSON-RPC error.
        """
        if not _is_safe_url(self._server_url):
            raise RuntimeError(
                f"MCP server URL blocked by SSRF policy: {self._server_url}"
            )

        # ── Lazy initialize handshake ────────────────────────────────
        # Google's hosted MCP servers require initialize before any
        # tool RPC. We call it once per client lifecycle, skipping for
        # the initialize method itself to avoid recursion.
        if not self._initialized and method != "initialize":
            try:
                await self.initialize()
                # Session ID is captured automatically by _rpc() from the
                # Mcp-Session-Id response header.
                self._initialized = True
                logger.info(f"MCP initialized: {self._server_url}")
            except Exception as init_exc:
                # Non-fatal for many open-source servers, but log it.
                logger.warning(f"MCP initialize failed ({self._server_url}): {init_exc}")
                self._initialized = True  # Don't retry endlessly

        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": await self._next_id(),
            "method": method,
        }
        if params:
            payload["params"] = params

        primary_endpoint = f"{self._server_url}/mcp"
        fallback_endpoint = self._server_url
        headers = self._headers()
        # ── BUG-B4 fix: reuse HTTP client for connection pooling ──────
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, verify=True
            )

        try:
            resp = await self._http_client.post(
                primary_endpoint, json=payload, headers=headers
            )

            # Many servers don't expose a /mcp path — fall back to root
            if resp.status_code == 404:
                logger.debug(
                    f"MCP /mcp endpoint returned 404, retrying root: {fallback_endpoint}"
                )
                resp = await self._http_client.post(
                    fallback_endpoint, json=payload, headers=headers
                )

            resp.raise_for_status()
            body = resp.json()

            # ── Stateful session tracking ─────────────────────────────
            # Google's hosted MCP servers return Mcp-Session-Id in the
            # response header after initialize. We must echo it back on
            # every subsequent request.
            session_id = resp.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id

        except httpx.TimeoutException:
            raise RuntimeError(
                f"MCP server timed out after {self._timeout}s ({self._server_url})"
            )
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"MCP server returned HTTP {exc.response.status_code} "
                f"({self._server_url}): {exc.response.text[:200]}"
            )
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"MCP network error ({self._server_url}): {exc}"
            )

        # Surface JSON-RPC level errors cleanly
        if "error" in body:
            err = body["error"]
            raise RuntimeError(
                f"MCP JSON-RPC error {err.get('code')}: {err.get('message', 'unknown')}"
            )

        return body.get("result")

    # ── Public API ───────────────────────────────────────────────────

    async def initialize(self) -> Dict:
        """
        Send the MCP initialize handshake.

        Optional but recommended for servers that require session setup.
        Safe to ignore the response — it contains server capability info.
        """
        try:
            result = await self._rpc("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {
                    "tools": {},
                },
                "clientInfo": {
                    "name": "voia-platform",
                    "version": "1.0.0",
                },
            })
            result = result or {}
            logger.info(
                f"MCP initialized: {self._server_url} | "
                f"server={result.get('serverInfo', {})} | "
                f"capabilities={result.get('capabilities', {})}"
            )
            return result
        except Exception as exc:
            # Non-fatal — many servers don't enforce the handshake
            logger.warning(f"MCP initialize skipped ({self._server_url}): {exc}")
            return {}

    async def list_tools(self, raise_on_error: bool = False) -> List[Dict]:
        """
        Fetch the list of tools available on this MCP server.

        Args:
            raise_on_error: If True, propagate network / JSON-RPC errors
                instead of silently returning an empty list.  Use this in
                test / health-check contexts so callers see the real failure.

        Returns:
            List of tool schema dicts, each with at minimum:
            ``{"name": "...", "description": "...", "inputSchema": {...}}``

            Returns an empty list if the server is unreachable or returns
            no tools, so callers don't need to guard against None.
        """
        try:
            result = await self._rpc("tools/list")
            tools = (result or {}).get("tools", [])
            logger.info(
                f"MCP tools/list returned {len(tools)} tool(s) from {self._server_url}"
            )
            if not tools and result:
                # Debug: log what the server actually returned when no tools found
                logger.debug(
                    f"MCP tools/list raw result from {self._server_url}: {json.dumps(result)[:500]}"
                )
            return tools if isinstance(tools, list) else []
        except Exception as exc:
            logger.warning(f"MCP list_tools failed ({self._server_url}): {exc}")
            if raise_on_error:
                raise
            return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict] = None,
    ) -> Dict:
        """
        Execute a named tool on the MCP server.

        The response is always truncated to ``MAX_RESPONSE_CHARS`` (4000)
        before being returned.  This is a hard safety boundary that prevents
        oversized payloads from overflowing the LLM context window or
        crashing the Vocode conversation thread.

        Args:
            tool_name:  Exact name of the tool to call (case-sensitive).
            arguments:  Dict of arguments matching the tool's inputSchema.

        Returns:
            Dict containing the tool result.  May include ``{"truncated": True}``
            if the raw response exceeded the size limit.

        Raises:
            RuntimeError: On network errors or JSON-RPC errors from the server.
        """
        logger.info(f"MCP call_tool: {tool_name} @ {self._server_url}")

        raw_result = await self._rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })

        # Normalise: some servers wrap in {"content": [...]}, others return dict
        if isinstance(raw_result, dict):
            result_payload = raw_result
        elif isinstance(raw_result, list):
            result_payload = {"items": raw_result}
        elif raw_result is None:
            result_payload = {"result": None}
        else:
            result_payload = {"data": raw_result}

        # ── Context Window Protection ──────────────────────────────
        result_str = json.dumps(result_payload)
        if len(result_str) > MAX_RESPONSE_CHARS:
            logger.warning(
                f"MCP response from {tool_name} truncated: "
                f"{len(result_str)} → {MAX_RESPONSE_CHARS} chars"
            )
            return {
                "truncated": True,
                "original_size_chars": len(result_str),
                "data": result_str[:MAX_RESPONSE_CHARS] + "...[truncated]",
            }

        return result_payload
