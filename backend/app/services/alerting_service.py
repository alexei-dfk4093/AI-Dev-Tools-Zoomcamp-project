from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.telemetry import API_REQUEST_COUNT
from app.repositories import telemetry_repository


def evaluate_user_impact_alert(
    *,
    db_path: Path | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Check whether a recent user-impacting error spike exceeds the configured threshold."""
    settings = settings or get_settings()
    rows = telemetry_repository.metric_rows(API_REQUEST_COUNT, limit=5000, db_path=db_path)

    total_requests = 0
    total_errors = 0
    for row in rows:
        value = int(float(row["value"]))
        total_requests += value
        status = row["dimensions"].get("status")
        if isinstance(status, int) and status >= 500:
            total_errors += value

    error_rate = (total_errors / total_requests) if total_requests else 0.0
    checked_at = datetime.now(timezone.utc).isoformat()

    if total_requests == 0:
        return {
            "active": False,
            "severity": "info",
            "message": "No recent request telemetry is available; no user-impact alert is active.",
            "error_rate": 0.0,
            "total_requests": 0,
            "total_errors": 0,
            "threshold": settings.alert_error_rate_threshold,
            "checked_at": checked_at,
        }

    if total_requests < settings.alert_min_requests:
        return {
            "active": False,
            "severity": "info",
            "message": (
                f"Recent request volume is too low for a reliable alert check "
                f"({total_requests} < {settings.alert_min_requests})."
            ),
            "error_rate": round(error_rate, 4),
            "total_requests": total_requests,
            "total_errors": total_errors,
            "threshold": settings.alert_error_rate_threshold,
            "checked_at": checked_at,
        }

    threshold = settings.alert_error_rate_threshold
    if error_rate >= threshold:
        severity = "critical" if error_rate >= min(0.5, threshold * 1.5) else "warning"
        return {
            "active": True,
            "severity": severity,
            "message": (
                f"User-impacting API errors exceeded the threshold: "
                f"{error_rate:.2%} error rate across {total_requests} requests "
                f"({total_errors} failed requests; threshold {threshold:.2%})."
            ),
            "error_rate": round(error_rate, 4),
            "total_requests": total_requests,
            "total_errors": total_errors,
            "threshold": threshold,
            "checked_at": checked_at,
        }

    return {
        "active": False,
        "severity": "info",
        "message": (
            f"API health is stable: {error_rate:.2%} error rate across {total_requests} "
            f"requests (threshold {threshold:.2%})."
        ),
        "error_rate": round(error_rate, 4),
        "total_requests": total_requests,
        "total_errors": total_errors,
        "threshold": threshold,
        "checked_at": checked_at,
    }
