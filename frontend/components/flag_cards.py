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

Risk band → colour mapping lives in frontend/components/theme.py (RISK_COLOR),
shared with plan_trace.py so the palette can't drift between components.

Escalation icon mapping:
  report    → 🚨
  review    → 🔍
  monitor   → 👁️
  no_action → ✅

Owner: Track B. No backend.agent.* imports.
"""

from __future__ import annotations

import streamlit as st

from frontend.components.theme import RISK_COLOR, RISK_TEXT_ON, TEXT_MUTED

_ESCALATION_ICON: dict[str, str] = {
    "report":    "🚨",
    "review":    "🔍",
    "monitor":   "👁️",
    "no_action": "✅",
}


def _risk_badge(level: str, score: float) -> str:
    colour = RISK_COLOR.get(level, "#64748b")
    text_colour = RISK_TEXT_ON.get(level, "#ffffff")
    return (
        f'<span style="background:{colour};color:{text_colour};border-radius:6px;'
        f'padding:4px 12px;font-size:14px;font-weight:700;letter-spacing:1px;">'
        f'{level.upper()} · {score:.1f}</span>'
    )


def render_flag_cards(flags: list[dict]) -> None:
    """Render a card for every flag in the list.

    HIGH-risk cards are expanded by default; MEDIUM and LOW are collapsed
    so the page doesn't drown when there are many flags.
    """
    if not flags:
        st.info("✅ No entities flagged by this query.")
        return

    high   = [f for f in flags if f.get("risk_level") == "high"]
    medium = [f for f in flags if f.get("risk_level") == "medium"]
    low    = [f for f in flags if f.get("risk_level") == "low"]
    other  = [f for f in flags if f.get("risk_level") not in ("high", "medium", "low")]

    total = len(flags)
    parts = []
    if high:   parts.append(f"🔴 {len(high)} HIGH")
    if medium: parts.append(f"🟠 {len(medium)} MEDIUM")
    if low:    parts.append(f"🟡 {len(low)} LOW")
    st.subheader(f"🚩 Flagged Entities ({total}) — {' · '.join(parts)}")

    for flag in high + medium + low + other:
        _render_one_flag(flag)


def _render_one_flag(flag: dict) -> None:
    """Render a single flag inside a collapsible expander."""
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

    esc_icon = _ESCALATION_ICON.get(escalation, "")

    # HIGH cards open by default; MEDIUM/LOW collapsed so the page stays clean
    expanded = risk_level == "high"
    label = f"{entity_id} · {risk_level.upper()} · {risk_score:.1f}"

    with st.expander(label, expanded=expanded, icon=esc_icon or "🚩"):
        with st.container(border=True):
            # Header row: badge + escalation
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(_risk_badge(risk_level, risk_score), unsafe_allow_html=True)
                st.markdown(f"### `{entity_id}`")
            with col2:
                st.markdown(
                    f"<div style='text-align:right;padding-top:8px;'>"
                    f"<span style='font-size:24px'>{esc_icon}</span><br/>"
                    f"<span style='color:{TEXT_MUTED};font-size:13px;'>{escalation.replace('_',' ').upper()}</span>"
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
                ev_rows = [
                    {
                        "Rule":      ev.get("rule_id") or "—",
                        "Feature":   ev.get("feature") or "—",
                        "Value":     ev.get("value", ""),
                        "Threshold": ev.get("threshold") or "—",
                        "Note":      ev.get("note", ""),
                    }
                    for ev in evidence
                ]
                st.dataframe(ev_rows, use_container_width=True, hide_index=True)

            # SAR draft (HIGH only) — rendered as st.code so judges can copy it.
            # Not wrapped in its own expander: this card is already inside the
            # outer st.expander in render_flag_cards(), and Streamlit disallows
            # nesting an expander inside another expander.
            if sar_draft:
                st.markdown("**📋 SAR Draft:**")
                st.code(sar_draft, language=None)
