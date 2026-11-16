"""In-process telemetry: correlated spans, logs and metrics.

EcoMind keeps its observability data inside the process instead of shipping
it to an external collector. Every user journey gets a trace id; spans form
a tree inside that trace; log records and metric samples carry the same
trace id; and everything is stored in SQLite next to the news cache through
``telemetry_repository``.

Sensitive data never enters the store:

- attribute keys that look like credentials are dropped,
- log messages are scrubbed for key/token patterns,
- user message text is never recorded as a span attribute,
- everything is truncated to bounded sizes.

Telemetry must never break the journey it observes: storage failures are
swallowed here, while application errors keep their normal behavior.
"""

import logging
import re
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator

from app.repositories import telemetry_repository

logger = logging.getLogger(__name__)

# Attribute key names that must never be persisted.
SENSITIVE_ATTRIBUTE_PATTERN = re.compile(
    r"(?i)(token|api[_-]?key|secret|password|authorization|credential|cookie)"
)

# Message patterns that would leak a credential inside a log line, e.g.
# "api_token=abc123" or "Authorization: Bearer abc123".
SENSITIVE_MESSAGE_PATTERN = re.compile(
    r"(?i)\b(api[_-]?token|api[_-]?key|x-api-key|authorization|password|secret)\b(\s*[:=]\s*)(\S+)"
)

MAX_ATTRIBUTE_VALUE_LENGTH = 400
MAX_MESSAGE_LENGTH = 1000

# Bounded retention, enforced on every write, so telemetry storage can
# never grow without limit.
SPAN_RETENTION_LIMIT = 1000
LOG_RETENTION_LIMIT = 2000
METRIC_RETENTION_LIMIT = 4000

# Metric names. Counters record one sample per event; durations record one
# sample (in milliseconds) per measured span.
API_REQUEST_COUNT = "api.request.count"
API_REQUEST_DURATION_MS = "api.request.duration_ms"
PROVIDER_FETCH_COUNT = "news.provider_fetch.count"
REFRESH_ARTICLES_SAVED = "news.refresh.articles_saved"
AI_REQUEST_COUNT = "ai.request.count"
AI_QUOTA_PAUSE_COUNT = "ai.quota_pause.count"


class SpanContext:
    """The trace/span ids that child spans attach to."""

    __slots__ = ("trace_id", "span_id")

    def __init__(self, trace_id: str, span_id: str) -> None:
        self.trace_id = trace_id
        self.span_id = span_id


_current_span: ContextVar[SpanContext | None] = ContextVar(
    "ecomind_current_span",
    default=None,
)


