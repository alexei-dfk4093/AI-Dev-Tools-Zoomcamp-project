"""End-to-end integration tests.

Each test walks the full backend stack in one run: the upstream news
provider, article enrichment, AI summarization, the SQLite cache, and the
HTTP API, with every external call mocked. These tests verify that the
layers work together, not only in isolation.
"""

import hashlib
import json as jsonlib
import sqlite3
import time

import httpx
from fastapi.testclient import TestClient

from app.api.routes import news as news_route
from app.core.config import Settings
from app.main import app
from app.repositories import news_repository
from app.services import news_service

ECON_URL = "https://example.com/economy/eurozone-inflation"
SPORTS_URL = "https://example.com/sports/hockey-recap"
ECON_ID = hashlib.sha256(ECON_URL.encode("utf-8")).hexdigest()[:16]
SPORTS_ID = hashlib.sha256(SPORTS_URL.encode("utf-8")).hexdigest()[:16]

AI_SUMMARY = (
    "Statistics offices reported that eurozone consumer prices rose 2.1 "
    "percent, slower than the previous month, as energy costs fell. The "
    "report keeps the central bank's next policy meeting in focus."
)

ECON_CONTENT = (
    "Consumer prices in the euro area rose 2.1 percent year on year, "
    "down from 2.4 percent the previous month, driven mainly by cheaper "
    "energy. Core inflation held steady. Economists said the figures keep "
    "the door open for the central bank to hold its policy rate at the "
    "next meeting, while several analysts cautioned that services prices "
    "remain elevated and that a single month of data does not settle the "
    "outlook."
)

NEWS_PAYLOAD = {
    "status": "ok",
    "articles": [
        {
            "source": {"name": "Econ Wire"},
            "publishedAt": "2026-11-10T12:00:00Z",
            "url": ECON_URL,
            "title": "Eurozone inflation cools to 2.1% as energy prices drop",
            "description": "Consumer price index figures show further moderation.",
            "content": ECON_CONTENT,
        },
        {
            "source": {"name": "Sports Daily"},
            "publishedAt": "2026-11-10T12:05:00Z",
            "url": SPORTS_URL,
            "title": "Florida Panthers Struggling Against the Better Teams in the NHL",
            "description": "A recap of hockey games.",
        },
    ],
}


