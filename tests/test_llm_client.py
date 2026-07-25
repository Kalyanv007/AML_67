import pytest

import backend.llm.client as client_mod
from backend.config import settings


@pytest.fixture(autouse=True)
def reset_cache_and_provider(monkeypatch):
    """Isolate the module-level success cache and settings.llm_provider per
    test — this cache is deliberately real module state (not something tests
    should reset for each other), so tests must clear it explicitly."""
    client_mod._CACHE.clear()
    original_provider = settings.llm_provider
    yield
    settings.llm_provider = original_provider
    client_mod._CACHE.clear()


def test_ollama_branch_calls_native_chat_endpoint_and_parses_response(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:11434")
    monkeypatch.setattr(settings, "ollama_model", "qwen2.5:7b-instruct")

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"intent": "ranking", "confidence": 0.9}'}}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("requests.post", fake_post)

    result = client_mod.complete_json("classify this query", "schema hint")

    assert result == {"intent": "ranking", "confidence": 0.9}
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["model"] == "qwen2.5:7b-instruct"
    assert captured["json"]["format"] == "json"
    assert captured["json"]["stream"] is False
    assert "classify this query" in captured["json"]["messages"][0]["content"]


def test_ollama_needs_no_api_key(monkeypatch):
    """Unlike gemini/openai/groq, the ollama branch has no `and settings.X_api_key`
    gate — it's local and unauthenticated. Confirm the branch is reachable with
    every other provider's key left empty."""
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "groq_api_key", "")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "{}"}}

    monkeypatch.setattr("requests.post", lambda *a, **kw: FakeResponse())

    result = client_mod.complete_json("q")
    assert result == {}


def test_successful_completion_is_cached(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    call_count = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            call_count["n"] += 1
            return {"message": {"content": '{"intent": "ranking"}'}}

    monkeypatch.setattr("requests.post", lambda *a, **kw: FakeResponse())

    r1 = client_mod.complete_json("same query", "same hint")
    r2 = client_mod.complete_json("same query", "same hint")

    assert r1 == r2 == {"intent": "ranking"}
    assert call_count["n"] == 1, "second call with identical args should hit the cache, not the provider"


def test_failed_completion_is_not_cached(monkeypatch):
    """The exact bug a plain @lru_cache would introduce: a transient failure
    (e.g. a rate limit) must not permanently poison that query — retrying the
    same query later, once the underlying condition clears, must actually
    retry the provider rather than replay a cached None forever."""
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    call_count = {"n": 0}

    def flaky_post(*a, **kw):
        call_count["n"] += 1
        raise ConnectionError("simulated transient network failure")

    monkeypatch.setattr("requests.post", flaky_post)
    r1 = client_mod.complete_json("same query", "same hint")
    assert r1 is None
    assert call_count["n"] == 1

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"intent": "ranking"}'}}

    monkeypatch.setattr("requests.post", lambda *a, **kw: FakeResponse())
    r2 = client_mod.complete_json("same query", "same hint")

    assert r2 == {"intent": "ranking"}, "the retry after the transient failure must actually hit the provider"
    assert call_count["n"] == 1, "the second (successful) call went through the new stub, not the flaky one"


def test_different_queries_are_cached_independently(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")

    class FakeResponse:
        def __init__(self, content):
            self._content = content

        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": self._content}}

    responses = iter([FakeResponse('{"intent": "ranking"}'), FakeResponse('{"intent": "eda"}')])
    monkeypatch.setattr("requests.post", lambda *a, **kw: next(responses))

    r1 = client_mod.complete_json("query A")
    r2 = client_mod.complete_json("query B")

    assert r1 == {"intent": "ranking"}
    assert r2 == {"intent": "eda"}
