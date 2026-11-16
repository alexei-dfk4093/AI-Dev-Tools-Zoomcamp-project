"""Request observability middleware.

Every HTTP request becomes one journey: the middleware assigns a trace id,
opens the root span, correlates its logs and metrics, and returns the trace
id to the client in the ``X-Trace-Id`` response header. Health checks and
the observability API itself are not traced, so they cannot flood the store.
"""

import logging
import secrets
import time

from app.core.config import get_settings
from app.core.telemetry import (
    API_REQUEST_COUNT,
    API_REQUEST_DURATION_MS,
    SPAN_RETENTION_LIMIT,
    Span,
    SpanContext,
    _current_span,
    record_metric,
    sanitize_attributes,
)
from app.repositories import telemetry_repository

logger = logging.getLogger(__name__)

# Paths that are never traced: liveness checks and the telemetry UI's own
# reads would otherwise dominate every stored journey.
UNTRACED_PATH_PREFIXES = ("/api/v1/observability",)
UNTRACED_PATHS = ("/health",)


class ObservabilityMiddleware:
    """Assign a trace id per request and record the root span and metrics."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or self._is_untraced(scope):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if not settings.telemetry_enabled:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        route_template = _route_template(scope)
        trace_id = secrets.token_hex(16)
        span_id = secrets.token_hex(8)

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            name=f"{method} {route_template}",
            attributes=sanitize_attributes(
                {
                    "method": method,
                    "route": route_template,
                }
            ),
        )
        token = _current_span.set(SpanContext(trace_id, span_id))
        started = time.perf_counter()
        status_code = 500
        failed = False

        async def send_with_trace_header(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                headers = list(message.get("headers") or [])
                headers.append((b"x-trace-id", trace_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_header)
        except Exception as exc:
            failed = True
            span.mark_error(exc)
            raise
        finally:
            _current_span.reset(token)
            span.set_attributes(
                {
                    "http.status_code": status_code if not failed else 500,
                    "http.route": route_template,
                }
            )
            self._store(span, method, route_template, status_code if not failed else 500)

    @staticmethod
    def _is_untraced(scope) -> bool:
        path = scope.get("path", "")
        return path in UNTRACED_PATHS or any(
            path.startswith(prefix) for prefix in UNTRACED_PATH_PREFIXES
        )

    @staticmethod
    def _store(
        span: Span,
        method: str,
        route_template: str,
        status_code: int,
    ) -> None:
        try:
            telemetry_repository.insert_span(span.to_row())
            telemetry_repository.prune_spans(SPAN_RETENTION_LIMIT)
            record_metric(
                API_REQUEST_COUNT,
                1,
                {"method": method, "route": route_template, "status": status_code},
                trace_id=span.trace_id,
            )
            record_metric(
                API_REQUEST_DURATION_MS,
                span.duration_ms,
                {"method": method, "route": route_template},
                trace_id=span.trace_id,
            )
        except Exception:  # noqa: BLE001
            logger.debug("Telemetry request span could not be stored.", exc_info=True)


def _route_template(scope) -> str:
    """Prefer the matched route template over the concrete path."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return scope.get("path", "")
