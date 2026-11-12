import asyncio
import json

import pytest

from app.services import article_extractor
from app.services.article_extractor import extract_article_text

PADDING = "<!-- " + ("x" * 600) + " -->"


def test_extracts_body_from_json_ld_article_body() -> None:
    body = (
        "The central bank left its policy rate unchanged on Thursday, saying "
        "inflation was still running above target while the labour market "
        "remained resilient, according to the statement released in the "
        "morning."
    )
    html = f"""
    <html><head>
      <script type="application/ld+json">
        {json.dumps({"@type": "NewsArticle", "articleBody": body})}
      </script>
    </head><body><div><p>Short teaser.</p></div>{PADDING}</body></html>
    """

    extracted = extract_article_text(html)

    assert extracted is not None
    assert extracted == body


def test_extracts_body_from_nested_json_ld_graph() -> None:
    body = (
        "Regulators outlined new capital requirements for lenders, a measure "
        "that industry groups said would raise the cost of borrowing for "
        "smaller banks operating with thinner margins, and that would take "
        "years to phase in for the largest institutions."
    )
    payload = {
        "@graph": [
            {"@type": "WebSite", "name": "Example"},
            {"@type": "NewsArticle", "articleBody": body},
        ]
    }
    html = f"""
    <html><head>
      <script type="application/ld+json">{json.dumps(payload)}</script>
    </head><body>{PADDING}</body></html>
    """

    extracted = extract_article_text(html)

    assert extracted == body


def test_extracts_body_from_article_scoped_paragraphs() -> None:
    html = f"""
    <html><body>
      <nav><p>Home Markets Economy Subscribe to our newsletter for updates</p></nav>
      <article>
        <p>European markets closed higher on Friday as investors weighed a
           fresh set of inflation readings against a weaker currency and a
           cautious outlook from the central bank.</p>
        <p>Traders said the data had not changed the rate path priced in for
           the next quarter, though bond yields slipped towards the end of
           the session.</p>
      </article>
    {PADDING}</body></html>
    """

    extracted = extract_article_text(html)

    assert extracted is not None
    assert "European markets closed higher" in extracted
    assert "Subscribe to our newsletter" not in extracted


def test_extracts_body_from_content_class_container() -> None:
    html = f"""
    <html><body>
      <div class="site-header"><p>Advertisement</p></div>
      <div class="entry-content">
        The finance ministry revised its growth forecast for the coming year,
        pointing to weaker export demand and a slower recovery in domestic
        investment, while flagging a sharp rise in borrowing costs for firms
        that had already been refinancing at record spreads.
      </div>
    {PADDING}</body></html>
    """

    extracted = extract_article_text(html)

    assert extracted is not None
    assert "finance ministry revised its growth forecast" in extracted


def test_returns_none_for_pages_without_readable_text() -> None:
    html = "<html><body><p>Hi</p></body></html>" + " " * 600

    assert extract_article_text(html) is None


def test_returns_none_for_paywalled_pages() -> None:
    html = """
    <html><body>
      <article>
        <p>Subscribe to continue reading this article and unlock the full
           analysis of the central bank's decision and its effect on markets.</p>
      </article>
    </body></html>
    """ + " " * 600

    assert extract_article_text(html) is None


def test_clean_reader_response_removes_metadata_header() -> None:
    payload = (
        "Title: Example headline\n"
        "URL Source: https://example.com/story\n"
        "Final URL: https://example.com/story\n"
        "\n"
        "The body of the story begins here and continues for long enough to "
        "pass the minimum length threshold used by the cleaner, describing "
        "what the central bank decided, which officials signed off on it, "
        "and how bond markets and equities reacted to the announcement."
    )

    cleaned = article_extractor._clean_reader_response(payload)

    assert cleaned is not None
    body, final_url = cleaned
    assert not body.startswith("Title:")
    assert "The body of the story" in body
    assert final_url == "https://example.com/story"


def test_redirects_to_a_different_article_are_rejected() -> None:
    assert article_extractor._same_article(
        "https://example.com/2026/markets/story-about-rates",
        "https://example.com/2026/markets/story-about-something-else",
    ) is False
    assert article_extractor._same_article(
        "https://example.com/2026/markets/story-about-rates",
        "https://example.com/2026/markets/story-about-rates/",
    ) is True
    assert article_extractor._same_article(
        "https://example.com/story-about-rates",
        "https://other.example.com/story-about-rates",
    ) is False


