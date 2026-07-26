from backend.agent.narrator import build_flags
from backend.config import settings


def _row(risk_level: str, entity_id: str = "C-TEST01", **overrides) -> dict:
    base = {
        "entity_id": entity_id,
        "risk_score": 50.0,
        "risk_level": risk_level,
        "escalation": None,
        "patterns": ["structuring"],
        "triggered_rules": ["R1"],
        "ml_score": None,
        "evidence": [{"rule_id": "R1", "feature": None, "value": 3, "threshold": 3, "note": "3 txns in band"}],
    }
    base.update(overrides)
    return base


def test_llm_polish_called_only_for_high_risk(monkeypatch):
    calls = []

    def fake_complete_json(prompt, schema_hint=""):
        calls.append(prompt)
        return {"paragraph": "polished text"}

    monkeypatch.setattr("backend.agent.narrator.complete_json", fake_complete_json)

    rows = [_row("high"), _row("medium"), _row("low"), _row("none")]
    flags = build_flags(rows)

    assert len(calls) == 1, "LLM should be called exactly once, only for the HIGH-risk row"
    assert flags[0].explanation == "polished text"
    assert flags[1].explanation == "3 txns in band"
    assert flags[2].explanation == "3 txns in band"
    assert flags[3].explanation == "3 txns in band"


def test_llm_failure_falls_back_to_template_for_high_risk(monkeypatch):
    monkeypatch.setattr("backend.agent.narrator.complete_json", lambda *a, **kw: None)
    flags = build_flags([_row("high")])
    assert flags[0].explanation == "3 txns in band"


def test_sar_draft_only_on_high_risk():
    flags = build_flags([_row("high"), _row("medium"), _row("low"), _row("none")])
    assert flags[0].sar_draft is not None
    assert all(f.sar_draft is None for f in flags[1:])


def test_escalation_defaults_from_risk_level_when_unset():
    flags = build_flags([_row("high"), _row("medium"), _row("low"), _row("none")])
    assert [f.escalation for f in flags] == ["report", "review", "monitor", "no_action"]


def test_llm_polish_capped_to_max_flags(monkeypatch):
    """Regression test for a real bug found live: a full_analysis run against
    real data produced 23 HIGH-risk flags, each triggering a separate LLM
    call — 144s total against local Ollama (no rate limit to fail fast on),
    well past the frontend's 60s request timeout. build_flags() must only
    LLM-polish the first settings.llm_polish_max_flags HIGH-risk rows, not
    every one of them, regardless of how many rows come in."""
    monkeypatch.setattr(settings, "llm_polish_max_flags", 3)
    calls = []
    monkeypatch.setattr(
        "backend.agent.narrator.complete_json",
        lambda *a, **kw: calls.append(1) or {"paragraph": "polished"},
    )

    rows = [_row("high", entity_id=f"C-{i:03d}") for i in range(10)]
    flags = build_flags(rows)

    assert len(calls) == 3, "expected exactly 3 LLM calls (the cap), not one per HIGH row"
    polished = [f for f in flags if f.explanation == "polished"]
    templated = [f for f in flags if f.explanation != "polished"]
    assert len(polished) == 3
    assert len(templated) == 7
    # every row still gets a complete, correct Flag regardless of polish cap
    assert all(f.risk_level == "high" for f in flags)
    assert all(f.escalation == "report" for f in flags)
    assert all(f.sar_draft is not None for f in flags)


def test_llm_polish_cap_only_counts_high_risk_rows(monkeypatch):
    """A mix of risk levels shouldn't let non-HIGH rows consume the cap, and
    shouldn't ever trigger an LLM call for them regardless of the cap value."""
    monkeypatch.setattr(settings, "llm_polish_max_flags", 2)
    calls = []
    monkeypatch.setattr(
        "backend.agent.narrator.complete_json",
        lambda *a, **kw: calls.append(1) or {"paragraph": "polished"},
    )

    rows = (
        [_row("medium", entity_id=f"C-MED{i}") for i in range(5)]
        + [_row("high", entity_id=f"C-HIGH{i}") for i in range(4)]
    )
    flags = build_flags(rows)

    assert len(calls) == 2, "only HIGH rows count toward the cap; MEDIUM rows must never call the LLM"
    high_flags = [f for f in flags if f.risk_level == "high"]
    assert sum(1 for f in high_flags if f.explanation == "polished") == 2
    assert all(f.explanation != "polished" for f in flags if f.risk_level == "medium")
