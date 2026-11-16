"""Response schemas for the observability API.

The telemetry UI reads correlated traces (span trees with their logs and
metrics) and aggregated metrics from these endpoints.
"""

from typing import Any

from pydantic import BaseModel


class TelemetrySpan(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    started_at: str
    duration_ms: float
    status: str
    attributes: dict[str, Any]


class TelemetryLogEntry(BaseModel):
    trace_id: str | None
    span_id: str | None
    level: str
    logger_name: str
    message: str
    recorded_at: str


class TelemetryMetricPoint(BaseModel):
    name: str
    value: float
    dimensions: dict[str, Any]
    trace_id: str | None
    recorded_at: str


class JourneySummary(BaseModel):
    trace_id: str
    name: str
    started_at: str
    duration_ms: float
    status: str
    span_count: int
    error_count: int
    log_count: int


class JourneyListResponse(BaseModel):
    journeys: list[JourneySummary]


class TraceDetailResponse(BaseModel):
    trace_id: str
    spans: list[TelemetrySpan]
    logs: list[TelemetryLogEntry]
    metrics: list[TelemetryMetricPoint]


class RouteMetrics(BaseModel):
    method: str
    route: str
    request_count: int
    error_count: int
    avg_duration_ms: float
    p95_duration_ms: float


class AiRequestMetrics(BaseModel):
    model: str
    outcome: str
    count: int


class ProviderFetchMetrics(BaseModel):
    provider: str
    outcome: str
    count: int


class MetricsSummaryResponse(BaseModel):
    generated_at: str
    total_requests: int
    total_errors: int
    routes: list[RouteMetrics]
    ai_requests: list[AiRequestMetrics]
    ai_quota_pauses: int
    provider_fetches: list[ProviderFetchMetrics]
    refreshes: int
    articles_saved: int


class AlertStatusResponse(BaseModel):
    active: bool
    severity: str
    message: str
    error_rate: float
    total_requests: int
    total_errors: int
    threshold: float
    checked_at: str


class OnCallInvestigationResponse(BaseModel):
    active: bool
    status: str
    severity: str
    summary: str
    human_approval_required: bool
    recommended_actions: list[str]
    verification_steps: list[str]
    approval_required_for: list[str]
    checked_at: str


class OnCallApprovalRequest(BaseModel):
    action: str
    approved: bool


class OnCallApprovalResponse(BaseModel):
    approved: bool
    action: str
    message: str
