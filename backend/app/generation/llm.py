"""Thin wrapper over any OpenAI-compatible chat endpoint (Groq, Ollama, vLLM, OpenAI...)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from openai import OpenAI

from app.config import get_settings


class LLMNotConfigured(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


@lru_cache
def _client() -> OpenAI:
    s = get_settings()
    if not s.llm_api_key and "localhost" not in s.llm_base_url:
        raise LLMNotConfigured(
            "LLM_API_KEY is not set. Get a free key at https://console.groq.com/keys "
            "and put it in backend/.env"
        )
    # max_retries handles free-tier 429 rate limits with exponential backoff.
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key or "ollama", max_retries=5, timeout=60)


def chat(
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> LLMResult:
    s = get_settings()
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if s.llm_reasoning_effort:
        kwargs["reasoning_effort"] = s.llm_reasoning_effort
    resp = _client().chat.completions.create(
        model=s.llm_model,
        messages=messages,
        temperature=s.llm_temperature if temperature is None else temperature,
        max_tokens=max_tokens or s.llm_max_tokens,
        **kwargs,
    )
    usage = resp.usage
    return LLMResult(
        text=(resp.choices[0].message.content or "").strip(),
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )
