"""
tests/test_features.py

Tests for backend/tools/features.py.

Ownership: explicitly listed in WORKPLAN.md §4 Track B ownership matrix
  (tests/test_features.py).

Test strategy:
  1. Hand-checkable rolling window arithmetic on a small fixture
  2. Selective computation (pattern_types param skips unrequested features)
  3. z-score fallback for thin history (< 3 samples → 0.0)
  4. Correct feature_list output (reflects what was actually computed)
  5. pass_through_ratio on a synthetic layering case
  6. Contract: never mutates ctx.df, output is DataFrame indexed by customer_id
"""

from __future__ import annotations

import math
import pandas as pd
import pytest

from backend.tools.base import ToolContext
from backend.tools.features import (
    feature_engineer,
    _requested_features,
    _ALL_FEATURES,
    _PATTERN_FEATURES,
    THRESHOLD_BAND_LOW,
    THRESHOLD_BAND_HIGH,
    NIGHT_HOURS_UTC,
    ZSCORE_MIN_SAMPLES,
)

# ---------------------------------------------------------------------------
# Hand-checkable fixture builder
# ---------------------------------------------------------------------------

def _make_tx(
    rows: list[dict],
    base_ts: str = "2025-01-10T12:00:00",
) -> pd.DataFrame:
    """Build a minimal canonical transactions DataFrame from a list of dicts.

    Required keys: sender_id, receiver_id, amount
    Optional keys: timestamp (default=base_ts), txn_type, channel, currency,
                   is_cross_border, label_is_laundering, pattern_label
    """
    records = []
    base = pd.Timestamp(base_ts)
    for i, r in enumerate(rows):
        records.append({
            "txn_id":             r.get("txn_id", f"T-{i:06d}"),
            "timestamp":          r.get("timestamp", base + pd.Timedelta(hours=i)),
            "sender_id":          r["sender_id"],
            "receiver_id":        r["receiver_id"],
            "amount":             float(r["amount"]),
            "currency":           r.get("currency", "USD"),
            "txn_type":           r.get("txn_type", "transfer"),
            "channel":            r.get("channel", "online"),
            "sender_country":     r.get("sender_country", "US"),
            "receiver_country":   r.get("receiver_country", "US"),
            "is_cross_border":    r.get("is_cross_border", False),
            "label_is_laundering": r.get("label_is_laundering", False),
            "pattern_label":      r.get("pattern_label", None),
        })
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["is_cross_border"] = df["is_cross_border"].astype(bool)
    return df


def _ctx(df: pd.DataFrame) -> ToolContext:
    return ToolContext(df=df.copy())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TX   = "data/sample/aml_sample.csv"
SAMPLE_CUST = "data/sample/aml_sample_customers.csv"


@pytest.fixture(scope="module")
def sample_df() -> pd.DataFrame:
    df = pd.read_csv(SAMPLE_TX)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["is_cross_border"] = df["is_cross_border"].astype(bool)
    return df


@pytest.fixture
def sample_ctx(sample_df: pd.DataFrame) -> ToolContext:
    return ToolContext(df=sample_df.copy())


# ---------------------------------------------------------------------------
# 1. Hand-checkable rolling window arithmetic
# ---------------------------------------------------------------------------


def test_rolling_1d_sum_exact() -> None:
    """Manually verified: C-A sends 3 transactions within the last 1 day."""
    ref = pd.Timestamp("2025-01-10T23:00:00")
    rows = [
        # C-A: 3 txns in the last 1d (all within 24h of ref)
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 1000.0,
         "timestamp": ref - pd.Timedelta(hours=23)},
        {"sender_id": "C-A", "receiver_id": "C-Y", "amount": 2000.0,
         "timestamp": ref - pd.Timedelta(hours=12)},
        {"sender_id": "C-A", "receiver_id": "C-Z", "amount": 3000.0,
         "timestamp": ref - pd.Timedelta(hours=1)},
        # C-B: 1 txn outside the 1d window (2 days ago)
        {"sender_id": "C-B", "receiver_id": "C-X", "amount": 5000.0,
         "timestamp": ref - pd.Timedelta(days=2)},
    ]
    df = _make_tx(rows)
    # Patch ref timestamp to match the fixture's actual max
    assert df["timestamp"].max() == ref - pd.Timedelta(hours=1)

    result = feature_engineer(_ctx(df), pattern_types=["structuring"])
    assert result.ok
    feat = result.artifacts["features"]

    # C-A: rolling_1d_sum = 1000 + 2000 + 3000 = 6000 (all within 24h of max ts)
    assert "C-A" in feat.index
    assert abs(feat.loc["C-A", "rolling_1d_sum"] - 6000.0) < 1.0, (
        f"Expected 6000, got {feat.loc['C-A', 'rolling_1d_sum']}"
    )
    assert int(feat.loc["C-A", "rolling_1d_count"]) == 3

    # C-B's txn is 2 days before ref → excluded from 1d window → sum=0
    # (C-B may not appear in sender-side features if all its txns are outside window)
    if "C-B" in feat.index:
        assert feat.loc["C-B", "rolling_1d_sum"] == 0.0 or feat.loc["C-B", "rolling_1d_sum"] < 5000.0


