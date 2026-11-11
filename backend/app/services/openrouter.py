"""Shared OpenRouter access.

Every service that talks to OpenRouter goes through this module so the
request shape, the tool handling and the response parsing stay in one place.

Two endpoints are used:

- ``/chat/completions`` for plain, cheap completions.
- ``/responses`` for requests that need OpenRouter's web tools
  (``openrouter:web_fetch`` and ``openrouter:web_search``), because the tool
  calls are executed by OpenRouter on that endpoint.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_RESPONSES_API_URL = "https://openrouter.ai/api/v1/responses"

REQUEST_TIMEOUT_SECONDS = 90.0

# The amount of fetched page text sent to the model. OpenRouter API keys can
# carry a prompt-token limit, and a large fetched page can exceed it, so the
# budget is reduced and the request retried when that happens.
FETCH_TOKEN_BUDGETS = (6000, 3000, 2000, 1200)

# OpenRouter's no-credit tier allows a small number of requests per day.
# The process keeps its own budget so the app cannot burn the allowance in a
# burst and then fail for the rest of the day.
_daily_calls = 0
_daily_call_date: date | None = None
_quota_blocked_until: datetime | None = None


class OpenRouterError(Exception):
    """Raised when OpenRouter cannot produce a usable response."""


@dataclass
class AssistantResponse:
    """The assistant text plus the web tools that were used to produce it."""

    text: str
    tools_used: list[str] = field(default_factory=list)

    @property
    def used_web(self) -> bool:
        return bool(self.tools_used)


def extract_json_payload(text: str) -> dict:
    """Parse a JSON object from a model response.

    Models occasionally wrap JSON in a code fence or prefix it with the word
    "json", so the first balanced object in the text is used.
    """
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*", "", candidate).strip()
        candidate = re.sub(r"```$", "", candidate).strip()

    start = candidate.find("{")
    if start == -1:
        raise ValueError("The response contains no JSON object.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(candidate)):
        character = candidate[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                payload = json.loads(candidate[start : index + 1])
                if not isinstance(payload, dict):
                    raise ValueError("The JSON payload must be an object.")
                return payload

    raise ValueError("The JSON payload is incomplete.")


def _headers(settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "EcoMind",
    }


async def request_assistant_text(
    settings,
    *,
    model: str,
    instructions: str,
    input_text: str = "",
    input_items: list[dict] | None = None,
    tools: list[dict] | None = None,
    max_output_tokens: int = 1200,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> AssistantResponse:
    """Ask a model for a reply, optionally letting it use the web tools."""
    if not settings.openrouter_api_key:
        raise OpenRouterError("No OpenRouter API key is configured.")

    now = datetime.now(timezone.utc)
    _budget_state(now)
    if _quota_is_blocked(now):
        raise OpenRouterError(
            "The AI provider's request allowance is temporarily exhausted. "
            "The app has paused AI calls for the next hour so the remaining "
            "allowance is not wasted; try again later or add credits to the "
            "OpenRouter account."
        )
    daily_budget = getattr(settings, "openrouter_daily_call_budget", 0)
    if daily_budget and _daily_calls >= daily_budget:
        raise OpenRouterError(
            f"The daily AI request budget of {daily_budget} calls is used up. "
            "Add credits to the OpenRouter account or raise "
            "OPENROUTER_DAILY_CALL_BUDGET to continue."
        )

    if input_items is None:
        input_items = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": input_text}],
            }
        ]

    payload: dict = {
        "model": model,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "instructions": instructions,
        "input": input_items,
    }

    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if json_mode:
        payload["text"] = {"format": {"type": "json_object"}}

    attempts: list[list[dict] | None] = [tools]
    if tools:
        for budget in FETCH_TOKEN_BUDGETS[1:]:
            attempts.append(_with_fetch_budget(tools, budget))
        attempts.append(_without_fetch(tools))
        attempts.append(None)

    last_error: OpenRouterError | None = None
    for attempt_tools in attempts:
        attempt_payload = dict(payload)
        if attempt_tools:
            attempt_payload["tools"] = attempt_tools
            attempt_payload["tool_choice"] = "auto"
        else:
            attempt_payload.pop("tools", None)
            attempt_payload.pop("tool_choice", None)

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    OPENROUTER_RESPONSES_API_URL,
                    json=attempt_payload,
                    headers=_headers(settings),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise OpenRouterError("The request to the AI provider timed out.") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(
                "The AI provider could not be reached."
            ) from exc
        except httpx.HTTPStatusError as exc:
            provider_detail = _provider_error_detail(exc.response)
            logger.warning(
                "OpenRouter request for %s returned HTTP %s",
                model,
                exc.response.status_code,
            )
            error = OpenRouterError(
                _http_error_message(
                    exc.response.status_code,
                    model,
                    provider_detail,
                )
            )
            last_error = error
            if _is_prompt_limit_error(str(error)):
                continue
            if (
                exc.response.status_code == 402
                and _is_free_tier_quota_error(provider_detail)
            ):
                _block_quota(now)
            raise error from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise OpenRouterError(
                "The AI provider returned an invalid response."
            ) from exc

        _note_call(now)
        return _parse_responses_output(data)

    raise last_error or OpenRouterError("The AI provider returned an invalid response.")


def _start_of_day(now: datetime) -> date:
    return now.date()


def _budget_state(now: datetime) -> None:
    """Reset the daily counters when the UTC day changes."""
    global _daily_calls, _daily_call_date
    today = _start_of_day(now)
    if _daily_call_date != today:
        _daily_calls = 0
        _daily_call_date = today


def _note_call(now: datetime) -> None:
    global _daily_calls
    _budget_state(now)
    _daily_calls += 1


def reset_request_budget() -> None:
    """Reset the daily counters and any quota pause (used by tests)."""
    global _daily_calls, _daily_call_date, _quota_blocked_until
    _daily_calls = 0
    _daily_call_date = None
    _quota_blocked_until = None


def _quota_is_blocked(now: datetime) -> bool:
    return _quota_blocked_until is not None and now < _quota_blocked_until


def _block_quota(now: datetime, minutes: int = 60) -> None:
    global _quota_blocked_until
    _quota_blocked_until = now + timedelta(minutes=minutes)
    logger.warning(
        "Pausing AI requests for %d minutes after a provider quota failure.",
        minutes,
    )


def _provider_error_detail(response: httpx.Response) -> str:
    """Extract the provider's own error text, when it sends one."""
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - the body may not be JSON
        return ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"].strip()
        if isinstance(error, str):
            return error.strip()
    return ""


