import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import news as news_route
from app.core.config import Settings
from app.main import app
from app.schemas.news import (
    AffectedAsset,
    ArticleImpact,
    ArticleInsightsResponse,
    NewsArticle,
)
from app.repositories import news_repository
from app.services import news_service
from app.services.article_insights_service import (
    ARTICLE_INSIGHTS_PROMPT_VERSION,
    ArticleInsightsProviderError,
    build_article_insights,
)
from app.services.news_service import (
    AI_SUMMARY_PROMPT_VERSION,
    NewsProviderError,
    classify_importance,
    fetch_articles,
    get_or_fetch_articles,
    is_economics_article,
    normalize_article,
    normalize_marketaux_article,
    refresh_articles,
    summarize_articles,
)
from app.services import article_insights_service, openrouter


def test_normalize_article_uses_publisher_description() -> None:
    normalized = normalize_article(
        {
            "source": {"name": "Example News"},
            "publishedAt": "2026-11-10T10:00:00Z",
            "url": "https://example.com/markets/story",
            "title": "Markets respond to new inflation data",
            "description": "Investors reassessed rate expectations after the report.",
        }
    )

    assert normalized is not None
    assert normalized.source == "Example News"
    assert normalized.summary == "Investors reassessed rate expectations after the report."
    assert normalized.summary_source == "publisher"
    assert normalized.importance == "important"


def test_normalize_article_skips_removed_and_invalid_urls() -> None:
    removed = normalize_article(
        {"title": "[Removed]", "url": "https://example.com/removed"}
    )
    invalid_url = normalize_article(
        {"title": "A headline", "url": "javascript:alert(1)"}
    )

    assert removed is None
    assert invalid_url is None


def test_normalize_article_preserves_complete_content_and_rejects_truncated_content() -> None:
    complete = normalize_article(
        {
            "title": "A financial headline",
            "url": "https://example.com/full-story",
            "description": "A publisher description.",
            "content": "The complete provider-supplied article text.",
        }
    )
    truncated = normalize_article(
        {
            "title": "Another financial headline",
            "url": "https://example.com/truncated-story",
            "content": "A partial story. [+1200 chars]",
        }
    )

    assert complete is not None
    assert complete.article_content == "The complete provider-supplied article text."
    assert truncated is not None
    assert truncated.article_content is None