def test_rolling_7d_sum_exact() -> None:
    """C-A: 2 txns exactly 6 days before ref → should appear in 7d window."""
    ref = pd.Timestamp("2025-01-15T00:00:00")
    rows = [
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 4000.0,
         "timestamp": ref - pd.Timedelta(days=6)},
        {"sender_id": "C-A", "receiver_id": "C-Y", "amount": 2500.0,
         "timestamp": ref - pd.Timedelta(days=3)},
        # Anchor point (max ts)
        {"sender_id": "C-A", "receiver_id": "C-Z", "amount": 100.0,
         "timestamp": ref},
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["structuring"])
    assert result.ok
    feat = result.artifacts["features"]
    # 7d window from ref: all 3 txns within window → sum = 4000 + 2500 + 100 = 6600
    assert abs(feat.loc["C-A", "rolling_7d_sum"] - 6600.0) < 1.0


def test_rolling_1d_count_exact() -> None:
    """C-A sends 5 transactions within the last 1 day."""
    ref = pd.Timestamp("2025-01-10T18:00:00")
    rows = [
        {"sender_id": "C-A", "receiver_id": f"C-R{i}", "amount": 1000.0,
         "timestamp": ref - pd.Timedelta(hours=i)}
        for i in range(5)
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["structuring"])
    assert result.ok
    feat = result.artifacts["features"]
    assert int(feat.loc["C-A", "rolling_1d_count"]) == 5


# ---------------------------------------------------------------------------
# 2. Selective computation (pattern_types skips unrequested features)
# ---------------------------------------------------------------------------


def test_structuring_only_skips_layering_features(sample_ctx: ToolContext) -> None:
    result = feature_engineer(sample_ctx, pattern_types=["structuring"])
    assert result.ok
    feat_list = result.artifacts["feature_list"]
    # Layering-exclusive features must NOT be computed
    layering_exclusive = {
        "pass_through_ratio", "cross_border_count", "cross_border_ratio",
    }
    for feat in layering_exclusive:
        assert feat not in feat_list, (
            f"'{feat}' should not be computed for pattern_types=['structuring']"
        )


def test_layering_only_skips_structuring_features(sample_ctx: ToolContext) -> None:
    result = feature_engineer(sample_ctx, pattern_types=["layering"])
    assert result.ok
    feat_list = result.artifacts["feature_list"]
    # pct_just_below_threshold is structuring-only
    assert "pct_just_below_threshold" not in feat_list, (
        "pct_just_below_threshold should not be computed for pattern_types=['layering']"
    )
    # pass_through_ratio MUST be in layering features
    assert "pass_through_ratio" in feat_list, (
        "pass_through_ratio must be computed for layering"
    )


def test_rapid_cashout_only_skips_structuring_features(sample_ctx: ToolContext) -> None:
    result = feature_engineer(sample_ctx, pattern_types=["rapid_cashout"])
    assert result.ok
    feat_list = result.artifacts["feature_list"]
    assert "pct_just_below_threshold" not in feat_list
    assert "pass_through_ratio" not in feat_list
    assert "rapid_cashout_ratio" in feat_list


