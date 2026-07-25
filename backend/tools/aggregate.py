"""
Track B — aggregate.py

Tool name  : aggregate_query  (Contract 2 fixed list)
Input      : ctx.df            — canonical transactions DataFrame (after filter_data)
             group_by          — list[str] column names to group on
             agg_col           — str column to aggregate (default: "amount")
             agg_func          — str "count" | "sum" | "mean" | "max" | "min" | "nunique"
             threshold         — float | None  — keep only rows where result ≥ threshold
             top_n             — int  — cap result to top_n rows (sorted desc), default 50

Output     : ToolResult.tables["agg_result"] — flat table (list[dict])
             ToolResult.metrics               — row_count, sum_total etc.
             ToolResult.df                    — None (aggregate_query never narrows ctx.df)

Use cases (per WORKPLAN.md §6 "threshold_query" intent):
  - "Which customers made 10+ transactions under $10,000?"
      group_by=["sender_id"], agg_func="count", threshold=10
  - "Total amount sent per country"
      group_by=["sender_country"], agg_col="amount", agg_func="sum"
  - "How many distinct receivers per customer in the last 7 days?"
      group_by=["sender_id"], agg_col="receiver_id", agg_func="nunique"

Design notes:
  - Never mutates ctx.df.
  - Returns ok=False only on unexpected exceptions, not on empty results.
  - For empty results (threshold excludes everything): returns ok=True,
    empty table, and a note explaining the filter.

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

VALID_AGG_FUNCS = {"count", "sum", "mean", "max", "min", "nunique"}
DEFAULT_AGG_COL = "amount"
DEFAULT_TOP_N   = 50


# ---------------------------------------------------------------------------
# Registered tool
# ---------------------------------------------------------------------------


@tool(
    name="aggregate_query",
    params={
        "group_by": (
            "list[str] — column names to group by. "
            "Valid: any column in the transactions schema."
        ),
        "agg_col": (
            "str — column to aggregate. Default: 'amount'. "
            "Use 'receiver_id' for distinct-receiver counts."
        ),
        "agg_func": (
            "str — aggregation function: 'count' | 'sum' | 'mean' | 'max' | 'min' | 'nunique'. "
            "Default: 'count'."
        ),
        "threshold": (
            "float | None — keep only groups where result >= threshold. "
            "e.g. threshold=10 for '10+ transactions'."
        ),
        "top_n": (
            "int — cap result to top_n rows (sorted descending). Default: 50."
        ),
    },
    description=(
        "Group-by aggregation on the working transaction set. Handles threshold-query "
        "intents like '10+ transactions under $10,000'. "
        "Returns tables['agg_result'] and metrics summary."
    ),
)
def aggregate_query(
    ctx: ToolContext,
    group_by: Optional[list[str]] = None,
    agg_col: str = DEFAULT_AGG_COL,
    agg_func: str = "count",
    threshold: Optional[float] = None,
    top_n: int = DEFAULT_TOP_N,
    **kw,
) -> ToolResult:
    """Run a group-by aggregation on ctx.df.

    Parameters
    ----------
    ctx       : ToolContext
    group_by  : list of column names to group on
    agg_col   : column to aggregate (default "amount")
    agg_func  : "count" | "sum" | "mean" | "max" | "min" | "nunique"
    threshold : only keep groups with result >= threshold (optional)
    top_n     : max rows returned (sorted desc)
    """
    try:
        df = ctx.df

        if df is None or len(df) == 0:
            return ToolResult(
                ok=True,
                tables={"agg_result": []},
                metrics={"row_count": 0},
                notes=["aggregate_query: working DataFrame is empty"],
            )

        # Defaults
        if not group_by:
            group_by = ["sender_id"]
        top_n = max(1, int(top_n))

        # Validate agg_func
        if agg_func not in VALID_AGG_FUNCS:
            return ToolResult(
                ok=False,
                error=(
                    f"aggregate_query: invalid agg_func='{agg_func}'. "
                    f"Valid: {sorted(VALID_AGG_FUNCS)}"
                ),
            )

        # Validate group_by columns exist
        missing_cols = [c for c in group_by if c not in df.columns]
        if missing_cols:
            return ToolResult(
                ok=False,
                error=(
                    f"aggregate_query: group_by columns not found: {missing_cols}. "
                    f"Available: {list(df.columns)}"
                ),
            )

        # Validate agg_col exists (for non-count)
        if agg_func != "count" and agg_col not in df.columns:
            return ToolResult(
                ok=False,
                error=(
                    f"aggregate_query: agg_col='{agg_col}' not found. "
                    f"Available: {list(df.columns)}"
                ),
            )

        # ------------------------------------------------------------------
        # Aggregation
        # ------------------------------------------------------------------
        grouped = df.groupby(group_by)

        if agg_func == "count":
            result = grouped.size().reset_index(name="result")
        elif agg_func == "nunique":
            if agg_col not in df.columns:
                return ToolResult(
                    ok=False,
                    error=f"aggregate_query: agg_col='{agg_col}' not found for nunique",
                )
            result = grouped[agg_col].nunique().reset_index(name="result")
        else:
            func_map = {
                "sum":  "sum",
                "mean": "mean",
                "max":  "max",
                "min":  "min",
            }
            result = grouped[agg_col].agg(func_map[agg_func]).reset_index(name="result")

        # ------------------------------------------------------------------
        # Apply threshold filter
        # ------------------------------------------------------------------
        pre_filter_count = len(result)
        if threshold is not None:
            result = result[result["result"] >= threshold]

        # ------------------------------------------------------------------
        # Sort descending and cap
        # ------------------------------------------------------------------
        result = result.sort_values("result", ascending=False).head(top_n)
        result = result.reset_index(drop=True)

        # Round float results for readability
        if result["result"].dtype in (float, np.float64, np.float32):
            result["result"] = result["result"].round(2)

        rows = result.to_dict(orient="records")

        # ------------------------------------------------------------------
        # Notes
        # ------------------------------------------------------------------
        threshold_str = f" ≥ {threshold}" if threshold is not None else ""
        note = (
            f"aggregate_query: grouped by {group_by}, "
            f"agg_func={agg_func}({agg_col}){threshold_str} → "
            f"{len(rows)} groups returned "
            f"(of {pre_filter_count} total, capped at top_{top_n})"
        )

        if len(rows) == 0:
            note = (
                f"aggregate_query: no groups meet the threshold {threshold} "
                f"after {agg_func}({agg_col}) grouped by {group_by}"
            )

        # Summary metrics
        total_result = float(result["result"].sum()) if len(result) > 0 else 0.0

        return ToolResult(
            ok=True,
            tables={"agg_result": rows},
            metrics={
                "row_count": len(rows),
                "pre_filter_count": pre_filter_count,
                "total_result": round(total_result, 2),
                "group_by": group_by,
                "agg_func": agg_func,
                "agg_col": agg_col,
                "threshold": threshold,
            },
            notes=[note],
        )

    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"aggregate_query failed: {exc}")
