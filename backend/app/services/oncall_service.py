from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.telemetry import API_REQUEST_COUNT
from app.repositories import telemetry_repository
from app.services.alerting_service import evaluate_user_impact_alert


def investigate_alert(
    *,
    db_path: Path | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return a safe on-call investigation summary for the current alert state."""
    settings = settings or get_settings()
    alert = evaluate_user_impact_alert(db_path=db_path, settings=settings)
    if not alert["active"]:
        return {
            "active": False,
            "status": "clear",
            "severity": alert["severity"],
            "summary": alert["message"],
            "human_approval_required": False,
            "recommended_actions": [],
            "verification_steps": [
                "Keep monitoring the error rate for the next sampling window.",
                "Confirm no new route regression appears in the telemetry dashboard.",
            ],
            "approval_required_for": [],
            "checked_at": alert["checked_at"],
        }

    rows = telemetry_repository.metric_rows(API_REQUEST_COUNT, limit=5000, db_path=db_path)
    route_errors: dict[str, int] = {}
    route_requests: dict[str, int] = {}

    for row in rows:
        dimensions = row["dimensions"]
        route = str(dimensions.get("route") or dimensions.get("http.route") or "unknown")
        value = int(float(row["value"]))
        route_requests[route] = route_requests.get(route, 0) + value
        status = dimensions.get("status")
        if isinstance(status, int) and status >= 500:
            route_errors[route] = route_errors.get(route, 0) + value

    top_route = None
    if route_requests:
        top_route = max(
            route_requests.items(),
            key=lambda item: (route_errors.get(item[0], 0), item[1]),
        )[0]

    route_error_rate = 0.0
    if route_requests.get(top_route, 0):
        route_error_rate = route_errors.get(top_route, 0) / route_requests[top_route]

    summary = (
        f"The system is above the alert threshold ({alert['error_rate']:.2%} vs. "
        f"{alert['threshold']:.2%}). "
    )
    if top_route and route_requests.get(top_route, 0):
        summary += (
            f"The highest failing route is {top_route} with {route_error_rate:.2%} "
            f"error rate across {route_requests[top_route]} requests."
        )
    else:
        summary += "The current failure pattern is concentrated in the latest request telemetry."

    return {
        "active": True,
        "status": "investigating",
        "severity": alert["severity"],
        "summary": summary,
        "human_approval_required": True,
        "recommended_actions": [
            "Inspect the highest-error route in the observability dashboard and confirm the failure pattern.",
            "Check the last deployment or configuration change that could have introduced the regression.",
            "Keep any rollback or traffic shift in a human-approved state until the fix is verified.",
        ],
        "verification_steps": [
            "Review the selected trace for the failing route to confirm the exact error signature.",
            "Verify the error rate falls below the threshold after the mitigation is applied.",
            "Run a fresh end-to-end check before closing the incident.",
        ],
        "approval_required_for": [
            "Human approval required for rollback or redeploy a service change",
            "Human approval required for traffic rerouting or rate-limit tuning",
            "Human approval required for configuration changes that affect the production path",
        ],
        "checked_at": alert["checked_at"],
    }


def approve_action(*, action: str, approved: bool) -> dict[str, Any]:
    """Record a human approval decision for a production-impacting action."""
    action_name = (action or "production-impacting action").strip() or "production-impacting action"
    if not approved:
        return {
            "approved": False,
            "action": action_name,
            "message": "Action blocked: human approval is required before production-impacting changes are executed.",
        }

    return {
        "approved": True,
        "action": action_name,
        "message": (
            f"Approved for {action_name}. The on-call agent can proceed to the next verification step "
            "only after confirming that the fix is effective and the alert is cleared."
        ),
    }
