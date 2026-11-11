import pytest

from app.services import openrouter


@pytest.fixture(autouse=True)
def reset_ai_request_budget():
    """Give every test a fresh AI request budget and no quota pause."""
    openrouter.reset_request_budget()
    yield
    openrouter.reset_request_budget()
