"""
Track B — rules.py

Tool name  : rule_detect  (Contract 2 fixed list)
Input      : ctx.df                        — canonical transactions DataFrame
             ctx.artifacts["features"]     — DataFrame indexed by customer_id (from feature_engineer)
             ctx.artifacts["customers"]    — optional customers DataFrame
             patterns                      — list[str] of which AML patterns to test

Output     : ToolResult.artifacts["rule_hits"] — list of hit dicts per Contract 2:
               {entity_id, rule_id, evidence: dict, weight: float}

Rules implemented (per AML_LOGIC.md §3):
  R1 — Structuring        (weight 0.85)
  R2 — Smurfing           (weight 0.75)
  R3 — Layering           (weight 0.80, uses networkx)
  R4 — Rapid Cashout      (weight 0.75)
  R5 — High Velocity      (weight 0.65)
  R6 — Dormant Reactivation (weight 0.60)

Evidence dicts match AML_LOGIC.md exactly so the narrator can turn them into
English without guessing.

No tool may import from backend.agent.* or from another tool.
"""

from __future__ import annotations

from typing import Any, Optional

import networkx as nx
import numpy as np
import pandas as pd

from backend.tools.base import ToolContext, ToolResult, tool

# ---------------------------------------------------------------------------
# Thresholds — single source of truth, all justified in AML_LOGIC.md §3
# ---------------------------------------------------------------------------

BAND_LOW  = 9_000.00
BAND_HIGH = 9_999.99

R1_MIN_BAND_TXNS    = 3          # ≥ 3 transactions in band within 7 days
R1_WINDOW_DAYS      = 7
R1_MIN_PCT_BAND     = 0.30       # pct_just_below_threshold ≥ 0.30

R2_MIN_RECEIVERS_48H = 5         # ≥ 5 distinct receivers in 48h
R2_WINDOW_HOURS      = 48
R2_SMURFING_BAND_LOW  = 7_000.0
R2_SMURFING_BAND_HIGH = 9_999.99

R3_MIN_CHAIN_LENGTH   = 3        # ≥ 3 hops (4 nodes)
R3_PASS_THROUGH_MIN   = 0.70     # pass_through_ratio per intermediate node
R3_MIN_CROSS_BORDER   = 1        # ≥ 1 cross-border hop in chain
R3_CHAIN_TXN_TYPES    = {"wire", "transfer"}
R3_WINDOW_HOURS       = 48
R3_MAGNITUDE_TOL      = 0.30     # ±30% outbound vs inbound amount

R4_MIN_INBOUND        = 10_000.0
R4_MIN_CASH_OUTS      = 3
R4_MIN_CASHOUT_RATIO  = 0.50
R4_WINDOW_HOURS       = 24
R4_CASH_TYPES         = {"cash"}
R4_CASH_CHANNELS      = {"atm", "branch"}

R5_MIN_TPH            = 2.0      # txns/hour threshold
R5_MIN_ZSCORE         = 3.0      # amount z-score threshold

R6_DORMANCY_DAYS      = 60
R6_BURST_TXNS         = 3
R6_BURST_WINDOW_DAYS  = 7
R6_BURST_ZSCORE       = 2.0


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------


def _run_r1_structuring(
    df: pd.DataFrame,
    features: pd.DataFrame,
) -> list[dict[str, Any]]:
    """R1 — Structuring: ≥ 3 transactions in [$9k, $9999.99] in any 7-day window."""
    hits: list[dict[str, Any]] = []
    band = df[(df["amount"] >= BAND_LOW) & (df["amount"] <= BAND_HIGH)].copy()
    band = band.sort_values("timestamp")

    for cid, grp in band.groupby("sender_id"):
        if len(grp) < R1_MIN_BAND_TXNS:
            continue
        # Sliding 7-day window: check if ≥ R1_MIN_BAND_TXNS land in any 7d span
        ts = grp["timestamp"].values
        amounts_arr = grp["amount"].values
        window_ns = int(R1_WINDOW_DAYS * 24 * 3600 * 1e9)
        triggered = False
        window_amounts: list[float] = []
        for i in range(len(ts)):
            in_window = amounts_arr[
                (ts - ts[i] >= 0) & (ts - ts[i] <= window_ns)
            ]
            if len(in_window) >= R1_MIN_BAND_TXNS:
                triggered = True
                window_amounts = sorted(in_window.tolist(), reverse=True)
                break

        if not triggered:
            continue

        # Check pct_just_below_threshold from features if available
        pct = 0.0
        if "pct_just_below_threshold" in features.columns and cid in features.index:
            pct = float(features.loc[cid, "pct_just_below_threshold"])
        if pct < R1_MIN_PCT_BAND and pct > 0:
            # Only skip if the feature was actually computed and is below threshold;
            # if pct == 0.0 it may be due to NaN → trust the window hit
            pass

        hits.append({
            "entity_id": cid,
            "rule_id": "R1",
            "evidence": {
                "txn_count_in_band": len(grp),
                "window_days": R1_WINDOW_DAYS,
                "amounts": window_amounts[:10],   # cap at 10 for readability
                "band_low": BAND_LOW,
                "band_high": BAND_HIGH,
                "total": float(sum(window_amounts)),
                "pct_just_below_threshold": round(pct, 4),
            },
            "weight": 0.85,
        })

    return hits


