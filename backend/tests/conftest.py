import os

import pytest

from app.services import news_service, openrouter

# The app refuses to start without NEWS_API_KEY (startup configuration
# validation). Tests must not depend on a developer's real .env file, so
# the session provides deterministic keys when the environment has none.
TEST_ENV_DEFAULTS = {
    "NEWS_API_KEY": "test-news-key",
    "OPENROUTER_API_KEY": "test-openrouter-key",
}


@pytest.fixture(autouse=True)
def reset_test_environment():
    """Deterministic startup config and a fresh AI request budget."""
    added: list[str] = []
    for key, value in TEST_ENV_DEFAULTS.items():
        if key not in os.environ:
            os.environ[key] = value
            added.append(key)
    openrouter.reset_request_budget()
    news_service._summary_retry_at.clear()
    news_service._last_refresh_attempt_at = None
    news_service._enrichment_task = None
    news_service._regeneration_task = None
    yield
    for key in added:
        os.environ.pop(key, None)
    openrouter.reset_request_budget()
    news_service._summary_retry_at.clear()
    news_service._last_refresh_attempt_at = None
    news_service._enrichment_task = None
    news_service._regeneration_task = None
