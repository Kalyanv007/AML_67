"""
frontend/components/flag_cards.py

Renders per-entity Flag cards from AgentResponse.flags (list[Flag]).

Each card shows:
  - Risk badge (colour-coded by band)
  - Entity ID + escalation action
  - Explanation paragraph
  - Evidence table (Flag.evidence rendered as a table, not prose)
  - SAR draft (only when sar_draft is not None — HIGH risk only per Contract 1)
  - Triggered rules + ML score

Risk band → colour mapping (stated here per the task instructions):
  high   → #ef4444  (red)
  medium → #f97316  (orange)
  low    → #f59e0b  (amber)
  none   → #64748b  (slate grey)

Escalation icon mapping:
  report    → 🚨
  review    → 🔍
  monitor   → 👁️
  no_action → ✅

Owner: Track B. No backend.agent.* imports.
"""

from __future__ import annotations

import streamlit as st

# ------------------------------------------------------------------
# Colour + icon maps
# ------------------------------------------------------------------

_RISK_COLOUR: dict[str, str] = {
    "high":   "#ef4444",
    "medium": "#f97316",
    "low":    "#f59e0b",
    "none":   "#64748b",
}

_ESCALATION_ICON: dict[str, str] = {
    "report":    "🚨",
    "review":    "🔍",
    "monitor":   "👁️",
    "no_action": "✅",
}


def _risk_badge(level: str, score: float) -> str:
    colour = _RISK_COLOUR.get(level, "#64748b")
    return (
        f'<span style="background:{colour};color:#fff;border-radius:6px;'
        f'padding:4px 12px;font-size:14px;font-weight:700;letter-spacing:1px;">'
        f'{level.upper()} · {score:.1f}</span>'
    )


def render_flag_cards(flags: list[dict]) -> None:
    """Render a card for every flag in the list."""
    if not flags:
        st.info("✅ No entities flagged by this query.")
        return

    st.subheader(f"🚩 Flagged Entities ({len(flags)})")

    for flag in flags:
        entity_id  = flag.get("entity_id", "?")
        risk_level = flag.get("risk_level", "none")
        risk_score = float(flag.get("risk_score", 0.0))
        escalation = flag.get("escalation", "no_action")
        patterns   = flag.get("patterns", [])
        rules      = flag.get("triggered_rules", [])
        ml_score   = flag.get("ml_score")
        explanation= flag.get("explanation", "")
        evidence   = flag.get("evidence", [])
        sar_draft  = flag.get("sar_draft")

        colour = _RISK_COLOUR.get(risk_level, "#64748b")
        esc_icon = _ESCALATION_ICON.get(escalation, "")

        with st.container():
            st.markdown(
                f'<div style="border-left:4px solid {colour};padding:12px 16px;'
                f'margin-bottom:16px;border-radius:4px;background:#1e293b;">',
                unsafe_allow_html=True,
            )

            # Header row: badge + entity + escalation
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    _risk_badge(risk_level, risk_score),
                    unsafe_allow_html=True,
                )
                st.markdown(f"### `{entity_id}`")
            with col2:
                st.markdown(
                    f"<div style='text-align:right;padding-top:8px;'>"
                    f"<span style='font-size:24px'>{esc_icon}</span><br/>"
                    f"<span style='color:#94a3b8;font-size:13px;'>{escalation.replace('_',' ').upper()}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # Patterns + rules + ML score
            meta_cols = st.columns(3)
            with meta_cols[0]:
                if patterns:
                    st.markdown(f"**Patterns:** {', '.join(f'`{p}`' for p in patterns)}")
            with meta_cols[1]:
                if rules:
                    st.markdown(f"**Rules triggered:** {', '.join(f'`{r}`' for r in rules)}")
            with meta_cols[2]:
                if ml_score is not None:
                    st.markdown(f"**ML percentile:** `{ml_score:.1%}`")

            # Explanation
            st.markdown(f"**Explanation:** {explanation}")

            # Evidence table
            if evidence:
                st.markdown("**Evidence:**")
                ev_rows = []
                for ev in evidence:
                    ev_rows.append({
                        "Rule":      ev.get("rule_id") or "—",
                        "Feature":   ev.get("feature") or "—",
                        "Value":     ev.get("value", ""),
                        "Threshold": ev.get("threshold") or "—",
                        "Note":      ev.get("note", ""),
                    })
                st.dataframe(ev_rows, use_container_width=True, hide_index=True)

            # SAR draft (HIGH only)
            if sar_draft:
                with st.expander("📋 SAR Draft (click to expand)", expanded=False):
                    st.markdown(
                        f'<div style="background:#1a1a2e;border:1px solid #ef4444;'
                        f'border-radius:6px;padding:12px;font-family:monospace;'
                        f'font-size:13px;color:#fca5a5;">{sar_draft}</div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("</div>", unsafe_allow_html=True)
