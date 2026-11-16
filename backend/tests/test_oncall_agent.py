from app.core.config import Settings
from app.core.telemetry import API_REQUEST_COUNT
from app.repositories import telemetry_repository
from app.services.oncall_service import approve_action, investigate_alert


def _settings(*, threshold: float = 0.2, min_requests: int = 10) -> Settings:
    return Settings(
        news_api_key="test-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="openrouter/free",
        alert_error_rate_threshold=threshold,
        alert_min_requests=min_requests,
    )


def test_oncall_investigation_is_clear_when_alert_is_not_active(tmp_path) -> None:
    db_path = tmp_path / "telemetry_oncall_clear.db"
    telemetry_repository.init_db(db_path)
    telemetry_repository.insert_metric(
        name=API_REQUEST_COUNT,
        value=12,
        dimensions={"method": "GET", "route": "/api/v1/news", "status": 200},
        trace_id="trace-ok",
        db_path=db_path,
    )

    result = investigate_alert(db_path=db_path, settings=_settings(min_requests=10))

    assert result["active"] is False
    assert result["status"] == "clear"
    assert result["human_approval_required"] is False
    assert "stable" in result["summary"].lower()


def test_oncall_investigation_recommends_human_approval_when_alert_is_active(tmp_path) -> None:
    db_path = tmp_path / "telemetry_oncall_alert.db"
    telemetry_repository.init_db(db_path)

    telemetry_repository.insert_metric(
        name=API_REQUEST_COUNT,
        value=15,
        dimensions={"method": "GET", "route": "/api/v1/news", "status": 200},
        trace_id="trace-ok",
        db_path=db_path,
    )
    telemetry_repository.insert_metric(
        name=API_REQUEST_COUNT,
        value=11,
        dimensions={"method": "GET", "route": "/api/v1/news", "status": 500},
        trace_id="trace-error",
        db_path=db_path,
    )

    result = investigate_alert(db_path=db_path, settings=_settings(min_requests=10))

    assert result["active"] is True
    assert result["status"] == "investigating"
    assert result["human_approval_required"] is True
    assert any("rollback" in action.lower() for action in result["recommended_actions"])
    assert "approval" in " ".join(result["approval_required_for"]).lower()


def test_oncall_approval_requires_explicit_human_decision() -> None:
    rejected = approve_action(action="rollback deployment", approved=False)
    approved = approve_action(action="reroute traffic", approved=True)

    assert rejected["approved"] is False
    assert rejected["message"].startswith("Action blocked")
    assert approved["approved"] is True
    assert "Approved for reroute traffic" in approved["message"]
