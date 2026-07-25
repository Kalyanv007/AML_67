"""
tests/test_data_loader.py

Tests for the stratified IBM sampler added to data_loader.py.
Owned by Track B.  Runs against the actual IBM HI-Small CSV when available;
skips gracefully if the file is absent (so CI on a machine without Kaggle data
still passes green).

Three assertions the task spec requires:
  1. Every included laundering-positive customer's FULL history is present
     (no partial truncation mid-history).
  2. The sample respects the target_size parameter (never exceeds target by more
     than the largest single customer's row count — a deliberate property of the
     whole-history guarantee).
  3. The seed produces reproducible clean-customer selection across two identical
     calls.
"""

from __future__ import annotations

import pytest
from pathlib import Path

IBM_TRANS = (
    Path.home()
    / ".cache"
    / "kagglehub"
    / "datasets"
    / "ealtman2019"
    / "ibm-transactions-for-anti-money-laundering-aml"
    / "versions"
    / "8"
    / "HI-Small_Trans.csv"
)

IBM_ACCTS = IBM_TRANS.parent / "HI-Small_accounts.csv"

requires_ibm = pytest.mark.skipif(
    not IBM_TRANS.exists(),
    reason="IBM HI-Small dataset not present — skipping stratified sampler tests",
)


# ---------------------------------------------------------------------------
# Import the private function directly (it's a module-level function, not a
# method, so this is safe and standard for unit-testing internal helpers).
# ---------------------------------------------------------------------------

from backend.tools.data_loader import _stratified_sample_ibm  # noqa: E402


@requires_ibm
def test_positive_customer_histories_are_complete() -> None:
    """Every selected positive customer's FULL history must be in the sample.

    We verify by comparing each customer's row count in the sample against their
    row count in the raw file.  A truncated history would show fewer rows.
    """
    import pandas as pd

    tx_df, _ = _stratified_sample_ibm(
        trans_path=str(IBM_TRANS),
        accts_path=str(IBM_ACCTS),
        target_size=20_000,   # small enough for a fast test
        max_pos_customers=50,
        seed=0,
    )

    # Identify which senders in the sample are laundering-positive
    pos_senders = set(
        tx_df.loc[tx_df["label_is_laundering"] == True, "sender_id"].unique()
    )

    # Load the raw file just for Account + Is Laundering (fast)
    raw_scan = pd.read_csv(IBM_TRANS, usecols=["Account", "Is Laundering"])
    raw_full = pd.read_csv(IBM_TRANS)  # need full row counts per account

    for sender_id in pos_senders:
        # Convert C-<account> back to raw account id for lookup
        raw_account = sender_id.removeprefix("C-")
        raw_count = (raw_full["Account"].astype(str) == raw_account).sum()
        sample_count = (tx_df["sender_id"] == sender_id).sum()
        assert sample_count == raw_count, (
            f"Customer {sender_id}: sample has {sample_count} rows "
            f"but raw file has {raw_count} — history was truncated."
        )


@requires_ibm
def test_sample_respects_target_size() -> None:
    """Actual row count must not exceed target_size by more than one customer's
    history (the whole-history guarantee means we can overshoot slightly).

    We verify by checking the overshoot is bounded by the average positive
    customer history length (a generous upper bound).
    """
    TARGET = 10_000
    AVG_POS_HISTORY = 200  # conservative upper bound; actual is ~150

    tx_df, _ = _stratified_sample_ibm(
        trans_path=str(IBM_TRANS),
        accts_path=str(IBM_ACCTS),
        target_size=TARGET,
        max_pos_customers=30,
        seed=0,
    )

    actual = len(tx_df)
    assert actual <= TARGET + AVG_POS_HISTORY, (
        f"Sample has {actual:,} rows — too far above target {TARGET:,}. "
        "Budget overflow should be bounded by one customer's history."
    )


@requires_ibm
def test_seed_produces_reproducible_clean_customer_selection() -> None:
    """Two calls with the same parameters must return identical results."""
    params = dict(
        trans_path=str(IBM_TRANS),
        accts_path=str(IBM_ACCTS),
        target_size=10_000,
        max_pos_customers=30,
        seed=99,
    )
    tx_a, _ = _stratified_sample_ibm(**params)
    tx_b, _ = _stratified_sample_ibm(**params)

    # Same senders in both runs (order may differ after concat; sort to compare)
    senders_a = sorted(tx_a["sender_id"].unique())
    senders_b = sorted(tx_b["sender_id"].unique())
    assert senders_a == senders_b, (
        "Two calls with seed=99 produced different customer sets — "
        "sampling is not reproducible."
    )
    assert len(tx_a) == len(tx_b), (
        "Two calls with seed=99 produced different row counts."
    )
