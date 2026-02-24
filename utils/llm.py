"""
OpenAI LLM helpers — shared across all activities.
"""

from __future__ import annotations

import json
import logging
import time
from openai import OpenAI, RateLimitError

import config

log = logging.getLogger(__name__)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


MAX_RETRIES = 5
BASE_DELAY = 10  # seconds


def chat(
    system: str,
    user: str,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """Send a chat completion request and return the assistant message.
    
    Retries up to MAX_RETRIES times on rate limit (429) errors with
    exponential backoff.
    """
    client = get_client()
    kwargs: dict = {
        "model": model or config.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except RateLimitError as e:
            delay = BASE_DELAY * (2 ** attempt)
            log.warning(
                "Rate limited (attempt %d/%d), retrying in %ds: %s",
                attempt + 1, MAX_RETRIES, delay, e,
            )
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(delay)

    return ""  # unreachable but satisfies type checker


def chat_json(system: str, user: str, **kwargs) -> dict:
    """Send a chat completion and parse the JSON response."""
    raw = chat(system, user, json_mode=True, **kwargs)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.error("Failed to parse LLM JSON response: %s", raw[:500])
        return {"error": "JSON parse failed", "raw": raw[:2000]}
