"""Free article-body extraction.

News providers hand out a headline and a one-line description; the body text
is only available on the publisher's own page. This module retrieves that page
and extracts the readable article text so the summarizer can ground its output
in the actual story instead of the headline alone.

No paid service is involved: a plain HTTP request per article, with a
best-effort extraction from JSON-LD metadata, ``<article>``/``<main>``
scopes, and paragraph-density heuristics.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.robotparser
from html import unescape
from html.parser import HTMLParser

import httpx

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MIN_BODY_LENGTH = 200
MAX_BODY_LENGTH = 30000
MIN_PARAGRAPH_LENGTH = 60

# Lines that are navigation, consent or subscription furniture rather than
# reporting. Matched case-insensitively against the start of a paragraph.
BOILERPLATE_PATTERNS = (
    r"^(subscribe|sign up|log in|register|newsletter|advertisement|read more"
    r"|share this|related articles?|comments?|cookie|accept all|privacy policy"
    r"|terms of (use|service)|all rights reserved|follow us|download the app"
    r"|this article was originally published|support our journalism"
    r"|skip (navigation|to)|menu|navigation|home\s*\|)",
)

# Container markers used by common CMS templates (WordPress, Drupal, Rails
# newsrooms) to wrap the article body. Paragraphs inside them are body text.
CONTENT_CLASS_PATTERNS = (
    "article-body",
    "articlebody",
    "article-content",
    "article_content",
    "article__body",
    "article-text",
    "story-body",
    "story-content",
    "storytext",
    "entry-content",
    "post-content",
    "post-body",
    "post-body-content",
    "rich-text",
    "richtext",
    "node__content",
    "field--name-body",
    "field-body",
    "content-body",
    "body-content",
    "main-content",
    "text-content",
    "news-content",
    "news-body",
    "c-article",
    "caas-body",
    "paywall",
    "inline-content",
    "body_text",
)

# Phrases that reveal a paywall or a consent wall instead of the story.
PAYWALL_MARKERS = (
    "subscribe to continue reading",
    "sign in to continue",
    "this content is only available to subscribers",
    "subscribe for full access",
    "become a subscriber to read",
    "paywall",
)

_robot_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _has_content_marker(value: str) -> bool:
    lowered = (value or "").lower()
    return any(pattern in lowered for pattern in CONTENT_CLASS_PATTERNS)


class _ArticleParser(HTMLParser):
    """Collect JSON-LD bodies, article-scoped paragraphs and meta descriptions."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jsonld_blocks: list[str] = []
        self.paragraphs: list[tuple[str, bool]] = []
        self.blocks: list[str] = []
        self.meta_description: str = ""
        self._in_jsonld = False
        self._jsonld_buffer: list[str] = []
        self._scope_depth = 0
        self._content_depth = 0
        self._content_buffer: list[str] | None = None
        self._paragraph_buffer: list[str] | None = None
        self._paragraph_in_scope = False

    # -- scope tracking -------------------------------------------------
    def _is_content_scope(self, tag: str, attrs: dict[str, str | None]) -> bool:
        if tag in {"article", "main"}:
            return True
        if attrs.get("role") == "main":
            return True
        itemprop = (attrs.get("itemprop") or "").lower()
        return "articlebody" in itemprop

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = {key: (value or "") for key, value in attrs_list}

        if tag == "script":
            script_type = (attrs.get("type") or "").lower()
            if "ld+json" in script_type:
                self._in_jsonld = True
                self._jsonld_buffer = []
            return

        if tag == "meta":
            name = (attrs.get("name") or "").lower()
            prop = (attrs.get("property") or "").lower()
            if name in {"description", "og:description"} or prop == "og:description":
                if not self.meta_description:
                    self.meta_description = (attrs.get("content") or "").strip()
            return

        if self._is_content_scope(tag, attrs):
            self._scope_depth += 1

        marker = f"{attrs.get('class', '')} {attrs.get('id', '')}"
        if _has_content_marker(marker):
            self._content_depth += 1
            if self._content_buffer is None:
                self._content_buffer = []

        if tag == "p" and self._paragraph_buffer is None:
            self._paragraph_buffer = []
            self._paragraph_in_scope = (
                self._scope_depth > 0 or self._content_depth > 0
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_jsonld:
            self.jsonld_blocks.append("".join(self._jsonld_buffer))
            self._in_jsonld = False
            self._jsonld_buffer = []

        if tag == "p" and self._paragraph_buffer is not None:
            text = normalize_whitespace(" ".join(self._paragraph_buffer))
            self.paragraphs.append((text, self._paragraph_in_scope))
            self._paragraph_buffer = None
            self._paragraph_in_scope = False

        if self._content_depth > 0 and tag in {"div", "section", "article", "main"}:
            self._content_depth -= 1
            if self._content_depth == 0 and self._content_buffer is not None:
                self.blocks.append(normalize_whitespace(" ".join(self._content_buffer)))
                self._content_buffer = None

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld_buffer.append(data)
            return
        if self._paragraph_buffer is not None:
            self._paragraph_buffer.append(data)
        if self._content_buffer is not None:
            self._content_buffer.append(data)

    @property
    def has_content_scope(self) -> bool:
        return self._scope_depth > 0


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _looks_like_boilerplate(text: str) -> bool:
    lowered = text.lower()
    return any(re.match(pattern, lowered) for pattern in BOILERPLATE_PATTERNS)


def _looks_like_paywall(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in PAYWALL_MARKERS)


def _jsonld_article_body(blocks: list[str]) -> str | None:
    """Return the longest ``articleBody`` found in any JSON-LD block."""
    candidates: list[str] = []

    def visit(node) -> None:
        if isinstance(node, dict):
            body = node.get("articleBody")
            if isinstance(body, str) and body.strip():
                candidates.append(body)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    for block in blocks:
        try:
            payload = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        visit(payload)

    if not candidates:
        return None

    best = max(candidates, key=len)
    cleaned = normalize_whitespace(unescape(best))
    return cleaned or None


def _paragraph_body(parser: _ArticleParser) -> str | None:
    """Join the densest run of substantial paragraphs."""
    candidates = [
        (text, in_scope)
        for text, in_scope in parser.paragraphs
        if len(text) >= MIN_PARAGRAPH_LENGTH
        and not _looks_like_boilerplate(text)
        and not _looks_like_paywall(text)
    ]
    if not candidates:
        return None

    scoped = [text for text, in_scope in candidates if in_scope]
    pool = scoped or [text for text, _ in candidates]

    # Keep the longest contiguous run so navigation blocks do not dilute the body.
    best_run: list[str] = []
    current: list[str] = []
    for text in pool:
        if len(text) >= MIN_PARAGRAPH_LENGTH:
            current.append(text)
            if len(" ".join(current)) > len(" ".join(best_run)):
                best_run = list(current)
        else:
            current = []

    body = normalize_whitespace(" ".join(best_run))
    return body or None


def _block_body(parser: _ArticleParser) -> str | None:
    """Use text captured from CMS content containers that hold no ``<p>`` tags."""
    blocks = [
        text
        for text in parser.blocks
        if len(text) >= MIN_BODY_LENGTH
        and not _looks_like_paywall(text)
    ]
    if not blocks:
        return None

    best = max(blocks, key=len)
    return normalize_whitespace(best)


def extract_article_text(html: str) -> str | None:
    """Extract the readable body of an article page, or None when unavailable."""
    if not html or len(html) < 500:
        return None

    parser = _ArticleParser()
    try:
        parser.feed(html)
    except Exception as exc:  # noqa: BLE001 - malformed markup must not break a refresh
        logger.debug("HTML parsing failed: %s", exc)

    body = _jsonld_article_body(parser.jsonld_blocks)
    if body and len(body) >= MIN_BODY_LENGTH:
        return body[:MAX_BODY_LENGTH]

    body = _paragraph_body(parser)
    if body and len(body) >= MIN_BODY_LENGTH:
        return body[:MAX_BODY_LENGTH]

    body = _block_body(parser)
    if body and len(body) >= MIN_BODY_LENGTH:
        return body[:MAX_BODY_LENGTH]

    description = normalize_whitespace(unescape(parser.meta_description))
    if len(description) >= MIN_BODY_LENGTH:
        return description[:MAX_BODY_LENGTH]

    return None


def _robots_allows(url: str, parser: urllib.robotparser.RobotFileParser | None) -> bool:
    """Respect robots.txt; unparsable or missing rules allow the request."""
    if parser is None:
        return True

    try:
        return parser.can_fetch(BROWSER_HEADERS["User-Agent"], url)
    except Exception:  # noqa: BLE001
        return True


async def _load_robots_parser(
    client: httpx.AsyncClient,
    host: str,
) -> urllib.robotparser.RobotFileParser | None:
    """Fetch and cache a host's robots.txt rules."""
    if host in _robot_cache:
        return _robot_cache[host]

    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"https://{host}/robots.txt")
    try:
        response = await client.get(f"https://{host}/robots.txt", timeout=8.0)
        if response.status_code == 200:
            parser.parse(response.text.splitlines())
            _robot_cache[host] = parser
        else:
            _robot_cache[host] = None
    except Exception:  # noqa: BLE001 - unreachable robots.txt means no rules
        _robot_cache[host] = None

    return _robot_cache[host]