def test_database_adds_article_content_column_to_existing_cache(tmp_path) -> None:
    db_file = tmp_path / "legacy-news-cache.db"
    with sqlite3.connect(db_file) as connection:
        connection.execute(
            """
            CREATE TABLE articles (
                id TEXT PRIMARY KEY,
                source TEXT,
                published_at TEXT,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                summary_source TEXT NOT NULL,
                importance TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    news_repository.init_db(db_file)

    with sqlite3.connect(db_file) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(articles)")
        }
    assert "article_content" in columns
    assert "summary_prompt_version" in columns


@pytest.mark.anyio
async def test_summarize_articles_requests_expanded_source_grounded_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = (
        "The central bank held its policy rate unchanged. Officials said recent "
        "inflation data remains above the target. The decision leaves borrowing "
        "costs at their current level. The source does not report a timeline for "
        "a future rate change."
    )
    observed_request: dict = {}

    class MockResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summaries": [
                                        {"id": "article-1", "summary": summary}
                                    ]
                                }
                            )
                        }
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
            observed_request.update(json)
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    article = NewsArticle(
        id="article-1",
        source="Example News",
        published_at=None,
        url="https://example.com/story",
        title="Central bank holds policy rate",
        summary="The bank held its policy rate unchanged.",
        article_content="Full provider-supplied article text.",
        summary_source="publisher",
        importance="important",
    )
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="test-model",
    )

    summaries = await summarize_articles(settings, [article])

    assert summaries == {"article-1": summary}
    assert observed_request["max_tokens"] == 4000
    assert "3-5 sentences" in observed_request["messages"][0]["content"]
    assert "Do not repeat or lightly rephrase the headline" in observed_request["messages"][0]["content"]
    assert "relevant figures" in observed_request["messages"][0]["content"]
    assert "Full provider-supplied article text." in observed_request["messages"][1]["content"]
    assert "summary_prompt_version" not in article.model_dump()


@pytest.mark.anyio
async def test_stale_ai_summaries_are_regenerated_with_the_current_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_file = tmp_path / "stale-summary.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    news_repository.save_articles(
        [
            NewsArticle(
                id="stale-ai-story",
                source="Example News",
                published_at="2026-11-10T10:00:00Z",
                url="https://example.com/stale-ai-story",
                title="Central bank holds interest rates",
                summary="Central bank holds interest rates.",
                summary_source="ai",
                summary_prompt_version=AI_SUMMARY_PROMPT_VERSION - 1,
                importance="important",
            )
        ]
    )
    refreshed_summary = (
        "The central bank kept its benchmark rate unchanged after reviewing "
        "the latest inflation figures. Officials said price growth remains "
        "above their target, while the statement did not give a date for "
        "future rate cuts."
    )
    summarized_ids: list[str] = []

    async def fake_summarize_articles(settings, articles):
        summarized_ids.extend(article.id for article in articles)
        return {"stale-ai-story": refreshed_summary}

    monkeypatch.setattr(
        "app.services.news_service.summarize_articles",
        fake_summarize_articles,
    )
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="test-model",
    )

    articles = await get_or_fetch_articles(settings, limit=1)
    # The regeneration runs in the background; the first response returns the
    # stored summary without waiting for it.
    assert summarized_ids == []
    await news_service.drain_background_tasks()
    cached = news_repository.get_article("stale-ai-story")
    articles = await get_or_fetch_articles(settings, limit=1)

    assert summarized_ids == ["stale-ai-story"]
    assert articles[0].summary == refreshed_summary
    assert cached is not None
    assert cached.summary_prompt_version == AI_SUMMARY_PROMPT_VERSION


def test_importance_classifier_marks_macro_policy_headline_important() -> None:
    assert classify_importance(
        "Central bank holds interest rates as inflation slows"
    ) == "important"


def test_importance_classifier_marks_general_personal_finance_as_other() -> None:
    assert classify_importance(
        "Five budgeting habits to help organize your monthly expenses"
    ) == "other"


def test_is_economics_article_accepts_macro_and_policy_news() -> None:
    assert is_economics_article("US inflation falls as Federal Reserve weighs rate decision")
    assert is_economics_article("Eurozone GDP growth slows amid weak consumer spending")
    assert is_economics_article("Central bank warns of economic headwinds and recession risk")


def test_is_economics_article_rejects_non_economics_topics() -> None:
    assert not is_economics_article("Florida Panthers Struggling Against the Better Teams in the NHL")
    assert not is_economics_article("Lions vs. Patriots odds: Opening lines for Week 10 matchup")
    assert not is_economics_article("Portal breach at Germany's top university exposes passwords")
    assert not is_economics_article("Celebrity actor reveals new relationship during movie premiere")


def test_news_endpoint_returns_validated_articles(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "test-news-key")

    async def fake_get_or_fetch(settings, *, limit, offset, category, force_refresh=False):
        assert settings.news_api_key == "test-news-key"
        assert limit == 3
        assert offset == 0
        assert force_refresh is False
        return [
            NewsArticle(
                id="article-id",
                source="Example News",
                published_at="2026-11-10T10:00:00Z",
                url="https://example.com/story",
                title="A financial headline",
                summary="A short summary grounded in the article.",
                summary_source="ai",
                importance="other",
            )
        ]

    monkeypatch.setattr(news_route, "get_or_fetch_articles", fake_get_or_fetch)
    app.dependency_overrides[news_route.get_settings] = lambda: Settings(
        news_api_key="test-news-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/news?limit=3")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["title"] == "A financial headline"
    assert response.json()[0]["summary_source"] == "ai"
    assert response.json()[0]["importance"] == "other"


def test_news_endpoint_validates_limit(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "test-news-key")

    with TestClient(app) as client:
        response = client.get("/api/v1/news?limit=21")

    assert response.status_code == 422


def test_news_endpoint_reports_missing_configuration(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "startup-test-key")
    app.dependency_overrides[news_route.get_settings] = lambda: Settings(
        news_api_key="",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/news")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503


def test_news_endpoint_sanitizes_provider_failures(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "test-news-key")

    async def fail_get_or_fetch(settings, *, limit, offset, category, force_refresh=False):
        raise NewsProviderError("provider detail that should not reach clients")

    monkeypatch.setattr(news_route, "get_or_fetch_articles", fail_get_or_fetch)
    app.dependency_overrides[news_route.get_settings] = lambda: Settings(
        news_api_key="test-news-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/news")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "provider detail" not in response.text


def test_news_article_endpoint_returns_cached_full_article_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("NEWS_API_KEY", "detail-test-key")
    db_file = tmp_path / "article-detail.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    article = NewsArticle(
        id="article-detail",
        source="Example News",
        published_at="2026-11-10T10:00:00Z",
        url="https://example.com/article-detail",
        title="Central bank holds interest rates",
        summary="An extended summary of the report.",
        article_content="The full article text supplied by the news provider.",
        summary_source="ai",
        importance="important",
    )
    news_repository.save_articles([article])

    with TestClient(app) as client:
        response = client.get("/api/v1/news/article-detail")

    assert response.status_code == 200
    assert response.json()["article_content"] == article.article_content
    assert response.json()["summary"] == article.summary


def test_article_insights_endpoint_generates_and_caches_analysis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_file = tmp_path / "article-insights.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    article = NewsArticle(
        id="insight-story",
        source="Example News",
        published_at="2026-11-10T12:00:00Z",
        url="https://example.com/us-inflation",
        title="U.S. inflation cools more than expected",
        summary="The report may affect expectations for interest rates.",
        article_content="Consumer prices rose more slowly this month.",
        summary_source="publisher",
        importance="important",
    )
    news_repository.save_articles([article])
    insights = ArticleInsightsResponse(
        assets=[
            AffectedAsset(
                name="Nvidia",
                symbol="NVDA",
                kind="company",
                relationship="mentioned",
                rationale="The article names Nvidia as a supplier to chipmakers.",
            )
        ],
        impact=ArticleImpact(
            direction="positive",
            summary="Cooler inflation supports the rate path priced by markets.",
            rationale="The report shows consumer prices rising more slowly.",
        ),
        suggested_questions=[
            "How does the cooler CPI change the rate path priced by markets?"
        ],
    )
    calls = 0

    async def build_insights(settings, requested_article):
        nonlocal calls
        calls += 1
        assert requested_article.id == article.id
        return insights

    monkeypatch.setattr(news_route, "build_article_insights", build_insights)
    app.dependency_overrides[news_route.get_settings] = lambda: Settings(
        news_api_key="test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            first_response = client.get(f"/api/v1/news/{article.id}/insights")
            second_response = client.get(f"/api/v1/news/{article.id}/insights")
    finally:
        app.dependency_overrides.clear()

    assert first_response.status_code == 200
    assert first_response.json()["impact"]["direction"] == "positive"
    assert first_response.json()["assets"][0]["symbol"] == "NVDA"
    assert first_response.json()["suggested_questions"]
    assert second_response.json() == first_response.json()
    assert calls == 1


@pytest.mark.anyio
async def test_article_insights_prompt_covers_related_companies_impact_and_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The analysis must ask for related companies, a direction and grounded questions."""
    observed_request: dict = {}

    class MockResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "output": [
                    {
                        "type": "openrouter:web_fetch",
                        "status": "completed",
                    },
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "assets": [
                                            {
                                                "name": "Lodha Group",
                                                "symbol": None,
                                                "kind": "company",
                                                "relationship": "mentioned",
                                                "rationale": "The article names Lodha Group.",
                                            },
                                            {
                                                "name": "Nvidia",
                                                "symbol": "NVDA",
                                                "kind": "company",
                                                "relationship": "mentioned",
                                                "rationale": "The article names Nvidia.",
                                            },
                                        ],
                                        "impact": {
                                            "direction": "negative",
                                            "summary": "Costs rose faster than revenue.",
                                            "rationale": "The report cites higher input costs.",
                                        },
                                        "suggested_questions": [
                                            "How do the higher input costs affect Lodha's margins?"
                                        ],
                                        "research_notes": (
                                            "Read the publisher page and checked the "
                                            "company's own statement."
                                        ),
                                    }
                                )
                            },
                        ],
                    },
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
            observed_request.update(json)
            return MockResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="test-model",
    )
    article = NewsArticle(
        id="lodha-worli",
        source="Example News",
        published_at="2026-11-10T12:00:00Z",
        url="https://example.com/lodha-worli",
        title="Mukul Agrawal buys office space in Lodha's Worli project",
        summary="The article mentions Lodha's Worli project.",
        article_content="Lodha Group is building the Worli project in Mumbai.",
        summary_source="publisher",
        importance="important",
    )

    insights = await build_article_insights(settings, article)

    system_prompt = observed_request["instructions"]
    assert "suppliers, customers, competitors, lenders" in system_prompt
    assert "positive" in system_prompt and "neutral" in system_prompt
    assert "negative" in system_prompt
    assert "answerable from the article's own content" in system_prompt
    assert "must include Nvidia (NVDA) as mentioned" in system_prompt
    assert "Lodha Developers with NSE symbol LODHA" in system_prompt
    assert "use the web-fetch tool" in system_prompt
    assert "use web search to corroborate" in system_prompt
    assert "never present a fact found online as if the article reported it" in system_prompt
    assert article_insights_service.ARTICLE_INSIGHTS_PROMPT_VERSION == 2

    # The web tools must be offered so the model can read and check the story.
    tool_types = [tool["type"] for tool in observed_request["tools"]]
    assert "openrouter:web_fetch" in tool_types
    assert "openrouter:web_search" in tool_types
    assert observed_request["text"] == {"format": {"type": "json_object"}}
    article_context = observed_request["input"][0]["content"][0]["text"]
    assert "Lodha" in article_context

    assert insights.impact.direction == "negative"
    assert insights.impact.rationale == "The report cites higher input costs."
    assert insights.research_notes is not None
    assert "company's own statement" in insights.research_notes
    assert insights.suggested_questions == [
        "How do the higher input costs affect Lodha's margins?"
    ]

    lodha = next(asset for asset in insights.assets if asset.symbol == "LODHA")
    assert lodha.name == "Lodha Developers"
    assert "LODHA" in lodha.rationale

    nvidia = next(asset for asset in insights.assets if asset.name == "Nvidia")
    assert nvidia.symbol == "NVDA"


