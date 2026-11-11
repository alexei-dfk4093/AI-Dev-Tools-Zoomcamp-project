from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class NewsArticle(BaseModel):
    id: str
    source: str | None
    published_at: str | None
    url: HttpUrl
    title: str
    summary: str | None
    summary_prompt_version: int = Field(default=0, exclude=True)
    article_content: str | None = Field(default=None, max_length=30000)
    summary_source: Literal["ai", "publisher", "unavailable"]
    importance: Literal["important", "other"]
    category: Literal["economic", "other"] = "economic"


class AffectedAsset(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    symbol: str | None = Field(default=None, max_length=20)
    kind: Literal["company", "etf", "index"]
    relationship: Literal["mentioned", "potential"]
    rationale: str = Field(min_length=1, max_length=300)


class ArticleMarketAssetsResponse(BaseModel):
    assets: list[AffectedAsset] = Field(max_length=12)


class ArticleImpact(BaseModel):
    direction: Literal["positive", "neutral", "negative"]
    summary: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=800)


class ArticleInsightsResponse(BaseModel):
    assets: list[AffectedAsset] = Field(max_length=12)
    impact: ArticleImpact
    suggested_questions: list[str] = Field(max_length=6)
    research_notes: str | None = Field(default=None, max_length=600)


class NewsStatusResponse(BaseModel):
    provider: str
    article_count: int
    newest_published_at: str | None = None
    data_age_seconds: int | None = None
    last_refresh_at: str | None = None
    refresh_interval_seconds: int
    is_stale: bool
