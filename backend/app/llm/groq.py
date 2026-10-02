"""Groq chat completions (OpenAI-compatible), traced as Langfuse generations and counted in Prometheus.

Rate limits are waited out, not failed on: the 429 tells us how long to wait ("try again in 7.5s"),
and tokens-per-minute limits often need longer than a fixed backoff.
"""

import asyncio
import json
import re

import httpx

from app.config import settings
from app.observability.metrics import label, llm_cost, llm_duration, llm_requests, llm_tokens
from app.observability.tracing import observe

MAX_RETRY_WAIT_S = 60.0
_client: httpx.AsyncClient | None = None


class LlmError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status, self.code = status, code


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=settings.groq_base_url.rstrip("/"), timeout=settings.llm_timeout_ms / 1000)
    return _client


def _retry_delay(res: httpx.Response | None, payload: dict, attempt: int) -> float:
    header = res.headers.get("retry-after") if res is not None else None
    hint = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str((payload.get("error") or {}).get("message", "")), re.I)
    seconds = float(header) if header and header.replace(".", "", 1).isdigit() else (int(hint.group(1) or 0) * 60 + float(hint.group(2))) if hint else None
    return min(seconds + 0.25, MAX_RETRY_WAIT_S) if seconds is not None else 0.5 * 2**attempt


async def _post(body: dict, max_retries: int) -> dict:
    if not settings.groq_api_key:
        raise LlmError("GROQ_API_KEY is not set.", code="missing_api_key")
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    for attempt in range(max_retries + 1):
        try:
            res = await _http().post("/chat/completions", json=body, headers=headers)
        except httpx.TimeoutException as error:
            if attempt < max_retries:
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            raise LlmError(f"Groq timed out after {settings.llm_timeout_ms} ms", code="timeout") from error
        except httpx.HTTPError as error:
            if attempt < max_retries:
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            raise LlmError(f"Groq unreachable: {error}", code="network") from error

        if res.is_success:
            return res.json()
        try:
            payload = res.json()
        except ValueError:
            payload = {}
        error = payload.get("error") or {}
        if (res.status_code == 429 or res.status_code >= 500) and attempt < max_retries:
            await asyncio.sleep(_retry_delay(res, payload, attempt))
            continue
        raise LlmError(f"Groq {res.status_code}: {error.get('message', res.reason_phrase)}", status=res.status_code, code=error.get("code") or error.get("type"))
    raise LlmError("unreachable")


def _status_label(error: LlmError) -> str:
    return "rate_limited" if error.status == 429 else "timeout" if error.code == "timeout" else "error"


async def chat(
    *,
    purpose: str,
    messages: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    reasoning_effort: str | None = None,
    max_retries: int | None = None,
) -> dict:
    model = model or settings.groq_model
    temperature = settings.llm_temperature if temperature is None else temperature
    max_tokens = max_tokens or settings.llm_max_tokens
    body = {"model": model, "messages": messages, "temperature": temperature, "max_completion_tokens": max_tokens}
    if response_format:
        body["response_format"] = response_format
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    parameters = {"temperature": temperature, "max_completion_tokens": max_tokens, **({"reasoning_effort": reasoning_effort} if reasoning_effort else {})}

    with observe(f"llm:{purpose}", as_type="generation", model=model, input=messages, model_parameters=parameters) as generation:
        histogram = llm_duration.labels(**label(model=model, purpose=purpose))
        with histogram.time():
            try:
                data = await _post(body, settings.llm_max_retries if max_retries is None else max_retries)
            except LlmError as error:
                llm_requests.labels(**label(model=model, purpose=purpose, status=_status_label(error))).inc()
                generation.update(level="ERROR", status_message=str(error))
                raise

        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        prompt_tokens, completion_tokens = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        price_in, price_out = (settings.llm_prices_per_million.get(model) or [0, 0])[:2]
        cost = {"input": prompt_tokens * price_in / 1e6, "output": completion_tokens * price_out / 1e6}

        llm_requests.labels(**label(model=model, purpose=purpose, status="ok")).inc()
        llm_tokens.labels(**label(model=model, purpose=purpose, type="prompt")).inc(prompt_tokens)
        llm_tokens.labels(**label(model=model, purpose=purpose, type="completion")).inc(completion_tokens)
        llm_cost.labels(**label(model=model, purpose=purpose)).inc(cost["input"] + cost["output"])
        generation.update(output=content, usage_details={"input": prompt_tokens, "output": completion_tokens}, cost_details=cost)
        return {"content": content, "usage": usage, "model": data.get("model", model)}


async def chat_json(**request) -> dict:
    """chat() that parses a JSON reply; one retry if the model returns malformed JSON."""
    for attempt in range(2):
        try:
            reply = await chat(**request)
            return {**reply, "json": json.loads(reply["content"])}
        except (json.JSONDecodeError, LlmError) as error:
            malformed = isinstance(error, json.JSONDecodeError) or getattr(error, "code", None) == "json_validate_failed"
            if not malformed or attempt == 1:
                raise
    raise LlmError("unreachable")