@pytest.mark.anyio
async def test_article_insights_reject_an_invalid_impact_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                                "text": json.dumps(
                                    {
                                        "assets": [],
                                        "impact": {
                                            "direction": "bullish",
                                            "summary": "Looks good.",
                                            "rationale": "Because.",
                                        },
                                        "suggested_questions": [],
                                    }
                                ),
                            },
                        ],
                    },
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
            return MockResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="test-model",
    )
    article = NewsArticle(
        id="invalid-impact",
        source="Example News",
        published_at="2026-11-10T12:00:00Z",
        url="https://example.com/invalid-impact",
        title="A story about rates",
        summary="Rates moved.",
        summary_source="publisher",
        importance="other",
    )

    with pytest.raises(ArticleInsightsProviderError):
        await build_article_insights(settings, article)


def test_news_feed_returns_at_once_and_caches_background_ai_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A read never waits for AI work: the summary lands on a later read."""
    monkeypatch.setenv("NEWS_API_KEY", "summary-test-key")
    db_file = tmp_path / "cached-summary.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    news_repository.save_articles(
        [
            NewsArticle(
                id="cached-story",
                source="Example News",
                published_at="2026-11-10T10:00:00Z",
                url="https://example.com/cached-story",
                title="Central bank holds interest rates",
                summary=None,
                summary_source="unavailable",
                importance="important",
            )
        ]
    )

    async def fake_summarize_articles(settings, articles):
        assert [article.id for article in articles] == ["cached-story"]
        return {
            "cached-story": (
                "The central bank kept its policy rate unchanged. Officials "
                "discussed the latest inflation figures and the outlook."
            )
        }

    monkeypatch.setattr(
        "app.services.news_service.summarize_articles",
        fake_summarize_articles,
    )
    app.dependency_overrides[news_route.get_settings] = lambda: Settings(
        news_api_key="summary-test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            first = client.get("/api/v1/news?limit=1")
            assert first.status_code == 200
            # The response is served from storage before any AI work runs.
            assert first.json()[0]["summary"] is None

            deadline = time.monotonic() + 5
            summary_source = ""
            while time.monotonic() < deadline:
                body = client.get("/api/v1/news?limit=1").json()[0]
                summary_source = body["summary_source"]
                if summary_source == "ai":
                    break
                time.sleep(0.05)
    finally:
        app.dependency_overrides.clear()

    assert summary_source == "ai"
    cached = news_repository.get_article("cached-story")
    assert cached is not None
    assert cached.summary_source == "ai"
    assert "central bank kept" in cached.summary


@pytest.mark.anyio
async def test_fetch_articles_filters_non_economics_news(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_payload = {
        "status": "ok",
        "articles": [
            {
                "source": {"name": "Sports Daily"},
                "publishedAt": "2026-11-10T12:00:00Z",
                "url": "https://example.com/sports/hockey",
                "title": "Florida Panthers Struggling Against the Better Teams in the NHL",
                "description": "A recap of hockey games.",
            },
            {
                "source": {"name": "Econ Wire"},
                "publishedAt": "2026-11-10T12:05:00Z",
                "url": "https://example.com/macro/inflation",
                "title": "Eurozone inflation cools to 2.1% as energy prices drop",
                "description": "Consumer price index figures show further moderation.",
            },
            {
                "source": {"name": "Betting News"},
                "publishedAt": "2026-11-10T12:10:00Z",
                "url": "https://example.com/betting/lines",
                "title": "Lions vs. Patriots odds: Opening lines for Week 10 matchup",
                "description": "Gambling odds and lines.",
            },
        ],
    }

    class MockResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return mock_payload

    class MockAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "MockAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def get(self, *args, **kwargs) -> MockResponse:
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    settings = Settings(
        news_api_key="dummy-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )
    econ_articles = await fetch_articles(settings, limit=5, category="economic")
    assert len(econ_articles) == 1
    assert econ_articles[0].title == "Eurozone inflation cools to 2.1% as energy prices drop"

    other_articles = await fetch_articles(settings, limit=5, category="other")
    assert len(other_articles) == 2

    all_articles = await fetch_articles(settings, limit=5, category="all")
    assert len(all_articles) == 3


def test_normalize_marketaux_article_filters_empty_disclosures() -> None:
    # Empty disclosure where description is a URL and snippet is missing
    empty_item = {
        "title": "Board Decisions by Passing",
        "url": "https://example.com/disclosure/123",
        "snippet": "",
        "description": "https://www.dfm.ae/the-exchange/news-disclosures/123",
        "source": "example.com",
    }
    assert normalize_marketaux_article(empty_item) is None

    # Valid real article
    valid_item = {
        "title": "Fed signals potential pause on interest rate hikes",
        "url": "https://example.com/macro/fed-rates",
        "snippet": "Officials indicated that economic conditions remain balanced.",
        "description": "A detailed discussion on the recent FOMC decision.",
        "source": "example.com",
        "published_at": "2026-11-10T12:00:00Z",
    }
    normalized = normalize_marketaux_article(valid_item)
    assert normalized is not None
    assert normalized.title == "Fed signals potential pause on interest rate hikes"
    assert normalized.summary == "Officials indicated that economic conditions remain balanced."


@pytest.mark.anyio
async def test_stale_cache_triggers_a_provider_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A cached feed must be refreshed from the provider once it goes stale."""
    db_file = tmp_path / "stale-cache.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    news_repository.save_articles(
        [
            NewsArticle(
                id=f"cached-{index}",
                source="Example News",
                published_at="2026-11-10T12:00:00Z",
                url=f"https://example.com/cached/{index}",
                title=f"Cached market story {index}",
                summary="The central bank discussed policy.",
                summary_source="publisher",
                importance="important",
            )
            for index in range(20)
        ]
    )

    provider_calls = 0

    async def fake_fetch_articles(settings, limit=20, category=None, start_page=None):
        nonlocal provider_calls
        provider_calls += 1
        return [
            NewsArticle(
                id="fresh-story",
                source="Example News",
                published_at="2026-11-10T18:00:00Z",
                url="https://example.com/fresh-story",
                title="Central bank signals a new rate path",
                summary="The central bank signalled a new rate path.",
                summary_source="publisher",
                importance="important",
            )
        ]

    monkeypatch.setattr(
        "app.services.news_service.fetch_articles",
        fake_fetch_articles,
    )
    monkeypatch.setattr(news_service, "_last_refresh_attempt_at", None)
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
        news_refresh_interval_seconds=60,
    )

    # A fresh cache (provider state recorded just now) must not hit the provider.
    news_repository.set_provider_state("newsapi")
    await get_or_fetch_articles(settings, limit=20)
    assert provider_calls == 0

    # Once the cache ages past the refresh interval the provider is queried again.
    news_repository.set_provider_state(
        "newsapi",
        datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    articles = await get_or_fetch_articles(settings, limit=20)

    assert provider_calls == 1
    assert articles[0].id == "fresh-story"
    assert news_repository.get_articles(limit=20)[0].title == (
        "Central bank signals a new rate path"
    )


@pytest.mark.anyio
async def test_force_refresh_reloads_the_feed_from_the_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_file = tmp_path / "forced-refresh.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    news_repository.save_articles(
        [
            NewsArticle(
                id="cached-story",
                source="Example News",
                published_at="2026-11-10T12:00:00Z",
                url="https://example.com/cached-story",
                title="Cached market story",
                summary="The central bank discussed policy.",
                summary_source="publisher",
                importance="important",
            )
        ]
    )
    news_repository.set_provider_state("newsapi")

    async def fake_fetch_articles(settings, limit=20, category=None, start_page=None):
        return [
            NewsArticle(
                id="forced-story",
                source="Example News",
                published_at="2026-11-10T18:30:00Z",
                url="https://example.com/forced-story",
                title="Freshly pulled market story",
                summary="The central bank held rates steady.",
                summary_source="publisher",
                importance="important",
            )
        ]

    monkeypatch.setattr(
        "app.services.news_service.fetch_articles",
        fake_fetch_articles,
    )
    monkeypatch.setattr(news_service, "_last_refresh_attempt_at", None)
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    articles = await get_or_fetch_articles(settings, limit=20, force_refresh=True)

    assert articles[0].id == "forced-story"


