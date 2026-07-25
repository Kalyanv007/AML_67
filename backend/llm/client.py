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


def complete_json(prompt: str, schema_hint: str = "") -> dict[str, Any] | None:
    try:
        if settings.llm_provider == "gemini" and settings.gemini_api_key:
            return _complete_gemini(prompt, schema_hint)
        if settings.llm_provider == "openai" and settings.openai_api_key:
            return _complete_openai(prompt, schema_hint)
        if settings.llm_provider == "groq" and settings.groq_api_key:
            return _complete_groq(prompt, schema_hint)
    except Exception:
        return None
    return None


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
