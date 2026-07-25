"""
data/generate_synthetic.py — Fixed-seed synthetic AML dataset generator.

Produces two files:
    data/sample/aml_sample.csv          (transactions, canonical schema)
    data/sample/aml_sample_customers.csv (customers, canonical schema)

Patterns generated
------------------
1. structuring   : customers making repeated cash/transfer transactions just
                   below $10,000 (the Bank Secrecy Act reporting threshold).
2. smurfing      : a single "hub" customer distributes funds to a ring of
                   "smurf" accounts each making sub-threshold deposits.
3. layering      : linear chain of wire transfers moving funds through
                   multiple intermediate accounts to obscure origin.
4. rapid_cashout : large incoming transfer followed by immediate cash
                   withdrawals within 24 hours.
normal           : regular transaction population (no pattern label).

Parameters logged
-----------------
All generation parameters are printed to stdout and documented below so they
can be copied verbatim into DATA_CARD.md.

PARAMETERS
----------
SEED              = 42          # fixed for reproducibility
TOTAL_ROWS        = 2000        # total transactions in output
NORMAL_CUSTOMERS  = 200         # customers in the normal population
NORMAL_TXN_FRAC   = 0.60        # 60% of rows from normal population

STRUCTURING_CUSTOMERS = 10
STRUCTURING_TXN_PER_CUST = 8   # avg txns per structuring customer
STRUCTURING_WINDOW_DAYS  = 7   # all within 7-day window
STRUCTURING_AMOUNT_MIN   = 8_800
STRUCTURING_AMOUNT_MAX   = 9_999

SMURFING_HUBS   = 3
SMURFING_RING   = 8             # smurf accounts per hub
SMURFING_TXN_PER_SMURF = 2     # deposits per smurf per hub transfer
SMURFING_HUB_AMOUNT_MIN = 50_000
SMURFING_HUB_AMOUNT_MAX = 200_000
SMURFING_SUB_AMOUNT_MIN = 7_000
SMURFING_SUB_AMOUNT_MAX = 9_500

LAYERING_CHAINS         = 5
LAYERING_HOPS           = 4     # intermediate accounts per chain
LAYERING_AMOUNT_MIN     = 20_000
LAYERING_AMOUNT_MAX     = 500_000
LAYERING_HOP_DELAY_HOURS = 12   # hours between hops

RAPID_CASHOUT_CUSTOMERS  = 8
RAPID_CASHOUT_IN_MIN     = 15_000
RAPID_CASHOUT_IN_MAX     = 80_000
RAPID_CASHOUT_SPLITS     = 4    # number of cash withdrawals after receipt
RAPID_CASHOUT_WINDOW_HOURS = 20 # all cashouts within 20 hours of receipt
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Parameters (all documented in the module docstring above)
# ---------------------------------------------------------------------------
SEED = 42
TOTAL_ROWS = 1800  # normal transactions; pattern rows add ~200 more for ~2000 total
NORMAL_CUSTOMERS = 200
NORMAL_TXN_FRAC = 1.00  # TOTAL_ROWS is now the exact normal count

STRUCTURING_CUSTOMERS = 10
STRUCTURING_TXN_PER_CUST = 8
STRUCTURING_WINDOW_DAYS = 7
STRUCTURING_AMOUNT_MIN = 8_800
STRUCTURING_AMOUNT_MAX = 9_999

SMURFING_HUBS = 3
SMURFING_RING = 8
SMURFING_TXN_PER_SMURF = 2
SMURFING_HUB_AMOUNT_MIN = 50_000
SMURFING_HUB_AMOUNT_MAX = 200_000
SMURFING_SUB_AMOUNT_MIN = 7_000
SMURFING_SUB_AMOUNT_MAX = 9_500

LAYERING_CHAINS = 5
LAYERING_HOPS = 4
LAYERING_AMOUNT_MIN = 20_000
LAYERING_AMOUNT_MAX = 500_000
LAYERING_HOP_DELAY_HOURS = 12

RAPID_CASHOUT_CUSTOMERS = 8
RAPID_CASHOUT_IN_MIN = 15_000
RAPID_CASHOUT_IN_MAX = 80_000
RAPID_CASHOUT_SPLITS = 4
RAPID_CASHOUT_WINDOW_HOURS = 20

# Base datetime for the synthetic dataset
BASE_DATE = datetime(2025, 1, 1, 0, 0, 0)
SIM_DAYS = 90  # dataset spans 90 days

OUTPUT_DIR = Path(__file__).parent / "sample"

# Canonical txn_type and channel enums
TXN_TYPES = ["deposit", "withdrawal", "transfer", "wire", "cash"]
CHANNELS = ["atm", "branch", "online", "mobile", "wire"]
CURRENCIES = ["USD"]  # keep synthetic dataset single-currency for simplicity
COUNTRIES = ["US", "GB", "DE", "CA", "FR", "AU", "JP", "SG"]

OCCUPATIONS = [
    "software engineer", "teacher", "nurse", "accountant", "retail worker",
    "consultant", "contractor", "student", "lawyer", "doctor",
]
FIRST_NAMES = [
    "Alice", "Bob", "Carol", "David", "Eva", "Frank", "Grace", "Hank",
    "Irene", "Jack", "Karen", "Leo", "Maria", "Nathan", "Olivia", "Paul",
    "Quinn", "Rachel", "Sam", "Tina", "Uma", "Victor", "Wendy", "Xavier",
    "Yara", "Zack", "Amber", "Brian", "Clara", "Derek",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
    "White", "Harris", "Martin", "Thompson", "Young", "Walker",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rng_name(rng: random.Random, idx: int) -> str:
    first = FIRST_NAMES[idx % len(FIRST_NAMES)]
    last = LAST_NAMES[(idx // len(FIRST_NAMES)) % len(LAST_NAMES)]
    return f"{first} {last}"


def _rand_date_in_window(rng: random.Random, start: datetime, days: int) -> datetime:
    offset_min = int(rng.uniform(0, days * 24 * 60))
    return start + timedelta(minutes=offset_min)


def _hash_risk(cid: str) -> str:
    import hashlib
    val = int(hashlib.md5((cid + "risk").encode()).hexdigest(), 16) % 100
    if val < 80:
        return "low"
    if val < 95:
        return "medium"
    return "high"


def _hash_kyc(cid: str) -> str:
    import hashlib
    val = int(hashlib.md5((cid + "kyc").encode()).hexdigest(), 16) % 100
    if val < 90:
        return "verified"
    if val < 97:
        return "pending"
    return "incomplete"


def _hash_pep(cid: str) -> bool:
    import hashlib
    val = int(hashlib.md5((cid + "pep").encode()).hexdigest(), 16) % 1000
    return val < 15  # ~1.5%


# ---------------------------------------------------------------------------
# Normal population
# ---------------------------------------------------------------------------

def _generate_normal(rng: random.Random, cust_ids: list[str]) -> list[dict]:
    """Generate normal (unlabelled) transactions for the normal population."""
    rows = []
    n_normal = TOTAL_ROWS  # NORMAL_TXN_FRAC is 1.0; TOTAL_ROWS is exact normal count
    for _ in range(n_normal):
        sender = rng.choice(cust_ids)
        receiver = rng.choice(cust_ids)
        ts = _rand_date_in_window(rng, BASE_DATE, SIM_DAYS)
        txn_type = rng.choice(["deposit", "withdrawal", "transfer", "transfer"])
        channel_map = {
            "deposit": rng.choice(["branch", "atm", "online"]),
            "withdrawal": rng.choice(["atm", "branch"]),
            "transfer": rng.choice(["online", "mobile"]),
        }
        channel = channel_map.get(txn_type, "online")
        s_country = rng.choice(COUNTRIES)
        r_country = rng.choice(COUNTRIES)
        rows.append({
            "timestamp": ts,
            "sender_id": sender,
            "receiver_id": receiver,
            "amount": round(rng.uniform(50, 15_000), 2),
            "currency": "USD",
            "txn_type": txn_type,
            "channel": channel,
            "sender_country": s_country,
            "receiver_country": r_country,
            "is_cross_border": s_country != r_country,
            "label_is_laundering": None,
            "pattern_label": None,
        })
    return rows


# ---------------------------------------------------------------------------
# Structuring cohort
# ---------------------------------------------------------------------------

def _generate_structuring(rng: random.Random, cust_ids: list[str]) -> list[dict]:
    """Multiple cash/transfer txns just below $10k within a 7-day window."""
    rows = []
    structuring_ids = [cid for cid in cust_ids if "STR" in cid]
    for cid in structuring_ids:
        window_start = _rand_date_in_window(rng, BASE_DATE, SIM_DAYS - STRUCTURING_WINDOW_DAYS)
        n_txn = rng.randint(STRUCTURING_TXN_PER_CUST - 1, STRUCTURING_TXN_PER_CUST + 2)
        # Receiver is always a random normal account (layering into normal pop)
        receiver = rng.choice([c for c in cust_ids if c != cid and "STR" not in c] or cust_ids)
        for _ in range(n_txn):
            ts = _rand_date_in_window(rng, window_start, STRUCTURING_WINDOW_DAYS)
            rows.append({
                "timestamp": ts,
                "sender_id": cid,
                "receiver_id": receiver,
                "amount": round(rng.uniform(STRUCTURING_AMOUNT_MIN, STRUCTURING_AMOUNT_MAX), 2),
                "currency": "USD",
                "txn_type": rng.choice(["cash", "transfer"]),
                "channel": rng.choice(["branch", "atm"]),
                "sender_country": "US",
                "receiver_country": "US",
                "is_cross_border": False,
                "label_is_laundering": True,
                "pattern_label": "structuring",
            })
    return rows


# ---------------------------------------------------------------------------
# Smurfing cohort
# ---------------------------------------------------------------------------

def _generate_smurfing(rng: random.Random, cust_ids: list[str]) -> list[dict]:
    """Hub receives large amount, fans out to ring of smurfs in sub-threshold deposits."""
    rows = []
    hub_ids = [cid for cid in cust_ids if "HUB" in cid]
    smurf_ids = [cid for cid in cust_ids if "SMF" in cid]
    ring_size = min(SMURFING_RING, len(smurf_ids))

    for i, hub in enumerate(hub_ids):
        start = _rand_date_in_window(rng, BASE_DATE, SIM_DAYS - 10)
        # Hub receives large amount from an external source
        external_sender = rng.choice([c for c in cust_ids if c not in hub_ids + smurf_ids] or cust_ids)
        hub_amount = round(rng.uniform(SMURFING_HUB_AMOUNT_MIN, SMURFING_HUB_AMOUNT_MAX), 2)
        rows.append({
            "timestamp": start,
            "sender_id": external_sender,
            "receiver_id": hub,
            "amount": hub_amount,
            "currency": "USD",
            "txn_type": "wire",
            "channel": "wire",
            "sender_country": "US",
            "receiver_country": "US",
            "is_cross_border": False,
            "label_is_laundering": True,
            "pattern_label": "smurfing",
        })
        # Hub fans out to ring of smurfs
        ring = smurf_ids[i * ring_size:(i + 1) * ring_size]
        if not ring:
            ring = smurf_ids[:ring_size]
        for smurf in ring:
            for _ in range(SMURFING_TXN_PER_SMURF):
                ts = start + timedelta(hours=rng.uniform(1, 48))
                rows.append({
                    "timestamp": ts,
                    "sender_id": hub,
                    "receiver_id": smurf,
                    "amount": round(rng.uniform(SMURFING_SUB_AMOUNT_MIN, SMURFING_SUB_AMOUNT_MAX), 2),
                    "currency": "USD",
                    "txn_type": "transfer",
                    "channel": "online",
                    "sender_country": "US",
                    "receiver_country": "US",
                    "is_cross_border": False,
                    "label_is_laundering": True,
                    "pattern_label": "smurfing",
                })
    return rows


# ---------------------------------------------------------------------------
# Layering cohort
# ---------------------------------------------------------------------------

def _generate_layering(rng: random.Random, cust_ids: list[str]) -> list[dict]:
    """Linear wire chain: A → B → C → D → E, international hops."""
    rows = []
    layering_ids = [cid for cid in cust_ids if "LAY" in cid]
    # Build chains by slicing layering_ids into groups of LAYERING_HOPS+1
    n_ids_per_chain = LAYERING_HOPS + 1
    for chain_idx in range(LAYERING_CHAINS):
        start_idx = chain_idx * n_ids_per_chain
        chain = layering_ids[start_idx:start_idx + n_ids_per_chain]
        if len(chain) < 2:
            break
        ts = _rand_date_in_window(rng, BASE_DATE, SIM_DAYS - 5)
        amount = round(rng.uniform(LAYERING_AMOUNT_MIN, LAYERING_AMOUNT_MAX), 2)
        countries = rng.sample(COUNTRIES, min(len(chain), len(COUNTRIES)))
        while len(countries) < len(chain):
            countries.append(rng.choice(COUNTRIES))
        for hop_idx in range(len(chain) - 1):
            sender = chain[hop_idx]
            receiver = chain[hop_idx + 1]
            s_country = countries[hop_idx]
            r_country = countries[hop_idx + 1]
            rows.append({
                "timestamp": ts,
                "sender_id": sender,
                "receiver_id": receiver,
                "amount": round(amount * rng.uniform(0.90, 1.00), 2),  # slight reduction per hop
                "currency": "USD",
                "txn_type": "wire",
                "channel": "wire",
                "sender_country": s_country,
                "receiver_country": r_country,
                "is_cross_border": s_country != r_country,
                "label_is_laundering": True,
                "pattern_label": "layering",
            })
            ts += timedelta(hours=LAYERING_HOP_DELAY_HOURS)
    return rows


# ---------------------------------------------------------------------------
# Rapid cashout cohort
# ---------------------------------------------------------------------------

def _generate_rapid_cashout(rng: random.Random, cust_ids: list[str]) -> list[dict]:
    """Large inbound wire followed by multiple ATM/cash withdrawals within 20h."""
    rows = []
    cashout_ids = [cid for cid in cust_ids if "RCO" in cid]
    for cid in cashout_ids:
        ts_in = _rand_date_in_window(rng, BASE_DATE, SIM_DAYS - 2)
        in_amount = round(rng.uniform(RAPID_CASHOUT_IN_MIN, RAPID_CASHOUT_IN_MAX), 2)
        sender = rng.choice([c for c in cust_ids if c != cid and "RCO" not in c] or cust_ids)
        rows.append({
            "timestamp": ts_in,
            "sender_id": sender,
            "receiver_id": cid,
            "amount": in_amount,
            "currency": "USD",
            "txn_type": "wire",
            "channel": "wire",
            "sender_country": rng.choice(COUNTRIES),
            "receiver_country": "US",
            "is_cross_border": True,
            "label_is_laundering": True,
            "pattern_label": "rapid_cashout",
        })
        per_split = round(in_amount / RAPID_CASHOUT_SPLITS * rng.uniform(0.85, 0.98), 2)
        for _ in range(RAPID_CASHOUT_SPLITS):
            ts_out = ts_in + timedelta(hours=rng.uniform(0.5, RAPID_CASHOUT_WINDOW_HOURS))
            rows.append({
                "timestamp": ts_out,
                "sender_id": cid,
                "receiver_id": rng.choice([c for c in cust_ids if c != cid] or cust_ids),
                "amount": per_split,
                "currency": "USD",
                "txn_type": "cash",
                "channel": rng.choice(["atm", "branch"]),
                "sender_country": "US",
                "receiver_country": "US",
                "is_cross_border": False,
                "label_is_laundering": True,
                "pattern_label": "rapid_cashout",
            })
    return rows


# ---------------------------------------------------------------------------
# Customer table generator
# ---------------------------------------------------------------------------

def _generate_customers(
    rng: random.Random,
    all_cids: list[str],
    tx_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build canonical customers table for all generated customer IDs."""
    rows = []
    names_used: set[str] = set()
    open_start = date(2015, 1, 1)

    for idx, cid in enumerate(all_cids):
        # name: deterministic from index
        name = _rng_name(rng, idx)
        while name in names_used:
            name = f"{name} Jr."
        names_used.add(name)

        # account_open_date: random in [2015-01-01, 2022-12-31]
        open_offset = rng.randint(0, (date(2022, 12, 31) - open_start).days)
        open_d = open_start + timedelta(days=open_offset)

        # customer_type: cohort-based, then fallback distribution
        if "HUB" in cid or "LAY" in cid or "RCO" in cid:
            ctype = "business"
        elif "SMF" in cid or "STR" in cid:
            ctype = "individual"
        else:
            ctype = "individual" if rng.random() < 0.85 else "business"

        country = rng.choice(COUNTRIES)
        occ = rng.choice(OCCUPATIONS) if ctype == "individual" else "corporate banking"

        risk = _hash_risk(cid)
        kyc = _hash_kyc(cid)
        pep = _hash_pep(cid)

        # expected_monthly_volume: median of actual monthly sent amounts
        cust_tx = tx_df[tx_df["sender_id"] == cid]
        if len(cust_tx) > 0:
            tmp = cust_tx.copy()
            tmp["month"] = pd.to_datetime(tmp["timestamp"]).dt.to_period("M")
            monthly = tmp.groupby("month")["amount"].sum()
            exp_vol = float(round(monthly.median(), 2))
        else:
            exp_vol = round(rng.uniform(1_000, 20_000), 2)

        rows.append({
            "customer_id": cid,
            "name": name,
            "account_open_date": open_d,
            "customer_type": ctype,
            "country": country,
            "occupation": occ,
            "risk_rating": risk,
            "kyc_status": kyc,
            "is_pep": pep,
            "expected_monthly_volume": exp_vol,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(output_dir: Path = OUTPUT_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate the synthetic dataset. Returns (transactions_df, customers_df)."""
    print("=" * 60)
    print("SYNTHETIC DATASET GENERATION PARAMETERS")
    print("=" * 60)
    print(f"SEED                     = {SEED}")
    print(f"TOTAL_ROWS (normal rows) = {TOTAL_ROWS}")
    print(f"NORMAL_CUSTOMERS         = {NORMAL_CUSTOMERS} (pattern rows add ~200 more)")
    print(f"NORMAL_TXN_FRAC          = {NORMAL_TXN_FRAC} (1.0 = TOTAL_ROWS is exact normal count)")
    print(f"STRUCTURING_CUSTOMERS    = {STRUCTURING_CUSTOMERS}")
    print(f"STRUCTURING_TXN_PER_CUST = {STRUCTURING_TXN_PER_CUST}")
    print(f"STRUCTURING_WINDOW_DAYS  = {STRUCTURING_WINDOW_DAYS}")
    print(f"STRUCTURING_AMOUNT       = [{STRUCTURING_AMOUNT_MIN}, {STRUCTURING_AMOUNT_MAX}]")
    print(f"SMURFING_HUBS            = {SMURFING_HUBS}")
    print(f"SMURFING_RING            = {SMURFING_RING}")
    print(f"SMURFING_TXN_PER_SMURF   = {SMURFING_TXN_PER_SMURF}")
    print(f"SMURFING_HUB_AMOUNT      = [{SMURFING_HUB_AMOUNT_MIN}, {SMURFING_HUB_AMOUNT_MAX}]")
    print(f"SMURFING_SUB_AMOUNT      = [{SMURFING_SUB_AMOUNT_MIN}, {SMURFING_SUB_AMOUNT_MAX}]")
    print(f"LAYERING_CHAINS          = {LAYERING_CHAINS}")
    print(f"LAYERING_HOPS            = {LAYERING_HOPS}")
    print(f"LAYERING_AMOUNT          = [{LAYERING_AMOUNT_MIN}, {LAYERING_AMOUNT_MAX}]")
    print(f"LAYERING_HOP_DELAY_HOURS = {LAYERING_HOP_DELAY_HOURS}")
    print(f"RAPID_CASHOUT_CUSTOMERS  = {RAPID_CASHOUT_CUSTOMERS}")
    print(f"RAPID_CASHOUT_IN         = [{RAPID_CASHOUT_IN_MIN}, {RAPID_CASHOUT_IN_MAX}]")
    print(f"RAPID_CASHOUT_SPLITS     = {RAPID_CASHOUT_SPLITS}")
    print(f"RAPID_CASHOUT_WINDOW_H   = {RAPID_CASHOUT_WINDOW_HOURS}")
    print("=" * 60)

    rng = random.Random(SEED)
    np.random.seed(SEED)

    # ------------------------------------------------------------------
    # Build customer ID pools (distinct prefixes for each cohort)
    # ------------------------------------------------------------------
    normal_ids = [f"C-N{i:04d}" for i in range(1, NORMAL_CUSTOMERS + 1)]
    structuring_ids = [f"C-STR{i:02d}" for i in range(1, STRUCTURING_CUSTOMERS + 1)]
    hub_ids = [f"C-HUB{i:02d}" for i in range(1, SMURFING_HUBS + 1)]
    smurf_ids = [f"C-SMF{i:02d}" for i in range(1, SMURFING_HUBS * SMURFING_RING + 1)]
    layering_ids = [
        f"C-LAY{i:02d}"
        for i in range(1, LAYERING_CHAINS * (LAYERING_HOPS + 1) + 1)
    ]
    cashout_ids = [f"C-RCO{i:02d}" for i in range(1, RAPID_CASHOUT_CUSTOMERS + 1)]

    all_cids = (
        normal_ids + structuring_ids + hub_ids +
        smurf_ids + layering_ids + cashout_ids
    )

    print(f"Customer pool: {len(all_cids)} unique IDs "
          f"({len(normal_ids)} normal, {len(structuring_ids)} structuring, "
          f"{len(hub_ids)} smurfing hubs, {len(smurf_ids)} smurfs, "
          f"{len(layering_ids)} layering, {len(cashout_ids)} rapid_cashout)")

    # ------------------------------------------------------------------
    # Generate all transaction rows
    # ------------------------------------------------------------------
    rows: list[dict] = []
    rows.extend(_generate_normal(rng, all_cids))
    rows.extend(_generate_structuring(rng, all_cids))
    rows.extend(_generate_smurfing(rng, all_cids))
    rows.extend(_generate_layering(rng, all_cids))
    rows.extend(_generate_rapid_cashout(rng, all_cids))

    # Shuffle so patterns are mixed with normal rows
    rng.shuffle(rows)

    # Assign txn_ids after shuffle
    for i, row in enumerate(rows):
        row["txn_id"] = f"T-{i + 1:06d}"

    tx_df = pd.DataFrame(rows)

    # Enforce column order and types
    tx_df["timestamp"] = pd.to_datetime(tx_df["timestamp"])
    tx_df["is_cross_border"] = tx_df["is_cross_border"].astype(bool)
    tx_df = tx_df[[
        "txn_id", "timestamp", "sender_id", "receiver_id",
        "amount", "currency", "txn_type", "channel",
        "sender_country", "receiver_country", "is_cross_border",
        "label_is_laundering", "pattern_label",
    ]]

    # ------------------------------------------------------------------
    # Generate customers table
    # ------------------------------------------------------------------
    cust_df = _generate_customers(rng, all_cids, tx_df)

    # ------------------------------------------------------------------
    # Print statistics
    # ------------------------------------------------------------------
    print()
    print("=== GENERATION SUMMARY ===")
    print(f"Total transactions : {len(tx_df):,}")
    print(f"Total customers    : {len(cust_df):,}")
    print()
    print("Pattern breakdown:")
    print(tx_df["pattern_label"].value_counts(dropna=False).to_string())
    print()
    print("label_is_laundering:")
    print(tx_df["label_is_laundering"].value_counts(dropna=False).to_string())
    print()
    print("customer_type distribution:")
    print(cust_df["customer_type"].value_counts().to_string())
    print()
    print("risk_rating distribution:")
    print(cust_df["risk_rating"].value_counts().to_string())
    print()
    print("kyc_status distribution:")
    print(cust_df["kyc_status"].value_counts().to_string())
    print()
    print(f"PEP count: {cust_df['is_pep'].sum()} ({100*cust_df['is_pep'].mean():.1f}%)")

    # ------------------------------------------------------------------
    # Write output files
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    tx_path = output_dir / "aml_sample.csv"
    cust_path = output_dir / "aml_sample_customers.csv"
    tx_df.to_csv(tx_path, index=False)
    cust_df.to_csv(cust_path, index=False)
    print()
    print(f"Written: {tx_path}")
    print(f"Written: {cust_path}")

    return tx_df, cust_df


if __name__ == "__main__":
    generate()
