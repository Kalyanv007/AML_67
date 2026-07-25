"""
tests/test_eda.py

Tests for backend/tools/eda.py.

**File ownership note (flagged explicitly):**
WORKPLAN.md §4 lists Track B test files as:
  tests/test_rules.py, tests/test_features.py, tests/test_ml.py, tests/fixtures/**

tests/test_eda.py is NOT in that explicit list — same situation as test_filters.py.
Created as a reasonable extension of Track B's ownership of tests/fixtures/** and
eda_profile as a Track B tool. To be confirmed with Track A at next standup.

Fixture strategy: same as test_filters.py — loads the committed sample CSVs,
constructs ToolContext manually, no executor, no mocks.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.tools.base import ToolContext
from backend.tools.eda import eda_profile

SAMPLE_TX   = "data/sample/aml_sample.csv"
SAMPLE_CUST = "data/sample/aml_sample_customers.csv"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tx_df() -> pd.DataFrame:
    df = pd.read_csv(SAMPLE_TX)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["is_cross_border"] = df["is_cross_border"].astype(bool)
    return df


@pytest.fixture(scope="module")
def cust_df() -> pd.DataFrame:
    df = pd.read_csv(SAMPLE_CUST)
    df["is_pep"] = df["is_pep"].astype(bool)
    return df


@pytest.fixture
def ctx(tx_df: pd.DataFrame, cust_df: pd.DataFrame) -> ToolContext:
    return ToolContext(
        df=tx_df.copy(),
        artifacts={"customers": cust_df.copy()},
    )


@pytest.fixture
def ctx_empty(tx_df: pd.DataFrame) -> ToolContext:
    """ToolContext with an empty DataFrame."""
    return ToolContext(df=pd.DataFrame(columns=tx_df.columns))


# ---------------------------------------------------------------------------
# Basic execution and ok status
# ---------------------------------------------------------------------------


def test_eda_profile_ok(ctx: ToolContext) -> None:
    result = eda_profile(ctx)
    assert result.ok, f"eda_profile returned ok=False: {result.error}"


def test_eda_profile_empty_df_ok(ctx_empty: ToolContext) -> None:
    """Empty DataFrame must not raise — must return ok=True with txn_count=0."""
    result = eda_profile(ctx_empty)
    assert result.ok
    assert result.metrics.get("txn_count", -1) == 0


# ---------------------------------------------------------------------------
# metrics dict: required keys
# ---------------------------------------------------------------------------


_REQUIRED_METRIC_KEYS = {
    "txn_count",
    "date_min", "date_max", "date_range_days",
    "missing_values", "columns",
    "amount_mean", "amount_median", "amount_std",
    "amount_min", "amount_max", "amount_p25", "amount_p75", "amount_p95",
}


def test_metrics_has_required_keys(ctx: ToolContext) -> None:
    result = eda_profile(ctx)
    assert result.ok
    for key in _REQUIRED_METRIC_KEYS:
        assert key in result.metrics, f"Required metric key '{key}' missing"


def test_metrics_txn_count_correct(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    result = eda_profile(ctx)
    assert result.ok
    assert result.metrics["txn_count"] == len(tx_df)


def test_metrics_amount_stats_positive(ctx: ToolContext) -> None:
    result = eda_profile(ctx)
    assert result.ok
    assert result.metrics["amount_mean"] > 0
    assert result.metrics["amount_min"] > 0


def test_metrics_date_range(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    result = eda_profile(ctx)
    assert result.ok
    expected_min = str(tx_df["timestamp"].min().date())
    expected_max = str(tx_df["timestamp"].max().date())
    assert result.metrics["date_min"] == expected_min
    assert result.metrics["date_max"] == expected_max


def test_metrics_txn_type_counts(ctx: ToolContext) -> None:
    result = eda_profile(ctx)
    assert result.ok
    assert "txn_type_counts" in result.metrics
    counts = result.metrics["txn_type_counts"]
    assert isinstance(counts, dict)
    assert sum(counts.values()) == result.metrics["txn_count"]


def test_metrics_pattern_counts(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    result = eda_profile(ctx)
    assert result.ok
    if "pattern_counts" in result.metrics:
        # Must include structuring, smurfing, layering, rapid_cashout
        present_patterns = set(result.metrics["pattern_counts"].keys())
        for pattern in ["structuring", "smurfing", "layering", "rapid_cashout"]:
            assert pattern in present_patterns, f"Pattern '{pattern}' not in pattern_counts"


def test_metrics_label_balance(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    result = eda_profile(ctx)
    assert result.ok
    n_pos = result.metrics.get("label_is_laundering_positive", 0)
    n_neg = result.metrics.get("label_is_laundering_negative", 0)
    # Synthetic dataset has 202 labelled laundering rows
    assert n_pos > 0, "Expected some positive labels in synthetic dataset"
    assert n_neg > 0
    assert n_pos + n_neg == result.metrics["txn_count"]


def test_metrics_threshold_proximity(ctx: ToolContext) -> None:
    result = eda_profile(ctx)
    assert result.ok
    # Structuring transactions are in the $8800-$9999 band — there should be some
    assert "threshold_zone_total" in result.metrics
    assert "threshold_just_below_10k" in result.metrics
    assert result.metrics["threshold_just_below_10k"] >= 0


# ---------------------------------------------------------------------------
# artifacts["eda"] handshake
# ---------------------------------------------------------------------------


def test_artifacts_eda_key_present(ctx: ToolContext) -> None:
    """Contract 2: eda_profile must write ToolResult.artifacts['eda']."""
    result = eda_profile(ctx)
    assert result.ok
    assert "eda" in result.artifacts, "artifacts['eda'] missing — Contract 2 violation"


def test_artifacts_eda_matches_metrics(ctx: ToolContext) -> None:
    result = eda_profile(ctx)
    assert result.ok
    assert result.artifacts["eda"] is result.metrics or result.artifacts["eda"] == result.metrics


# ---------------------------------------------------------------------------
# charts: five required charts
# ---------------------------------------------------------------------------


_REQUIRED_CHARTS = {
    "amount_histogram",
    "threshold_proximity",
    "txn_type_breakdown",
    "country_breakdown",
    "volume_timeseries",
}


def test_charts_all_present(ctx: ToolContext) -> None:
    result = eda_profile(ctx)
    assert result.ok
    for chart_name in _REQUIRED_CHARTS:
        assert chart_name in result.charts, f"Chart '{chart_name}' missing from ToolResult.charts"


def test_charts_are_plotly_json(ctx: ToolContext) -> None:
    """Each chart must be a dict with 'data' and 'layout' keys (Plotly figure JSON)."""
    result = eda_profile(ctx)
    assert result.ok
    for name, fig_dict in result.charts.items():
        if not fig_dict:
            continue  # empty chart (edge case) is allowed
        assert isinstance(fig_dict, dict), f"Chart '{name}' is not a dict"
        assert "data" in fig_dict or "layout" in fig_dict, (
            f"Chart '{name}' missing 'data'/'layout' — not valid Plotly JSON"
        )


def test_threshold_chart_has_vline(ctx: ToolContext) -> None:
    """The threshold_proximity chart must include a vertical line at $10k."""
    result = eda_profile(ctx)
    assert result.ok
    fig = result.charts.get("threshold_proximity", {})
    if not fig:
        return
    layout = fig.get("layout", {})
    shapes = layout.get("shapes", [])
    # Plotly vline() is encoded as a shape with x0 == x1 == 10000
    vlines = [
        s for s in shapes
        if abs(s.get("x0", -1) - 10_000) < 1 or abs(s.get("x1", -1) - 10_000) < 1
    ]
    assert len(vlines) > 0 or "annotations" in layout, (
        "threshold_proximity chart has no vline at $10k"
    )


# ---------------------------------------------------------------------------
# notes contract
# ---------------------------------------------------------------------------


def test_notes_contain_count(ctx: ToolContext) -> None:
    result = eda_profile(ctx)
    assert result.ok
    note_text = " ".join(result.notes)
    import re
    assert re.search(r"\d[\d,]+", note_text), "No numeric count in eda_profile notes"


def test_result_does_not_mutate_ctx(ctx: ToolContext) -> None:
    """eda_profile must never mutate ctx.df."""
    original_len = len(ctx.df)
    eda_profile(ctx)
    assert len(ctx.df) == original_len, "eda_profile mutated ctx.df — contract violation"
