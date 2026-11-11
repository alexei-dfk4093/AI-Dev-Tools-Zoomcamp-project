import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import discussions as discussions_route
from app.core.config import Settings
from app.main import app
from app.schemas.discussion import (
    DiscussionArticle,
    DiscussionRequest,
)
from app.services import discussion_service, openrouter


def _request_body() -> dict:
    return {
        "article": {
            "id": "article-123",
            "title": "Central bank holds interest rates",
            "source": "Example News",
            "published_at": "2026-11-10T10:00:00Z",
            "url": "https://example.com/economy/story",
            "summary": "The bank kept its policy rate unchanged.",
        },
        "message": "What are the possible implications?",
        "history": [],
    }


def test_discussion_endpoint_routes_non_social_questions_to_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "discussion-test-key")
    calls = 0

    async def fake_generate_reply(settings, request):
        nonlocal calls
        calls += 1
        assert settings.openrouter_api_key == "openrouter-test-key"
        assert request.article.title == "Central bank holds interest rates"
        assert request.message == "What are the possible implications?"
        return "Potential upside exists, but evidence is limited and downside risks remain."

    monkeypatch.setattr(discussions_route, "generate_reply", fake_generate_reply)
    app.dependency_overrides[discussions_route.get_settings] = lambda: Settings(
        news_api_key="discussion-test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/discussions", json=_request_body())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Potential upside exists, but evidence is limited and downside risks remain."
    }
    assert calls == 1


def test_discussion_endpoint_requires_openrouter_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "discussion-test-key")
    app.dependency_overrides[discussions_route.get_settings] = lambda: Settings(
        news_api_key="discussion-test-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/discussions", json=_request_body())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


def test_discussion_models_endpoint_returns_configured_choices() -> None:
    app.dependency_overrides[discussions_route.get_settings] = lambda: Settings(
        news_api_key="discussion-test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="openrouter/free",
        openrouter_models=(
            "openrouter/free",
            "google/gemma-4-31b-it:free",
            "z-ai/glm-5.3",
        ),
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/discussions/models")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {"id": "openrouter/free", "label": "OpenRouter Free Models"},
            {
                "id": "google/gemma-4-31b-it:free",
                "label": "Gemma 4 31B (free)",
            },
        ],
        "default_model": "openrouter/free",
    }


def test_discussion_endpoint_rejects_models_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(settings, request):
        raise AssertionError("Unapproved model must not be sent to the provider.")

    monkeypatch.setattr(discussions_route, "generate_reply", fail_if_called)
    app.dependency_overrides[discussions_route.get_settings] = lambda: Settings(
        news_api_key="discussion-test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="deepseek/deepseek-chat",
        openrouter_models=("deepseek/deepseek-chat",),
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/discussions",
                json={**_request_body(), "model": "unapproved/model"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "Choose a free model from the discussion model list."


def test_discussion_endpoint_rejects_paid_model_even_if_allowlisted() -> None:
    app.dependency_overrides[discussions_route.get_settings] = lambda: Settings(
        news_api_key="discussion-test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="deepseek/deepseek-chat",
        openrouter_models=("deepseek/deepseek-chat",),
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/discussions",
                json={**_request_body(), "model": "deepseek/deepseek-chat"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "Choose a free model from the discussion model list."


def test_discussion_endpoint_returns_actionable_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_with_provider_error(settings, request):
        raise discussion_service.DiscussionProviderError(
            "OpenRouter could not serve moonshotai/kimi-k3."
        )

    monkeypatch.setattr(discussions_route, "generate_reply", fail_with_provider_error)
    app.dependency_overrides[discussions_route.get_settings] = lambda: Settings(
        news_api_key="discussion-test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="deepseek/deepseek-chat",
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/discussions",
                json={**_request_body(), "model": "google/gemma-4-31b-it:free"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "OpenRouter could not serve moonshotai/kimi-k3."
    )


def test_discussion_endpoint_answers_introduction_without_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "discussion-test-key")
    app.dependency_overrides[discussions_route.get_settings] = lambda: Settings(
        news_api_key="discussion-test-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/discussions",
                json={
                    **_request_body(),
                    "message": "iam mina",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Nice to meet you, Mina! What would you like to discuss?"
    }


def test_discussion_endpoint_validates_message_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "discussion-test-key")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/discussions",
            json={**_request_body(), "message": "x" * 2001},
        )

    assert response.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("message", "expected_reply"),
    [
        ("hello", "Hi! What would you like to know about this story?"),
        ("iam mina", "Nice to meet you, Mina! What would you like to discuss?"),
        ("I'm Mina", "Nice to meet you, Mina! What would you like to discuss?"),
    ],
)
async def test_social_messages_do_not_call_the_model(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    expected_reply: str,
) -> None:
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("Social messages should not call the model.")

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", fail_if_called)
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )
    request = DiscussionRequest(
        article=DiscussionArticle(
            id="article-123",
            title="Central bank holds interest rates",
            url="https://example.com/economy/story",
        ),
        message=message,
    )

    assert await discussion_service.generate_reply(settings, request) == expected_reply


@pytest.mark.anyio
async def test_generate_reply_uses_the_configured_model_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    observed_request: dict = {}

    class MockResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "One balanced assessment.",
                            }
                        ],
                    }
                ]
            }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, *, json: dict, headers: dict) -> MockResponse:
            nonlocal calls
            calls += 1
            observed_request.update(json)
            return MockResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="test-model",
    )
    request = DiscussionRequest(
        article=DiscussionArticle(
            id="article-123",
            title="Central bank holds interest rates",
            url="https://example.com/economy/story",
        ),
        message="What changed since the prior answer?",
        model="moonshotai/kimi-k3",
        history=[
            {"speaker": "user", "content": "What could happen?"},
            {"speaker": "assistant", "content": "The earlier assessment."},
        ],
    )

    reply = await discussion_service.generate_reply(settings, request)

    assert reply == "One balanced assessment."
    assert calls == 1
    assert observed_request["model"] == "moonshotai/kimi-k3"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected_detail"),
    [
        (404, "could not serve moonshotai/kimi-k3"),
        (402, "requires credits to use moonshotai/kimi-k3"),
        (429, "rate-limiting moonshotai/kimi-k3"),
    ],
)
async def test_generate_reply_reports_model_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_detail: str,
) -> None:
    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(
                status_code,
                request=httpx.Request("POST", url),
                json={"error": {"message": "Provider error detail"}},
            )

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="deepseek/deepseek-chat",
    )
    request = DiscussionRequest(
        article=DiscussionArticle(
            id="article-123",
            title="Central bank holds interest rates",
            url="https://example.com/economy/story",
        ),
        message="What are the possible implications?",
        model="moonshotai/kimi-k3",
    )

    with pytest.raises(
        discussion_service.DiscussionProviderError,
        match=expected_detail,
    ):
        await discussion_service.generate_reply(settings, request)


