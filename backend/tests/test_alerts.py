from app.core.config import Settings
from app.core.telemetry import API_REQUEST_COUNT
from app.repositories import telemetry_repository
from app.services.alerting_service import evaluate_user_impact_alert


def _settings(*, threshold: float = 0.2, min_requests: int = 10) -> Settings:
    return Settings(
        news_api_key="test-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="openrouter/free",
        alert_error_rate_threshold=threshold,
        alert_min_requests=min_requests,
    )


def test_alert_stays_clear_when_error_rate_is_below_threshold(tmp_path) -> None:
    db_path = tmp_path / "telemetry_alerts.db"
    telemetry_repository.init_db(db_path)

    telemetry_repository.insert_metric(
        name=API_REQUEST_COUNT,
        value=25,
        dimensions={"method": "GET", "route": "/api/v1/news", "status": 200},
        trace_id="trace-ok",
        db_path=db_path,
    )
    telemetry_repository.insert_metric(
        name=API_REQUEST_COUNT,
        value=5,
        dimensions={"method": "GET", "route": "/api/v1/news", "status": 500},
        trace_id="trace-error",
        db_path=db_path,
    )

    result = evaluate_user_impact_alert(db_path=db_path, settings=_settings())

    assert result["active"] is False
    assert result["total_requests"] == 30
    assert result["total_errors"] == 5
    assert result["error_rate"] == 0.1667


def test_alert_triggers_when_error_rate_exceeds_threshold(tmp_path) -> None:
    db_path = tmp_path / "telemetry_alerts_trigger.db"
    telemetry_repository.init_db(db_path)

    telemetry_repository.insert_metric(
        name=API_REQUEST_COUNT,
        value=12,
        dimensions={"method": "GET", "route": "/api/v1/news", "status": 200},
        trace_id="trace-ok",
        db_path=db_path,
    )
    telemetry_repository.insert_metric(
        name=API_REQUEST_COUNT,
        value=8,
        dimensions={"method": "GET", "route": "/api/v1/news", "status": 500},
        trace_id="trace-error",
        db_path=db_path,
    )

    result = evaluate_user_impact_alert(db_path=db_path, settings=_settings())

    assert result["active"] is True
    assert result["severity"] in {"warning", "critical"}
    assert result["error_rate"] == 0.4
    assert result["threshold"] == 0.2