class _MockHttpResponse:
    def __init__(self, *, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.url = "https://example.com/requested"
        self.headers = {"content-type": "text/html"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", self.url),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


class _FullStackMockClient:
    """Mock httpx.AsyncClient for every external call in one stack run.

    Dispatches by URL: the news provider, OpenRouter (both the chat
    summarization request and the online assistant request), robots.txt,
    and publisher pages.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FullStackMockClient":
        return self

    async def __aexit__(self, *args) -> None:
        pass

    async def get(self, url: str, *, params=None, headers=None, **kwargs):
        if "newsapi.org" in url:
            return _MockHttpResponse(payload=NEWS_PAYLOAD)
        if url.endswith("/robots.txt"):
            return _MockHttpResponse(text="User-agent: *\nAllow: /\n")
        # Publisher pages: unreachable in this scenario (HTTP 404), so the
        # article without provider content keeps its publisher description.
        return _MockHttpResponse(status_code=404)

    async def post(self, url: str, *, json=None, headers=None, **kwargs):
        if "messages" in json:
            # Chat-completions batch summarization: echo back one summary
            # per article id found in the request.
            request_articles = jsonlib.loads(json["messages"][1]["content"])["articles"]
            content = jsonlib.dumps(
                {
                    "summaries": [
                        {"id": item["id"], "summary": AI_SUMMARY}
                        for item in request_articles
                    ]
                }
            )
            return _MockHttpResponse(
                payload={"choices": [{"message": {"content": content}}]}
            )
        # Assistant (online) request: the article context is the input text.
        context = jsonlib.loads(json["input"][0]["content"][0]["text"])
        content = jsonlib.dumps({"id": context["id"], "summary": AI_SUMMARY})
        return _MockHttpResponse(
            payload={
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                ]
            }
        )


def test_provider_refresh_persists_to_storage_and_serves_the_feed(
    monkeypatch,
    tmp_path,
) -> None:
    """Provider HTTP -> SQLite -> API, one full pass with mocked externals."""
    db_file = tmp_path / "integration.db"
    monkeypatch.setattr(news_repository, "DEFAULT_DB_PATH", db_file)
    news_repository.init_db()
    monkeypatch.setattr(news_service, "_last_refresh_attempt_at", None)
    monkeypatch.setattr(httpx, "AsyncClient", _FullStackMockClient)

    provider_calls: list[str] = []
    original_get = _FullStackMockClient.get

    async def counting_get(self, url, **kwargs):
        provider_calls.append(url)
        return await original_get(self, url, **kwargs)

    monkeypatch.setattr(_FullStackMockClient, "get", counting_get)
    app.dependency_overrides[news_route.get_settings] = lambda: Settings(
        news_api_key="test-news-key",
        openrouter_api_key="openrouter-test-key",
        openrouter_model="test-model",
    )

    try:
        with TestClient(app) as client:
            # 1. The API process is up.
            assert client.get("/health").json() == {"status": "ok"}

            # 2. Startup prefetch has pulled from the provider and stored it.
            prefetch = getattr(app.state, "prefetch_task", None)
            assert prefetch is not None
            deadline = time.monotonic() + 15
            while not prefetch.done() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert prefetch.done(), "startup prefetch did not finish in time"
            assert len(provider_calls) >= 1

            # 3. The feed serves the stored economics article with the
            #    AI summary generated from the provider content. Summaries
            #    are produced by a background task, so early reads may still
            #    show the publisher summary; poll until it lands.
            econ = None
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                feed = client.get("/api/v1/news", params={"limit": 5})
                assert feed.status_code == 200
                econ = next((a for a in feed.json() if a["id"] == ECON_ID), None)
                if econ is not None and econ["summary_source"] == "ai":
                    break
                time.sleep(0.05)
            assert econ is not None, "economics article missing from the feed"
            assert econ["summary"] == AI_SUMMARY
            assert econ["summary_source"] == "ai"
            assert econ["source"] == "Econ Wire"
            assert econ["published_at"] == "2026-11-10T12:00:00Z"

            # Background enrichment and summarization are finished by now, so
            # this is the baseline for counting provider traffic below.
            calls_after_startup = len(provider_calls)

            # 4. An explicit refresh reaches the provider exactly once more.
            refreshed = client.get(
                "/api/v1/news", params={"limit": 5, "refresh": "true"}
            )
            assert refreshed.status_code == 200
            assert len(provider_calls) == calls_after_startup + 1

            # 5. A plain read afterwards is served from storage, with no
            #    additional provider traffic.
            again = client.get("/api/v1/news", params={"limit": 5})
            assert again.status_code == 200
            assert len(provider_calls) == calls_after_startup + 1
            assert again.json() == refreshed.json()

            # 6. The other-category article is served through the same
            #    storage path.
            others = client.get("/api/v1/news", params={"limit": 5, "category": "other"})
            assert others.status_code == 200
            assert any(a["id"] == SPORTS_ID for a in others.json())

            # 7. The status endpoint describes the stored feed.
            status = client.get("/api/v1/news/status")
            assert status.status_code == 200
            status_body = status.json()
            assert status_body["provider"] == "newsapi"
            assert status_body["article_count"] >= 2
            assert status_body["is_stale"] is False
    finally:
        app.dependency_overrides.clear()

    # 8. The economics article is really persisted in the SQLite cache,
    #    with the AI summary and the original publication timestamp.
    with sqlite3.connect(db_file) as connection:
        row = connection.execute(
            "SELECT title, summary, summary_source, published_at, category "
            "FROM articles WHERE id = ?",
            (ECON_ID,),
        ).fetchone()
    assert row is not None
    assert row[0] == "Eurozone inflation cools to 2.1% as energy prices drop"
    assert row[1] == AI_SUMMARY
    assert row[2] == "ai"
    assert row[3] == "2026-11-10T12:00:00Z"
    assert row[4] == "economic"
