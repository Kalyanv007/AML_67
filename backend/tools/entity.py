"""
Track B — entity.py

Tool name  : entity_lookup  (Contract 2 fixed list)
Input      : ctx.df                       — canonical transactions DataFrame
             ctx.artifacts["customers"]   — customers DataFrame (from load_data)
             entity_id                    — str | list[str] — normalised customer ID(s)

Output     : ToolResult.artifacts["entity_profile"] — dict per Contract 2's handshake table
             ToolResult.tables["entity_txns"]        — recent transactions table for UI

Per Contract 2 ("entity_profile" shape):
    dict — one customer's profile + txn summary

This tool is invoked for the "entity_investigation" intent (Contract 4):
    load_data → filter_data(entity) → entity_lookup → feature_engineer(scoped) → rule_detect → risk_classify

Design notes:
  - Accepts a single entity_id or a list (for multi-entity investigation).
  - If entity_id is a bare number (e.g. "4521"), normalises to "C-4521"
    (per CONTRACTS.md: "Entity IDs in user queries may arrive bare").
  - Returns ok=False only for unexpected exceptions, NOT for unknown IDs.
    Unknown IDs → ok=True with a note (graceful degradation).
  - Never mutates ctx.df.
  - Customers data is read from ctx.artifacts["customers"] (Contract 2).

No tool may import from backend.agent.* or from another tool.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from backend.tools.base import ToolContext, ToolResult, tool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RECENT_TXNS  = 20    # rows in entity_txns table
RECENT_DAYS      = 30    # "recent" window for summary stats


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise_entity_id(raw: str) -> str:
    """Normalise bare numbers to 'C-XXXXX' format.

    Per CONTRACTS.md: '4521' → 'C-04521', 'C-4521' → 'C-4521'
    """
    raw = str(raw).strip()
    if raw.isdigit():
        return f"C-{int(raw):05d}"
    return raw


def _build_profile(
    cid: str,
    customers: Optional[pd.DataFrame],
    df: pd.DataFrame,
) -> dict[str, Any]:
    """Build the entity profile dict for a single customer."""
    profile: dict[str, Any] = {"customer_id": cid}

    # ------------------------------------------------------------------
    # Customer record (from customers table if available)
    # ------------------------------------------------------------------
    if customers is not None and len(customers) > 0:
        cust_col = "customer_id" if "customer_id" in customers.columns else customers.columns[0]
        cust_row = customers[customers[cust_col] == cid]
        if len(cust_row) > 0:
            profile.update(cust_row.iloc[0].to_dict())

    # ------------------------------------------------------------------
    # Transaction summary (sender side)
    # ------------------------------------------------------------------
    sent = df[df["sender_id"] == cid].copy()
    received = df[df["receiver_id"] == cid].copy()

    profile["total_transactions_sent"]     = int(len(sent))
    profile["total_transactions_received"] = int(len(received))

    if len(sent) > 0:
        profile["total_amount_sent"]   = round(float(sent["amount"].sum()), 2)
        profile["mean_amount_sent"]    = round(float(sent["amount"].mean()), 2)
        profile["max_amount_sent"]     = round(float(sent["amount"].max()), 2)
        profile["min_amount_sent"]     = round(float(sent["amount"].min()), 2)
        profile["first_txn_date"]      = str(sent["timestamp"].min().date())
        profile["last_txn_date"]       = str(sent["timestamp"].max().date())
        profile["distinct_receivers"]  = int(sent["receiver_id"].nunique())
        profile["txn_types_used"]      = sorted(sent["txn_type"].unique().tolist())
        profile["channels_used"]       = sorted(sent["channel"].unique().tolist())
        profile["countries_sent_to"]   = sorted(sent["receiver_country"].unique().tolist())
        profile["cross_border_txns"]   = int(sent["is_cross_border"].sum())

        # Recent window
        ref_time = df["timestamp"].max()
        cutoff   = ref_time - pd.Timedelta(days=RECENT_DAYS)
        recent   = sent[sent["timestamp"] >= cutoff]
        profile["recent_txn_count"]   = int(len(recent))
        profile["recent_amount_sent"] = round(float(recent["amount"].sum()), 2)
    else:
        profile["total_amount_sent"]   = 0.0
        profile["distinct_receivers"]  = 0
        profile["recent_txn_count"]    = 0
        profile["recent_amount_sent"]  = 0.0

    if len(received) > 0:
        profile["total_amount_received"] = round(float(received["amount"].sum()), 2)
    else:
        profile["total_amount_received"] = 0.0

    # ------------------------------------------------------------------
    # Laundering label (synthetic data ground-truth; null in production)
    # ------------------------------------------------------------------
    if "label_is_laundering" in df.columns:
        all_cust = pd.concat([sent, received], ignore_index=True)
        any_laundering = all_cust["label_is_laundering"].dropna()
        if len(any_laundering) > 0:
            profile["label_is_laundering"] = bool(any_laundering.any())
        else:
            profile["label_is_laundering"] = None

    if "pattern_label" in df.columns:
        all_cust_txns = pd.concat([sent, received], ignore_index=True)
        labels = all_cust_txns["pattern_label"].dropna().unique().tolist()
        profile["pattern_labels"] = sorted(labels)

    return profile


# ---------------------------------------------------------------------------
# Registered tool
# ---------------------------------------------------------------------------


@tool(
    name="entity_lookup",
    params={
        "entity_id": (
            "str | list[str] — one or more customer IDs to look up. "
            "Bare numbers (e.g. '4521') are normalised to 'C-04521'. "
            "Required."
        ),
    },
    description=(
        "Look up a customer's full profile and transaction summary. "
        "Reads ctx.df and ctx.artifacts['customers']. "
        "Emits artifacts['entity_profile'] (dict) and tables['entity_txns'] (recent txns)."
    ),
)
def entity_lookup(
    ctx: ToolContext,
    entity_id: Optional[Any] = None,
    **kw,
) -> ToolResult:
    """Look up one or more customers by ID.

    Parameters
    ----------
    ctx       : ToolContext — transactions in ctx.df, customers in ctx.artifacts
    entity_id : str or list[str] — customer ID(s) to look up
    """
    try:
        df = ctx.df

        if df is None or len(df) == 0:
            return ToolResult(
                ok=True,
                artifacts={"entity_profile": {}},
                tables={"entity_txns": []},
                notes=["entity_lookup: working DataFrame is empty"],
            )

        if entity_id is None:
            return ToolResult(
                ok=False,
                error="entity_lookup: entity_id is required",
            )

        # Normalise to list of IDs
        if isinstance(entity_id, str):
            ids = [_normalise_entity_id(entity_id)]
        elif isinstance(entity_id, list):
            ids = [_normalise_entity_id(str(i)) for i in entity_id]
        else:
            ids = [_normalise_entity_id(str(entity_id))]

        # Retrieve customers from artifacts (Contract 2 handshake)
        customers: Optional[pd.DataFrame] = ctx.artifacts.get("customers", None)

        # ------------------------------------------------------------------
        # Build profiles for each entity
        # ------------------------------------------------------------------
        profiles: list[dict[str, Any]] = []
        notes:    list[str] = []

        for cid in ids:
            cust_sent = df[df["sender_id"] == cid]
            cust_recv = df[df["receiver_id"] == cid]
            if len(cust_sent) == 0 and len(cust_recv) == 0:
                notes.append(f"entity_lookup: entity '{cid}' not found in transaction data")
                continue
            profile = _build_profile(cid, customers, df)
            profiles.append(profile)

        if not profiles:
            return ToolResult(
                ok=True,
                artifacts={"entity_profile": {}},
                tables={"entity_txns": []},
                metrics={"entities_found": 0},
                notes=notes or [f"entity_lookup: none of {ids} found in data"],
            )

        # For single-entity lookup: entity_profile is a flat dict
        # For multi-entity: entity_profile is a dict keyed by entity_id
        if len(profiles) == 1:
            entity_profile = profiles[0]
        else:
            entity_profile = {p["customer_id"]: p for p in profiles}

        # ------------------------------------------------------------------
        # Recent transactions table for UI
        # ------------------------------------------------------------------
        # Union of sent + received for all requested entities
        all_ids = [p["customer_id"] for p in profiles]
        entity_txns = df[
            df["sender_id"].isin(all_ids) | df["receiver_id"].isin(all_ids)
        ].copy()
        entity_txns = entity_txns.sort_values("timestamp", ascending=False).head(MAX_RECENT_TXNS)

        # Convert timestamps to strings for JSON serialisation
        if "timestamp" in entity_txns.columns:
            entity_txns = entity_txns.copy()
            entity_txns["timestamp"] = entity_txns["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

        txn_rows = entity_txns.to_dict(orient="records")

        # Fill None for JSON safety
        for row in txn_rows:
            for k, v in row.items():
                if pd.isna(v) if not isinstance(v, (list, dict)) else False:
                    row[k] = None

        notes.append(
            f"entity_lookup: found {len(profiles)} of {len(ids)} entities; "
            f"showing {len(txn_rows)} recent transactions"
        )

        return ToolResult(
            ok=True,
            artifacts={"entity_profile": entity_profile},
            tables={"entity_txns": txn_rows},
            metrics={
                "entities_found": len(profiles),
                "entities_requested": len(ids),
                "txn_rows_returned": len(txn_rows),
            },
            notes=notes,
        )

    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"entity_lookup failed: {exc}")
