"""
Track B — eda.py

Tool name  : eda_profile  (Contract 2 fixed list)
Input      : ctx.df          — canonical transactions DataFrame
Output     : ToolResult.metrics — profile stats dict
             ToolResult.charts  — Plotly figure JSON for each chart
             ToolResult.artifacts["eda"] — same stats dict (for tool-to-tool handshake)

Charts produced (all Plotly figure JSON, no matplotlib):
  amount_histogram        — log-scale amount distribution
  threshold_proximity     — transactions near $10k CTR threshold ($7k–$12k)
  txn_type_breakdown      — bar chart by txn_type
  country_breakdown       — top-15 sender/receiver country bar chart
  volume_timeseries       — daily transaction count

No tool may import from backend.agent.* or from another tool.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from backend.tools.base import ToolContext, ToolResult, tool

# CTR reporting threshold (Bank Secrecy Act)
_CTR_THRESHOLD = 10_000.0
_PROXIMITY_LOW = 7_000.0
_PROXIMITY_HIGH = 12_000.0


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


def _profile_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Row counts, date range, missingness."""
    stats: dict[str, Any] = {
        "txn_count": int(len(df)),
    }

    if "timestamp" in df.columns and len(df) > 0:
        stats["date_min"] = str(df["timestamp"].min().date())
        stats["date_max"] = str(df["timestamp"].max().date())
        stats["date_range_days"] = int(
            (df["timestamp"].max() - df["timestamp"].min()).days
        )
    else:
        stats["date_min"] = None
        stats["date_max"] = None
        stats["date_range_days"] = 0

    # Missingness per column
    missing = df.isnull().sum()
    stats["missing_values"] = {
        col: int(cnt) for col, cnt in missing.items() if cnt > 0
    }
    stats["columns"] = list(df.columns)

    return stats


def _amount_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Summary stats for the amount column."""
    if "amount" not in df.columns or df.empty:
        return {}
    amt = df["amount"]
    return {
        "amount_mean":   round(float(amt.mean()), 2),
        "amount_median": round(float(amt.median()), 2),
        "amount_std":    round(float(amt.std()), 2),
        "amount_min":    round(float(amt.min()), 2),
        "amount_max":    round(float(amt.max()), 2),
        "amount_p25":    round(float(amt.quantile(0.25)), 2),
        "amount_p75":    round(float(amt.quantile(0.75)), 2),
        "amount_p95":    round(float(amt.quantile(0.95)), 2),
    }


def _label_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Class balance and pattern breakdown."""
    stats: dict[str, Any] = {}

    if "label_is_laundering" in df.columns and len(df) > 0:
        n_labelled = df["label_is_laundering"].notna().sum()
        bool_series = df["label_is_laundering"].where(df["label_is_laundering"].notna(), other=False)
        n_pos = int(bool_series.astype(bool).sum())
        stats["label_is_laundering_positive"] = n_pos
        stats["label_is_laundering_negative"] = int(len(df) - n_pos)
        stats["label_is_laundering_pct_positive"] = (
            round(100.0 * n_pos / len(df), 3) if len(df) > 0 else 0.0
        )

    if "pattern_label" in df.columns:
        pc = df["pattern_label"].value_counts(dropna=True).to_dict()
        stats["pattern_counts"] = {str(k): int(v) for k, v in pc.items()}
        stats["unlabelled_count"] = int(df["pattern_label"].isna().sum())

    return stats


