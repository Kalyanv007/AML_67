"""
data/build_ibm_cache.py — one-time offline cache builder
=========================================================

Run this script ONCE on a machine that has the IBM AML HI-Small dataset
downloaded via kagglehub.  It:

  1. Runs the stratified sampler over the full 5M-row CSV (takes ~150s).
  2. Writes the result to data/processed/ibm_stratified_sample.parquet.
  3. Writes a sidecar metadata file so it's obvious when the cache is stale.

After this runs, load_data(source='ibm_stratified') reads the parquet directly
instead of re-reading the raw CSV, cutting load time from ~153s to ~2s.

Usage:
    python data/build_ibm_cache.py [--target-size N] [--max-pos-customers M] [--seed S] [--force]

Flags:
    --target-size          Approximate total transaction count (default: 200000)
    --max-pos-customers    Hard cap on laundering-positive customers (default: 500)
    --seed                 Random seed for clean-customer sampling (default: 42)
    --force                Overwrite existing cache even if present
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running as a script from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.tools.data_loader import _stratified_sample_ibm, _IBM_TRANS_FILE, _IBM_ACCTS_FILE

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CACHE_DIR = Path(__file__).parent / "processed"
CACHE_TX   = CACHE_DIR / "ibm_stratified_sample.parquet"
CACHE_CUST = CACHE_DIR / "ibm_stratified_customers.parquet"
CACHE_META = CACHE_DIR / "ibm_stratified_cache_meta.json"


def build(
    target_size: int = 200_000,
    max_pos_customers: int = 500,
    seed: int = 42,
    force: bool = False,
) -> None:
    """Build (or rebuild) the stratified IBM sample cache."""
    if not _IBM_TRANS_FILE.exists():
        print(
            f"ERROR: IBM HI-Small dataset not found at {_IBM_TRANS_FILE}.\n"
            "Run: python -c \"import kagglehub; kagglehub.dataset_download("
            "'ealtman2019/ibm-transactions-for-anti-money-laundering-aml')\""
        )
        sys.exit(1)

    if CACHE_TX.exists() and not force:
        meta = {}
        if CACHE_META.exists():
            with open(CACHE_META) as f:
                meta = json.load(f)
        print(
            f"Cache already exists: {CACHE_TX}\n"
            f"  rows={meta.get('row_count','?')}, "
            f"target={meta.get('target_size','?')}, "
            f"max_pos={meta.get('max_pos_customers','?')}, "
            f"seed={meta.get('seed','?')}, "
            f"built={meta.get('built_utc','?')}\n"
            "Use --force to rebuild."
        )
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(
        f"Building stratified IBM cache...\n"
        f"  target_size={target_size:,}, max_pos_customers={max_pos_customers}, seed={seed}"
    )
    print(f"  Source: {_IBM_TRANS_FILE}")

    t0 = time.time()
    tx_df, cust_df = _stratified_sample_ibm(
        trans_path=str(_IBM_TRANS_FILE),
        accts_path=str(_IBM_ACCTS_FILE),
        target_size=target_size,
        max_pos_customers=max_pos_customers,
        seed=seed,
    )
    elapsed = time.time() - t0

    pos_count = int(tx_df["label_is_laundering"].sum())
    pos_rate  = pos_count / len(tx_df) * 100

    print(f"  Stratification done in {elapsed:.1f}s")
    print(f"  Rows: {len(tx_df):,} | Customers: {tx_df['sender_id'].nunique():,}")
    print(f"  Positive rows: {pos_count:,} ({pos_rate:.2f}%)")

    # Write parquet files
    tx_df.to_parquet(CACHE_TX, index=False)
    cust_df.to_parquet(CACHE_CUST, index=False)

    # Write sidecar metadata
    meta = {
        "built_utc":        datetime.now(timezone.utc).isoformat(),
        "source_csv":       str(_IBM_TRANS_FILE),
        "target_size":      target_size,
        "max_pos_customers": max_pos_customers,
        "seed":             seed,
        "row_count":        len(tx_df),
        "customer_count":   int(tx_df["sender_id"].nunique()),
        "pos_row_count":    pos_count,
        "pos_rate_pct":     round(pos_rate, 4),
        "build_seconds":    round(elapsed, 1),
    }
    with open(CACHE_META, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nCache written to {CACHE_DIR}/")
    print(f"  {CACHE_TX.name}")
    print(f"  {CACHE_CUST.name}")
    print(f"  {CACHE_META.name}")
    print(f"\nNext load_data(source='ibm_stratified') will read from cache (~2s vs {elapsed:.0f}s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build IBM stratified sample parquet cache.")
    parser.add_argument("--target-size",       type=int, default=200_000)
    parser.add_argument("--max-pos-customers", type=int, default=500)
    parser.add_argument("--seed",              type=int, default=42)
    parser.add_argument("--force",             action="store_true")
    args = parser.parse_args()
    build(
        target_size=args.target_size,
        max_pos_customers=args.max_pos_customers,
        seed=args.seed,
        force=args.force,
    )
