import json

import httpx
import pytest

from app.core.config import Settings
from app.services import openrouter


def _settings(**overrides) -> Settings:
    values = {
        "news_api_key": "test-key",
        "openrouter_api_key": "test-openrouter-key",
        "openrouter_model": "test-model",
    }
    values.update(overrides)
    return Settings(**values)


def test_extract_json_payload_handles_fences_and_prefixes() -> None:
    assert openrouter.extract_json_payload('```json\n{"a": 1}\n```') == {"a": 1}
    assert openrouter.extract_json_payload('json\n{"a": {"b": 2}}') == {"a": {"b": 2}}
    assert openrouter.extract_json_payload('Here you go: {"a": 3} done') == {"a": 3}


def test_extract_json_payload_rejects_text_without_an_object() -> None:
    with pytest.raises(ValueError):
        openrouter.extract_json_payload("no json here")


@pytest.mark.anyio
async def test_daily_budget_stops_further_ai_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    class MockResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}],
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

        async def post(self, url: str, **kwargs) -> MockResponse:
            nonlocal calls
            calls += 1
            return MockResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = _settings(openrouter_daily_call_budget=2)

    await openrouter.request_assistant_text(
        settings,
        model="test-model",
        instructions="Answer briefly.",
        input_text="hello",
    )
    await openrouter.request_assistant_text(
        settings,
        model="test-model",
        instructions="Answer briefly.",
        input_text="hello again",
    )

    with pytest.raises(openrouter.OpenRouterError, match="daily AI request budget"):
        await openrouter.request_assistant_text(
            settings,
            model="test-model",
            instructions="Answer briefly.",
            input_text="one too many",
        )

    assert calls == 2


@pytest.mark.anyio
async def test_prompt_limit_error_retries_with_a_smaller_fetch_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key with a small prompt limit must not break the request."""
    observed: list[dict] = []

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, *, json: dict, headers: dict):
            observed.append(json)
            if len(observed) == 1:
                return httpx.Response(
                    402,
                    request=httpx.Request("POST", url),
                    json={
                        "error": {
                            "message": "Prompt tokens limit exceeded: 8671 > 5783."
                        }
                    },
                )
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "fetched"}],
                        }
                    ]
                },
            )

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = _settings()

    response = await openrouter.request_assistant_text(
        settings,
        model="test-model",
        instructions="Read the article.",
        input_text="Article: https://example.com/story",
        tools=openrouter.web_tools(fetch_domains=["example.com"], allow_search=False),
    )

    assert response.text == "fetched"
    first_budget = observed[0]["tools"][0]["parameters"]["max_content_tokens"]
    second_budget = observed[1]["tools"][0]["parameters"]["max_content_tokens"]
    assert first_budget > second_budget
    assert second_budget in openrouter.FETCH_TOKEN_BUDGETS


@pytest.mark.anyio
async def test_quota_failure_pauses_further_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, **kwargs) -> httpx.Response:
            return httpx.Response(
                402,
                request=httpx.Request("POST", url),
                json={
                    "error": {
                        "message": "The free model daily request limit is exceeded."
                    }
                },
            )

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = _settings()

    with pytest.raises(openrouter.OpenRouterError):
        await openrouter.request_assistant_text(
            settings,
            model="test-model",
            instructions="Answer briefly.",
            input_text="hello",
        )

    with pytest.raises(openrouter.OpenRouterError, match="allowance is temporarily"):
        await openrouter.request_assistant_text(
            settings,
            model="test-model",
            instructions="Answer briefly.",
            input_text="hello again",
        )


@pytest.mark.anyio
async def test_paid_model_credit_error_does_not_pause_free_model_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, **kwargs) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    402,
                    request=httpx.Request("POST", url),
                    json={"error": {"message": "Insufficient credits"}},
                )
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "free reply"}],
                        }
                    ]
                },
            )

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = _settings()

    with pytest.raises(openrouter.OpenRouterError, match="requires credits"):
        await openrouter.request_assistant_text(
            settings,
            model="z-ai/glm-5.3",
            instructions="Answer briefly.",
            input_text="hello",
        )

    response = await openrouter.request_assistant_text(
        settings,
        model="openrouter/free",
        instructions="Answer briefly.",
        input_text="hello again",
    )

    assert response.text == "free reply"
    assert calls == 2


def test_web_tools_build_fetch_and_search_definitions() -> None:
    tools = openrouter.web_tools(fetch_domains=["example.com"], allow_search=True)

    assert tools[0]["type"] == "openrouter:web_fetch"
    assert tools[0]["parameters"]["allowed_domains"] == ["example.com"]
    assert tools[1]["type"] == "openrouter:web_search"
    # Search is not limited to the publisher so it can corroborate the story.
    assert "allowed_domains" not in tools[1]["parameters"]

    search_only = openrouter.web_tools(fetch_domains=None, allow_search=True)
    assert [tool["type"] for tool in search_only] == ["openrouter:web_search"]


@pytest.mark.anyio
async def test_chat_completion_counts_toward_the_daily_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch summarization shares the daily request budget with other AI."""
    calls = 0

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, **kwargs) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"choices": [{"message": {"content": '{"summaries": []}'}}]},
            )

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = _settings(openrouter_daily_call_budget=2)

    await openrouter.request_chat_completion(
        settings,
        model="test-model",
        messages=[{"role": "user", "content": "summarize"}],
    )
    await openrouter.request_chat_completion(
        settings,
        model="test-model",
        messages=[{"role": "user", "content": "summarize"}],
    )

    with pytest.raises(openrouter.OpenRouterError, match="daily AI request budget"):
        await openrouter.request_chat_completion(
            settings,
            model="test-model",
            messages=[{"role": "user", "content": "one too many"}],
        )

    assert calls == 2


@pytest.mark.anyio
async def test_chat_completion_rate_limit_pauses_further_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 from the provider pauses AI calls instead of inviting retries."""
    calls = 0

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, **kwargs) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                429,
                request=httpx.Request("POST", url),
                json={"error": {"message": "Rate limit exceeded"}},
            )

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = _settings()

    with pytest.raises(openrouter.OpenRouterError, match="rate-limiting"):
        await openrouter.request_chat_completion(
            settings,
            model="test-model",
            messages=[{"role": "user", "content": "summarize"}],
        )
    assert calls == 1

    with pytest.raises(openrouter.OpenRouterError, match="allowance is temporarily"):
        await openrouter.request_chat_completion(
            settings,
            model="test-model",
            messages=[{"role": "user", "content": "summarize"}],
        )
    assert calls == 1  # the paused call never reaches the provider


@pytest.mark.anyio
async def test_summarize_batch_goes_through_the_shared_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Summary batches may not bypass the budget with their own HTTP calls."""
    from app.schemas.news import NewsArticle
    from app.services import news_service

    calls = 0

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, **kwargs) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                429,
                request=httpx.Request("POST", url),
                json={"error": {"message": "Rate limit exceeded"}},
            )

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = _settings()
    article = NewsArticle(
        id="batch-story",
        source="Example News",
        published_at="2026-11-10T10:00:00Z",
        url="https://example.com/batch-story",
        title="Central bank holds interest rates",
        summary="Publisher summary.",
        summary_source="publisher",
        importance="important",
    )

    summaries = await news_service.summarize_articles(settings, [article])
    assert summaries == {}

    # The single 429 paused AI calls, so a later batch makes no HTTP request.
    second = await news_service.summarize_articles(settings, [article])
    assert second == {}
    assert calls == 1