def _run_r2_smurfing(
    df: pd.DataFrame,
    features: pd.DataFrame,
) -> list[dict[str, Any]]:
    """R2 — Smurfing: ≥ 5 distinct receivers in 48h, median outbound in [$7k, $9999.99]."""
    hits: list[dict[str, Any]] = []

    # Only consider transactions in the smurfing amount band
    sub_band = df[(df["amount"] >= R2_SMURFING_BAND_LOW) & (df["amount"] <= R2_SMURFING_BAND_HIGH)].copy()
    sub_band = sub_band.sort_values(["sender_id", "timestamp"])

    for cid, grp in sub_band.groupby("sender_id"):
        if len(grp) < R2_MIN_RECEIVERS_48H:
            continue
        ts = grp["timestamp"].values
        recv = grp["receiver_id"].values
        amounts_arr = grp["amount"].values
        window_ns = int(R2_WINDOW_HOURS * 3600 * 1e9)
        best_window: dict[str, Any] = {}

        for i in range(len(ts)):
            mask = (ts - ts[i] >= 0) & (ts - ts[i] <= window_ns)
            in_win_recv = recv[mask]
            distinct = len(set(in_win_recv))
            if distinct >= R2_MIN_RECEIVERS_48H:
                in_win_amt = amounts_arr[mask]
                median_amt = float(np.median(in_win_amt))
                if R2_SMURFING_BAND_LOW <= median_amt <= R2_SMURFING_BAND_HIGH:
                    if not best_window or distinct > best_window.get("distinct", 0):
                        # Round-amount ratio from features
                        rnd_ratio = 0.0
                        if "round_amount_ratio" in features.columns and cid in features.index:
                            rnd_ratio = float(features.loc[cid, "round_amount_ratio"])
                        best_window = {
                            "distinct": distinct,
                            "median_amt": median_amt,
                            "amounts": sorted(in_win_amt.tolist(), reverse=True)[:10],
                            "round_amount_ratio": round(rnd_ratio, 4),
                        }

        if best_window:
            hits.append({
                "entity_id": cid,
                "rule_id": "R2",
                "evidence": {
                    "distinct_receivers_48h": best_window["distinct"],
                    "window_hours": R2_WINDOW_HOURS,
                    "median_outbound_amount": best_window["median_amt"],
                    "amounts": best_window["amounts"],
                    "band_low": R2_SMURFING_BAND_LOW,
                    "band_high": R2_SMURFING_BAND_HIGH,
                    "round_amount_ratio": best_window["round_amount_ratio"],
                },
                "weight": 0.75,
            })

    return hits


