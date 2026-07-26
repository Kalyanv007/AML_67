"""
frontend/components/theme.py

Single source of truth for color tokens and the metrics-key alias resolver.
Keep BG_APP/BG_CARD/BORDER/TEXT_MUTED in sync with .streamlit/config.toml.

Status/risk palette: fixed good/warning/serious/critical roles. These are
self-contained filled badges (colored background + fixed text color), so
they read correctly regardless of the page's light/dark theme — always
ship with a text label or icon alongside the color, never color alone.

Owner: Track B. No backend.agent.* imports. No Streamlit import — pure
constants + one pure function, safe to import from every component.
"""

from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Brand — light, professional slate & blue (enterprise/compliance-software look)
# ---------------------------------------------------------------------------

BRAND_PRIMARY = "#2563eb"        # blue-600
BRAND_PRIMARY_LIGHT = "#3b82f6"  # blue-500
BRAND_GRADIENT = ("#1e40af", "#2563eb", "#3b82f6")  # blue-800 -> blue-600 -> blue-500

# Surfaces — mirror .streamlit/config.toml
BG_APP = "#f8fafc"    # slate-50
BG_CARD = "#ffffff"   # white cards
BORDER = "#e2e8f0"    # slate-200
TEXT_MUTED = "#64748b"  # slate-500

# ---------------------------------------------------------------------------
# Risk-severity palette (none -> low -> medium -> high), dark-surface validated
# ---------------------------------------------------------------------------

RISK_COLOR: dict[str, str] = {
    "high": "#d03b3b",
    "medium": "#ec835a",
    "low": "#fab219",
    "none": "#0ca30c",
}

# Badge/bar text must adapt per band for contrast — "low" (bright gold) needs
# dark text; the other three are dark enough for white text.
RISK_TEXT_ON: dict[str, str] = {
    "high": "#ffffff",
    "medium": "#ffffff",
    "low": "#1a1a19",
    "none": "#ffffff",
}

# Plan-trace step status reuses the same 4 roles; "skipped" is a genuinely
# neutral, non-risk slate (kept distinct from the 4 risk roles on purpose).
PLAN_STEP_COLOR: dict[str, str] = {
    "ok": RISK_COLOR["none"],
    "pending": RISK_COLOR["low"],
    "error": RISK_COLOR["high"],
    "skipped": "#64748b",
}
PLAN_STEP_TEXT_ON: dict[str, str] = {
    "ok": "#ffffff",
    "pending": "#1a1a19",
    "error": "#ffffff",
    "skipped": "#ffffff",
}

# ---------------------------------------------------------------------------
# Metrics alias resolution — fixes the confirmed key-mismatch bug.
# Backend tools (risk.py, data_loader.py, ...) and the hand-authored fixture
# use different key names for the same concept; resolve by trying aliases
# in order so BOTH live and fixture responses render correctly.
# ---------------------------------------------------------------------------


def resolve_metric(metrics: dict[str, Any], *aliases: str) -> Optional[Any]:
    for key in aliases:
        if key in metrics:
            return metrics[key]
    return None


# label, ordered aliases (fixture-style name first, live tool-emitted name second)
KPI_SPECS: list[tuple[str, tuple[str, ...]]] = [
    ("Transactions", ("total_transactions", "txn_count", "row_count")),
    ("Customers", ("total_customers", "customer_count")),
    ("Flags Raised", ("flags_raised", "total_flagged")),
    ("High Risk", ("high_risk", "high")),
    ("Medium Risk", ("medium_risk", "medium")),
    ("Low Risk", ("low_risk", "low")),
]
