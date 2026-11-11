import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings, get_settings, is_free_openrouter_model
from app.schemas.discussion import (
    DiscussionModelOption,
    DiscussionModelsResponse,
    DiscussionRequest,
    DiscussionResponse,
)
from app.services.discussion_service import (
    DiscussionProviderError,
    generate_reply,
    get_social_reply,
)

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL_LABELS = {
    "openrouter/free": "OpenRouter Free Models",
    "thinkingmachines/inkling-2-small:free": "Inkling 2 Small (free)",
    "liquid/lfm-3-1.7b:free": "LFM3 1.7B (free)",
    "recursive/flint-v1.0:free": "Flint (free)",
    "xingchen-agi/xing4.0-29b-a4b:free": "Xing4.0 29B (free)",
    "nvidia/nemotron-3.5-super-vl:free": "Nemotron 3.5 Super VL (free)",
    "dots-studio/dots-3-note-preview:free": "Dots3-Note Preview (free)",
    "liquid/lfm-2.5-2.6b:free": "LFM2.5 2.6B (free)",
    "nvidia/nemotron-3.5-lightning:free": "Nemotron 3.5 Lightning (free)",
    "cohere/north-mini-code:free": "North Mini Code (free)",
    "nvidia/nemotron-3-ultra-550b-a55b:free": "Nemotron 3 Ultra (free)",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": (
        "Nemotron 3 Nano Omni (free)"
    ),
    "google/gemma-4-26b-a4b-it:free": "Gemma 4 26B (free)",
    "google/gemma-4-31b-it:free": "Gemma 4 31B (free)",
}


def _model_label(model: str) -> str:
    return MODEL_LABELS.get(model, f"{model} (free)")


def _available_free_models(settings: Settings) -> tuple[str, ...]:
    models = tuple(
        model for model in settings.openrouter_models if is_free_openrouter_model(model)
    )
    return models or ("openrouter/free",)


@router.get("/models", response_model=DiscussionModelsResponse)
async def get_discussion_models(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DiscussionModelsResponse:
    available_models = _available_free_models(settings)
    default_model = (
        settings.openrouter_model
        if settings.openrouter_model in available_models
        else available_models[0]
    )
    return DiscussionModelsResponse(
        models=[
            DiscussionModelOption(
                id=model,
                label=_model_label(model),
            )
            for model in available_models
        ],
        default_model=default_model,
    )


@router.post("", response_model=DiscussionResponse)
async def discuss_about_headline(
    request: DiscussionRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DiscussionResponse:
    social_reply = get_social_reply(request.message)
    if social_reply:
        return DiscussionResponse(reply=social_reply)

    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI discussions are not configured. Set OPENROUTER_API_KEY in the project .env file.",
        )

    available_models = _available_free_models(settings)
    if request.model is not None and (
        not is_free_openrouter_model(request.model)
        or request.model not in available_models
    ):
        raise HTTPException(
            status_code=422,
            detail="Choose a free model from the discussion model list.",
        )
    selected_model = (
        request.model
        if request.model in available_models
        else (
            settings.openrouter_model
            if settings.openrouter_model in available_models
            else available_models[0]
        )
    )
    request = request.model_copy(update={"model": selected_model})

    try:
        reply = await generate_reply(settings, request)
    except DiscussionProviderError as exc:
        logger.warning("Headline discussion could not be completed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return DiscussionResponse(reply=reply)
