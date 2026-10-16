"""Request-scoped middleware: request IDs + latency metrics.

Every request gets an X-Request-ID (or honors the caller's), which is echoed
back and attached to logs - essential for tracing issues across services.
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

try:
    from prometheus_client import Counter, Histogram

    REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "path", "status"])
    REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["path"])
    METRICS_ENABLED = True
except ImportError:  # pragma: no cover
    METRICS_ENABLED = False


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        response.headers["X-Request-ID"] = request_id
        if METRICS_ENABLED:
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path) if route else request.url.path
            REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
            REQUEST_LATENCY.labels(path).observe(elapsed)
        return response