def test_none_pattern_computes_all(sample_ctx: ToolContext) -> None:
    """pattern_types=None must compute ALL features."""
    result = feature_engineer(sample_ctx, pattern_types=None)
    assert result.ok
    feat_list = set(result.artifacts["feature_list"])
    # Every feature in _ALL_FEATURES must be present
    for f in _ALL_FEATURES:
        assert f in feat_list, f"Feature '{f}' missing when pattern_types=None"


def test_feature_list_reflects_computed_only(sample_ctx: ToolContext) -> None:
    """feature_list must not include features for un-requested patterns."""
    result = feature_engineer(sample_ctx, pattern_types=["smurfing"])
    assert result.ok
    expected = _PATTERN_FEATURES["smurfing"]
    feat_list = set(result.artifacts["feature_list"])
    # Everything in feat_list must be in smurfing's feature set (plus metadata like zscore_n_samples)
    allowed = expected | {"zscore_n_samples"}
    for f in feat_list:
        assert f in allowed, f"Unexpected feature '{f}' for smurfing pattern"


# ---------------------------------------------------------------------------
# 3. z-score fallback for thin history
# ---------------------------------------------------------------------------


def test_zscore_fallback_below_min_samples() -> None:
    """Customer with < 3 transactions gets zscore=0.0 (fallback per AML_LOGIC.md §5.3)."""
    rows = [
        {"sender_id": "C-THIN", "receiver_id": "C-X", "amount": 9500.0},
        {"sender_id": "C-THIN", "receiver_id": "C-Y", "amount": 9200.0},
        # Only 2 txns — below ZSCORE_MIN_SAMPLES=3
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["structuring"])
    assert result.ok
    feat = result.artifacts["features"]
    assert "C-THIN" in feat.index
    assert feat.loc["C-THIN", "amount_zscore_90d"] == 0.0, (
        f"Expected 0.0 fallback, got {feat.loc['C-THIN', 'amount_zscore_90d']}"
    )


def test_zscore_nonzero_with_sufficient_samples() -> None:
    """Customer with ≥ 3 transactions and variance gets non-zero zscore."""
    rows = [
        {"sender_id": "C-RICH", "receiver_id": "C-X", "amount": 100.0},
        {"sender_id": "C-RICH", "receiver_id": "C-Y", "amount": 200.0},
        {"sender_id": "C-RICH", "receiver_id": "C-Z", "amount": 9999.0},  # outlier
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["structuring"])
    assert result.ok
    feat = result.artifacts["features"]
    assert feat.loc["C-RICH", "amount_zscore_90d"] > 1.0, (
        "Expected high z-score for outlier amount"
    )


def test_zscore_n_samples_reported(sample_ctx: ToolContext) -> None:
    """zscore_n_samples must be in the feature DataFrame when zscore is computed."""
    result = feature_engineer(sample_ctx, pattern_types=["structuring"])
    assert result.ok
    feat = result.artifacts["features"]
    assert "zscore_n_samples" in feat.columns


# ---------------------------------------------------------------------------
# 4. pct_just_below_threshold
# ---------------------------------------------------------------------------


def test_pct_threshold_exact() -> None:
    """4 of 5 transactions in [$9000, $9999.99] → pct = 0.8."""
    rows = [
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 9500.0},
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 9200.0},
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 9800.0},
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 9100.0},
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 50000.0},  # outside band
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["structuring"])
    assert result.ok
    feat = result.artifacts["features"]
    assert abs(feat.loc["C-A", "pct_just_below_threshold"] - 0.8) < 0.01


def test_pct_threshold_band_boundaries() -> None:
    """Test exact band boundaries: $9000 is IN, $10000 is OUT, $8999.99 is OUT."""
    rows = [
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": THRESHOLD_BAND_LOW},      # IN
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": THRESHOLD_BAND_HIGH},     # IN
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 10_000.0},                # OUT
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": THRESHOLD_BAND_LOW - 1},  # OUT
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["structuring"])
    assert result.ok
    feat = result.artifacts["features"]
    # 2 of 4 txns in band → 0.5
    assert abs(feat.loc["C-A", "pct_just_below_threshold"] - 0.5) < 0.01


# ---------------------------------------------------------------------------
# 5. pass_through_ratio (layering defining signal)
# ---------------------------------------------------------------------------