@pytest.mark.anyio
async def test_refresh_only_summarizes_articles_that_are_not_cached(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Repeated refreshes must not pay for summaries of known articles."""
    db_file = tmp_path / "summary-cost.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    known = NewsArticle(
        id="known-story",
        source="Example News",
        published_at="2026-11-10T12:00:00Z",
        url="https://example.com/known-story",
        title="Central bank holds interest rates",
        summary="Publisher summary.",
        summary_source="publisher",
        importance="important",
    )
    news_repository.save_articles([known])

    async def fake_fetch_articles(settings, limit=20, category=None, start_page=None):
        return [known]

    summarized_ids: list[str] = []

    async def fake_summarize_articles(settings, articles):
        summarized_ids.extend(article.id for article in articles)
        return {"known-story": "An AI summary of the known story."}

    monkeypatch.setattr(
        "app.services.news_service.fetch_articles",
        fake_fetch_articles,
    )
    monkeypatch.setattr(
        "app.services.news_service.summarize_articles",
        fake_summarize_articles,
    )
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="test-model",
    )

    await refresh_articles(settings, limit=10)

    assert summarized_ids == []


def test_news_status_reports_feed_freshness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    db_file = tmp_path / "news-status.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    news_repository.save_articles(
        [
            NewsArticle(
                id="status-story",
                source="Example News",
                published_at="2026-11-10T12:00:00Z",
                url="https://example.com/status-story",
                title="Central bank holds interest rates",
                summary="Publisher summary.",
                summary_source="publisher",
                importance="important",
            )
        ]
    )
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    status = news_service.get_news_status(settings)

    assert status["provider"] == "newsapi"
    assert status["article_count"] == 1
    assert status["newest_published_at"] == "2026-11-10T12:00:00Z"
    assert status["is_stale"] is True
    assert status["data_age_seconds"] is not None


@pytest.mark.anyio
async def test_automatic_refreshes_are_throttled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Repeated requests must not spend more than one provider call per interval."""
    db_file = tmp_path / "throttled-refresh.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    provider_calls = 0

    async def fake_fetch_articles(settings, limit=20, category=None, start_page=None):
        nonlocal provider_calls
        provider_calls += 1
        return []

    monkeypatch.setattr(
        "app.services.news_service.fetch_articles",
        fake_fetch_articles,
    )
    monkeypatch.setattr(news_service, "_last_refresh_attempt_at", None)
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
        news_refresh_interval_seconds=1800,
    )

    await refresh_articles(settings, limit=10)
    await refresh_articles(settings, limit=10)
    await refresh_articles(settings, limit=10)

    assert provider_calls == 1

    # A user-triggered refresh is allowed to bypass the throttle.
    await refresh_articles(settings, limit=10, force=True)
    assert provider_calls == 2


