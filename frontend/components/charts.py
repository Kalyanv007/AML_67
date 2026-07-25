"""
frontend/components/charts.py

Renders Plotly charts from AgentResponse.charts (dict[str, dict]).

The dict values are already Plotly figure JSON (per Contract 1 / ToolResult.charts).
We render them directly with st.plotly_chart — no reconstruction from metrics.

Owner: Track B. No backend.agent.* imports.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go


def render_charts(charts: dict) -> None:
    """Render all charts from AgentResponse.charts.

    charts: dict[str, dict] — chart name → Plotly figure JSON dict
    """
    if not charts:
        return

    st.markdown("---")
    st.subheader("📊 Dataset Charts")

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

    st.markdown("---")
    st.subheader("📋 Result Tables")

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
    st.markdown("---")
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
