# EcoMind backend

The first backend slice exposes a read-only economics news API:

- `GET /api/v1/news?limit=8` fetches English economics and macroeconomic headlines from NewsAPI.
- Non-economics content (sports, entertainment, gambling, unrelated local stories) is filtered out so only economics intelligence is served.
- Each article includes an `importance` label. The initial label is based on explicit policy, macroeconomic, and market-impact keywords in the headline and publisher description; it is a topic filter, not an investment recommendation or prediction.
- If an OpenRouter key is configured, article summaries use the supplied headline, publisher description, and the full article body retrieved from the publisher's own page. Summaries add concrete reported details and context instead of restating the headline; they stay shorter when the source provides little detail rather than inventing information.
- Article bodies are retrieved for free: the publisher page is fetched directly and the text is extracted from JSON-LD metadata, `<article>`/`<main>` scopes, or CMS content containers. When no body could be retrieved, the model reads the publisher's page itself with an OpenRouter web-fetch tool, so a blocked site still gets an accurate summary. No paid service is involved, `robots.txt` is respected, and redirects to a different article are rejected so a summary can never be built from an unrelated story. Roughly 85% of reachable publisher pages yield usable body text; pages behind a hard bot block keep the publisher description.
- A background task backfills bodies for articles stored before this was enabled and re-summarizes them with the recovered text.
- When AI summaries cannot be generated, the API explicitly marks publisher descriptions or unavailable summaries rather than inventing content.
- News-feed summaries are AI-generated extended summaries when OpenRouter is configured; existing cached publisher descriptions are upgraded when possible. The discussion page requests `GET /api/v1/news/{article_id}` for provider-supplied article text and sends that text plus the original article URL to the selected model.
- `GET /api/v1/news/{article_id}/insights` analyses the article with the configured OpenRouter model and returns three things for the discussion window: the companies and traded symbols connected to the story (not only the company named in the headline, but also suppliers, customers, competitors, lenders and sector peers), the directional effect the article reports (`positive`, `neutral` or `negative`) with its stated reasons, and suggested questions that can be answered from that article's own content. Results are cached per article and prompt version. A company mention is not a verified market effect or price prediction, uncertain symbols are omitted, and the direction describes what the article reports rather than a forecast.
- The analysis researches before it answers: the model fetches the publisher's own page (which succeeds on sites that block direct requests) and searches for corroboration - the company's statement, a filing, or other coverage of the same event. It must attribute every claim to the article or to a source it read, ignore results about unrelated events or other periods, and record what it verified in `research_notes`, which the discussion window shows as a "Verified online" note.
- `POST /api/v1/discussions` accepts an article link and available article text, a question, and recent conversation turns, then returns one integrated response that weighs relevant optimistic, neutral, and cautious considerations using the configured OpenRouter model. When a cached article analysis exists, the reply covers the other companies connected to the story and states the article's direction plainly. The assistant reads the publisher's page with a web-fetch tool restricted to that domain and searches the wider web to corroborate the event, and it must name the source of a web finding and say so when the sources disagree. Article-related questions enable OpenRouter's beta `openrouter:web_fetch` tool, restricted to the publisher's domain, so the model can retrieve the page; if direct retrieval fails, it can use one domain-restricted web search. The model must disclose when a paywall, blocked page, or excerpt prevents it from reading the full article. Web search may incur additional OpenRouter charges.
- If an OpenRouter request fails, the discussion API reports model-access, credit, or rate-limit guidance instead of a generic unavailable message. A listed model may still be inaccessible for a particular account or temporarily at capacity.
- `GET /api/v1/discussions/models` returns free-only choices for the discussion composer. `OPENROUTER_MODELS` can select from the `openrouter/free` router and exact `:free` model IDs; paid IDs are ignored, and only free model IDs can be submitted to the discussion endpoint.
- `GET /health` reports whether the local API process is responsive.

The news feed headline opens a discussion page for that specific story. The original publisher link remains available from the discussion page. Web retrieval only works for public HTTPS pages accessible to OpenRouter; publisher restrictions may prevent full-text retrieval. In that case, provide the article through a licensed API/feed or paste the text. Discussions require `OPENROUTER_API_KEY`; without it, the API returns a configuration error rather than showing generated or placeholder replies.

## Setup on Windows

From the project root, create and activate a virtual environment and install the backend dependencies:

```powershell
python -m venv backend\.venv
.\backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

Set `NEWS_API_KEY` and `OPENROUTER_API_KEY` in the project-root `.env` file. `OPENROUTER_MODEL` is optional and defaults to OpenRouter's `openrouter/free` router, which chooses an available free model that supports the request's features. The discussion picker includes current zero-cost `:free` model variants and the free router; paid model IDs are ignored in `OPENROUTER_MODEL` and `OPENROUTER_MODELS`. To configure a specific free model, use its exact `:free` ID from OpenRouter's catalog. Availability of individual free variants can change, so the router is the recommended default. Keep `.env` private; never expose API keys to the frontend.

Optional settings for the news feed:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEWS_REFRESH_INTERVAL_SECONDS` | `1800` | How often the feed is refreshed from the provider. |
| `ARTICLE_CONTENT_FETCH_ENABLED` | `true` | Retrieve full article bodies from the publisher page. |
| `ARTICLE_CONTENT_FETCH_CONCURRENCY` | `5` | Parallel page fetches per cycle. |
| `ARTICLE_CONTENT_FETCH_PER_CYCLE` | `12` | Articles enriched per cycle. |
| `ARTICLE_READER_PROXY_URL` | *(empty)* | Optional reader proxy prefix (for example `https://r.jina.ai/`) used only when a direct fetch fails. Free proxies without a key are rate limited, so this stays off by default. |
| `OPENROUTER_WEB_TOOLS_ENABLED` | `true` | Let the model read and search the web for article analysis and discussion answers. |
| `OPENROUTER_DAILY_CALL_BUDGET` | `40` | Maximum AI provider calls per day from this process, so a free tier is not spent in a burst. |

**Provider allowance.** Free models have OpenRouter rate and availability
limits. The app keeps its own daily budget and pauses AI calls for an hour
when OpenRouter explicitly reports that the free-model allowance is exhausted.
A credits-required error for a paid model does not block later requests to
free models. Web fetch and web search can be billed separately by OpenRouter;
disable `OPENROUTER_WEB_TOOLS_ENABLED` if you need to avoid those tools.

Start the API from the project root:

```powershell
.\start.ps1
```

This one command also starts the frontend and opens the app; see the root
[README](../README.md#run-locally). To run the backend alone:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

The Vite development server proxies `/api` requests to this API. Start it separately with `npm run dev` from `frontend`.

## Tests

One command runs the backend and frontend suites together from the project
root: `.\run-tests.ps1` (see the root [README](../README.md#tests)). The
backend suite alone:

```powershell
python -m pip install -r backend\requirements.txt
python -m pytest backend\tests
```

Tests use mocked API responses and do not send requests to NewsAPI or OpenRouter.
