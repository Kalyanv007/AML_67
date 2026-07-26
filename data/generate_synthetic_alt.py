"""
data/generate_synthetic_alt.py — Fixed-seed synthetic AML dataset generator,
alternate raw schema.

Produces two files:
    data/sample/aml_sample_alt.csv           (transactions, ALT raw schema)
    data/sample/aml_sample_alt_customers.csv (customers, ALT raw schema)

This generator reuses the same cohort-based pattern logic as
data/generate_synthetic.py (structuring, smurfing, layering, rapid_cashout,
normal) but with a different seed and different cohort sizes, so the
underlying dataset is genuinely distinct — not a re-serialization of
aml_sample.csv. The output columns are deliberately renamed/re-encoded
relative to the canonical schema (docs/CONTRACTS.md Contract 0) to exercise
the backend/tools/data_loader.py `_adapt_synthetic_alt` adapter:

    canonical column      -> alt raw column   (encoding change)
    ---------------------------------------------------------------
    txn_id                -> ref_no           (same format)
    timestamp              -> event_ts         (same)
    sender_id              -> debit_acct       (prefix ACC- instead of C-)
    receiver_id             -> credit_acct      (prefix ACC- instead of C-)
    amount                 -> txn_value        (same)
    currency                -> ccy              (same)
    txn_type                -> activity_code    (DEP/WD/XFER/WIRE/CSH)
    channel                 -> channel_cd       (ATM/BRN/ONL/MOB/WR)
    sender_country           -> orig_ctry        (same ISO2)
    receiver_country          -> dest_ctry        (same ISO2)
    is_cross_border           -> (omitted)        adapter derives it
    label_is_laundering        -> aml_flag         (Y/N/blank instead of bool)
    pattern_label             -> typology         (UPPERCASE)

    customer_id             -> acct_id          (prefix ACC-)
    name                    -> cust_name        (same)
    account_open_date        -> open_dt          (same)
    customer_type            -> segment          (RETAIL/CORP)
    country                  -> domicile         (same)
    occupation                -> job_title        (same)
    risk_rating               -> risk_tier        (L/M/H)
    kyc_status                -> kyc_stat         (V/P/I)
    is_pep                    -> pep_ind          (Y/N instead of bool)
    expected_monthly_volume    -> exp_vol_monthly  (same)
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
SEED = 99
TOTAL_ROWS = 1500  # normal transactions; pattern rows add more on top
NORMAL_CUSTOMERS = 220

STRUCTURING_CUSTOMERS = 12
STRUCTURING_TXN_PER_CUST = 7
STRUCTURING_WINDOW_DAYS = 7
STRUCTURING_AMOUNT_MIN = 8_800
STRUCTURING_AMOUNT_MAX = 9_999

SMURFING_HUBS = 4
SMURFING_RING = 6
SMURFING_TXN_PER_SMURF = 2
SMURFING_HUB_AMOUNT_MIN = 50_000
SMURFING_HUB_AMOUNT_MAX = 200_000
SMURFING_SUB_AMOUNT_MIN = 7_000
SMURFING_SUB_AMOUNT_MAX = 9_500

LAYERING_CHAINS = 6
LAYERING_HOPS = 3
LAYERING_AMOUNT_MIN = 20_000
LAYERING_AMOUNT_MAX = 500_000
LAYERING_HOP_DELAY_HOURS = 12

RAPID_CASHOUT_CUSTOMERS = 10
RAPID_CASHOUT_IN_MIN = 15_000
RAPID_CASHOUT_IN_MAX = 80_000
RAPID_CASHOUT_SPLITS = 4
RAPID_CASHOUT_WINDOW_HOURS = 20

BASE_DATE = datetime(2025, 3, 1, 0, 0, 0)
SIM_DAYS = 90

OUTPUT_DIR = Path(__file__).parent / "sample"

TXN_TYPES = ["deposit", "withdrawal", "transfer", "wire", "cash"]
CHANNELS = ["atm", "branch", "online", "mobile", "wire"]
COUNTRIES = ["US", "GB", "DE", "CA", "FR", "AU", "JP", "SG"]

OCCUPATIONS = [
    "software engineer", "teacher", "nurse", "accountant", "retail worker",
    "consultant", "contractor", "student", "lawyer", "doctor",
]
FIRST_NAMES = [
    "Ivan", "Nora", "Omar", "Priya", "Quincy", "Rosa", "Sami", "Talia",
    "Ugo", "Vera", "Walt", "Ximena", "Yusuf", "Zoe", "Adrian", "Bianca",
    "Cyrus", "Delia", "Ewan", "Freya", "Gustavo", "Hana", "Ilia", "Juno",
    "Kiran", "Lior", "Mira", "Noah", "Opal", "Petra",
]
LAST_NAMES = [
    "Alvarez", "Becker", "Chen", "Dubois", "Eriksen", "Farrell", "Gomez",
    "Haddad", "Ibarra", "Jansen", "Kowalski", "Lindqvist", "Mercer",
    "Nakamura", "Okafor", "Petrov", "Quintero", "Rossi", "Suleiman", "Tran",
]

TXN_TYPE_CODE = {"deposit": "DEP", "withdrawal": "WD", "transfer": "XFER", "wire": "WIRE", "cash": "CSH"}
CHANNEL_CODE = {"atm": "ATM", "branch": "BRN", "online": "ONL", "mobile": "MOB", "wire": "WR"}
CUSTOMER_TYPE_CODE = {"individual": "RETAIL", "business": "CORP"}
RISK_CODE = {"low": "L", "medium": "M", "high": "H"}
KYC_CODE = {"verified": "V", "pending": "P", "incomplete": "I"}


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
    val = int(hashlib.md5((cid + "risk-alt").encode()).hexdigest(), 16) % 100
    if val < 80:
        return "low"
    if val < 95:
        return "medium"
    return "high"


def _hash_kyc(cid: str) -> str:
    import hashlib
    val = int(hashlib.md5((cid + "kyc-alt").encode()).hexdigest(), 16) % 100
    if val < 90:
        return "verified"
    if val < 97:
        return "pending"
    return "incomplete"


def _hash_pep(cid: str) -> bool:
    import hashlib
    val = int(hashlib.md5((cid + "pep-alt").encode()).hexdigest(), 16) % 1000
    return val < 15


# ---------------------------------------------------------------------------
# Normal population
# ---------------------------------------------------------------------------

def _generate_normal(rng: random.Random, cust_ids: list[str]) -> list[dict]:
    rows = []
    for _ in range(TOTAL_ROWS):
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
    rows = []
    structuring_ids = [cid for cid in cust_ids if "STR" in cid]
    for cid in structuring_ids:
        window_start = _rand_date_in_window(rng, BASE_DATE, SIM_DAYS - STRUCTURING_WINDOW_DAYS)
        n_txn = rng.randint(STRUCTURING_TXN_PER_CUST - 1, STRUCTURING_TXN_PER_CUST + 2)
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
    rows = []
    hub_ids = [cid for cid in cust_ids if "HUB" in cid]
    smurf_ids = [cid for cid in cust_ids if "SMF" in cid]
    ring_size = min(SMURFING_RING, len(smurf_ids))

    for i, hub in enumerate(hub_ids):
        start = _rand_date_in_window(rng, BASE_DATE, SIM_DAYS - 10)
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
    rows = []
    layering_ids = [cid for cid in cust_ids if "LAY" in cid]
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
                "amount": round(amount * rng.uniform(0.90, 1.00), 2),
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
# Customer table generator (canonical form, before alt re-encoding)
# ---------------------------------------------------------------------------

def _generate_customers(
    rng: random.Random,
    all_cids: list[str],
    tx_df: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    names_used: set[str] = set()
    open_start = date(2015, 1, 1)

    for idx, cid in enumerate(all_cids):
        name = _rng_name(rng, idx)
        while name in names_used:
            name = f"{name} Jr."
        names_used.add(name)

        open_offset = rng.randint(0, (date(2022, 12, 31) - open_start).days)
        open_d = open_start + timedelta(days=open_offset)

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
# Alt-schema re-encoding (canonical -> raw alt columns/values)
# ---------------------------------------------------------------------------

def _to_alt_transactions(tx_df: pd.DataFrame) -> pd.DataFrame:
    alt = pd.DataFrame()
    alt["ref_no"] = tx_df["txn_id"]
    alt["event_ts"] = tx_df["timestamp"]
    alt["debit_acct"] = tx_df["sender_id"].str.replace("^C-", "ACC-", regex=True)
    alt["credit_acct"] = tx_df["receiver_id"].str.replace("^C-", "ACC-", regex=True)
    alt["txn_value"] = tx_df["amount"]
    alt["ccy"] = tx_df["currency"]
    alt["activity_code"] = tx_df["txn_type"].map(TXN_TYPE_CODE)
    alt["channel_cd"] = tx_df["channel"].map(CHANNEL_CODE)
    alt["orig_ctry"] = tx_df["sender_country"]
    alt["dest_ctry"] = tx_df["receiver_country"]
    # is_cross_border intentionally omitted -- adapter must derive it
    alt["aml_flag"] = tx_df["label_is_laundering"].map(
        lambda v: "Y" if v is True else ("N" if v is False else "")
    )
    alt["typology"] = tx_df["pattern_label"].map(
        lambda v: v.upper() if isinstance(v, str) else ""
    )
    return alt


def _to_alt_customers(cust_df: pd.DataFrame) -> pd.DataFrame:
    alt = pd.DataFrame()
    alt["acct_id"] = cust_df["customer_id"].str.replace("^C-", "ACC-", regex=True)
    alt["cust_name"] = cust_df["name"]
    alt["open_dt"] = cust_df["account_open_date"]
    alt["segment"] = cust_df["customer_type"].map(CUSTOMER_TYPE_CODE)
    alt["domicile"] = cust_df["country"]
    alt["job_title"] = cust_df["occupation"]
    alt["risk_tier"] = cust_df["risk_rating"].map(RISK_CODE)
    alt["kyc_stat"] = cust_df["kyc_status"].map(KYC_CODE)
    alt["pep_ind"] = cust_df["is_pep"].map(lambda v: "Y" if v else "N")
    alt["exp_vol_monthly"] = cust_df["expected_monthly_volume"]
    return alt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(output_dir: Path = OUTPUT_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate the alt-schema synthetic dataset. Returns (alt_tx_df, alt_cust_df)."""
    print("=" * 60)
    print("SYNTHETIC DATASET GENERATION PARAMETERS (ALT SCHEMA)")
    print("=" * 60)
    print(f"SEED                     = {SEED}")
    print(f"TOTAL_ROWS (normal rows) = {TOTAL_ROWS}")
    print(f"NORMAL_CUSTOMERS         = {NORMAL_CUSTOMERS}")
    print(f"STRUCTURING_CUSTOMERS    = {STRUCTURING_CUSTOMERS}")
    print(f"SMURFING_HUBS/RING       = {SMURFING_HUBS}/{SMURFING_RING}")
    print(f"LAYERING_CHAINS/HOPS     = {LAYERING_CHAINS}/{LAYERING_HOPS}")
    print(f"RAPID_CASHOUT_CUSTOMERS  = {RAPID_CASHOUT_CUSTOMERS}")
    print("=" * 60)

    rng = random.Random(SEED)
    np.random.seed(SEED)

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

    rows: list[dict] = []
    rows.extend(_generate_normal(rng, all_cids))
    rows.extend(_generate_structuring(rng, all_cids))
    rows.extend(_generate_smurfing(rng, all_cids))
    rows.extend(_generate_layering(rng, all_cids))
    rows.extend(_generate_rapid_cashout(rng, all_cids))

    rng.shuffle(rows)
    for i, row in enumerate(rows):
        row["txn_id"] = f"T-{i + 1:06d}"

    tx_df = pd.DataFrame(rows)
    tx_df["timestamp"] = pd.to_datetime(tx_df["timestamp"])
    tx_df["is_cross_border"] = tx_df["is_cross_border"].astype(bool)
    tx_df = tx_df[[
        "txn_id", "timestamp", "sender_id", "receiver_id",
        "amount", "currency", "txn_type", "channel",
        "sender_country", "receiver_country", "is_cross_border",
        "label_is_laundering", "pattern_label",
    ]]

    cust_df = _generate_customers(rng, all_cids, tx_df)

    print()
    print("=== GENERATION SUMMARY (canonical values, pre alt-encoding) ===")
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
    print(f"PEP count: {cust_df['is_pep'].sum()} ({100*cust_df['is_pep'].mean():.1f}%)")

    alt_tx_df = _to_alt_transactions(tx_df)
    alt_cust_df = _to_alt_customers(cust_df)

    output_dir.mkdir(parents=True, exist_ok=True)
    tx_path = output_dir / "aml_sample_alt.csv"
    cust_path = output_dir / "aml_sample_alt_customers.csv"
    alt_tx_df.to_csv(tx_path, index=False)
    alt_cust_df.to_csv(cust_path, index=False)
    print()
    print(f"Written: {tx_path}")
    print(f"Written: {cust_path}")

    return alt_tx_df, alt_cust_df


if __name__ == "__main__":
    generate()
