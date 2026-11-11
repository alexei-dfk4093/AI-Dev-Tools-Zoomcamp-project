from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

class DiscussionArticle(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    source: str | None = Field(default=None, max_length=200)
    published_at: str | None = Field(default=None, max_length=64)
    url: HttpUrl
    summary: str | None = Field(default=None, max_length=2500)
    article_content: str | None = Field(default=None, max_length=30000)


class DiscussionTurn(BaseModel):
    speaker: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class DiscussionRequest(BaseModel):
    article: DiscussionArticle
    message: str = Field(min_length=1, max_length=2000)
    history: list[DiscussionTurn] = Field(default_factory=list, max_length=12)
    model: str | None = Field(default=None, min_length=1, max_length=120)


class DiscussionResponse(BaseModel):
    reply: str


class DiscussionModelOption(BaseModel):
    id: str
    label: str


class DiscussionModelsResponse(BaseModel):
    models: list[DiscussionModelOption]
    default_model: str
