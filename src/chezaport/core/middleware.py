"""Cross-cutting HTTP middleware."""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import UUID, uuid4

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

_REQUEST_ID_HEADER = "X-Request-ID"
log = structlog.get_logger(__name__)


def _valid_request_id(value: str | None) -> str | None:
    if not value or len(value) > 128:
        return None
    with suppress(ValueError):
        UUID(value)
        return value
    return None


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a bounded request ID to every request and response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _valid_request_id(request.headers.get(_REQUEST_ID_HEADER)) or str(uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
            response.headers[_REQUEST_ID_HEADER] = request_id
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
            )
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
            if request.url.path == "/":
                response.headers.setdefault(
                    "Content-Security-Policy",
                    "default-src 'self'; base-uri 'self'; object-src 'none'; "
                    "frame-ancestors 'none'; form-action 'self'; img-src 'self' data:; "
                    "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                    "connect-src 'self'",
                )
            if request.url.scheme == "https":
                response.headers.setdefault(
                    "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                )
            return response
        except Exception:
            log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
            )
            raise
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
