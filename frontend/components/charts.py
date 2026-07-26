"""
frontend/components/charts.py

Renders Plotly charts from AgentResponse.charts (dict[str, dict]), the
KPI metrics row, and the risk-distribution bar chart.

The chart dict values are already Plotly figure JSON (per Contract 1 /
ToolResult.charts). We render them directly with st.plotly_chart — no
reconstruction from metrics.

Owner: Track B. No backend.agent.* imports.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from frontend.components.theme import KPI_SPECS, RISK_COLOR, TEXT_MUTED, resolve_metric


def render_kpi_row(metrics: dict) -> None:
    """Bordered-container KPI cards — the streamlit==1.39-compatible
    equivalent of st.metric(border=True) (that param needs streamlit>=1.40).

    Resolves both the live tools' key names and the fixture's aspirational
    key names via theme.resolve_metric, so this renders correctly in both
    LIVE and FIXTURE mode.
    """
    if not metrics:
        return

    present = [(label, resolve_metric(metrics, *aliases)) for label, aliases in KPI_SPECS]
    present = [(label, val) for label, val in present if val is not None]
    if not present:
        return

    cols = st.columns(len(present), gap="small")
    for col, (label, val) in zip(cols, present):
        with col, st.container(border=True):
            st.metric(label, f"{val:,}" if isinstance(val, int) else val)


def render_risk_distribution(metrics: dict) -> None:
    """HIGH/MEDIUM/LOW bar — shows the risk breakdown at a glance.

    Uses the same alias resolver as render_kpi_row, so it can no longer
    disagree with the KPI row (previously read a different, inconsistent
    set of keys than the metrics row above it).
    """
    h = resolve_metric(metrics, "high_risk", "high") or 0
    m = resolve_metric(metrics, "medium_risk", "medium") or 0
    low = resolve_metric(metrics, "low_risk", "low") or 0
    if not (h or m or low):
        return

    fig = go.Figure(
        go.Bar(
            x=[h, m, low],
            y=["HIGH", "MEDIUM", "LOW"],
            orientation="h",
            marker_color=[RISK_COLOR["high"], RISK_COLOR["medium"], RISK_COLOR["low"]],
            text=[str(v) for v in (h, m, low)],
            textposition="outside",
        )
    )
    fig.update_layout(
        height=140,
        margin=dict(t=4, b=4, l=8, r=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_MUTED, size=13),
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_charts(charts: dict) -> None:
    """Render all charts from AgentResponse.charts.

    charts: dict[str, dict] — chart name → Plotly figure JSON dict
    """
    if not charts:
        return

    st.subheader("Dataset Charts", divider="grey")

    for chart_name, fig_json in charts.items():
        if not fig_json:
            continue
        try:
            fig = go.Figure(fig_json)
            label = chart_name.replace("_", " ").title()
            st.markdown(f"**{label}**")
            st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
            st.warning(f"Could not render chart '{chart_name}': {exc}")


def render_tables(tables: dict, response: dict) -> None:
    """Render AgentResponse.tables and provide CSV/JSON export.

    tables: dict[str, list[dict]] — table name → list of row dicts
    """
    if not tables:
        return

    st.subheader("Result Tables", divider="grey")

    import json
    import pandas as pd

    for table_name, rows in tables.items():
        if not rows:
            continue
        label = table_name.replace("_", " ").title()
        st.markdown(f"**{label}**")
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        col_csv, col_json = st.columns(2)
        with col_csv:
            st.download_button(
                label=f"⬇️ Download {label} (CSV)",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=f"{table_name}.csv",
                mime="text/csv",
                key=f"csv_{table_name}",
            )
        with col_json:
            st.download_button(
                label=f"⬇️ Download {label} (JSON)",
                data=json.dumps(rows, indent=2).encode("utf-8"),
                file_name=f"{table_name}.json",
                mime="application/json",
                key=f"json_{table_name}",
            )

    # Full AgentResponse export
    st.divider()
    st.markdown("**Export full AgentResponse:**")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="⬇️ Full Response (JSON)",
            data=json.dumps(response, indent=2, default=str).encode("utf-8"),
            file_name="agent_response.json",
            mime="application/json",
            key="export_full_json",
        )