def test_news_repository_persistence_and_pagination(tmp_path) -> None:
    db_file = tmp_path / "test_economind.db"
    news_repository.init_db(db_file)

    sample_articles = [
        NewsArticle(
            id=f"id-{i}",
            source="Source A",
            published_at=f"2026-11-10T12:{i:02d}:00Z",
            url=f"https://example.com/story-{i}",
            title=f"Article {i}",
            summary=f"Summary {i}",
            summary_source="ai",
            importance="important",
            category="economic",
        )
        for i in range(15)
    ]

    inserted = news_repository.save_articles(sample_articles, db_path=db_file)
    assert inserted == 15

    # Test deduplication on re-save
    inserted_again = news_repository.save_articles(sample_articles, db_path=db_file)
    assert inserted_again == 0

    # Test pagination: limit 10, offset 0
    page_1 = news_repository.get_articles(limit=10, offset=0, db_path=db_file)
    assert len(page_1) == 10
    # Published at descending, so story 14 is first
    assert page_1[0].title == "Article 14"

    # Test pagination: limit 10, offset 10 (remaining 5)
    page_2 = news_repository.get_articles(limit=10, offset=10, db_path=db_file)
    assert len(page_2) == 5
    assert page_2[0].title == "Article 4"


@pytest.mark.anyio
async def test_marketaux_refresh_always_reads_the_newest_pages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A refresh must read the provider's newest pages, never deeper history."""
    db_file = tmp_path / "marketaux-refresh.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    requested_pages: list[int] = []

    class MockResponse:
        status_code = 200

        def __init__(self, page: int) -> None:
            self.page = page

        def json(self) -> dict:
            return {
                "data": [
                    {
                        "title": f"Central bank policy update for page {self.page}",
                        "url": f"https://example.com/economy/page-{self.page}",
                        "snippet": "The central bank discussed interest rate policy.",
                        "source": "Example News",
                        "published_at": "2026-11-10T12:00:00Z",
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

        async def get(self, url: str, *, params: dict, **kwargs) -> MockResponse:
            page = params["page"]
            requested_pages.append(page)
            return MockResponse(page)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="g" * 40,
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    first_page = await fetch_articles(settings, limit=3)
    news_repository.save_articles(first_page)
    second_page = await fetch_articles(settings, limit=3)

    # Both reads start at the newest page instead of walking into history.
    assert requested_pages == [1, 1]
    assert first_page[0].title.endswith("page 1")
    assert second_page[0].title.endswith("page 1")


@pytest.mark.anyio
async def test_marketaux_backfill_continues_from_the_saved_cursor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Explicit backfill reads continue from the saved provider cursor."""
    db_file = tmp_path / "marketaux-backfill.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    requested_pages: list[int] = []

    class MockResponse:
        status_code = 200

        def json(self) -> dict:
            return {
                "data": [
                    {
                        "title": "Interest rate decision from central bank",
                        "url": "https://example.com/economy/backfill",
                        "snippet": "Central bank policy update.",
                        "source": "Example News",
                        "published_at": "2026-11-10T12:00:00Z",
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

        async def get(self, url: str, *, params: dict, **kwargs) -> MockResponse:
            requested_pages.append(params["page"])
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="h" * 40,
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    await fetch_articles(settings, limit=3)
    news_repository.set_provider_cursor("marketaux", 21)
    await fetch_articles(settings, limit=3, start_page=21)

    assert requested_pages == [1, 21]
    assert news_repository.get_provider_cursor("marketaux") == 22

@pytest.mark.anyio
async def test_article_without_a_body_is_summarized_through_a_web_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no body is stored, the model must read the page with the web tool."""
    observed_request: dict = {}

    class MockResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "output": [
                    {
                        "type": "openrouter:web_fetch",
                        "status": "completed",
                    },
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "id": "web-story",
                                        "summary": (
                                            "The regulator approved the merger after "
                                            "reviewing the filings, with conditions that "
                                            "cut the agreed price by a fifth."
                                        ),
                                    }
                                ),
                            }
                        ],
                    },
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
            observed_request.update(json)
            return MockResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="test-model",
    )
    article = NewsArticle(
        id="web-story",
        source="Example News",
        published_at="2026-11-10T12:00:00Z",
        url="https://example.com/economy/merger",
        title="Regulator clears merger after review",
        summary="The merger cleared review.",
        summary_source="publisher",
        importance="important",
    )

    summaries = await summarize_articles(settings, [article])

    assert "cut the agreed price by a fifth" in summaries["web-story"]
    tool_types = [tool["type"] for tool in observed_request["tools"]]
    assert "openrouter:web_fetch" in tool_types
    assert observed_request["input"][0]["content"][0]["text"].count(
        "https://example.com/economy/merger"
    ) == 1


