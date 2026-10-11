"""
Voice Platform — Request Logging & Correlation Middleware

Adds a unique request ID to every request, logs method/path/status/duration,
and propagates the request ID in response headers.

Usage:
  from voice_platform.middleware.request_logging import RequestLoggingMiddleware
  app.add_middleware(RequestLoggingMiddleware)

Response headers:
  X-Request-ID: <uuid4 hex>

Log format (loguru):
  REQUEST  GET /api/agents 200 45ms req_id=abc123
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from loguru import logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Assigns a correlation ID, logs each request, and sets response header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Generate or reuse request ID
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]

        # Attach to request state so handlers can access it
        request.state.request_id = request_id

        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            status_code = response.status_code if response else 500

            # Log with structured fields
            method = request.method
            path = request.url.path

            if status_code >= 500:
                logger.error(
                    f"REQUEST  {method} {path} {status_code} {elapsed_ms:.0f}ms "
                    f"req_id={request_id}"
                )
            elif status_code >= 400:
                logger.warning(
                    f"REQUEST  {method} {path} {status_code} {elapsed_ms:.0f}ms "
                    f"req_id={request_id}"
                )
            else:
                logger.info(
                    f"REQUEST  {method} {path} {status_code} {elapsed_ms:.0f}ms "
                    f"req_id={request_id}"
                )

        # Set response header
        response.headers["X-Request-ID"] = request_id
        return response