def _is_free_tier_quota_error(detail: str) -> bool:
    lowered = detail.casefold()
    return "free" in lowered and any(
        marker in lowered
        for marker in ("limit", "quota", "allowance", "exhausted", "exceeded")
    )


def _http_error_message(status_code: int, model: str, detail: str = "") -> str:
    suffix = f" Provider detail: {detail}" if detail else ""
    if status_code == 402 and "prompt tokens limit" in detail.lower():
        return (
            "The request exceeded the OpenRouter key's prompt-token limit. "
            "Raise the limit on the API key or use a shorter article page."
            f"{suffix}"
        )
    if status_code == 404:
        return (
            f"OpenRouter could not serve {model}. The model may be unavailable "
            "or not enabled for your account; choose another model or check "
            "OpenRouter model access."
            f"{suffix}"
        )
    if status_code == 402:
        if _is_free_tier_quota_error(detail):
            return (
                "OpenRouter's free-model allowance is exhausted. Wait and "
                "retry, or add credits to your account."
                f"{suffix}"
            )
        return (
            f"OpenRouter requires credits to use {model}. Select OpenRouter "
            f"Free Models or another model marked free, or check your balance."
            f"{suffix}"
        )
    if status_code == 429:
        return (
            f"OpenRouter is rate-limiting {model} or its provider is at capacity. "
            "Wait and retry, or choose another model."
        )
    if status_code in (401, 403):
        return (
            f"OpenRouter denied access to {model}. Check the API key and "
            "model permissions."
        )
    return (
        f"OpenRouter returned HTTP {status_code} for {model}. "
        "Try another model or retry."
    )


def _parse_responses_output(data: object) -> AssistantResponse:
    if not isinstance(data, dict) or not isinstance(data.get("output"), list):
        raise OpenRouterError("The AI provider returned an invalid response.")

    text_parts: list[str] = []
    tools_used: list[str] = []

    for output_item in data["output"]:
        if not isinstance(output_item, dict):
            continue
        item_type = output_item.get("type")
        if isinstance(item_type, str) and item_type.startswith("openrouter:"):
            tools_used.append(item_type)
            continue
        if item_type != "message" or output_item.get("role") != "assistant":
            continue
        content_items = output_item.get("content")
        if not isinstance(content_items, list):
            continue
        text_parts.extend(
            item["text"]
            for item in content_items
            if isinstance(item, dict)
            and item.get("type") == "output_text"
            and isinstance(item.get("text"), str)
        )

    text = "\n".join(text_parts).strip()
    if not text:
        raise OpenRouterError("The AI provider returned an empty response.")

    return AssistantResponse(text=text, tools_used=tools_used)


def _with_fetch_budget(tools: list[dict], budget: int) -> list[dict]:
    """Return the tools with a smaller fetch budget for the fetched page."""
    scaled: list[dict] = []
    for tool in tools:
        if tool.get("type") == "openrouter:web_fetch":
            parameters = dict(tool.get("parameters", {}))
            parameters["max_content_tokens"] = budget
            scaled.append({**tool, "parameters": parameters})
        else:
            scaled.append(tool)
    return scaled


def _without_fetch(tools: list[dict]) -> list[dict]:
    """Return the tools with the page fetch removed, keeping web search."""
    return [tool for tool in tools if tool.get("type") != "openrouter:web_fetch"]


def _is_prompt_limit_error(message: str) -> bool:
    lowered = (message or "").lower()
    return "prompt tokens limit" in lowered or "context length" in lowered


def web_tools(
    fetch_domains: list[str] | None = None,
    allow_search: bool = True,
    max_fetch_uses: int = 1,
    max_search_uses: int = 2,
) -> list[dict]:
    """Build the OpenRouter web tool definitions for a request."""
    tools: list[dict] = []

    if fetch_domains:
        tools.append(
            {
                "type": "openrouter:web_fetch",
                "parameters": {
                    "engine": "openrouter",
                    "max_uses": max_fetch_uses,
                    "max_content_tokens": 12000,
                    "allowed_domains": fetch_domains,
                },
            }
        )

    if allow_search:
        # Search is deliberately not limited to the publisher: the model may
        # need an official statement or other coverage of the same event.
        search_parameters: dict = {
            "engine": "exa",
            "max_uses": max_search_uses,
            "max_results": 3,
            "max_total_results": 3,
            "search_context_size": "medium",
        }
        tools.append(
            {
                "type": "openrouter:web_search",
                "parameters": search_parameters,
            }
        )

    return tools
