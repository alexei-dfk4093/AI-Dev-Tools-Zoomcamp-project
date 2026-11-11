import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import ValidationError

from app.repositories import news_repository
from app.core.config import Settings, get_settings
from app.schemas.news import (
    ArticleInsightsResponse,
    NewsArticle,
    NewsStatusResponse,
)
from app.services import news_service
from app.services.article_insights_service import (
    ARTICLE_INSIGHTS_PROMPT_VERSION,
    ArticleInsightsProviderError,
    build_article_insights,
)
from app.services.news_service import (
    NewsProviderError,
    get_or_fetch_articles,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/status", response_model=NewsStatusResponse)
async def get_news_status(
    settings: Settings = Depends(get_settings),
) -> NewsStatusResponse:
    if not settings.news_api_key:
        raise HTTPException(
            status_code=503,
            detail="News service is not configured. Set NEWS_API_KEY in the project .env file.",
        )

    return NewsStatusResponse(**news_service.get_news_status(settings))


@router.get("", response_model=list[NewsArticle])
async def get_news(
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    category: Annotated[str | None, Query()] = None,
    refresh: Annotated[bool, Query()] = False,
    settings: Settings = Depends(get_settings),
) -> list[NewsArticle]:
    if not settings.news_api_key:
        raise HTTPException(
            status_code=503,
            detail="News service is not configured. Set NEWS_API_KEY in the project .env file.",
        )

    try:
        return await get_or_fetch_articles(
            settings,
            limit=limit,
            offset=offset,
            category=category,
            force_refresh=refresh,
        )
    except NewsProviderError as exc:
        logger.warning("News request could not be completed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="News is temporarily unavailable. Please try again later.",
        ) from exc


@router.get("/{article_id}", response_model=NewsArticle)
async def get_news_article(
    article_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> NewsArticle:
    article = news_repository.get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="The requested article was not found.")
    return article


@router.get(
    "/{article_id}/insights",
    response_model=ArticleInsightsResponse,
)
async def get_article_insights(
    article_id: Annotated[str, Path(min_length=1, max_length=64)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ArticleInsightsResponse:
    article = news_repository.get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="The requested article was not found.")

    cached = news_repository.get_article_insights(
        article_id,
        ARTICLE_INSIGHTS_PROMPT_VERSION,
    )
    if cached is not None:
        try:
            return ArticleInsightsResponse.model_validate(cached)
        except ValidationError:
            logger.warning("Cached article insights for %s are invalid.", article_id)

    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI article analysis is not configured.",
        )

    try:
        insights = await build_article_insights(settings, article)
    except ArticleInsightsProviderError as exc:
        logger.warning("Article insights could not be produced: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    news_repository.save_article_insights(
        article_id,
        ARTICLE_INSIGHTS_PROMPT_VERSION,
        insights.model_dump(mode="json"),
    )
    return insights
