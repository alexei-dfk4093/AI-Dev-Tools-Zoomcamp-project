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
