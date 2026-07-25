"""
Provider-agnostic LLM client. Owner: Track A.

complete_json() returns None on ANY failure (no key, timeout, rate limit, bad
JSON) so every caller has a defined non-LLM fallback path — never assume the
LLM is available.
"""

import json
from typing import Any

from backend.config import settings

_TIMEOUT_SECONDS = 10

# Cache SUCCESSFUL completions only, keyed on the exact (prompt, schema_hint)
# pair. Deliberately not a plain @lru_cache on the whole function: today's
# actual failure mode is transient rate-limiting (429s that clear up later),
# and caching a None failure would poison that exact query for the rest of
# the process — the one case this cache must never produce. Re-running the
# same query during demo rehearsal costs zero additional API/inference calls
# once it has succeeded once; free-tier quotas are small enough that repeated
# identical testing alone can exhaust them in one session.
_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_CACHE_MAXSIZE = 256


def complete_json(prompt: str, schema_hint: str = "") -> dict[str, Any] | None:
    cache_key = (prompt, schema_hint)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    result: dict[str, Any] | None = None
    try:
        if settings.llm_provider == "gemini" and settings.gemini_api_key:
            result = _complete_gemini(prompt, schema_hint)
        elif settings.llm_provider == "openai" and settings.openai_api_key:
            result = _complete_openai(prompt, schema_hint)
        elif settings.llm_provider == "groq" and settings.groq_api_key:
            result = _complete_groq(prompt, schema_hint)
        elif settings.llm_provider == "ollama":
            result = _complete_ollama(prompt, schema_hint)
    except Exception:
        result = None

    if result is not None:
        if len(_CACHE) >= _CACHE_MAXSIZE:
            _CACHE.pop(next(iter(_CACHE)))  # crude FIFO eviction, fine at this scale
        _CACHE[cache_key] = result

    return result


def _complete_gemini(prompt: str, schema_hint: str) -> dict[str, Any] | None:
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    # "latest" alias, not a dated version string — Google periodically retires
    # specific model versions (gemini-1.5-flash 404s now; gemini-2.0-flash has
    # zero free-tier quota on new accounts), so pinning to a version drifts out
    # of the free tier over time. The alias tracks whatever's current.
    model = genai.GenerativeModel("gemini-flash-latest")
    full_prompt = f"{prompt}\n\n{schema_hint}\nRespond with strict JSON only, no markdown fences."
    response = model.generate_content(
        full_prompt,
        generation_config={"response_mime_type": "application/json", "temperature": 0.0},
        request_options={"timeout": _TIMEOUT_SECONDS},
    )
    return json.loads(response.text)


def _complete_openai(prompt: str, schema_hint: str) -> dict[str, Any] | None:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, timeout=_TIMEOUT_SECONDS)
    full_prompt = f"{prompt}\n\n{schema_hint}"
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": full_prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    return json.loads(response.choices[0].message.content)


def _complete_groq(prompt: str, schema_hint: str) -> dict[str, Any] | None:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    full_prompt = f"{prompt}\n\n{schema_hint}\nRespond with strict JSON only, no markdown fences."
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": full_prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
        timeout=_TIMEOUT_SECONDS,
    )
    return json.loads(response.choices[0].message.content)


def _complete_ollama(prompt: str, schema_hint: str) -> dict[str, Any] | None:
    # Local, no API key. Uses Ollama's native /api/chat endpoint (not the
    # OpenAI-compatibility layer) — format="json" is Ollama's own documented
    # JSON-mode flag, simpler and more robust than routing through a
    # compatibility shim. `requests` is already a project dependency.
    import requests

    full_prompt = f"{prompt}\n\n{schema_hint}\nRespond with strict JSON only, no markdown fences."
    response = requests.post(
        f"{settings.ollama_base_url}/api/chat",
        json={
            "model": settings.ollama_model,
            "messages": [{"role": "user", "content": full_prompt}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0},
        },
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return json.loads(response.json()["message"]["content"])
