"""Aggregation for the telemetry UI.

Turns the raw span, log and metric rows kept by ``telemetry_repository``
into the summaries the observability API serves: one metrics overview and
one correlated trace view per journey.
"""

import math
from datetime import datetime, timezone
from typing import Any

from app.core.telemetry import (
    AI_QUOTA_PAUSE_COUNT,
    AI_REQUEST_COUNT,
    API_REQUEST_COUNT,
    API_REQUEST_DURATION_MS,
    PROVIDER_FETCH_COUNT,
    REFRESH_ARTICLES_SAVED,
)
from app.repositories import telemetry_repository


def get_metrics_summary() -> dict[str, Any]:
    """Aggregate the stored metric samples into one overview."""
    request_rows = telemetry_repository.metric_rows(API_REQUEST_COUNT)
    duration_rows = telemetry_repository.metric_rows(API_REQUEST_DURATION_MS)
    ai_rows = telemetry_repository.metric_rows(AI_REQUEST_COUNT)
    quota_rows = telemetry_repository.metric_rows(AI_QUOTA_PAUSE_COUNT)
    fetch_rows = telemetry_repository.metric_rows(PROVIDER_FETCH_COUNT)
    saved_rows = telemetry_repository.metric_rows(REFRESH_ARTICLES_SAVED)

    routes = _route_metrics(request_rows, duration_rows)
    ai_requests = _grouped_counts(ai_rows, ("model", "outcome"), ("model", "outcome"))
    provider_fetches = _grouped_counts(
        fetch_rows,
        ("provider", "outcome"),
        ("provider", "outcome"),
    )

    total_requests = sum(route.request_count for route in routes)
    total_errors = sum(route.error_count for route in routes)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": total_requests,
        "total_errors": total_errors,
        "routes": [route.model_dump() for route in routes],
        "ai_requests": [
            {"model": key["model"], "outcome": key["outcome"], "count": count}
            for key, count in ai_requests
        ],
        "ai_quota_pauses": int(sum(row["value"] for row in quota_rows)),
        "provider_fetches": [
            {"provider": key["provider"], "outcome": key["outcome"], "count": count}
            for key, count in provider_fetches
        ],
        "refreshes": len(saved_rows),
        "articles_saved": int(sum(row["value"] for row in saved_rows)),
    }


def _route_metrics(
    request_rows: list[dict[str, Any]],
    duration_rows: list[dict[str, Any]],
) -> list[Any]:
    """Per-route request counts, errors and duration statistics."""
    from app.schemas.observability import RouteMetrics

    counts: dict[tuple[str, str], int] = {}
    errors: dict[tuple[str, str], int] = {}
    for row in request_rows:
        method = str(row["dimensions"].get("method", "?"))
        route = str(row["dimensions"].get("route", "?"))
        key = (method, route)
        counts[key] = counts.get(key, 0) + int(row["value"])
        status = row["dimensions"].get("status")
        if isinstance(status, int) and status >= 500:
            errors[key] = errors.get(key, 0) + int(row["value"])

    durations: dict[tuple[str, str], list[float]] = {}
    for row in duration_rows:
        method = str(row["dimensions"].get("method", "?"))
        route = str(row["dimensions"].get("route", "?"))
        durations.setdefault((method, route), []).append(float(row["value"]))

    metrics: list[RouteMetrics] = []
    for key in sorted(counts, key=lambda item: (-counts[item], item[1])):
        samples = sorted(durations.get(key, []))
        metrics.append(
            RouteMetrics(
                method=key[0],
                route=key[1],
                request_count=counts[key],
                error_count=errors.get(key, 0),
                avg_duration_ms=_mean(samples),
                p95_duration_ms=_percentile(samples, 95),
            )
        )
    return metrics


def _grouped_counts(
    rows: list[dict[str, Any]],
    dimension_keys: tuple[str, ...],
    output_keys: tuple[str, ...],
) -> list[tuple[dict[str, str], int]]:
    """Sum counter samples grouped by the given dimension keys."""
    totals: dict[tuple[str, ...], int] = {}
    for row in rows:
        dimensions = row["dimensions"]
        key = tuple(str(dimensions.get(name, "?")) for name in dimension_keys)
        totals[key] = totals.get(key, 0) + int(row["value"])

    grouped: list[tuple[dict[str, str], int]] = []
    for key, count in sorted(totals.items(), key=lambda item: (-item[1], item[0])):
        grouped.append(
            (
                dict(zip(output_keys, key)),
                count,
            )
        )
    return grouped


def _mean(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return round(sum(samples) / len(samples), 1)


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    index = min(
        len(samples) - 1,
        math.ceil(len(samples) * percentile / 100.0) - 1,
    )
    return round(samples[max(index, 0)], 1)


def get_recent_journeys(limit: int = 30) -> dict[str, Any]:
    """Summarize the newest root spans: one row per journey."""
    from app.schemas.observability import JourneyListResponse, JourneySummary

    roots = telemetry_repository.list_root_spans(limit=limit)
    trace_ids = [root["trace_id"] for root in roots]
    counts = telemetry_repository.count_trace_spans(trace_ids)

    journeys = []
    for root in roots:
        summary = counts.get(root["trace_id"], {})
        journeys.append(
            JourneySummary(
                trace_id=root["trace_id"],
                name=root["name"],
                started_at=root["started_at"],
                duration_ms=root["duration_ms"],
                status=root["status"],
                span_count=summary.get("span_count", 1),
                error_count=summary.get("error_count", 0),
                log_count=summary.get("log_count", 0),
            )
        )
    return JourneyListResponse(journeys=journeys).model_dump()


def get_trace_detail(trace_id: str) -> dict[str, Any] | None:
    """Return the full correlated view of one journey."""
    from app.schemas.observability import (
        TelemetryLogEntry,
        TelemetryMetricPoint,
        TelemetrySpan,
        TraceDetailResponse,
    )

    spans = telemetry_repository.get_spans_for_trace(trace_id)
    if not spans:
        return None

    logs = telemetry_repository.get_logs_for_trace(trace_id)
    metrics = telemetry_repository.get_metrics_for_trace(trace_id)

    return TraceDetailResponse(
        trace_id=trace_id,
        spans=[TelemetrySpan(**span) for span in spans],
        logs=[TelemetryLogEntry(**entry) for entry in logs],
        metrics=[TelemetryMetricPoint(**metric) for metric in metrics],
    ).model_dump(mode="json")
