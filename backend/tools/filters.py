"""
Track B — filters.py

Composable filters on the working transaction DataFrame.

Tool name  : filter_data  (Contract 2 fixed list)
Input      : ctx.df          — canonical transactions DataFrame
             ctx.artifacts   — must contain "customers" key if customer_segment used
Output     : ToolResult.df   — filtered DataFrame (never mutates ctx.df in place)
             ToolResult.notes — one factual note per filter applied

Design decisions (documented here so tests can reference them):

  countries      : matches sender_country OR receiver_country.
                   AML analysis cares whether a jurisdiction appears anywhere
                   in the transaction flow, not just on one side.

  min_txn_count  : counts transactions by sender_id only (outbound volume).
                   Structuring / smurfing are sender behaviours — flagging
                   entities that *sent* >= N transactions in the working set.
                   Returns all transactions (both directions) for qualifying
                   senders, so downstream feature engineering sees full context.

  customer_segment : reads ctx.artifacts["customers"] exclusively.
                   Returns ok=False with a clear error if the key is absent.
                   Supported values: "business", "pep", "high_risk".
                   Join is on sender_id against customers.customer_id —
                   transactions where the sender matches the segment are kept.

No tool may import from backend.agent.* or from another tool.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from backend.tools.base import ToolContext, ToolResult, tool

# ---------------------------------------------------------------------------
# Internal filter helpers — each returns (filtered_df, note_str)
# ---------------------------------------------------------------------------


def _filter_date(
    df: pd.DataFrame,
    date_from: Optional[date],
    date_to: Optional[date],
) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    original = len(df)
    if date_from is not None:
        cutoff = pd.Timestamp(date_from)
        df = df[df["timestamp"] >= cutoff]
    if date_to is not None:
        # inclusive upper bound: include all transactions on date_to
        cutoff = pd.Timestamp(date_to) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[df["timestamp"] <= cutoff]
    if date_from is not None or date_to is not None:
        lo = str(date_from) if date_from else "start"
        hi = str(date_to) if date_to else "end"
        notes.append(
            f"date filter: {len(df):,} of {original:,} transactions "
            f"({lo} → {hi})"
        )
    return df, notes


def _filter_countries(
    df: pd.DataFrame,
    countries: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    # Same "all" sentinel issue as txn_types — see _filter_txn_types.
    countries = [c for c in (countries or []) if c and c.lower() != "all"]
    if not countries:
        return df, notes
    original = len(df)
    # Match sender_country OR receiver_country (either side)
    mask = df["sender_country"].isin(countries) | df["receiver_country"].isin(countries)
    df = df[mask]
    notes.append(
        f"country filter (sender OR receiver): {len(df):,} of {original:,} transactions "
        f"matching {countries}"
    )
    return df, notes


def _filter_txn_types(
    df: pd.DataFrame,
    txn_types: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    # The LLM intent parser sometimes emits a literal "all" sentinel to mean
    # "no restriction" rather than omitting the field. "all" isn't a real
    # txn_type value, so isin() would match zero rows and empty the dataset —
    # treat it (and any other non-values) as no-op instead.
    txn_types = [t for t in (txn_types or []) if t and t.lower() != "all"]
    if not txn_types:
        return df, notes
    original = len(df)
    df = df[df["txn_type"].isin(txn_types)]
    notes.append(
        f"txn_type filter: {len(df):,} of {original:,} transactions "
        f"with type in {txn_types}"
    )
    return df, notes


def _filter_amount(
    df: pd.DataFrame,
    amount_min: Optional[float],
    amount_max: Optional[float],
) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    original = len(df)
    if amount_min is not None:
        df = df[df["amount"] >= amount_min]
    if amount_max is not None:
        df = df[df["amount"] <= amount_max]
    if amount_min is not None or amount_max is not None:
        lo = f"${amount_min:,.2f}" if amount_min is not None else "any"
        hi = f"${amount_max:,.2f}" if amount_max is not None else "any"
        notes.append(
            f"amount filter: {len(df):,} of {original:,} transactions "
            f"in range [{lo}, {hi}]"
        )
    return df, notes


def _filter_min_txn_count(
    df: pd.DataFrame,
    min_txn_count: int,
) -> tuple[pd.DataFrame, list[str]]:
    """Keep transactions whose sender_id appears >= min_txn_count times in df.

    Counts by sender_id only (outbound volume). Structuring is a sender
    behaviour; we flag entities that sent >= N transactions in the working set.
    All transactions (both directions) for qualifying senders are returned so
    downstream tools see full context.
    """
    notes: list[str] = []
    original = len(df)
    sender_counts = df["sender_id"].value_counts()
    qualifying = sender_counts[sender_counts >= min_txn_count].index
    df = df[df["sender_id"].isin(qualifying)]
    notes.append(
        f"min_txn_count filter (sender outbound >= {min_txn_count}): "
        f"{len(df):,} of {original:,} transactions, "
        f"{len(qualifying):,} qualifying senders"
    )
    return df, notes


def _filter_customer_segment(
    df: pd.DataFrame,
    customer_segment: str,
    customers: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """Keep transactions whose sender_id matches the customer segment.

    Supported segments:
      "business"  — customers.customer_type == "business"
      "pep"       — customers.is_pep == True
      "high_risk" — customers.risk_rating == "high"

    Joins on sender_id → customers.customer_id.
    """
    notes: list[str] = []
    original = len(df)
    seg = customer_segment.lower().strip()

    if seg == "business":
        matching = customers.loc[
            customers["customer_type"] == "business", "customer_id"
        ]
        label = "customer_type=business"
    elif seg == "pep":
        matching = customers.loc[
            customers["is_pep"] == True, "customer_id"  # noqa: E712
        ]
        label = "is_pep=True"
    elif seg == "high_risk":
        matching = customers.loc[
            customers["risk_rating"] == "high", "customer_id"
        ]
        label = "risk_rating=high"
    else:
        # Unknown segment — return ok=False handled in caller
        return df, [f"__unknown_segment__{seg}"]

    df = df[df["sender_id"].isin(matching)]
    notes.append(
        f"customer_segment filter ({label}): "
        f"{len(df):,} of {original:,} transactions "
        f"({len(matching):,} matching customers)"
    )
    return df, notes


# ---------------------------------------------------------------------------
# Registered tool
# ---------------------------------------------------------------------------


@tool(
    name="filter_data",
    params={
        "date_from":        "str | None — ISO date 'YYYY-MM-DD', inclusive lower bound on timestamp.",
        "date_to":          "str | None — ISO date 'YYYY-MM-DD', inclusive upper bound on timestamp.",
        "countries":        "list[str] — ISO-3166 alpha-2 codes; keeps txns where sender OR receiver country matches.",
        "txn_types":        "list[str] — one or more of: deposit, withdrawal, transfer, wire, cash.",
        "amount_min":       "float | None — keep transactions with amount >= this value.",
        "amount_max":       "float | None — keep transactions with amount <= this value.",
        "min_txn_count":    "int | None — keep only senders with >= this many transactions (outbound count).",
        "customer_segment": "str | None — one of: 'business', 'pep', 'high_risk'. Requires ctx.artifacts['customers'].",
    },
    description=(
        "Apply composable filters to the working transaction DataFrame. "
        "Every active filter is applied in sequence; each reduces the frame. "
        "Returns ToolResult.df with the filtered transactions. "
        "Returns ok=False if customer_segment is requested but ctx.artifacts['customers'] is missing."
    ),
)
def filter_data(
    ctx: ToolContext,
    date_from: Optional[str] = None,
    date_to: Optional[date] = None,
    countries: Optional[list[str]] = None,
    txn_types: Optional[list[str]] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    min_txn_count: Optional[int] = None,
    customer_segment: Optional[str] = None,
    **kw,
) -> ToolResult:
    """Apply composable filters to ctx.df.

    Parameters mirror schemas.Filters exactly.  Filters are applied in this
    fixed order: date → countries → txn_types → amount → min_txn_count →
    customer_segment.  Each reduces the working frame; later filters see the
    already-narrowed result.
    """
    try:
        df = ctx.df.copy()
        original_total = len(df)
        all_notes: list[str] = []

        # ------------------------------------------------------------------
        # 1. Date range
        # ------------------------------------------------------------------
        _date_from: Optional[date] = None
        if date_from is not None:
            if isinstance(date_from, str):
                _date_from = date.fromisoformat(date_from)
            else:
                _date_from = date_from

        _date_to: Optional[date] = None
        if date_to is not None:
            if isinstance(date_to, str):
                _date_to = date.fromisoformat(date_to)
            else:
                _date_to = date_to

        df, notes = _filter_date(df, _date_from, _date_to)
        all_notes.extend(notes)

        if df.empty:
            all_notes.append(
                f"filter_data: date filter emptied the set "
                f"(was {original_total:,} rows)"
            )
            return ToolResult(ok=True, df=df, notes=all_notes,
                              metrics={"rows_in": original_total, "rows_out": 0,
                                       "emptied_by": "date"})

        # ------------------------------------------------------------------
        # 2. Countries (sender OR receiver)
        # ------------------------------------------------------------------
        df, notes = _filter_countries(df, countries or [])
        all_notes.extend(notes)

        if df.empty:
            all_notes.append(
                f"filter_data: country filter emptied the set "
                f"(countries={countries})"
            )
            return ToolResult(ok=True, df=df, notes=all_notes,
                              metrics={"rows_in": original_total, "rows_out": 0,
                                       "emptied_by": "countries"})

        # ------------------------------------------------------------------
        # 3. txn_types
        # ------------------------------------------------------------------
        df, notes = _filter_txn_types(df, txn_types or [])
        all_notes.extend(notes)

        if df.empty:
            all_notes.append(
                f"filter_data: txn_type filter emptied the set "
                f"(txn_types={txn_types})"
            )
            return ToolResult(ok=True, df=df, notes=all_notes,
                              metrics={"rows_in": original_total, "rows_out": 0,
                                       "emptied_by": "txn_types"})

        # ------------------------------------------------------------------
        # 4. Amount range
        # ------------------------------------------------------------------
        df, notes = _filter_amount(df, amount_min, amount_max)
        all_notes.extend(notes)

        if df.empty:
            all_notes.append(
                f"filter_data: amount filter emptied the set "
                f"(min={amount_min}, max={amount_max})"
            )
            return ToolResult(ok=True, df=df, notes=all_notes,
                              metrics={"rows_in": original_total, "rows_out": 0,
                                       "emptied_by": "amount"})

        # ------------------------------------------------------------------
        # 5. min_txn_count (sender outbound)
        # ------------------------------------------------------------------
        if min_txn_count is not None:
            df, notes = _filter_min_txn_count(df, min_txn_count)
            all_notes.extend(notes)

            if df.empty:
                all_notes.append(
                    f"filter_data: min_txn_count filter emptied the set "
                    f"(no sender has >= {min_txn_count} transactions)"
                )
                return ToolResult(ok=True, df=df, notes=all_notes,
                                  metrics={"rows_in": original_total, "rows_out": 0,
                                           "emptied_by": "min_txn_count"})

        # ------------------------------------------------------------------
        # 6. customer_segment — requires ctx.artifacts["customers"]
        # ------------------------------------------------------------------
        if customer_segment is not None:
            customers = ctx.artifacts.get("customers")
            if customers is None:
                return ToolResult(
                    ok=False,
                    error=(
                        "filter_data: customer_segment filter requires "
                        "ctx.artifacts['customers'] but it is missing. "
                        "Ensure load_data runs before filter_data."
                    ),
                )

            df, notes = _filter_customer_segment(df, customer_segment, customers)

            # Check for unknown segment sentinel
            if notes and notes[0].startswith("__unknown_segment__"):
                seg = notes[0].replace("__unknown_segment__", "")
                return ToolResult(
                    ok=False,
                    error=(
                        f"filter_data: unknown customer_segment '{seg}'. "
                        "Valid values: 'business', 'pep', 'high_risk'."
                    ),
                )

            all_notes.extend(notes)

            if df.empty:
                all_notes.append(
                    f"filter_data: customer_segment='{customer_segment}' "
                    f"emptied the set (no matching sender customers)"
                )
                return ToolResult(ok=True, df=df, notes=all_notes,
                                  metrics={"rows_in": original_total, "rows_out": 0,
                                           "emptied_by": "customer_segment"})

        # ------------------------------------------------------------------
        # Summary note if no individual filter added a note
        # ------------------------------------------------------------------
        if not all_notes:
            all_notes.append(
                f"filter_data: no filters applied, "
                f"returning all {len(df):,} transactions"
            )
        else:
            all_notes.append(
                f"filter_data: {len(df):,} of {original_total:,} transactions "
                f"after all filters"
            )

        return ToolResult(
            ok=True,
            df=df,
            notes=all_notes,
            metrics={
                "rows_in": original_total,
                "rows_out": len(df),
                "filters_applied": _active_filters(
                    _date_from, _date_to, countries, txn_types,
                    amount_min, amount_max, min_txn_count, customer_segment
                ),
            },
        )

    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"filter_data failed: {exc}")


def _active_filters(
    date_from, date_to, countries, txn_types,
    amount_min, amount_max, min_txn_count, customer_segment,
) -> list[str]:
    """Return a list of filter names that were non-trivial."""
    active = []
    if date_from or date_to:
        active.append("date")
    if countries:
        active.append("countries")
    if txn_types:
        active.append("txn_types")
    if amount_min is not None or amount_max is not None:
        active.append("amount")
    if min_txn_count is not None:
        active.append("min_txn_count")
    if customer_segment is not None:
        active.append("customer_segment")
    return active