@pytest.mark.anyio
async def test_article_with_a_body_is_summarized_without_web_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored body means no web call is needed."""
    observed_request: dict = {}

    class MockResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summaries": [
                                        {
                                            "id": "stored-story",
                                            "summary": (
                                                "The central bank kept its policy rate "
                                                "unchanged and said inflation stayed "
                                                "above target."
                                            ),
                                        }
                                    ]
                                }
                            )
                        }
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
            observed_request.update(json)
            return MockResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", MockAsyncClient)
    settings = Settings(
        news_api_key="test-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="test-model",
    )
    article = NewsArticle(
        id="stored-story",
        source="Example News",
        published_at="2026-11-10T12:00:00Z",
        url="https://example.com/economy/rates",
        title="Central bank holds interest rates",
        summary="The bank held its policy rate unchanged.",
        article_content=(
            "The central bank kept its policy rate unchanged and said inflation "
            "remained above its target while the labour market stayed resilient, "
            "adding that decisions would be taken meeting by meeting as the "
            "incoming data arrives."
        ),
        summary_source="publisher",
        importance="important",
    )

    summaries = await summarize_articles(settings, [article])

    assert "kept its policy rate unchanged" in summaries["stored-story"]
    assert "tools" not in observed_request


@pytest.mark.anyio
async def test_publisher_summaries_are_served_without_new_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A publisher summary is final; feed reads never re-summarize it."""
    db_file = tmp_path / "publisher-final.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    news_repository.save_articles(
        [
            NewsArticle(
                id="publisher-story",
                source="Example News",
                published_at="2026-11-10T10:00:00Z",
                url="https://example.com/publisher-story",
                title="Central bank holds interest rates",
                summary="The publisher's own description.",
                summary_source="publisher",
                importance="important",
            )
        ]
    )
    summarized_ids: list[str] = []

    async def fake_summarize_articles(settings, articles):
        summarized_ids.extend(article.id for article in articles)
        return {}

    monkeypatch.setattr(
        "app.services.news_service.summarize_articles",
        fake_summarize_articles,
    )
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="test-model",
    )

    articles = await get_or_fetch_articles(settings, limit=1)
    await news_service.drain_background_tasks()
    articles = await get_or_fetch_articles(settings, limit=1)

    assert summarized_ids == []
    assert articles[0].summary == "The publisher's own description."
    assert articles[0].summary_source == "publisher"


