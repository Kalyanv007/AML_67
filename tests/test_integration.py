"""
Phase 6 — integration tests against Track B's real tools (AML_USE_MOCKS=0)
and the real sample dataset, not the mock fixtures.

executor._TOOLS_CACHE is a module-level cache keyed on whatever
settings.aml_use_mocks was at first call — earlier tests in the suite call it
with mocks on, so it must be reset (both before and after) whenever a test
here flips the setting, or the real tools never actually get imported.
"""

import backend.agent.executor as executor_mod
from backend.agent.executor import run_plan
from backend.agent.planner import build_plan
from backend.config import settings
from backend.schemas import Filters, QueryIntent

import pytest

# A real customer ID present in data/sample/aml_sample.csv's structuring cohort
# (mock fixtures use C-04521, which does not exist in the real dataset — real
# IDs follow Track B's synthetic generator's own scheme, e.g. C-STR02, C-N0001).
REAL_STRUCTURING_ENTITY = "C-STR02"


@pytest.fixture
def real_tools(monkeypatch):
    monkeypatch.setattr(settings, "aml_use_mocks", False)
    executor_mod._TOOLS_CACHE = None
    yield
    executor_mod._TOOLS_CACHE = None


def test_full_analysis_against_real_tools(real_tools):
    intent = QueryIntent(raw_query="Analyse this dataset for suspicious activity",
                          intent="full_analysis", parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps), [(s.tool, s.status) for s in plan.steps]
    assert not response.warnings
    assert response.flags, "expected flags against the real structuring/smurfing/layering/cashout cohorts"
    assert all(f.explanation for f in response.flags)
    assert all(f.escalation in ("report", "review", "monitor", "no_action") for f in response.flags)