def test_pass_through_ratio_perfect_passthrough() -> None:
    """A layering intermediate who receives $10k then sends $9.5k (within 30% tolerance) → high ratio."""
    ref = pd.Timestamp("2025-01-10T00:00:00")
    rows = [
        # C-HUB sends to C-MID
        {"sender_id": "C-HUB", "receiver_id": "C-MID", "amount": 10000.0,
         "timestamp": ref, "txn_type": "wire"},
        # C-MID sends to C-OUT within 24h (magnitude within 30%: 10000 * 0.7 = 7000 min)
        {"sender_id": "C-MID", "receiver_id": "C-OUT", "amount": 9500.0,
         "timestamp": ref + pd.Timedelta(hours=20), "txn_type": "wire"},
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["layering"])
    assert result.ok
    feat = result.artifacts["features"]
    assert "pass_through_ratio" in feat.columns
    assert "C-MID" in feat.index
    # In a 48h window: C-MID received 10000, sent 9500 → ratio = min/max = 9500/10000 = 0.95
    assert feat.loc["C-MID", "pass_through_ratio"] > 0.7, (
        f"Expected high pass_through_ratio for C-MID, got {feat.loc['C-MID', 'pass_through_ratio']}"
    )


def test_pass_through_ratio_non_passthrough() -> None:
    """A customer who only sends (no inbound) has pass_through_ratio = 0."""
    rows = [
        {"sender_id": "C-SENDER", "receiver_id": "C-R1", "amount": 5000.0},
        {"sender_id": "C-SENDER", "receiver_id": "C-R2", "amount": 3000.0},
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["layering"])
    assert result.ok
    feat = result.artifacts["features"]
    if "C-SENDER" in feat.index:
        assert feat.loc["C-SENDER", "pass_through_ratio"] == 0.0, (
            "Sender-only customer should have pass_through_ratio=0"
        )


# ---------------------------------------------------------------------------
# 6. Contract: output is DataFrame indexed by customer_id
# ---------------------------------------------------------------------------


def test_output_indexed_by_customer_id(sample_ctx: ToolContext) -> None:
    result = feature_engineer(sample_ctx)
    assert result.ok
    feat = result.artifacts["features"]
    assert isinstance(feat, pd.DataFrame)
    assert feat.index.name == "customer_id"


def test_output_feature_list_is_list_of_str(sample_ctx: ToolContext) -> None:
    result = feature_engineer(sample_ctx)
    assert result.ok
    fl = result.artifacts["feature_list"]
    assert isinstance(fl, list)
    assert all(isinstance(f, str) for f in fl)


def test_ctx_df_not_mutated(sample_ctx: ToolContext, sample_df: pd.DataFrame) -> None:
    original_len = len(sample_ctx.df)
    feature_engineer(sample_ctx)
    assert len(sample_ctx.df) == original_len, "feature_engineer mutated ctx.df"


def test_empty_df_returns_ok() -> None:
    df = pd.DataFrame(columns=["txn_id", "timestamp", "sender_id", "receiver_id",
                                "amount", "currency", "txn_type", "channel",
                                "sender_country", "receiver_country", "is_cross_border",
                                "label_is_laundering", "pattern_label"])
    result = feature_engineer(ToolContext(df=df))
    assert result.ok
    assert result.artifacts["feature_list"] == []


# ---------------------------------------------------------------------------
# 7. round_amount_ratio on smurfing cohort
# ---------------------------------------------------------------------------


def test_round_amount_ratio_exact() -> None:
    """3 of 4 txns are $500-divisible → ratio = 0.75."""
    rows = [
        {"sender_id": "C-A", "receiver_id": "C-X", "amount": 9000.0},   # round
        {"sender_id": "C-A", "receiver_id": "C-Y", "amount": 9500.0},   # round
        {"sender_id": "C-A", "receiver_id": "C-Z", "amount": 8500.0},   # round
        {"sender_id": "C-A", "receiver_id": "C-W", "amount": 8750.0},   # NOT round
    ]
    df = _make_tx(rows)
    result = feature_engineer(_ctx(df), pattern_types=["smurfing"])
    assert result.ok
    feat = result.artifacts["features"]
    assert abs(feat.loc["C-A", "round_amount_ratio"] - 0.75) < 0.01