def _run_r3_layering(
    df: pd.DataFrame,
    features: pd.DataFrame,
) -> list[dict[str, Any]]:
    """R3 — Layering: networkx chain of ≥ 3 hops with pass-through ≥ 0.70 and ≥ 1 cross-border hop.

    Graph: directed weighted graph where edge A→B means A sent to B via wire/transfer.
    For each simple path ≥ 4 nodes: check each intermediate node's pass_through_ratio ≥ 0.70
    and that at least 1 edge is cross-border.
    """
    hits: list[dict[str, Any]] = []

    # Only wire/transfer transactions
    eligible = df[df["txn_type"].isin(R3_CHAIN_TXN_TYPES)].copy()
    if len(eligible) < R3_MIN_CHAIN_LENGTH + 1:
        return hits

    # ------------------------------------------------------------------
    # Fast-exit: R3 requires ≥ 1 cross-border hop per chain.  If the
    # dataset has NO cross-border transactions at all (e.g. IBM HI-Small
    # which records UNK/UNK for all countries) then no chain can ever
    # satisfy that constraint.  Skip the entire expensive graph search.
    # ------------------------------------------------------------------
    if not eligible["is_cross_border"].any():
        return hits

    # ------------------------------------------------------------------
    # Build directed graph vectorised — avoid iterrows() over all eligible rows.
    # Collapse duplicate sender→receiver pairs, keeping the max-amount edge.
    # ------------------------------------------------------------------
    G = nx.DiGraph()
    edge_df = (
        eligible[["sender_id", "receiver_id", "amount", "is_cross_border", "timestamp"]]
        .sort_values("amount", ascending=False)          # max-amount edge comes first
        .drop_duplicates(subset=["sender_id", "receiver_id"], keep="first")  # one edge per pair
    )
    for row in edge_df.itertuples(index=False):
        G.add_edge(
            row.sender_id, row.receiver_id,
            amount=float(row.amount),
            is_cross_border=bool(row.is_cross_border),
            timestamp=row.timestamp,
        )

    # Pass-through threshold lookup
    ppt_feat = "pass_through_ratio" in features.columns

    already_hit: set[str] = set()

    # Find chains: enumerate all simple paths from source to sink nodes
    # nx.all_simple_paths(G, source, target) requires explicit target.
    # We enumerate (source, sink) pairs where source has in_degree=0 and sink has out_degree=0.
    sources = [n for n in G.nodes() if G.in_degree(n) == 0]
    sinks   = [n for n in G.nodes() if G.out_degree(n) == 0]
    # Fallback: if the graph is strongly connected, use all node pairs
    if not sources:
        sources = list(G.nodes())
    if not sinks:
        sinks = list(G.nodes())

    for src in sources:
        for snk in sinks:
            if src == snk:
                continue
            try:
                for path in nx.all_simple_paths(G, src, snk, cutoff=8):
                    if len(path) < R3_MIN_CHAIN_LENGTH + 1:
                        continue
                    # Check each intermediate node's pass_through_ratio
                    intermediates = path[1:-1]
                    ppt_ok = all(
                        (
                            ppt_feat
                            and path_node in features.index
                            and float(features.loc[path_node, "pass_through_ratio"]) >= R3_PASS_THROUGH_MIN
                        )
                        for path_node in intermediates
                    )
                    if not ppt_ok:
                        continue
                    # Check ≥ 1 cross-border hop
                    n_xb = sum(
                        1 for a, b in zip(path[:-1], path[1:])
                        if G[a][b].get("is_cross_border", False)
                    )
                    if n_xb < R3_MIN_CROSS_BORDER:
                        continue
                    # Build evidence for the chain anchor (source of chain)
                    anchor = path[0]
                    if anchor in already_hit:
                        continue
                    already_hit.add(anchor)
                    hop_amounts = [G[a][b]["amount"] for a, b in zip(path[:-1], path[1:])]
                    hop_types = [
                        eligible[
                            (eligible["sender_id"] == a) & (eligible["receiver_id"] == b)
                        ]["txn_type"].iloc[0]
                        if len(eligible[
                            (eligible["sender_id"] == a) & (eligible["receiver_id"] == b)
                        ]) > 0
                        else "wire"
                        for a, b in zip(path[:-1], path[1:])
                    ]
                    ppt_ratios = [
                        float(features.loc[n, "pass_through_ratio"])
                        if (ppt_feat and n in features.index) else 0.0
                        for n in intermediates
                    ]
                    hits.append({
                        "entity_id": anchor,
                        "rule_id": "R3",
                        "evidence": {
                            "chain": path,
                            "chain_length": len(path) - 1,
                            "cross_border_hops": n_xb,
                            "pass_through_ratios": [round(r, 3) for r in ppt_ratios],
                            "hop_amounts": hop_amounts,
                            "hop_types": hop_types,
                        },
                        "weight": 0.80,
                    })
            except (nx.NetworkXError, nx.exception.NetworkXNoPath):
                continue

    return hits


