"""
frontend/components/plan_trace.py

Renders the execution-plan trace panel.
WORKPLAN.md: "the highest-value component in the whole project."
Placed directly under the query box, above results.

Renders from AgentResponse fields:
  - intent  : QueryIntent
  - plan    : ExecutionPlan
    - steps : list[ToolCall]
    - decisions[]
    - tools_considered_but_skipped[]

Owner: Track B. No backend.agent.* imports.
"""

from __future__ import annotations

import streamlit as st

# Status badge colours
_STATUS_COLOUR: dict[str, str] = {
    "ok":      "#22c55e",   # green
    "skipped": "#94a3b8",   # slate
    "error":   "#ef4444",   # red
    "pending": "#f59e0b",   # amber
}

_INTENT_LABEL: dict[str, str] = {
    "full_analysis":       "🔍 Full Analysis",
    "pattern_search":      "🎯 Pattern Search",
    "threshold_query":     "📊 Threshold Query",
    "entity_investigation":"🧑 Entity Investigation",
    "ranking":             "🏆 Ranking",
    "eda":                 "📈 Exploratory Analysis",
    "explain_flag":        "💡 Explain Flag",
}


def render_plan_trace(response: dict) -> None:
    """Render the full execution-plan trace panel from an AgentResponse dict."""
    intent_obj = response.get("intent", {})
    plan_obj   = response.get("plan", {})

    st.markdown("---")
    st.subheader("🗺️ Execution Plan Trace")

    # ------------------------------------------------------------------
    # Intent summary row
    # ------------------------------------------------------------------
    intent_str  = intent_obj.get("intent", "unknown")
    parsed_by   = intent_obj.get("parsed_by", "?")
    confidence  = intent_obj.get("confidence", 0.0)
    entities    = intent_obj.get("entities", [])
    patterns    = intent_obj.get("pattern_types", [])
    filters     = intent_obj.get("filters", {})

    col_a, col_b, col_c = st.columns([2, 1, 1])
    with col_a:
        st.markdown(
            f"**Detected intent:** {_INTENT_LABEL.get(intent_str, intent_str)}"
        )
    with col_b:
        st.markdown(f"**Parsed by:** `{parsed_by}`")
    with col_c:
        st.markdown(f"**Confidence:** `{confidence:.0%}`")

    # Entities + patterns + active filters
    detail_parts: list[str] = []
    if entities:
        detail_parts.append(f"**Entities:** {', '.join(f'`{e}`' for e in entities)}")
    if patterns:
        detail_parts.append(f"**Patterns:** {', '.join(f'`{p}`' for p in patterns)}")

    active_filters = {k: v for k, v in filters.items() if v not in (None, [], "")}
    if active_filters:
        filt_str = " · ".join(f"`{k}={v}`" for k, v in active_filters.items())
        detail_parts.append(f"**Filters:** {filt_str}")

    if detail_parts:
        st.markdown("  \n".join(detail_parts))
    else:
        st.markdown("*No entity, pattern, or filter constraints extracted.*")

    # ------------------------------------------------------------------
    # Tool steps timeline
    # ------------------------------------------------------------------
    steps = plan_obj.get("steps", [])
    if steps:
        st.markdown("#### 🔧 Tool Steps")
        for i, step in enumerate(steps, 1):
            status   = step.get("status", "pending")
            colour   = _STATUS_COLOUR.get(status, "#94a3b8")
            tool     = step.get("tool", "unknown")
            reason   = step.get("reason", "")
            duration = step.get("duration_ms")
            dur_str  = f"`{duration} ms`" if duration is not None else "`—`"

            badge = f'<span style="background:{colour};color:#000;border-radius:4px;padding:1px 7px;font-size:12px;font-weight:600;">{status.upper()}</span>'
            st.markdown(
                f"**{i}. `{tool}`** {badge} &nbsp;&nbsp;{dur_str}",
                unsafe_allow_html=True,
            )
            st.markdown(f"<span style='color:#94a3b8;font-size:13px;margin-left:16px;'>↳ {reason}</span>", unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # Skipped tools
    # ------------------------------------------------------------------
    skipped = plan_obj.get("tools_considered_but_skipped", [])
    if skipped:
        st.markdown("#### ⏭️ Tools Considered but Skipped")
        for s in skipped:
            st.markdown(f"- <span style='color:#94a3b8;'>{s}</span>", unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # Re-planning decisions log
    # ------------------------------------------------------------------
    decisions = plan_obj.get("decisions", [])
    if decisions:
        st.markdown("#### 🔄 Re-planning Decisions")
        for d in decisions:
            st.info(d)
