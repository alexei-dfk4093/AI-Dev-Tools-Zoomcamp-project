import logging
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Path, Query

from app.schemas.observability import (
    AlertStatusResponse,
    JourneyListResponse,
    MetricsSummaryResponse,
    OnCallApprovalRequest,
    OnCallApprovalResponse,
    OnCallInvestigationResponse,
    TraceDetailResponse,
)
from app.services import alerting_service, oncall_service, telemetry_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/metrics", response_model=MetricsSummaryResponse)
async def get_metrics() -> MetricsSummaryResponse:
    return MetricsSummaryResponse(**telemetry_service.get_metrics_summary())


@router.get("/journeys", response_model=JourneyListResponse)
async def get_journeys(
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> JourneyListResponse:
    return JourneyListResponse(**telemetry_service.get_recent_journeys(limit=limit))


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
async def get_trace(
    trace_id: Annotated[str, Path(min_length=8, max_length=64)],
) -> TraceDetailResponse:
    detail = telemetry_service.get_trace_detail(trace_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="No telemetry was recorded for this trace id.",
        )
    return TraceDetailResponse(**detail)


@router.get("/alerts", response_model=AlertStatusResponse)
async def get_alert_status() -> AlertStatusResponse:
    return AlertStatusResponse(**alerting_service.evaluate_user_impact_alert())


@router.get("/oncall", response_model=OnCallInvestigationResponse)
async def get_oncall_investigation() -> OnCallInvestigationResponse:
    return OnCallInvestigationResponse(**oncall_service.investigate_alert())


@router.post("/oncall/approve", response_model=OnCallApprovalResponse)
async def approve_oncall_action(
    payload: Annotated[OnCallApprovalRequest, Body(...)],
) -> OnCallApprovalResponse:
    return OnCallApprovalResponse(**oncall_service.approve_action(
        action=payload.action,
        approved=payload.approved,
    ))