def _same_article(requested: str, final: str) -> bool:
    """Check that a redirect still points at the same story.

    A publisher may redirect a request to a different article; storing that
    body would attach unrelated reporting to the headline, so such redirects
    are rejected.
    """
    try:
        requested_url = httpx.URL(requested)
        final_url = httpx.URL(final)
    except Exception:  # noqa: BLE001 - unparsable URLs are treated as different
        return False

    if requested_url.host.replace("www.", "") != final_url.host.replace("www.", ""):
        return False

    requested_slug = requested_url.path.strip("/").split("/")[-1].lower()
    final_slug = final_url.path.strip("/").split("/")[-1].lower()
    if not requested_slug or not final_slug:
        return True

    return requested_slug == final_slug


async def fetch_article_text(
    client: httpx.AsyncClient,
    url: str,
    timeout: float = 12.0,
) -> str | None:
    """Download one article page and return its extracted body text."""
    try:
        response = await client.get(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - network errors are expected
        logger.debug("Article fetch failed for %s: %s", url, exc)
        return None

    if response.status_code != 200:
        logger.debug("Article fetch returned HTTP %s for %s", response.status_code, url)
        return None

    if not _same_article(url, str(response.url)):
        logger.info("Skipping %s: the request redirected to a different article.", url)
        return None

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        return None

    return extract_article_text(response.text)


READER_PROXY_HEADER_LINES = (
    "title:",
    "url source:",
    "final url:",
    "published time:",
    "markdown content:",
    "content:",
    "warning:",
)


def _clean_reader_response(text: str) -> str | None:
    """Strip the reader proxy's metadata header from a markdown response."""
    lines = text.splitlines()
    index = 0
    final_url = ""
    while index < len(lines) and lines[index].strip():
        lowered = lines[index].strip().lower()
        if lowered.startswith("final url:"):
            final_url = lines[index].split(":", 1)[1].strip()
        if any(lowered.startswith(prefix) for prefix in READER_PROXY_HEADER_LINES):
            index += 1
            continue
        break

    body = normalize_whitespace(" ".join(lines[index:]))
    if len(body) < MIN_BODY_LENGTH:
        return None
    return body[:MAX_BODY_LENGTH], final_url


async def fetch_via_reader_proxy(
    client: httpx.AsyncClient,
    url: str,
    proxy_base: str,
) -> str | None:
    """Fetch a page through a free reader proxy that renders JavaScript."""
    try:
        response = await client.get(f"{proxy_base}{url}", timeout=30.0)
    except Exception as exc:  # noqa: BLE001 - proxy failures are expected
        logger.debug("Reader proxy failed for %s: %s", url, exc)
        return None

    if response.status_code != 200:
        return None

    cleaned = _clean_reader_response(response.text)
    if not cleaned:
        return None

    body, final_url = cleaned
    if final_url and not _same_article(url, final_url):
        logger.info("Skipping %s: the reader proxy resolved a different article.", url)
        return None

    return body


async def fetch_article_texts(
    urls: list[str],
    concurrency: int = 5,
    timeout: float = 12.0,
    proxy_base: str = "",
) -> dict[str, str]:
    """Fetch several article bodies concurrently, keyed by URL."""
    if not urls:
        return {}

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: dict[str, str] = {}

    async with httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        follow_redirects=True,
        timeout=timeout,
    ) as client:

        async def worker(url: str) -> None:
            async with semaphore:
                host = httpx.URL(url).host
                parser = await _load_robots_parser(client, host)
                if not _robots_allows(url, parser):
                    logger.info("Skipping %s: robots.txt disallows it.", url)
                    return
                text = await fetch_article_text(client, url, timeout=timeout)
                if text:
                    results[url] = text
                    return
                if proxy_base:
                    proxy_text = await fetch_via_reader_proxy(client, url, proxy_base)
                    if proxy_text:
                        results[url] = proxy_text

        await asyncio.gather(*(worker(url) for url in urls))

    return results