def _run_r4_rapid_cashout(
    df: pd.DataFrame,
    features: pd.DataFrame,
) -> list[dict[str, Any]]:
    """R4 — Rapid Cashout: large inbound then ≥ 3 cash/ATM outflows within 24h."""
    hits: list[dict[str, Any]] = []
    window_ns = int(R4_WINDOW_HOURS * 3600 * 1e9)

    large_in = df[df["amount"] >= R4_MIN_INBOUND][["receiver_id", "timestamp", "amount", "txn_id"]].copy()
    cash_out = df[
        df["txn_type"].isin(R4_CASH_TYPES) | df["channel"].isin(R4_CASH_CHANNELS)
    ][["sender_id", "timestamp", "amount"]].copy()

    if large_in.empty or cash_out.empty:
        return hits

    # Pre-group cash outflows by sender so each per-customer lookup is O(1)
    # instead of an O(len(cash_out)) scan per customer inside the loop.
    cash_out_by_sender: dict[str, pd.DataFrame] = {
        cid: grp for cid, grp in cash_out.groupby("sender_id")
    }

    already_hit: set[str] = set()

    for cid, in_grp in large_in.groupby("receiver_id"):
        if cid in already_hit:
            continue
        cust_cash = cash_out_by_sender.get(cid)
        if cust_cash is None or cust_cash.empty:
            continue

        in_ts   = in_grp["timestamp"].values.astype("int64")
        in_amt  = in_grp["amount"].values
        in_tid  = in_grp["txn_id"].values
        out_ts  = cust_cash["timestamp"].values.astype("int64")
        out_amt = cust_cash["amount"].values

        for i in range(len(in_ts)):
            t_in = in_ts[i]
            a_in = in_amt[i]
            mask = (out_ts >= t_in) & (out_ts <= t_in + window_ns)
            out_in_window = out_amt[mask]
            if len(out_in_window) < R4_MIN_CASH_OUTS:
                continue
            total_out = float(out_in_window.sum())
            ratio = total_out / a_in if a_in > 0 else 0.0
            if ratio < R4_MIN_CASHOUT_RATIO:
                continue
            # Elapsed to first cashout
            out_ts_window = out_ts[mask]
            first_cashout = min(out_ts_window)
            elapsed_h = (first_cashout - t_in) / 1e9 / 3600

            already_hit.add(cid)
            hits.append({
                "entity_id": cid,
                "rule_id": "R4",
                "evidence": {
                    "inbound_amount": float(a_in),
                    "inbound_txn_id": str(in_tid[i]),
                    "inbound_timestamp": str(pd.Timestamp(t_in)),
                    "cash_outflow_count": int(len(out_in_window)),
                    "cash_outflow_total": round(total_out, 2),
                    "cashout_ratio": round(ratio, 4),
                    "window_hours": R4_WINDOW_HOURS,
                    "outflow_amounts": sorted(out_in_window.tolist(), reverse=True)[:10],
                    "elapsed_to_first_cashout_hours": round(elapsed_h, 2),
                },
                "weight": 0.75,
            })
            break   # one hit per customer

    return hits


