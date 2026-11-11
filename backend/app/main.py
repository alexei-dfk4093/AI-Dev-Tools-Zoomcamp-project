import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.discussions import router as discussions_router
from app.api.routes.news import router as news_router
from app.core.config import get_settings
from app.repositories import news_repository
from app.repositories.news_repository import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# How often the background task retrieves full bodies for stored articles.
CONTENT_BACKFILL_INTERVAL_SECONDS = 600


async def _prefetch_news(settings) -> None:
    """Warm up the SQLite cache on startup so the first user request is fast."""
    from app.services.news_service import is_cache_stale, refresh_articles, NewsProviderError

    try:
        if not is_cache_stale(settings):
            total = news_repository.count_articles()
            logger.info(
                "Startup prefetch skipped — %d articles cached and still fresh.", total
            )
            return
        logger.info("Startup prefetch: refreshing news cache…")
        saved = await refresh_articles(settings, limit=60)
        logger.info("Startup prefetch complete: %d articles saved.", saved)
    except NewsProviderError as exc:
        logger.warning("Startup prefetch failed (non-fatal): %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Startup prefetch raised unexpected error (non-fatal): %s", exc)


async def _refresh_news_loop(settings, interval_seconds: int) -> None:
    """Keep the stored feed fresh so the site never serves a frozen snapshot."""
    from app.services.news_service import NewsProviderError, refresh_articles

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            saved = await refresh_articles(settings, limit=60)
            if saved:
                logger.info("Background refresh stored %d new articles.", saved)
        except NewsProviderError as exc:
            logger.warning("Background refresh failed (non-fatal): %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Background refresh raised unexpected error (non-fatal): %s", exc)


async def _backfill_content_loop(settings, interval_seconds: int) -> None:
    """Retrieve full article bodies for stored articles that lack them."""
    from app.services.news_service import backfill_article_content

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            filled = await backfill_article_content(settings)
            if filled:
                logger.info("Content backfill enriched %d articles.", filled)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Content backfill raised unexpected error (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    settings = get_settings()
    if not settings.news_api_key:
        raise RuntimeError("NEWS_API_KEY must be configured in the project .env file.")
    if not settings.openrouter_api_key:
        logger.warning(
            "OPENROUTER_API_KEY is not configured; publisher descriptions will be used."
        )
    # Keep a reference so the fire-and-forget warmup task is not garbage collected.
    app.state.prefetch_task = asyncio.create_task(_prefetch_news(settings))
    app.state.refresh_task = asyncio.create_task(
        _refresh_news_loop(settings, settings.news_refresh_interval_seconds)
    )
    app.state.backfill_task = asyncio.create_task(
        _backfill_content_loop(settings, CONTENT_BACKFILL_INTERVAL_SECONDS)
    )
    try:
        yield
    finally:
        for task_name in ("prefetch_task", "refresh_task", "backfill_task"):
            task = getattr(app.state, task_name, None)
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


app = FastAPI(
    title="EcoMind News API",
    description="Financial news headlines with concise, source-grounded summaries.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(news_router, prefix="/api/v1/news", tags=["news"])
app.include_router(
    discussions_router,
    prefix="/api/v1/discussions",
    tags=["discussions"],
)
