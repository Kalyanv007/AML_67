from backend.agent.narrator import build_flags


def _row(risk_level: str, **overrides) -> dict:
    base = {
        "entity_id": "C-TEST01",
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