def test_pattern_search_scopes_features_and_rules(real_tools):
    intent = QueryIntent(raw_query="Find structuring patterns in the last 30 days",
                          intent="pattern_search", pattern_types=["structuring"],
                          parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    # only R1 should have been evaluated, not all 6 rules
    assert response.metrics.get("rules_evaluated") == ["R1"]
    assert response.flags


def test_threshold_query_against_real_tools(real_tools):
    intent = QueryIntent(raw_query="Which customers made 10+ transactions under $10,000?",
                          intent="threshold_query",
                          filters=Filters(min_txn_count=10, amount_max=10000.0),
                          parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    assert "ml_detect" not in [s.tool for s in plan.steps]
    assert response.metrics.get("row_count", 0) > 0
    assert str(response.metrics["row_count"]) in response.summary


def test_entity_investigation_scopes_to_one_entity(real_tools):
    intent = QueryIntent(raw_query=f"Is customer {REAL_STRUCTURING_ENTITY} suspicious?",
                          intent="entity_investigation", entities=[REAL_STRUCTURING_ENTITY],
                          parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    assert len(response.flags) == 1
    assert response.flags[0].entity_id == REAL_STRUCTURING_ENTITY
    assert response.flags[0].explanation


def test_entity_resolution_maps_bare_number_to_real_customer(real_tools):
    """intent_parser normalises 'customer 2' -> 'C-00002', which doesn't exist
    in the real dataset (real IDs are e.g. C-N0002). The executor should
    resolve it by numeric id to a real customer_id, not just fail to match."""
    intent = QueryIntent(raw_query="Is customer 2 suspicious?", intent="entity_investigation",
                          entities=["C-00002"], parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    assert intent.entities != ["C-00002"], "entity should have been resolved to a real customer_id"
    assert intent.entities[0].startswith("C-") and intent.entities[0] != "C-00002"
    assert any("resolved entity" in d for d in plan.decisions)
    entity_lookup_step = next(s for s in plan.steps if s.tool == "entity_lookup")
    assert entity_lookup_step.params["entity_id"] == intent.entities[0]


def test_entity_resolution_leaves_out_of_range_id_unresolved(real_tools):
    """A number with no real counterpart (out of the ~270-customer range)
    should degrade gracefully — no crash, no flags, not silently matched to
    the wrong customer."""
    intent = QueryIntent(raw_query="Is customer 4521 suspicious?", intent="entity_investigation",
                          entities=["C-04521"], parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    assert intent.entities == ["C-04521"]
    assert response.flags == []
    assert any("no real customer found" in d for d in plan.decisions)


def test_entity_resolution_passes_through_already_real_id(real_tools):
    intent = QueryIntent(raw_query=f"Is customer {REAL_STRUCTURING_ENTITY} suspicious?",
                          intent="entity_investigation", entities=[REAL_STRUCTURING_ENTITY],
                          parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    run_plan(intent, plan)

    assert intent.entities == [REAL_STRUCTURING_ENTITY]
    assert not any("resolved entity" in d for d in plan.decisions)


def test_entity_investigation_unknown_id_returns_no_flags_not_a_crash(real_tools):
    intent = QueryIntent(raw_query="Is customer 4521 suspicious?", intent="entity_investigation",
                          entities=["C-04521"], parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    assert response.flags == []
    assert response.summary


def test_ranking_truncates_to_top_n(real_tools):
    intent = QueryIntent(raw_query="Top 5 highest-risk customers", intent="ranking", top_n=5,
                          parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    assert len(response.flags) == 5
    scores = [f.risk_score for f in response.flags]
    assert scores == sorted(scores, reverse=True)


def test_eda_intent_runs_no_detection_against_real_tools(real_tools):
    intent = QueryIntent(raw_query="Show transaction distribution by country", intent="eda",
                          parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    assert response.flags == []
    assert response.metrics.get("txn_type_counts") or response.metrics.get("channel_counts")


def test_explain_flag_actually_scores_the_entity(real_tools):
    """Phase 7 fix: explain_flag previously never loaded data (per Contract 4's
    'reuse cached run' design, which was never wired to anything) and always
    returned empty. It now loads data and scores just the requested entity."""
    intent = QueryIntent(raw_query=f"Why was customer {REAL_STRUCTURING_ENTITY} flagged?",
                          intent="explain_flag", entities=[REAL_STRUCTURING_ENTITY],
                          parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert all(s.status == "ok" for s in plan.steps)
    assert "load_data" in [s.tool for s in plan.steps]
    assert "eda_profile" not in [s.tool for s in plan.steps]
    assert "ml_detect" not in [s.tool for s in plan.steps]
    assert len(response.flags) == 1
    assert response.flags[0].entity_id == REAL_STRUCTURING_ENTITY
    assert response.flags[0].explanation in response.summary


def test_false_positive_reduction_vs_naive_baseline(real_tools):
    """README.md's Results section quantifies this against the synthetic
    dataset's label_is_laundering ground truth: our system flags far fewer
    customers than a naive 'any txn > $9,000' rule, at a far lower
    false-positive rate. This test protects that headline claim without
    pinning exact percentages (which would be brittle to minor threshold
    tuning) — if this ever fails, the false-positive-reduction story in the
    README is no longer true and needs re-validating, not just re-asserting.
    """
    import pandas as pd

    intent = QueryIntent(raw_query="Analyse this dataset for suspicious activity",
                          intent="full_analysis", parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)
    our_flagged = {f.entity_id for f in response.flags}

    df = pd.read_csv("data/sample/aml_sample.csv")
    cust = pd.read_csv("data/sample/aml_sample_customers.csv")
    all_customers = set(cust["customer_id"])
    positives = set(df[df.label_is_laundering == True]["sender_id"]) & all_customers
    negatives = all_customers - positives
    naive_flagged = set(df[df.amount > 9000]["sender_id"].unique()) & all_customers

    def false_positive_rate(flagged):
        fp = len(flagged & negatives)
        tn = len(negatives - flagged)
        return fp / (fp + tn) if (fp + tn) else 0.0

    naive_fpr = false_positive_rate(naive_flagged)
    our_fpr = false_positive_rate(our_flagged)

    assert len(our_flagged) < len(naive_flagged) / 5, (
        f"our system flagged {len(our_flagged)}, naive flagged {len(naive_flagged)} — "
        "expected at least a 5x reduction in flagged customers"
    )
    assert our_fpr < naive_fpr / 5, (
        f"our FPR {our_fpr:.3f} vs naive FPR {naive_fpr:.3f} — expected at least a 5x FPR reduction"
    )
    # sanity: we shouldn't be achieving low FPR by simply not flagging anyone
    assert len(our_flagged & positives) > 0, "our system caught zero true positives"


def test_full_analysis_response_is_actually_json_serializable(real_tools):
    """Regression test for a real bug found live: eda_profile's Plotly figures
    (via .to_dict()) embed raw numpy.ndarray values in trace data (x/y/text/
    marker.color). AgentResponse.charts is Any-typed, so Pydantic validates
    these fine at construction time — but FastAPI's JSON response
    serialization crashed with PydanticSerializationError once this actually
    reached the HTTP layer. Every other test calls run_plan() directly and
    inspects the object, which never exercises serialization — this test
    exists specifically to catch that gap. A 500 on the demo's flagship query
    is the worst possible thing to have work in tests and fail live."""
    intent = QueryIntent(raw_query="Analyse this dataset for suspicious activity",
                          intent="full_analysis", parsed_by="rules", confidence=0.9)
    plan = build_plan(intent)
    response = run_plan(intent, plan)

    assert response.charts, "expected eda_profile to have produced charts to test against"
    # this is the exact call FastAPI makes when returning the response over HTTP
    response.model_dump_json()
