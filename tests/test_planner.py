from backend.agent.planner import build_plan
from backend.schemas import Filters, QueryIntent

ALL_INTENTS = [
    "full_analysis", "pattern_search", "threshold_query",
    "entity_investigation", "ranking", "eda", "explain_flag",
]


def _intent(intent: str, **kw) -> QueryIntent:
    filters = kw.pop("filters", Filters())
    return QueryIntent(raw_query="q", intent=intent, filters=filters, parsed_by="rules", confidence=0.9, **kw)


def _tool_names(plan) -> list[str]:
    return [s.tool for s in plan.steps]


def test_entity_investigation_excludes_eda_and_ml():
    """WORKPLAN.md Section 8 plan-divergence test: 'Is customer 4521 suspicious?'"""
    plan = build_plan(_intent("entity_investigation", entities=["C-04521"]))
    names = _tool_names(plan)
    assert "eda_profile" not in names
    assert "ml_detect" not in names


def test_threshold_query_excludes_ml():
    """WORKPLAN.md Section 8: 'Which customers made 10+ transactions under $10,000?'"""
    plan = build_plan(_intent("threshold_query", filters=Filters(min_txn_count=10, amount_max=10000.0)))
    assert "ml_detect" not in _tool_names(plan)


def test_full_analysis_includes_eda_and_ml():
    """WORKPLAN.md Section 8: 'Analyse this dataset for suspicious activity'"""
    plan = build_plan(_intent("full_analysis"))
    names = _tool_names(plan)
    assert "eda_profile" in names
    assert "ml_detect" in names


def test_pattern_search_skips_eda_but_detects():
    plan = build_plan(_intent("pattern_search", pattern_types=["structuring"]))
    names = _tool_names(plan)
    assert "eda_profile" not in names
    assert "rule_detect" in names


def test_eda_intent_skips_all_detection():
    plan = build_plan(_intent("eda"))
    names = _tool_names(plan)
    assert "eda_profile" in names
    for tool in ("rule_detect", "ml_detect", "risk_classify"):
        assert tool not in names


def test_explain_flag_skips_reload_and_rescoring():
    plan = build_plan(_intent("explain_flag", entities=["T-000123"]))
    names = _tool_names(plan)
    assert "load_data" not in names
    assert "ml_detect" not in names


def test_every_intent_produces_a_reason_on_every_step():
    for intent_name in ALL_INTENTS:
        plan = build_plan(_intent(intent_name, entities=["C-04521"]))
        for step in plan.steps:
            assert step.reason, f"{intent_name}/{step.tool} missing a reason"


def test_unknown_intent_falls_back_and_logs_decision():
    plan = build_plan(_intent("full_analysis"))
    # sanity: known intents never populate the fallback decision message
    assert not any("unrecognised" in d for d in plan.decisions)