def _threshold_proximity_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Transactions in the $7k-$12k zone, split above/below $10k."""
    if "amount" not in df.columns:
        return {}
    zone = df[(df["amount"] >= _PROXIMITY_LOW) & (df["amount"] <= _PROXIMITY_HIGH)]
    just_below = zone[zone["amount"] < _CTR_THRESHOLD]
    just_above = zone[zone["amount"] >= _CTR_THRESHOLD]
    return {
        "threshold_zone_total":     int(len(zone)),
        "threshold_just_below_10k": int(len(just_below)),
        "threshold_just_above_10k": int(len(just_above)),
        "threshold_proximity_ratio": (
            round(len(just_below) / len(zone), 4) if len(zone) > 0 else 0.0
        ),
    }


# ---------------------------------------------------------------------------
# Chart builders — all return Plotly figure JSON (dict)
# ---------------------------------------------------------------------------


def _chart_amount_histogram(df: pd.DataFrame) -> dict:
    """Log-scale histogram of all transaction amounts."""
    if "amount" not in df.columns or df.empty:
        return {}
    label_col = None
    if "pattern_label" in df.columns:
        plot_df = df.copy()
        plot_df["_label"] = plot_df["pattern_label"].fillna("normal")
        label_col = "_label"
    else:
        plot_df = df.copy()

    fig = px.histogram(
        plot_df,
        x="amount",
        color=label_col,
        nbins=60,
        log_y=True,
        title="Transaction Amount Distribution (log scale)",
        color_discrete_map={
            "normal":       "#78909C",
            "structuring":  "#EF5350",
            "smurfing":     "#AB47BC",
            "layering":     "#42A5F5",
            "rapid_cashout": "#FFA726",
        },
        labels={"amount": "Amount (USD)", "count": "Count (log)"},
    )
    fig.update_layout(bargap=0.05, legend_title_text="Pattern")
    return fig.to_dict()


def _chart_threshold_proximity(df: pd.DataFrame) -> dict:
    """Threshold-proximity histogram ($7k–$12k) with CTR line at $10k.

    This is the single most important chart for demonstrating structuring
    detection — a spike just below $10k is the defining visual signal.
    """
    if "amount" not in df.columns or df.empty:
        return {}

    zone = df[(df["amount"] >= _PROXIMITY_LOW) & (df["amount"] <= _PROXIMITY_HIGH)].copy()

    if zone.empty:
        # Return an empty figure rather than raising
        fig = go.Figure()
        fig.update_layout(title="Threshold-Proximity Histogram (no data in zone)")
        return fig.to_dict()

    if "pattern_label" in zone.columns:
        zone["_label"] = zone["pattern_label"].fillna("normal")
        fig = px.histogram(
            zone,
            x="amount",
            color="_label",
            nbins=50,
            barmode="overlay",
            opacity=0.75,
            title=f"Threshold-Proximity Histogram (${_PROXIMITY_LOW/1000:.0f}k–"
                  f"${_PROXIMITY_HIGH/1000:.0f}k) — Structuring Spike Visible Below $10k",
            color_discrete_map={
                "normal":        "#90A4AE",
                "structuring":   "#EF5350",
                "smurfing":      "#AB47BC",
                "layering":      "#42A5F5",
                "rapid_cashout": "#FFA726",
            },
            labels={"amount": "Amount (USD)", "count": "Count"},
        )
    else:
        fig = px.histogram(
            zone, x="amount", nbins=50,
            title="Threshold-Proximity Histogram",
            color_discrete_sequence=["#78909C"],
        )

    fig.add_vline(
        x=_CTR_THRESHOLD,
        line_dash="dash",
        line_color="#212121",
        annotation_text="$10,000 CTR threshold",
        annotation_position="top right",
        annotation_font_size=12,
    )
    fig.update_layout(legend_title_text="Pattern")
    return fig.to_dict()


def _chart_txn_type_breakdown(df: pd.DataFrame) -> dict:
    """Bar chart of transaction counts by txn_type."""
    if "txn_type" not in df.columns or df.empty:
        return {}
    vc = df["txn_type"].value_counts().reset_index()
    vc.columns = ["txn_type", "count"]
    fig = px.bar(
        vc,
        x="txn_type",
        y="count",
        text="count",
        title="Transaction Volume by Type",
        color="txn_type",
        color_discrete_sequence=px.colors.qualitative.Set2,
        labels={"txn_type": "Transaction Type", "count": "Count"},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False)
    return fig.to_dict()


def _chart_country_breakdown(df: pd.DataFrame) -> dict:
    """Top-15 countries across sender + receiver columns."""
    if df.empty:
        return {}

    combined: list[str] = []
    if "sender_country" in df.columns:
        combined.extend(df["sender_country"].dropna().tolist())
    if "receiver_country" in df.columns:
        combined.extend(df["receiver_country"].dropna().tolist())

    if not combined:
        return {}

    country_series = pd.Series(combined)
    vc = country_series.value_counts().head(15).reset_index()
    vc.columns = ["country", "count"]

    fig = px.bar(
        vc,
        x="country",
        y="count",
        text="count",
        title="Top 15 Countries (sender + receiver combined)",
        labels={"country": "Country (ISO-3166)", "count": "Appearances"},
        color="count",
        color_continuous_scale="Blues",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(coloraxis_showscale=False)
    return fig.to_dict()


def _chart_volume_timeseries(df: pd.DataFrame) -> dict:
    """Daily transaction count time series."""
    if "timestamp" not in df.columns or df.empty:
        return {}

    tmp = df.copy()
    tmp["date"] = tmp["timestamp"].dt.date

    if "pattern_label" in tmp.columns:
        tmp["_label"] = tmp["pattern_label"].fillna("normal")
        daily = (
            tmp.groupby(["date", "_label"])
            .size()
            .reset_index(name="count")
        )
        fig = px.line(
            daily,
            x="date",
            y="count",
            color="_label",
            title="Daily Transaction Volume by Pattern",
            color_discrete_map={
                "normal":        "#78909C",
                "structuring":   "#EF5350",
                "smurfing":      "#AB47BC",
                "layering":      "#42A5F5",
                "rapid_cashout": "#FFA726",
            },
            labels={"date": "Date", "count": "Transactions", "_label": "Pattern"},
        )
    else:
        daily = tmp.groupby("date").size().reset_index(name="count")
        fig = px.line(
            daily,
            x="date",
            y="count",
            title="Daily Transaction Volume",
            color_discrete_sequence=["#42A5F5"],
            labels={"date": "Date", "count": "Transactions"},
        )

    fig.update_layout(legend_title_text="Pattern")
    return fig.to_dict()


# ---------------------------------------------------------------------------
# Registered tool
# ---------------------------------------------------------------------------


@tool(
    name="eda_profile",
    params={},
    description=(
        "Compute exploratory data analysis stats and Plotly charts over the working "
        "transaction DataFrame (ctx.df). Returns ToolResult.metrics (profile stats) "
        "and ToolResult.charts (Plotly figure JSON). Also stores the stats dict in "
        "ToolResult.artifacts['eda'] per the Contract 2 handshake table."
    ),
)
def eda_profile(ctx: ToolContext, **kw) -> ToolResult:
    """Run EDA over ctx.df and return metrics + Plotly chart JSON.

    Does not filter or modify the working frame. Safe to call at any point
    in the plan — operates on whatever transactions are in ctx.df.
    """
    try:
        df = ctx.df

        if df is None or len(df) == 0:
            return ToolResult(
                ok=True,
                metrics={"txn_count": 0},
                artifacts={"eda": {"txn_count": 0}},
                notes=["eda_profile: working DataFrame is empty — no stats computed"],
            )

        # ------------------------------------------------------------------
        # Compute all stats
        # ------------------------------------------------------------------
        stats: dict[str, Any] = {}
        stats.update(_profile_stats(df))
        stats.update(_amount_stats(df))
        stats.update(_label_stats(df))
        stats.update(_threshold_proximity_stats(df))

        # txn_type and channel breakdowns (compact)
        if "txn_type" in df.columns:
            stats["txn_type_counts"] = {
                str(k): int(v)
                for k, v in df["txn_type"].value_counts().items()
            }
        if "channel" in df.columns:
            stats["channel_counts"] = {
                str(k): int(v)
                for k, v in df["channel"].value_counts().items()
            }
        if "currency" in df.columns:
            stats["currency_counts"] = {
                str(k): int(v)
                for k, v in df["currency"].value_counts().head(10).items()
            }

        # ------------------------------------------------------------------
        # Build charts
        # ------------------------------------------------------------------
        charts: dict[str, dict] = {}
        charts["amount_histogram"]    = _chart_amount_histogram(df)
        charts["threshold_proximity"] = _chart_threshold_proximity(df)
        charts["txn_type_breakdown"]  = _chart_txn_type_breakdown(df)
        charts["country_breakdown"]   = _chart_country_breakdown(df)
        charts["volume_timeseries"]   = _chart_volume_timeseries(df)

        note = (
            f"eda_profile: {stats['txn_count']:,} transactions analysed"
        )
        if stats.get("date_min"):
            note += f" ({stats['date_min']} → {stats['date_max']})"

        return ToolResult(
            ok=True,
            metrics=stats,
            charts=charts,
            artifacts={"eda": stats},
            notes=[note],
        )

    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, error=f"eda_profile failed: {exc}")
