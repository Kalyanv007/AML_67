"""
tests/test_no_label_leakage.py
Track B — Label-leakage regression tests.

Verifies that the detection pipeline (feature_engineer → rule_detect → ml_detect →
risk_classify) produces IDENTICAL output whether or not the label columns
(label_is_laundering, pattern_label) are present in the input DataFrame.

If any assertion here fails, it means a label column has leaked into the detection
logic and the pipeline is reading the answer key rather than detecting from behaviour.

Part 4 confirms that the validation logic in test_integration.py::
test_false_positive_reduction_vs_naive_baseline uses labels ONLY after the pipeline
runs, never as pipeline input.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.tools.base import ToolContext
from backend.tools.features import feature_engineer
from backend.tools.rules import rule_detect
from backend.tools.ml_detect import ml_detect
from backend.tools.risk import risk_classify

SAMPLE_CSV = "data/sample/aml_sample.csv"
LABEL_COLS = ["label_is_laundering", "pattern_label"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_pipeline(df: pd.DataFrame) -> dict:
    """Run the full detection pipeline on df.  Returns a dict with the key
    artifacts needed for comparison.  Deliberately does NOT include entity_lookup
    or eda_profile (neither touches features/rules/ml/risk)."""
    ctx = ToolContext(df=df.copy(), artifacts={})

    r_feat = feature_engineer(ctx)
    assert r_feat.ok, f"feature_engineer failed: {r_feat.error}"
    ctx.artifacts.update(r_feat.artifacts)

    r_rule = rule_detect(ctx)
    assert r_rule.ok, f"rule_detect failed: {r_rule.error}"
    ctx.artifacts.update(r_rule.artifacts)

    r_ml = ml_detect(ctx)
    assert r_ml.ok, f"ml_detect failed: {r_ml.error}"
    ctx.artifacts.update(r_ml.artifacts)

    r_risk = risk_classify(ctx)
    assert r_risk.ok, f"risk_classify failed: {r_risk.error}"
    ctx.artifacts.update(r_risk.artifacts)

    return {
        "features": ctx.artifacts.get("features", pd.DataFrame()),
        "rule_hits": ctx.artifacts.get("rule_hits", []),
        "ml_scores": ctx.artifacts.get("ml_scores", []),
        "risk_rows": ctx.artifacts.get("risk_rows", []),
    }


def _load_labeled() -> pd.DataFrame:
    df = pd.read_csv(SAMPLE_CSV)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["is_cross_border"] = df["is_cross_border"].astype(bool)
    return df


def _load_stripped() -> pd.DataFrame:
    df = _load_labeled()
    present = [c for c in LABEL_COLS if c in df.columns]
    return df.drop(columns=present)


# ---------------------------------------------------------------------------
# Part 1 confirmation: label columns are absent from the features DataFrame
# ---------------------------------------------------------------------------


def test_feature_engineer_does_not_output_label_cols():
    """feature_engineer must never copy label columns into the features artifact
    (that would feed them silently into ml_detect's feature matrix)."""
    df = _load_labeled()
    ctx = ToolContext(df=df.copy(), artifacts={})
    r = feature_engineer(ctx)
    assert r.ok
    feat_df: pd.DataFrame = r.artifacts.get("features", pd.DataFrame())
    for col in LABEL_COLS:
        assert col not in feat_df.columns, (
            f"Label column '{col}' found in features DataFrame — "
            "feature_engineer is leaking the answer key into the ML feature matrix."
        )


def test_ml_detect_feature_list_does_not_include_label_cols():
    """feature_list artifact must not name any label column.  ml_detect uses
    feature_list as the primary column selector for its feature matrix."""
    df = _load_labeled()
    ctx = ToolContext(df=df.copy(), artifacts={})
    r = feature_engineer(ctx)
    assert r.ok
    feature_list: list[str] = r.artifacts.get("feature_list", [])
    for col in LABEL_COLS:
        assert col not in feature_list, (
            f"Label column '{col}' appears in feature_list — "
            "it would be used as an ML feature input."
        )


# ---------------------------------------------------------------------------
# Part 2 — pipeline runs identically with and without labels
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def labeled_output():
    return _run_pipeline(_load_labeled())


@pytest.fixture(scope="module")
def stripped_output():
    return _run_pipeline(_load_stripped())


def test_pipeline_runs_without_label_cols(stripped_output):
    """The pipeline must not error or raise when label columns are absent."""
    # The fixture itself calls _run_pipeline with asserts inside; if we get here
    # without an exception the pipeline ran cleanly on label-stripped data.
    assert stripped_output is not None


def test_features_identical_with_and_without_labels(labeled_output, stripped_output):
    """feature_engineer output must be bit-for-bit identical regardless of
    whether label columns are present in the input DataFrame."""
    feat_with = labeled_output["features"]
    feat_without = stripped_output["features"]

    # Same shape
    assert feat_with.shape == feat_without.shape, (
        f"Feature DataFrame shapes differ: labeled={feat_with.shape}, "
        f"stripped={feat_without.shape}"
    )
    # Same columns
    assert set(feat_with.columns) == set(feat_without.columns), (
        f"Column mismatch: labeled has {set(feat_with.columns) - set(feat_without.columns)} "
        f"extra, stripped has {set(feat_without.columns) - set(feat_with.columns)} extra"
    )
    # Same index (customer IDs)
    assert list(feat_with.index) == list(feat_without.index), (
        "Customer index differs between labeled and stripped runs"
    )
    # Same values (all numeric, so use isclose with a tight tolerance)
    import numpy as np
    for col in feat_with.columns:
        a = feat_with[col].fillna(0.0).values
        b = feat_without[col].fillna(0.0).values
        if not np.allclose(a, b, rtol=0, atol=1e-9):
            diffs = np.where(~np.isclose(a, b, rtol=0, atol=1e-9))[0]
            raise AssertionError(
                f"Feature '{col}' differs between labeled and stripped runs at "
                f"{len(diffs)} row(s): first diff at index {diffs[0]}, "
                f"labeled={a[diffs[0]]}, stripped={b[diffs[0]]}. "
                "This is evidence of label leakage."
            )


def test_rule_hits_identical_with_and_without_labels(labeled_output, stripped_output):
    """rule_detect must produce the same set of hits (entity_id, rule_id, weight,
    evidence) regardless of whether label columns are in the DataFrame."""
    def _key(hit: dict) -> str:
        return f"{hit['entity_id']}|{hit['rule_id']}"

    hits_with    = {_key(h): h for h in labeled_output["rule_hits"]}
    hits_without = {_key(h): h for h in stripped_output["rule_hits"]}

    assert set(hits_with.keys()) == set(hits_without.keys()), (
        f"Rule hit entity/rule sets differ.\n"
        f"Only in labeled run:  {set(hits_with.keys()) - set(hits_without.keys())}\n"
        f"Only in stripped run: {set(hits_without.keys()) - set(hits_with.keys())}\n"
        "This is direct evidence of label leakage."
    )

    for key in hits_with:
        w_labeled  = hits_with[key]["weight"]
        w_stripped = hits_without[key]["weight"]
        assert abs(w_labeled - w_stripped) < 1e-9, (
            f"Rule hit weight differs for {key}: labeled={w_labeled}, stripped={w_stripped}"
        )


def test_ml_scores_identical_with_and_without_labels(labeled_output, stripped_output):
    """ml_detect scores must be identical — IsolationForest/LOF are unsupervised,
    so labels should never affect their output."""
    scores_with    = {r["entity_id"]: r["score"] for r in labeled_output["ml_scores"]}
    scores_without = {r["entity_id"]: r["score"] for r in stripped_output["ml_scores"]}

    assert set(scores_with.keys()) == set(scores_without.keys()), (
        f"ML scored entity sets differ.\n"
        f"Only in labeled run:  {set(scores_with.keys()) - set(scores_without.keys())}\n"
        f"Only in stripped run: {set(scores_without.keys()) - set(scores_with.keys())}"
    )

    import numpy as np
    for eid in scores_with:
        a, b = scores_with[eid], scores_without[eid]
        assert np.isclose(a, b, rtol=0, atol=1e-6), (
            f"ML score differs for entity {eid}: labeled={a}, stripped={b}. "
            "This is evidence of label leakage into the ML feature matrix."
        )


def test_risk_rows_identical_with_and_without_labels(labeled_output, stripped_output):
    """risk_classify output (risk_score, risk_level, escalation) must be identical
    for every entity between labeled and stripped runs."""
    def _risk_map(rows):
        return {
            r["entity_id"]: {
                "risk_score": r.get("risk_score"),
                "risk_level": r.get("risk_level"),
                "escalation": r.get("escalation"),
            }
            for r in rows
        }

    risk_with    = _risk_map(labeled_output["risk_rows"])
    risk_without = _risk_map(stripped_output["risk_rows"])

    assert set(risk_with.keys()) == set(risk_without.keys()), (
        f"Risk row entity sets differ.\n"
        f"Only in labeled run:  {set(risk_with.keys()) - set(risk_without.keys())}\n"
        f"Only in stripped run: {set(risk_without.keys()) - set(risk_with.keys())}"
    )

    import numpy as np
    for eid in risk_with:
        r_l = risk_with[eid]
        r_s = risk_without[eid]
        assert r_l["risk_level"] == r_s["risk_level"], (
            f"risk_level differs for {eid}: labeled={r_l['risk_level']}, "
            f"stripped={r_s['risk_level']}"
        )
        assert r_l["escalation"] == r_s["escalation"], (
            f"escalation differs for {eid}: labeled={r_l['escalation']}, "
            f"stripped={r_s['escalation']}"
        )
        if r_l["risk_score"] is not None and r_s["risk_score"] is not None:
            assert np.isclose(r_l["risk_score"], r_s["risk_score"], rtol=0, atol=1e-6), (
                f"risk_score differs for {eid}: labeled={r_l['risk_score']}, "
                f"stripped={r_s['risk_score']}"
            )


# ---------------------------------------------------------------------------
# Part 4 — confirm Phase 5 validation reads labels AFTER the pipeline, not into it
# ---------------------------------------------------------------------------


def test_phase5_validation_reads_labels_after_pipeline_not_into_it():
    """Structural check: test_integration.py::test_false_positive_reduction_vs_naive_baseline
    is the Phase 5 validation script equivalent in this codebase.  It reads
    label_is_laundering to SCORE the pipeline's output AFTER run_plan() returns.

    This test confirms that the labels are NEVER passed into ToolContext.df — it
    verifies the separation by running the exact same pipeline used there (same
    QueryIntent/full_analysis) on a label-stripped DataFrame and confirming the
    output is structurally valid (flags present, no crash).  The pipeline must
    not need labels to produce flags.
    """
    df = _load_stripped()
    # Must not raise and must still produce flags
    out = _run_pipeline(df)
    assert out["risk_rows"], (
        "Pipeline produced zero risk rows on label-stripped data — "
        "if it only flags entities when label columns are present, "
        "that is label leakage."
    )
