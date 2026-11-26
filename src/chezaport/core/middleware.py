"""Cross-cutting HTTP middleware."""

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from math import ceil
from time import monotonic, time
from uuid import UUID, uuid4

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

_REQUEST_ID_HEADER = "X-Request-ID"
log = structlog.get_logger(__name__)


def _valid_request_id(value: str | None) -> str | None:
    if not value or len(value) > 128:
        return None
    with suppress(ValueError):
        UUID(value)
        return value
    return None


@dataclass
class _RateBucket:
    window_started_at: float
    count: int = 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Bounded per-process public API limiter; use an edge limiter when scaling out."""

    def __init__(
        self,
        app,
        *,
        public_requests_per_minute: int = 120,
        match_report_requests_per_minute: int = 10,
        window_seconds: int = 60,
        max_buckets: int = 20_000,
    ) -> None:
        super().__init__(app)
        self.public_limit = public_requests_per_minute
        self.match_report_limit = match_report_requests_per_minute
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self._buckets: OrderedDict[tuple[str, str], _RateBucket] = OrderedDict()
        self._lock = asyncio.Lock()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if (
            not path.startswith("/api/v1/")
            or request.method == "OPTIONS"
            or path in {"/api/health/live", "/api/health/ready"}
        ):
            return await call_next(request)

        client_ip = request.client.host if request.client is not None else "unknown"
        category = "match-report" if path.endswith("/report") else "public"
        limit = self.match_report_limit if category == "match-report" else self.public_limit
        now = monotonic()
        key = (client_ip, category)

        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or now - bucket.window_started_at >= self.window_seconds:
                bucket = _RateBucket(window_started_at=now)
            if bucket.count >= limit:
                retry_after = max(1, ceil(self.window_seconds - (now - bucket.window_started_at)))
                self._buckets[key] = bucket
                self._buckets.move_to_end(key)
                response = JSONResponse(
                    {"detail": "Rate limit exceeded"},
                    status_code=429,
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(time() + retry_after)),
                    },
                )
                return response

            bucket.count += 1
            self._buckets[key] = bucket
            self._buckets.move_to_end(key)
            while len(self._buckets) > self.max_buckets:
                self._buckets.popitem(last=False)
            remaining = max(0, limit - bucket.count)
            reset_at = int(time() + max(0, self.window_seconds - (now - bucket.window_started_at)))

        response = await call_next(request)
        response.headers.setdefault("X-RateLimit-Limit", str(limit))
        response.headers.setdefault("X-RateLimit-Remaining", str(remaining))
        response.headers.setdefault("X-RateLimit-Reset", str(reset_at))
        return response


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
