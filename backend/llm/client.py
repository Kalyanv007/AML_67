"""
Provider-agnostic LLM client. Owner: Track A.

Implementation pending (WORKPLAN.md Track A, H2-H8). Must stay provider-agnostic
(Gemini or OpenAI, selected via backend.config.settings.llm_provider) and must
return None on any failure (missing key, timeout, rate limit, bad JSON) so every
caller has a defined fallback path — never let a caller assume the LLM is available.
"""

from typing import Any


def complete_json(prompt: str, schema_hint: str = "") -> dict[str, Any] | None:
    """Send `prompt` to the configured LLM provider and parse a JSON object from
    the response. Returns None on any failure (no key, timeout, bad JSON, etc.)
    so callers must always have a non-LLM fallback.
    """
    raise NotImplementedError("Track A: implement LLM call + JSON parsing, see WORKPLAN.md H2-H8")
