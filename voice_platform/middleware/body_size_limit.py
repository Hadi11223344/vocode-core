"""
Voice Platform — Request Body Size Limit Middleware

Rejects requests with bodies exceeding a configurable size to prevent
memory exhaustion from oversized payloads.

Usage:
  from voice_platform.middleware.body_size_limit import BodySizeLimitMiddleware
  app.add_middleware(BodySizeLimitMiddleware, max_body_size=10 * 1024 * 1024)  # 10 MB
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects request bodies larger than max_body_size bytes."""

    def __init__(self, app, max_body_size: int = 10 * 1024 * 1024):
        self.max_body_size = max_body_size
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                cl = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "INVALID_CONTENT_LENGTH",
                            "message": "Content-Length header is not a valid integer.",
                            "suggestion": "Ensure the Content-Length header is a valid number.",
                        }
                    },
                )
            if cl > self.max_body_size:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": f"Request body exceeds maximum size of {self.max_body_size // (1024 * 1024)} MB.",
                            "suggestion": "Reduce the payload size and try again.",
                        }
                    },
                )
        return await call_next(request)