@pytest.mark.anyio
async def test_fetch_article_texts_returns_bodies_for_reachable_pages(monkeypatch) -> None:
    body = (
        "A full article body that is comfortably longer than the minimum "
        "length required to be treated as the extracted body of this story, "
        "with enough detail for the summarizer to work from and to cite the "
        "reported figures rather than only the headline."
    )

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def __init__(self, url: str) -> None:
            self.url = url

        @property
        def text(self) -> str:
            return (
                "<html><head><script type='application/ld+json'>"
                + json.dumps({"@type": "NewsArticle", "articleBody": body})
                + "</script></head><body>"
                + PADDING
                + "</body></html>"
            )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def get(self, url: str, **kwargs):
            return FakeResponse(url)

    monkeypatch.setattr(article_extractor.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(article_extractor, "_load_robots_parser", _allow_all)

    results = await article_extractor.fetch_article_texts(["https://example.com/a"])

    assert "https://example.com/a" in results
    assert "full article body" in results["https://example.com/a"]


async def _allow_all(client, host):  # noqa: ANN001 - test double
    return None


@pytest.mark.anyio
async def test_robots_redirect_is_not_followed_and_failure_is_cached(monkeypatch) -> None:
    """A redirecting robots.txt costs one request and is not retried per article."""
    body = (
        "A full article body that is comfortably longer than the minimum "
        "length required to be treated as the extracted body of this story, "
        "with enough detail for the summarizer to work from and to cite the "
        "reported figures rather than only the headline."
    )
    requested: list[str] = []

    class FakeResponse:
        def __init__(self, url: str, status_code: int = 200) -> None:
            self.url = url
            self.status_code = status_code
            self.headers = {"content-type": "text/html; charset=utf-8"}

        @property
        def text(self) -> str:
            return (
                "<html><head><script type='application/ld+json'>"
                + json.dumps({"@type": "NewsArticle", "articleBody": body})
                + "</script></head><body>"
                + PADDING
                + "</body></html>"
            )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def get(self, url: str, **kwargs):
            requested.append(url)
            if url.endswith("/robots.txt"):
                assert kwargs.get("follow_redirects") is False
                return FakeResponse(url, status_code=301)
            return FakeResponse(url)

    monkeypatch.setattr(article_extractor.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(article_extractor, "_robot_cache", {})
    monkeypatch.setattr(article_extractor, "_robot_locks", {})

    urls = [f"https://looping.example/story-{index}" for index in range(3)]
    results = await article_extractor.fetch_article_texts(urls)

    # No rules were obtained, so pages are still fetched — but robots.txt was
    # requested exactly once, without following the redirect.
    robots_requests = [url for url in requested if url.endswith("/robots.txt")]
    assert len(results) == 3
    assert len(robots_requests) == 1
    assert all(not url.endswith("robots.txt/") for url in requested)

    # A second cycle within the retry window does not re-request robots.txt.
    await article_extractor.fetch_article_texts(urls)
    assert len([url for url in requested if url.endswith("/robots.txt")]) == 1


@pytest.mark.anyio
async def test_concurrent_workers_share_one_robots_request(monkeypatch) -> None:
    """Workers for the same host do not stampede robots.txt concurrently."""
    robots_calls = 0
    robots_gate = asyncio.Event()

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def __init__(self, url: str) -> None:
            self.url = url

        @property
        def text(self) -> str:
            if self.url.endswith("/robots.txt"):
                return "User-agent: *\nAllow: /\n"
            sentence = (
                "The central bank held its policy rate steady and explained "
                "its reasoning to reporters after the meeting ended today. "
            )
            return "<html><body><p>" + sentence * 6 + "</p></body></html>"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def get(self, url: str, **kwargs):
            nonlocal robots_calls
            if url.endswith("/robots.txt"):
                robots_calls += 1
                # Hold the fetch open so concurrent workers pile up on it.
                await asyncio.wait_for(robots_gate.wait(), timeout=2)
                return FakeResponse(url)
            return FakeResponse(url)

    class SlowStartClient(FakeAsyncClient):
        pass

    monkeypatch.setattr(article_extractor.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(article_extractor, "_robot_cache", {})
    monkeypatch.setattr(article_extractor, "_robot_locks", {})

    original_get = FakeAsyncClient.get

    # Start both workers, then release the robots fetch so they overlap.
    async def opener() -> None:
        await asyncio.sleep(0.05)
        robots_gate.set()

    async def counting_get(self, url, **kwargs):
        return await original_get(self, url, **kwargs)

    monkeypatch.setattr(FakeAsyncClient, "get", counting_get)
    gate_task = asyncio.create_task(opener())

    results = await article_extractor.fetch_article_texts(
        ["https://shared.example/one", "https://shared.example/two"],
        concurrency=2,
    )
    await gate_task

    assert len(results) == 2
    assert robots_calls == 1
