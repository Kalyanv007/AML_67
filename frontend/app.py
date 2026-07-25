"""
frontend/app.py

AML Suspicious Activity Detection — Streamlit UI.
Owner: Track B.

HTTP client only — talks to Track A's API at http://localhost:8000.
No imports from backend.agent.* or backend.tools.*.

OPERATION MODES
---------------
LIVE mode   : API_BASE_URL responds to GET /health.
              All queries go to POST /query. Sidebar shows live dataset summary.
FIXTURE mode: API not reachable. Queries are matched to a saved fixture JSON
              (frontend/fixtures/full_analysis.json) so the demo is never blocked.
              A banner clearly labels that fixture data is being shown.
              The HTTP-client code path is IDENTICAL in both modes —
              fixtures are only loaded if the HTTP call fails, not instead of it.

Switching modes: start Track A's API (uvicorn backend.main:app) and refresh.

Per WORKPLAN.md §7:
  "B never waits for A. Test every tool directly with pytest;
   the UI can render a saved AgentResponse JSON fixture until the API is live."
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
import streamlit as st

from frontend.components.plan_trace import render_plan_trace
from frontend.components.flag_cards import render_flag_cards
from frontend.components.charts import render_charts, render_tables

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE_URL  = os.getenv("AML_API_URL", "http://localhost:8000")
FIXTURE_DIR   = Path(__file__).parent / "fixtures"
REQUEST_TIMEOUT = 60   # seconds

# ---------------------------------------------------------------------------
# Example queries — covers all plan-divergence test cases (WORKPLAN §8)
# ---------------------------------------------------------------------------

EXAMPLE_QUERIES: list[dict] = [
    {
        "label": "🔍 Full analysis",
        "query": "Analyse this dataset for suspicious activity",
        "intent": "full_analysis",
    },
    {
        "label": "🧑 Entity investigation",
        "query": "Is customer 4521 suspicious?",
        "intent": "entity_investigation",
    },
    {
        "label": "📊 Threshold query",
        "query": "Which customers made 10+ transactions under $10,000?",
        "intent": "threshold_query",
    },
    {
        "label": "🎯 Pattern search",
        "query": "Find structuring patterns in the last 30 days",
        "intent": "pattern_search",
    },
    {
        "label": "🏆 Ranking",
        "query": "Rank the top 10 highest-risk customers",
        "intent": "ranking",
    },
    {
        "label": "📈 Exploratory analysis",
        "query": "Show me a breakdown of transaction types and countries",
        "intent": "eda",
    },
]

# ---------------------------------------------------------------------------
# HTTP client helpers — same code in LIVE and FIXTURE mode
# ---------------------------------------------------------------------------


def _check_health() -> dict | None:
    """Return /health payload, or None if unreachable."""
    try:
        r = requests.get(f"{API_BASE_URL}/health", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _get_dataset_summary() -> dict | None:
    try:
        r = requests.get(f"{API_BASE_URL}/dataset/summary", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _post_query(query_text: str, dataset: str | None = None) -> dict | None:
    """POST to /query and return the AgentResponse dict, or None on failure."""
    try:
        payload = {"query": query_text}
        if dataset:
            payload["dataset"] = dataset
        r = requests.post(
            f"{API_BASE_URL}/query",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _load_fixture(intent_hint: str | None = None) -> dict:
    """Load the best-matching fixture JSON for the query intent.

    Falls back to full_analysis.json if no specific fixture found.
    """
    intent_to_file = {
        "full_analysis":        "full_analysis.json",
        "entity_investigation": "full_analysis.json",
        "threshold_query":      "full_analysis.json",
        "pattern_search":       "full_analysis.json",
        "ranking":              "full_analysis.json",
        "eda":                  "full_analysis.json",
    }
    filename = intent_to_file.get(intent_hint or "full_analysis", "full_analysis.json")
    fixture_path = FIXTURE_DIR / filename
    with open(fixture_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AML Detection Agent",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
        min-height: 100vh;
    }

    .main-header {
        background: linear-gradient(90deg, #6366f1, #8b5cf6, #a855f7);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.5rem;
        font-weight: 700;
        letter-spacing: -1px;
        margin-bottom: 0;
    }

    .fixture-banner {
        background: linear-gradient(90deg, #7c3aed22, #6366f122);
        border: 1px solid #6366f1;
        border-radius: 8px;
        padding: 10px 16px;
        margin-bottom: 16px;
        color: #a5b4fc;
        font-size: 13px;
    }

    .stButton > button {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }

    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
    }

    .example-btn > button {
        background: #1e293b !important;
        border: 1px solid #334155 !important;
        color: #94a3b8 !important;
        font-size: 12px !important;
        font-weight: 500 !important;
        padding: 4px 10px !important;
    }

    .example-btn > button:hover {
        border-color: #6366f1 !important;
        color: #a5b4fc !important;
        transform: none !important;
        box-shadow: none !important;
    }

    [data-testid="metric-container"] {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px;
    }

    .stDataFrame {
        border: 1px solid #334155;
        border-radius: 6px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🔎 AML Agent")
    st.markdown("---")

    health = _check_health()
    api_live = health is not None

    if api_live:
        st.success("✅ API Online")
        llm_ok = health.get("llm_available", False)
        mocks  = health.get("mocks", False)
        st.markdown(f"**LLM:** {'✅ Available' if llm_ok else '⚠️ Offline (fallback mode)'}")
        st.markdown(f"**Mocks:** `{'on' if mocks else 'off'}`")

        summary = _get_dataset_summary()
        if summary:
            st.markdown("---")
            st.markdown("### 📂 Dataset")
            st.metric("Transactions", f"{summary.get('row_count', 0):,}")
            st.metric("Customers",    f"{summary.get('customer_count', 0):,}")
            cols = summary.get("columns", [])
            if cols:
                with st.expander("Schema columns"):
                    for c in cols:
                        st.markdown(f"- `{c}`")
    else:
        st.warning("⚠️ API Offline")
        st.markdown(
            "<small>Track A's API is not running.<br/>"
            "Showing fixture data — results are illustrative.</small>",
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.markdown("### 📂 Fixture Dataset")
        st.metric("Transactions", "2,000")
        st.metric("Customers",    "270")

    st.markdown("---")
    st.markdown("### ℹ️ About")
    st.markdown(
        "<small>AI-powered Suspicious Activity Detection.<br/>"
        "Built for the 48h AML hackathon.<br/>"
        "Track B: Data · Detection · UI</small>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

st.markdown('<h1 class="main-header">AML Suspicious Activity Detection</h1>', unsafe_allow_html=True)
st.markdown(
    "<p style='color:#94a3b8;margin-top:0;'>Natural-language queries over financial transaction data · "
    "Adaptive execution plans · Risk-scored flags with escalation actions</p>",
    unsafe_allow_html=True,
)

# Fixture mode banner
if not api_live:
    st.markdown(
        '<div class="fixture-banner">⚡ <strong>Fixture mode</strong> — '
        "Track A's API is not reachable at <code>localhost:8000</code>. "
        "Results below are from a pre-computed fixture that matches the live AgentResponse schema exactly. "
        "Start <code>uvicorn backend.main:app</code> and refresh to switch to live mode.</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Query box
# ---------------------------------------------------------------------------

st.markdown("### 💬 Query")

# Pre-fill from example button clicks (stored in session state)
if "query_prefill" not in st.session_state:
    st.session_state["query_prefill"] = ""

query_input = st.text_area(
    label="Enter your query:",
    value=st.session_state["query_prefill"],
    placeholder="e.g. 'Analyse this dataset for suspicious activity'",
    height=80,
    key="query_text",
    label_visibility="collapsed",
)

submit_col, _ = st.columns([1, 4])
with submit_col:
    run_query = st.button("🔍 Run Query", type="primary", use_container_width=True)

# Example query buttons — one row
st.markdown("**Quick queries:**")
btn_cols = st.columns(len(EXAMPLE_QUERIES))
for i, ex in enumerate(EXAMPLE_QUERIES):
    with btn_cols[i]:
        st.markdown('<div class="example-btn">', unsafe_allow_html=True)
        if st.button(ex["label"], key=f"ex_{i}", use_container_width=True):
            st.session_state["query_prefill"] = ex["query"]
            st.session_state["pending_intent"] = ex.get("intent")
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Execute query
# ---------------------------------------------------------------------------

response: dict | None = None
using_fixture = False

if run_query and query_input.strip():
    intent_hint = st.session_state.pop("pending_intent", None)

    with st.spinner("Running analysis…"):
        t0 = time.time()
        response = _post_query(query_input.strip())
        elapsed = time.time() - t0

    if response is None:
        # Live call failed — fall back to fixture
        using_fixture = True
        response = _load_fixture(intent_hint)
        # Patch the query field so the trace shows what was actually asked
        response = dict(response)
        response["query"] = query_input.strip()
        st.warning(
            f"⚠️ API call failed or timed out. Showing fixture data instead. "
            f"(elapsed: {elapsed:.1f}s)"
        )
    else:
        st.success(f"✅ Response received in {elapsed:.1f}s")

elif "pending_intent" in st.session_state:
    # Example button was just clicked — show fixture immediately so the
    # user sees something without needing to press Run Query
    intent_hint = st.session_state["pending_intent"]
    using_fixture = True
    response = _load_fixture(intent_hint)
    response = dict(response)
    response["query"] = st.session_state.get("query_prefill", response.get("query", ""))

# ---------------------------------------------------------------------------
# Render results
# ---------------------------------------------------------------------------

if response:
    # Header: query + summary
    st.markdown("---")
    st.markdown(f"**Query:** *{response.get('query', '')}*")

    summary_text = response.get("summary", "")
    warnings     = response.get("warnings", [])

    if summary_text:
        st.markdown(
            f'<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            f'border-left:4px solid #6366f1;margin-bottom:12px;">'
            f'<strong>Summary:</strong> {summary_text}</div>',
            unsafe_allow_html=True,
        )

    for w in warnings:
        st.warning(w)

    # Metrics row
    metrics = response.get("metrics", {})
    if metrics:
        metric_keys = ["total_transactions", "total_customers", "flags_raised", "high_risk", "medium_risk", "low_risk"]
        present = {k: metrics[k] for k in metric_keys if k in metrics}
        if present:
            m_cols = st.columns(len(present))
            for col, (key, val) in zip(m_cols, present.items()):
                col.metric(key.replace("_", " ").title(), f"{val:,}" if isinstance(val, int) else val)

    # 1 — Execution plan trace (highest-value component, above results)
    render_plan_trace(response)

    # 2 — Flag cards
    st.markdown("---")
    flags = response.get("flags", [])
    if flags:
        render_flag_cards(flags)
    else:
        # Graceful empty-result handling
        no_flag_msg = summary_text or "No suspicious entities were flagged by this query."
        st.success(f"✅ {no_flag_msg}")
        if warnings:
            for w in warnings:
                st.info(w)

    # 3 — Charts (Plotly JSON from AgentResponse.charts)
    charts = response.get("charts", {})
    render_charts(charts)

    # 4 — Tables + exports
    tables = response.get("tables", {})
    render_tables(tables, response)

elif not run_query:
    # Landing state — prompt the user
    st.markdown("---")
    st.markdown(
        '<div style="text-align:center;padding:40px;color:#475569;">'
        '<div style="font-size:48px;margin-bottom:16px;">🔎</div>'
        '<div style="font-size:18px;font-weight:500;">Enter a query or click an example above</div>'
        '<div style="font-size:14px;margin-top:8px;">The agent will build a custom execution plan, '
        'run only the relevant tools, and return risk-scored flags with escalation actions.</div>'
        '</div>',
        unsafe_allow_html=True,
    )