@pytest.mark.anyio
async def test_discussion_prompt_answers_the_latest_question_without_forcing_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_request: dict = {}

    class MockResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "A grounded perspective.",
                            }
                        ],
                    }
                ]
            }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, *, json: dict, headers: dict) -> MockResponse:
            assert url == openrouter.OPENROUTER_RESPONSES_API_URL
            assert headers["Authorization"] == "Bearer test-openrouter-key"
            observed_request.update(json)
            return MockResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="test-model",
    )
    request = DiscussionRequest(
        article=DiscussionArticle(
            id="article-123",
            title="Central bank holds interest rates",
            url="https://example.com/economy/story",
            article_content="The central bank held its policy rate steady.",
        ),
        message="What changed since the prior answer?",
        history=[
            {"speaker": "user", "content": "What could happen?"},
            {"speaker": "assistant", "content": "The earlier assessment."},
        ],
    )

    reply = await discussion_service.generate_reply(settings, request)

    assert reply == "A grounded perspective."
    assert observed_request["model"] == "test-model"
    system_prompt = observed_request["instructions"]
    assert "use the web-fetch tool" in system_prompt
    assert "Do not claim to have read the full article" in system_prompt
    assert "use web search to check the story" in system_prompt
    assert "Never present a fact found online as if the article reported it" in system_prompt
    assert "Name the source when you use a web finding" in system_prompt
    assert "For a greeting, thanks, or other small talk" in system_prompt
    assert "do not analyze the article" in system_prompt
    assert "Do not use a fixed template" in system_prompt
    assert "When relevant to the question" in system_prompt
    assert "A headline or short summary alone does not establish unstated facts" in system_prompt
    assert "Do not add generic company details" in system_prompt
    assert "answer the new question" in system_prompt
    article_context = observed_request["input"][0]["content"][0]["text"]
    assert "Central bank holds interest rates" in article_context
    assert "https://example.com/economy/story" in article_context
    assert "held its policy rate steady" in article_context
    assert observed_request["tools"] == [
        {
            "type": "openrouter:web_fetch",
            "parameters": {
                "engine": "openrouter",
                "max_uses": 1,
                "max_content_tokens": 12000,
                "allowed_domains": ["example.com"],
            },
        },
        {
            "type": "openrouter:web_search",
            "parameters": {
                "engine": "exa",
                "max_uses": 2,
                "max_results": 3,
                "max_total_results": 3,
                "search_context_size": "medium",
            },
        },
    ]
    assert observed_request["input"][-2] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "input_text", "text": "The earlier assessment."}],
    }
    assert observed_request["input"][-1] == {
        "type": "message",
        "role": "user",
        "content": [
            {"type": "input_text", "text": "What changed since the prior answer?"}
        ],
    }
    assert observed_request["max_output_tokens"] == 700
    assert observed_request["tool_choice"] == "auto"


@pytest.mark.parametrize(
    "article_url",
    [
        "http://example.com/story",
        "https://localhost/story",
        "https://127.0.0.1/story",
        "https://service.internal/story",
    ],
)
def test_article_web_tools_reject_nonpublic_or_insecure_urls(
    article_url: str,
) -> None:
    assert discussion_service._article_web_tools(article_url) == []