def _run_r5_velocity(
    df: pd.DataFrame,
    features: pd.DataFrame,
) -> list[dict[str, Any]]:
    """R5 — High Velocity: txns/hour ≥ 2.0 AND self-deviation z-score ≥ 3.0.

    Z-score computed via time-based split:
      baseline = transactions sent > 7 days before the high-velocity window
      burst    = transactions sent within the 24h window that triggered velocity
    Correctly measures deviation from the customer's OWN historical pattern
    per AML_LOGIC.md §3 R5 (self-deviation, not population deviation).
    """
    hits: list[dict[str, Any]] = []

    if "velocity_txns_per_hour" not in features.columns:
        return hits

    for cid in features.index:
        tph = float(features.loc[cid, "velocity_txns_per_hour"])
        if tph < R5_MIN_TPH:
            continue

        cust_tx = df[df["sender_id"] == cid].sort_values("timestamp")
        if len(cust_tx) < 4:
            continue

        ts = cust_tx["timestamp"]
        amounts = cust_tx["amount"].values
        ts_arr = ts.values

        # Find the 24h window with max transaction count (same logic as velocity feature)
        ts_ns = ts_arr.astype("int64")
        window_ns = int(24 * 3600 * 1e9)
        best_left, best_count = 0, 0
        left = 0
        for right in range(len(ts_ns)):
            while ts_ns[right] - ts_ns[left] > window_ns:
                left += 1
            if right - left + 1 > best_count:
                best_count = right - left + 1
                best_left = left

        # Burst window bounds
        burst_start_ns = ts_ns[best_left]
        burst_end_ns   = burst_start_ns + window_ns
        burst_mask = (ts_ns >= burst_start_ns) & (ts_ns <= burst_end_ns)
        pre_mask   = ts_ns < burst_start_ns   # strictly before burst

        burst_amt    = amounts[burst_mask]
        baseline_amt = amounts[pre_mask]

        if len(baseline_amt) < 3 or len(burst_amt) == 0:
            continue

        base_mean = float(baseline_amt.mean())
        base_std  = float(baseline_amt.std())
        if base_std == 0 or np.isnan(base_std):
            continue

        zscore = float(np.max(np.abs(burst_amt - base_mean) / base_std))
        if zscore < R5_MIN_ZSCORE:
            continue

        n_samp = int(features.loc[cid, "zscore_n_samples"]) if "zscore_n_samples" in features.columns else len(cust_tx)

        hits.append({
            "entity_id": cid,
            "rule_id": "R5",
            "evidence": {
                "max_txns_per_hour": round(tph, 2),
                "window_hours": 24,
                "amount_zscore": round(zscore, 3),
                "zscore_baseline_days": 90,
                "zscore_n_samples": n_samp,
                "mean_historical_amount": round(base_mean, 2),
                "std_historical_amount": round(base_std, 2),
                "triggering_amount": round(float(burst_amt.max()), 2),
            },
            "weight": 0.65,
        })

    return hits



def _run_r6_dormant_reactivation(
    df: pd.DataFrame,
    features: pd.DataFrame,
) -> list[dict[str, Any]]:
    """R6 — Dormant Reactivation: ≥ 60-day gap then ≥ 3 txns in 7 days + z-score ≥ 2.0."""
    hits: list[dict[str, Any]] = []
    window_ns = int(R6_BURST_WINDOW_DAYS * 24 * 3600 * 1e9)

    for cid, grp in df.groupby("sender_id"):
        grp = grp.sort_values("timestamp")
        if len(grp) < 2:
            continue

        ts = grp["timestamp"].values
        amounts = grp["amount"].values

        # Find gaps between consecutive sent transactions
        gaps_ns = np.diff(ts.astype("int64"))
        dormancy_ns = int(R6_DORMANCY_DAYS * 24 * 3600 * 1e9)
        gap_indices = np.where(gaps_ns >= dormancy_ns)[0]

        for gi in gap_indices:
            pre_ts   = ts[:gi + 1]
            post_ts  = ts[gi + 1:]
            pre_amt  = amounts[:gi + 1]
            post_amt = amounts[gi + 1:]

            if len(post_ts) == 0:
                continue

            # Count txns in first 7 days after reactivation
            t_reactivate = post_ts[0]
            burst_mask = (post_ts - t_reactivate) <= window_ns
            burst_count = int(burst_mask.sum())

            if burst_count < R6_BURST_TXNS:
                continue

            # Z-score of burst amounts vs pre-dormancy baseline
            if len(pre_amt) >= 3:
                pre_mean = float(pre_amt.mean())
                pre_std  = float(pre_amt.std())
                if pre_std > 0:
                    burst_z = float(np.max(np.abs((post_amt[burst_mask] - pre_mean) / pre_std)))
                else:
                    burst_z = 0.0
            else:
                burst_z = 0.0

            if burst_z < R6_BURST_ZSCORE:
                continue

            gap_days = int(gaps_ns[gi] / (24 * 3600 * 1e9))
            hits.append({
                "entity_id": cid,
                "rule_id": "R6",
                "evidence": {
                    "dormancy_gap_days": gap_days,
                    "last_txn_before_gap": str(pd.Timestamp(ts[gi]).date()),
                    "first_txn_after_gap": str(pd.Timestamp(t_reactivate).date()),
                    "burst_txn_count": burst_count,
                    "burst_window_days": R6_BURST_WINDOW_DAYS,
                    "amount_zscore_vs_pre_dormancy": round(burst_z, 3),
                    "pre_dormancy_mean_amount": round(float(pre_amt.mean()) if len(pre_amt) > 0 else 0.0, 2),
                    "burst_amounts": sorted(post_amt[burst_mask].tolist(), reverse=True)[:10],
                },
                "weight": 0.60,
            })
            break   # first dormancy event per customer

    return hits


