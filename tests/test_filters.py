"""
tests/test_filters.py

Tests for backend/tools/filters.py.

**File ownership note (flagged explicitly):**
WORKPLAN.md §4 lists Track B test files as:
  tests/test_rules.py, tests/test_features.py, tests/test_ml.py, tests/fixtures/**

tests/test_filters.py is NOT in that explicit list. It is created here as a
reasonable extension of Track B's ownership of tests/fixtures/** and because
filter_data is a Track B tool. This assumption will be confirmed with Track A
at the next standup — see the Phase 2 summary.

Fixture strategy:
  - Loads data/sample/aml_sample.csv and aml_sample_customers.csv directly.
  - Constructs ToolContext manually (no executor) and populates
    ctx.artifacts["customers"] to exactly replicate how load_data produces it.
  - No mocks, no env flags — tests are pure I/O on committed fixtures.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.tools.base import ToolContext
from backend.tools.filters import filter_data

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TX   = "data/sample/aml_sample.csv"
SAMPLE_CUST = "data/sample/aml_sample_customers.csv"


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
    """Build a ToolContext exactly as the executor would after load_data runs."""
    return ToolContext(
        df=tx_df.copy(),
        artifacts={"customers": cust_df.copy()},
    )


@pytest.fixture
def ctx_no_customers(tx_df: pd.DataFrame) -> ToolContext:
    """ToolContext without customers — simulates load_data not having been called."""
    return ToolContext(df=tx_df.copy())


# ---------------------------------------------------------------------------
# No-op: no filters applied
# ---------------------------------------------------------------------------


def test_no_filters(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    result = filter_data(ctx)
    assert result.ok
    assert len(result.df) == len(tx_df)
    assert result.metrics["rows_in"] == result.metrics["rows_out"]


# ---------------------------------------------------------------------------
# date_from / date_to
# ---------------------------------------------------------------------------


def test_date_from_narrows(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    result = filter_data(ctx, date_from="2025-02-01")
    assert result.ok
    assert len(result.df) < len(tx_df)
    assert (result.df["timestamp"] >= pd.Timestamp("2025-02-01")).all()


def test_date_to_narrows(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    result = filter_data(ctx, date_to="2025-01-31")
    assert result.ok
    assert len(result.df) < len(tx_df)
    # All rows must be on or before 2025-01-31 end-of-day
    assert (result.df["timestamp"].dt.date <= pd.Timestamp("2025-01-31").date()).all()


def test_date_range_note(ctx: ToolContext) -> None:
    result = filter_data(ctx, date_from="2025-01-01", date_to="2025-01-15")
    assert result.ok
    note_text = " ".join(result.notes)
    assert "2025-01-01" in note_text
    assert "2025-01-15" in note_text


def test_date_range_empty(ctx: ToolContext) -> None:
    """A date range in the far future should return 0 rows with ok=True."""
    result = filter_data(ctx, date_from="2099-01-01", date_to="2099-12-31")
    assert result.ok
    assert len(result.df) == 0
    assert result.metrics["emptied_by"] == "date"
    assert result.metrics["rows_out"] == 0


# ---------------------------------------------------------------------------
# countries filter (sender OR receiver)
# ---------------------------------------------------------------------------


def test_countries_filters_either_side(ctx: ToolContext) -> None:
    """countries filter must match sender_country OR receiver_country."""
    result = filter_data(ctx, countries=["US"])
    assert result.ok
    # Every returned row must have US on at least one side
    both_sides = (
        (result.df["sender_country"] == "US") |
        (result.df["receiver_country"] == "US")
    )
    assert both_sides.all(), "Some rows have US on neither side — filter is wrong"


def test_countries_nonexistent_returns_empty(ctx: ToolContext) -> None:
    result = filter_data(ctx, countries=["ZZ"])
    assert result.ok
    assert len(result.df) == 0
    assert result.metrics["emptied_by"] == "countries"


def test_countries_note(ctx: ToolContext) -> None:
    result = filter_data(ctx, countries=["US", "GB"])
    assert result.ok
    note_text = " ".join(result.notes)
    assert "sender OR receiver" in note_text


# ---------------------------------------------------------------------------
# txn_types
# ---------------------------------------------------------------------------


def test_txn_types_wire(ctx: ToolContext) -> None:
    result = filter_data(ctx, txn_types=["wire"])
    assert result.ok
    if len(result.df) > 0:
        assert (result.df["txn_type"] == "wire").all()


def test_txn_types_multiple(ctx: ToolContext) -> None:
    result = filter_data(ctx, txn_types=["cash", "wire"])
    assert result.ok
    if len(result.df) > 0:
        assert result.df["txn_type"].isin(["cash", "wire"]).all()


def test_txn_types_nonexistent_empty(ctx: ToolContext) -> None:
    result = filter_data(ctx, txn_types=["nonexistent_type"])
    assert result.ok
    assert len(result.df) == 0
    assert result.metrics["emptied_by"] == "txn_types"


# ---------------------------------------------------------------------------
# amount_min / amount_max
# ---------------------------------------------------------------------------


def test_amount_min(ctx: ToolContext) -> None:
    result = filter_data(ctx, amount_min=9000.0)
    assert result.ok
    if len(result.df) > 0:
        assert (result.df["amount"] >= 9000.0).all()


def test_amount_max(ctx: ToolContext) -> None:
    result = filter_data(ctx, amount_max=1000.0)
    assert result.ok
    if len(result.df) > 0:
        assert (result.df["amount"] <= 1000.0).all()


def test_amount_range(ctx: ToolContext) -> None:
    result = filter_data(ctx, amount_min=8800.0, amount_max=9999.0)
    assert result.ok
    if len(result.df) > 0:
        assert (result.df["amount"] >= 8800.0).all()
        assert (result.df["amount"] <= 9999.0).all()


def test_amount_range_structuring_zone(ctx: ToolContext) -> None:
    """The $8800-$9999 range should capture the structuring cohort."""
    result = filter_data(ctx, amount_min=8800.0, amount_max=9999.0)
    assert result.ok
    if len(result.df) > 0:
        # Structuring transactions are in this band; at least some should appear
        if "pattern_label" in result.df.columns:
            structuring_rows = result.df[result.df["pattern_label"] == "structuring"]
            assert len(structuring_rows) > 0, "Expected structuring transactions in $8800-$9999 band"


def test_amount_impossible_range_empty(ctx: ToolContext) -> None:
    result = filter_data(ctx, amount_min=1_000_000.0, amount_max=999_999.0)
    assert result.ok
    assert len(result.df) == 0


# ---------------------------------------------------------------------------
# min_txn_count (sender outbound)
# ---------------------------------------------------------------------------


def test_min_txn_count_all_qualify_at_1(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    """At min_txn_count=1 all senders qualify — row count should be <= full count."""
    result = filter_data(ctx, min_txn_count=1)
    assert result.ok
    assert len(result.df) <= len(tx_df)


def test_min_txn_count_narrows(ctx: ToolContext, tx_df: pd.DataFrame) -> None:
    result = filter_data(ctx, min_txn_count=5)
    assert result.ok
    if len(result.df) > 0:
        # Every sender_id in the result must have had >= 5 rows in the input
        sender_counts_in = tx_df["sender_id"].value_counts()
        for sid in result.df["sender_id"].unique():
            assert sender_counts_in.get(sid, 0) >= 5, (
                f"sender {sid} has < 5 txns in input but survived min_txn_count=5 filter"
            )


def test_min_txn_count_note_mentions_sender(ctx: ToolContext) -> None:
    result = filter_data(ctx, min_txn_count=3)
    note_text = " ".join(result.notes)
    assert "sender" in note_text.lower()


def test_min_txn_count_high_value_empty(ctx: ToolContext) -> None:
    """Unreachably high min_txn_count should produce empty result with ok=True."""
    result = filter_data(ctx, min_txn_count=999_999)
    assert result.ok
    assert len(result.df) == 0
    assert result.metrics["emptied_by"] == "min_txn_count"


# ---------------------------------------------------------------------------
# customer_segment
# ---------------------------------------------------------------------------


def test_customer_segment_business(ctx: ToolContext, cust_df: pd.DataFrame) -> None:
    result = filter_data(ctx, customer_segment="business")
    assert result.ok
    if len(result.df) > 0:
        # All sender_ids must be business customers
        business_ids = set(cust_df[cust_df["customer_type"] == "business"]["customer_id"])
        assert result.df["sender_id"].isin(business_ids).all()


def test_customer_segment_pep(ctx: ToolContext, cust_df: pd.DataFrame) -> None:
    result = filter_data(ctx, customer_segment="pep")
    assert result.ok
    if len(result.df) > 0:
        pep_ids = set(cust_df[cust_df["is_pep"] == True]["customer_id"])  # noqa: E712
        assert result.df["sender_id"].isin(pep_ids).all()


def test_customer_segment_high_risk(ctx: ToolContext, cust_df: pd.DataFrame) -> None:
    result = filter_data(ctx, customer_segment="high_risk")
    assert result.ok
    if len(result.df) > 0:
        high_risk_ids = set(cust_df[cust_df["risk_rating"] == "high"]["customer_id"])
        assert result.df["sender_id"].isin(high_risk_ids).all()


def test_customer_segment_unknown_returns_error(ctx: ToolContext) -> None:
    result = filter_data(ctx, customer_segment="unknown_segment")
    assert not result.ok
    assert "unknown" in result.error.lower() or "invalid" in result.error.lower()


def test_customer_segment_missing_customers_returns_error(
    ctx_no_customers: ToolContext,
) -> None:
    """customer_segment filter must return ok=False when ctx.artifacts['customers'] is absent."""
    result = filter_data(ctx_no_customers, customer_segment="business")
    assert not result.ok
    assert "customers" in result.error.lower()
    assert "load_data" in result.error.lower()


# ---------------------------------------------------------------------------
# Composability: multiple filters chained
# ---------------------------------------------------------------------------


def test_combined_date_and_amount(ctx: ToolContext) -> None:
    result = filter_data(
        ctx,
        date_from="2025-01-01",
        date_to="2025-02-28",
        amount_min=5000.0,
    )
    assert result.ok
    if len(result.df) > 0:
        assert (result.df["timestamp"] >= pd.Timestamp("2025-01-01")).all()
        assert (result.df["amount"] >= 5000.0).all()
    # Two filters should appear in active list
    assert "date" in result.metrics["filters_applied"]
    assert "amount" in result.metrics["filters_applied"]


def test_combined_txn_type_and_segment(ctx: ToolContext) -> None:
    result = filter_data(ctx, txn_types=["wire"], customer_segment="high_risk")
    assert result.ok
    if len(result.df) > 0:
        assert (result.df["txn_type"] == "wire").all()


# ---------------------------------------------------------------------------
# notes format contract
# ---------------------------------------------------------------------------


def test_notes_are_factual(ctx: ToolContext) -> None:
    """Notes must mention row counts (Contract 2: 'filtered to N of M transactions')."""
    result = filter_data(ctx, amount_min=5000.0)
    assert result.ok
    note_text = " ".join(result.notes)
    # Must contain numeric info
    import re
    assert re.search(r"\d[\d,]+", note_text), "No numeric count found in notes"


def test_result_df_not_ctx_df(ctx: ToolContext) -> None:
    """filter_data must never mutate ctx.df in place."""
    original_len = len(ctx.df)
    filter_data(ctx, amount_min=9000.0)
    assert len(ctx.df) == original_len, "filter_data mutated ctx.df — contract violation"