@pytest.mark.anyio
async def test_feed_read_returns_while_summaries_regenerate_in_background(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """The feed response must not wait on AI summarization."""
    db_file = tmp_path / "nonblocking.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    news_repository.save_articles(
        [
            NewsArticle(
                id="slow-summary-story",
                source="Example News",
                published_at="2026-11-10T10:00:00Z",
                url="https://example.com/slow-summary-story",
                title="Central bank holds interest rates",
                summary=None,
                summary_source="unavailable",
                importance="important",
            )
        ]
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_summarize_articles(settings, articles):
        started.set()
        await release.wait()
        return {"slow-summary-story": "An AI summary written after the read."}

    monkeypatch.setattr(
        "app.services.news_service.summarize_articles",
        fake_summarize_articles,
    )
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="test-model",
    )

    articles = await get_or_fetch_articles(settings, limit=1)
    assert articles[0].summary is None

    # Give the background task a chance to start; the read above already
    # returned while the summarization is still blocked.
    for _ in range(20):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()
    assert release.is_set() is False

    release.set()
    await news_service.drain_background_tasks()

    cached = news_repository.get_article("slow-summary-story")
    assert cached is not None
    assert cached.summary == "An AI summary written after the read."
    assert cached.summary_source == "ai"


@pytest.mark.anyio
async def test_failed_summary_attempt_backs_off_before_retrying(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A failed AI-summary attempt is not retried on the next feed read."""
    db_file = tmp_path / "backoff.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    news_repository.save_articles(
        [
            NewsArticle(
                id="failing-story",
                source="Example News",
                published_at="2026-11-10T10:00:00Z",
                url="https://example.com/failing-story",
                title="Central bank holds interest rates",
                summary=None,
                summary_source="unavailable",
                importance="important",
            )
        ]
    )
    summarized_ids: list[str] = []

    async def fake_summarize_articles(settings, articles):
        summarized_ids.extend(article.id for article in articles)
        return {}

    monkeypatch.setattr(
        "app.services.news_service.summarize_articles",
        fake_summarize_articles,
    )
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key="test-openrouter-key",
        openrouter_model="test-model",
    )

    await get_or_fetch_articles(settings, limit=1)
    await news_service.drain_background_tasks()
    assert summarized_ids == ["failing-story"]
    assert news_service._summary_retry_at["failing-story"] > time.monotonic()

    await get_or_fetch_articles(settings, limit=1)
    await news_service.drain_background_tasks()
    assert summarized_ids == ["failing-story"]  # no second attempt while in backoff


@pytest.mark.anyio
async def test_refresh_records_provider_state_before_background_enrichment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """The cache is marked fresh once articles are stored, not after AI work."""
    db_file = tmp_path / "state-first.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    fresh = NewsArticle(
        id="fresh-story",
        source="Example News",
        published_at="2026-11-10T10:00:00Z",
        url="https://example.com/fresh-story",
        title="Central bank holds interest rates",
        summary="Publisher summary.",
        summary_source="publisher",
        importance="important",
    )

    async def fake_fetch_articles(settings, limit=20, category=None, start_page=None):
        return [fresh]

    enrichment_started = asyncio.Event()
    release_enrichment = asyncio.Event()

    async def fake_enrich(settings, articles):
        enrichment_started.set()
        await release_enrichment.wait()
        return {}

    monkeypatch.setattr(
        "app.services.news_service.fetch_articles",
        fake_fetch_articles,
    )
    monkeypatch.setattr(
        "app.services.news_service.enrich_articles_with_content",
        fake_enrich,
    )
    settings = Settings(
        news_api_key="test-news-key",
        openrouter_api_key=None,
        openrouter_model="test-model",
    )

    saved = await refresh_articles(settings, limit=10)

    # The refresh returned while enrichment was still blocked, and the cache
    # is already recorded as fresh so no other read triggers another refresh.
    assert saved == 1
    assert news_repository.get_provider_state("newsapi") is not None
    assert news_service.is_cache_stale(settings) is False
    assert enrichment_started.is_set() is False

    release_enrichment.set()
    await news_service.drain_background_tasks()
