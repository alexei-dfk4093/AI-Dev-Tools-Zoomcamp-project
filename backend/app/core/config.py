import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_OPENROUTER_MODELS = (
    "openrouter/free",
    "thinkingmachines/inkling-2-small:free",
    "liquid/lfm-3-1.7b:free",
    "recursive/flint-v1.0:free",
    "xingchen-agi/xing4.0-29b-a4b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "dots-studio/dots-3-note-preview:free",
    "liquid/lfm-2.5-2.6b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
)
DEFAULT_OPENROUTER_MODEL = "openrouter/free"


def is_free_openrouter_model(model: str) -> bool:
    return model == "openrouter/free" or model.endswith(":free")

# How often the stored feed is refreshed from the upstream news provider.
# Provider plans cap daily requests, so the default keeps refreshes well
# inside a typical free-tier allowance.
DEFAULT_NEWS_REFRESH_INTERVAL_SECONDS = 1800

# Full article bodies are retrieved from the publisher's own page so the
# summarizer can ground its output in the story, not just the headline.
DEFAULT_ARTICLE_FETCH_CONCURRENCY = 5
DEFAULT_ARTICLE_FETCH_PER_CYCLE = 12

# OpenRouter's no-credit tier allows a small number of requests per day, so
# the process keeps its own budget instead of spending the allowance in a
# burst.
DEFAULT_OPENROUTER_DAILY_CALL_BUDGET = 40


@dataclass(frozen=True)
class Settings:
    news_api_key: str
    openrouter_api_key: str | None
    openrouter_model: str
    openrouter_models: tuple[str, ...] = DEFAULT_OPENROUTER_MODELS
    news_refresh_interval_seconds: int = DEFAULT_NEWS_REFRESH_INTERVAL_SECONDS
    article_content_fetch_enabled: bool = True
    article_content_fetch_concurrency: int = DEFAULT_ARTICLE_FETCH_CONCURRENCY
    article_content_fetch_per_cycle: int = DEFAULT_ARTICLE_FETCH_PER_CYCLE
    article_reader_proxy_url: str = ""
    openrouter_web_tools_enabled: bool = True
    openrouter_daily_call_budget: int = DEFAULT_OPENROUTER_DAILY_CALL_BUDGET


def get_settings() -> Settings:
    news_api_key = os.getenv("NEWS_API_KEY", "").strip()
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip() or None
    configured_model = os.getenv(
        "OPENROUTER_MODEL",
        DEFAULT_OPENROUTER_MODEL,
    ).strip()
    if is_free_openrouter_model(configured_model):
        openrouter_model = configured_model
    else:
        logger.warning(
            "Ignoring paid OPENROUTER_MODEL %s; using the free model router.",
            configured_model,
        )
        openrouter_model = DEFAULT_OPENROUTER_MODEL
    news_refresh_interval_seconds = _read_refresh_interval()
    article_content_fetch_enabled = _read_bool(
        "ARTICLE_CONTENT_FETCH_ENABLED",
        default=True,
    )
    article_content_fetch_concurrency = _read_int(
        "ARTICLE_CONTENT_FETCH_CONCURRENCY",
        DEFAULT_ARTICLE_FETCH_CONCURRENCY,
    )
    article_content_fetch_per_cycle = _read_int(
        "ARTICLE_CONTENT_FETCH_PER_CYCLE",
        DEFAULT_ARTICLE_FETCH_PER_CYCLE,
    )
    article_reader_proxy_url = os.getenv("ARTICLE_READER_PROXY_URL", "").strip()
    openrouter_web_tools_enabled = _read_bool(
        "OPENROUTER_WEB_TOOLS_ENABLED",
        default=True,
    )
    openrouter_daily_call_budget = _read_int(
        "OPENROUTER_DAILY_CALL_BUDGET",
        DEFAULT_OPENROUTER_DAILY_CALL_BUDGET,
    )
    configured_models = os.getenv("OPENROUTER_MODELS", "").strip()
    configured_openrouter_models = tuple(
        dict.fromkeys(
            model.strip()
            for model in configured_models.split(",")
            if model.strip()
        )
    ) if configured_models else DEFAULT_OPENROUTER_MODELS
    paid_models = tuple(
        model
        for model in configured_openrouter_models
        if not is_free_openrouter_model(model)
    )
    if paid_models:
        logger.warning(
            "Ignoring paid models in OPENROUTER_MODELS: %s",
            ", ".join(paid_models),
        )
    openrouter_models = tuple(
        model
        for model in configured_openrouter_models
        if is_free_openrouter_model(model)
    )
    if not openrouter_models:
        openrouter_models = DEFAULT_OPENROUTER_MODELS
    if openrouter_model and openrouter_model not in openrouter_models:
        openrouter_models = (openrouter_model, *openrouter_models)

    return Settings(
        news_api_key=news_api_key,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
        openrouter_models=openrouter_models,
        news_refresh_interval_seconds=news_refresh_interval_seconds,
        article_content_fetch_enabled=article_content_fetch_enabled,
        article_content_fetch_concurrency=article_content_fetch_concurrency,
        article_content_fetch_per_cycle=article_content_fetch_per_cycle,
        article_reader_proxy_url=article_reader_proxy_url,
        openrouter_web_tools_enabled=openrouter_web_tools_enabled,
        openrouter_daily_call_budget=openrouter_daily_call_budget,
    )


def _read_refresh_interval() -> int:
    raw_value = os.getenv("NEWS_REFRESH_INTERVAL_SECONDS", "").strip()
    if not raw_value:
        return DEFAULT_NEWS_REFRESH_INTERVAL_SECONDS
    try:
        parsed = int(raw_value)
    except ValueError:
        return DEFAULT_NEWS_REFRESH_INTERVAL_SECONDS
    return parsed if parsed > 0 else DEFAULT_NEWS_REFRESH_INTERVAL_SECONDS


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, "").strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
