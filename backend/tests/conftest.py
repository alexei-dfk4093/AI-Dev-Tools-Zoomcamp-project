import pytest

from app.services import news_service, openrouter


@pytest.fixture(autouse=True)
def reset_ai_request_budget():
    """Give every test a fresh AI request budget and no quota pause."""
    openrouter.reset_request_budget()
    news_service._summary_retry_at.clear()
    news_service._last_refresh_attempt_at = None
    news_service._enrichment_task = None
    news_service._regeneration_task = None
    yield
    openrouter.reset_request_budget()
    news_service._summary_retry_at.clear()
    news_service._last_refresh_attempt_at = None
    news_service._enrichment_task = None
    news_service._regeneration_task = None
