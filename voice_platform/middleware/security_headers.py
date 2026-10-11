"""
Voice Platform — Security Headers Middleware

Adds browser security headers to every HTTP response:
  • X-Content-Type-Options: nosniff
  • X-Frame-Options: DENY
  • Strict-Transport-Security (HSTS)
  • Referrer-Policy: strict-origin-when-cross-origin
  • X-XSS-Protection: 0 (modern browsers; CSP is the preferred defense)

Usage:
  from voice_platform.middleware.security_headers import SecurityHeadersMiddleware
  app.add_middleware(SecurityHeadersMiddleware)
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects security headers into all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"

        # Only set HSTS when served over HTTPS (or behind a TLS-terminating proxy
        # that sets X-Forwarded-Proto). Setting HSTS on plain HTTP can lock out
        # users who accidentally visit the HTTP URL.
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if request.url.scheme == "https" or forwarded_proto == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response