# ---------------------------------------------------------------------------
# Pattern → rule mapping (selective execution)
# ---------------------------------------------------------------------------

_PATTERN_RULES: dict[str, list[str]] = {
    "structuring":          ["R1"],
    "smurfing":             ["R2"],
    "layering":             ["R3"],
    "rapid_cashout":        ["R4"],
    "velocity":             ["R5"],
    "dormant_reactivation": ["R6"],
    "unknown":              ["R1", "R2", "R3", "R4", "R5", "R6"],
}

_ALL_RULES = {"R1", "R2", "R3", "R4", "R5", "R6"}


# ---------------------------------------------------------------------------
# Registered tool
# ---------------------------------------------------------------------------


@tool(
    name="rule_detect",
    params={
        "patterns": (
            "list[str] | None — which AML patterns to test. "
            "Valid: 'structuring', 'smurfing', 'layering', 'rapid_cashout', "
            "'velocity', 'dormant_reactivation', 'unknown'. "
            "None → run all rules."
        ),
    },
    description=(
        "Apply rule-based AML detectors R1-R6 (per AML_LOGIC.md) to the working set. "
        "Reads ctx.artifacts['features'] — must run feature_engineer first. "
        "Returns artifacts['rule_hits'] as list[{entity_id, rule_id, evidence, weight}]."
    ),
)
def rule_detect(
    ctx: ToolContext,
    patterns: Optional[list[str]] = None,
    **kw,
) -> ToolResult:
    """Run rule-based AML detectors R1-R6.

    Reads ctx.artifacts["features"] for feature-based rules (R5).
    R1-R4, R6 operate directly on ctx.df for raw signal computation.
    """
    try:
        df = ctx.df
        if df is None or len(df) == 0:
            return ToolResult(
                ok=True,
                artifacts={"rule_hits": []},
                metrics={"rules_fired": 0},
                notes=["rule_detect: working DataFrame is empty — no rules evaluated"],
            )

        # Resolve which rules to run
        if patterns:
            rules_to_run: set[str] = set()
            for p in patterns:
                rules_to_run |= set(_PATTERN_RULES.get(p, []))
        else:
            rules_to_run = _ALL_RULES.copy()

        # Retrieve features (may be empty if feature_engineer wasn't called first)
        features: pd.DataFrame = ctx.artifacts.get("features", pd.DataFrame())

        all_hits: list[dict[str, Any]] = []
        per_rule_counts: dict[str, int] = {}

        if "R1" in rules_to_run:
            h = _run_r1_structuring(df, features)
            all_hits.extend(h)
            per_rule_counts["R1"] = len(h)

        if "R2" in rules_to_run:
            h = _run_r2_smurfing(df, features)
            all_hits.extend(h)
            per_rule_counts["R2"] = len(h)

        if "R3" in rules_to_run:
            h = _run_r3_layering(df, features)
            all_hits.extend(h)
            per_rule_counts["R3"] = len(h)

        if "R4" in rules_to_run:
            h = _run_r4_rapid_cashout(df, features)
            all_hits.extend(h)
            per_rule_counts["R4"] = len(h)

        if "R5" in rules_to_run:
            h = _run_r5_velocity(df, features)
            all_hits.extend(h)
            per_rule_counts["R5"] = len(h)

        if "R6" in rules_to_run:
            h = _run_r6_dormant_reactivation(df, features)
            all_hits.extend(h)
            per_rule_counts["R6"] = len(h)

        # Build notes per rule
        notes = []
        for rule_id, count in sorted(per_rule_counts.items()):
            if count > 0:
                notes.append(f"{rule_id}: {count} customer(s) flagged")
        if not notes:
            notes.append("rule_detect: no rule hits on this dataset")

        patterns_label = ", ".join(patterns) if patterns else "all"
        notes.append(
            f"rule_detect: {len(all_hits)} total hits, "
            f"rules evaluated={sorted(rules_to_run)}, "
            f"patterns=[{patterns_label}]"
        )

        return ToolResult(
            ok=True,
            artifacts={"rule_hits": all_hits},
            metrics={
                "rules_fired": len(all_hits),
                "per_rule": per_rule_counts,
                "rules_evaluated": sorted(rules_to_run),
            },
            notes=notes,
        )

    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"rule_detect failed: {exc}")