class Span:
    """One measured operation inside a trace."""

    __slots__ = (
        "trace_id",
        "span_id",
        "parent_span_id",
        "name",
        "status",
        "attributes",
        "_started_at",
        "_start_counter",
    )

    def __init__(
        self,
        *,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        name: str,
        attributes: dict[str, Any],
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.status = "ok"
        self.attributes = attributes
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._start_counter = time.perf_counter()

    def set_attributes(self, values: dict[str, Any]) -> None:
        self.attributes.update(sanitize_attributes(values))

    def mark_error(self, exc: BaseException) -> None:
        self.status = "error"
        self.attributes.update(
            sanitize_attributes(
                {
                    "error.type": type(exc).__name__,
                    "error.message": str(exc),
                }
            )
        )

    @property
    def started_at(self) -> str:
        return self._started_at

    @property
    def duration_ms(self) -> float:
        return (time.perf_counter() - self._start_counter) * 1000.0

    def to_row(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "started_at": self._started_at,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
        }


def current_trace() -> tuple[str | None, str | None]:
    """Return the active trace id and span id, if any."""
    span = _current_span.get()
    if span is None:
        return None, None
    return span.trace_id, span.span_id


@contextmanager
def start_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    *,
    metric_name: str | None = None,
    metric_dimensions: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """Measure one operation as a span of the current journey.

    Called inside an active trace the span becomes a child span; called
    without one (for example by a background task) it starts a new journey.
    When ``metric_name`` is given, one counter sample is recorded when the
    span ends, with ``outcome`` ("ok" or "error") added to its dimensions.
    """
    parent = _current_span.get()
    if parent is not None:
        trace_id = parent.trace_id
        parent_span_id: str | None = parent.span_id
    else:
        trace_id = secrets.token_hex(16)
        parent_span_id = None

    span = Span(
        trace_id=trace_id,
        span_id=secrets.token_hex(8),
        parent_span_id=parent_span_id,
        name=name,
        attributes=sanitize_attributes(attributes),
    )
    token = _current_span.set(SpanContext(span.trace_id, span.span_id))
    try:
        yield span
    except BaseException as exc:
        span.mark_error(exc)
        raise
    finally:
        _current_span.reset(token)
        _store_span(span, metric_name, metric_dimensions)


def _store_span(
    span: Span,
    metric_name: str | None,
    metric_dimensions: dict[str, Any] | None,
) -> None:
    try:
        telemetry_repository.insert_span(span.to_row())
        telemetry_repository.prune_spans(SPAN_RETENTION_LIMIT)
        if metric_name:
            record_metric(
                metric_name,
                1,
                {**(metric_dimensions or {}), "outcome": span.status},
                trace_id=span.trace_id,
            )
    except Exception:  # noqa: BLE001 - telemetry must never break the journey
        logger.debug("Telemetry span could not be stored.", exc_info=True)


def record_metric(
    name: str,
    value: float,
    dimensions: dict[str, Any] | None = None,
    *,
    trace_id: str | None = None,
) -> None:
    """Record one metric sample, correlated with the active trace."""
    if trace_id is None:
        span = _current_span.get()
        trace_id = span.trace_id if span else None
    try:
        telemetry_repository.insert_metric(
            name=name,
            value=float(value),
            dimensions=sanitize_attributes(dimensions),
            trace_id=trace_id,
        )
        telemetry_repository.prune_metrics(METRIC_RETENTION_LIMIT)
    except Exception:  # noqa: BLE001
        logger.debug("Telemetry metric could not be stored.", exc_info=True)


def sanitize_attributes(
    attributes: dict[str, Any] | None,
) -> dict[str, Any]:
    """Drop credential-like keys and bound value sizes before storage."""
    if not attributes:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in attributes.items():
        if SENSITIVE_ATTRIBUTE_PATTERN.search(str(key)):
            continue
        sanitized[str(key)] = _truncate_value(value)
    return sanitized


def _truncate_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else str(value)
    if len(text) > MAX_ATTRIBUTE_VALUE_LENGTH:
        return text[:MAX_ATTRIBUTE_VALUE_LENGTH] + "…[truncated]"
    return text


def scrub_message(message: str) -> str:
    """Redact credential-like fragments from a log message."""
    scrubbed = SENSITIVE_MESSAGE_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        message,
    )
    if len(scrubbed) > MAX_MESSAGE_LENGTH:
        return scrubbed[:MAX_MESSAGE_LENGTH] + "…[truncated]"
    return scrubbed


class TelemetryLogHandler(logging.Handler):
    """Store app log records with the trace context they were emitted in.

    Attached to the ``app`` logger namespace only, so third-party request
    logs (which can carry provider URLs with tokens) are never persisted.
    """

    def __init__(self, level: int = logging.INFO) -> None:
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord) -> None:
        # Logging inside emit must be avoided: a failure here would recurse.
        try:
            trace_id, span_id = current_trace()
            telemetry_repository.insert_log(
                trace_id=trace_id,
                span_id=span_id,
                level=record.levelname,
                logger_name=record.name,
                message=scrub_message(record.getMessage()),
            )
            telemetry_repository.prune_logs(LOG_RETENTION_LIMIT)
        except Exception:  # noqa: BLE001
            pass


def setup() -> None:
    """Create the telemetry tables and attach the correlated log handler."""
    telemetry_repository.init_db()
    app_logger = logging.getLogger("app")
    if not any(
        isinstance(handler, TelemetryLogHandler) for handler in app_logger.handlers
    ):
        app_logger.addHandler(TelemetryLogHandler())
