"""
Mock tool implementations — activated when AML_USE_MOCKS=1.

Owner: Track A. Lets the agent core (intent parsing, planning, execution,
narration) be built and tested end-to-end before Track B's real tools land.
Registered under the exact same names as the real tools in docs/CONTRACTS.md
Contract 2, so swapping AML_USE_MOCKS=0 requires no changes anywhere else.
"""

from datetime import date

import pandas as pd

from backend.tools.base import ToolContext, ToolResult, tool

_MOCK_CUSTOMER_IDS = ["C-04521", "C-01187", "C-09902"]


@tool(name="load_data", description="Loads the working transaction + customer datasets.")
def load_data(ctx: ToolContext, dataset: str | None = None, **kw) -> ToolResult:
    df = pd.DataFrame(
        {
            "txn_id": [f"T-{i:06d}" for i in range(1, 6)],
            "timestamp": pd.date_range("2026-06-01", periods=5, freq="D"),
            "sender_id": ["C-04521", "C-01187", "C-04521", "C-09902", "C-04521"],
            "receiver_id": ["C-01187", "C-04521", "C-09902", "C-04521", "C-01187"],
            "amount": [9500.0, 200.0, 9800.0, 15000.0, 9100.0],
            "currency": ["USD"] * 5,
            "txn_type": ["transfer", "deposit", "transfer", "wire", "transfer"],
            "channel": ["online", "branch", "online", "wire", "mobile"],
            "sender_country": ["US", "US", "US", "US", "US"],
            "receiver_country": ["US", "US", "US", "GB", "US"],
            "is_cross_border": [False, False, False, True, False],
            "label_is_laundering": [None] * 5,
            "pattern_label": ["structuring", None, "structuring", None, "structuring"],
        }
    )
    customers = pd.DataFrame(
        {
            "customer_id": _MOCK_CUSTOMER_IDS,
            "name": ["Mock Customer A", "Mock Customer B", "Mock Customer C"],
            "account_open_date": [date(2020, 1, 1)] * 3,
            "customer_type": ["individual", "individual", "business"],
            "country": ["US", "US", "US"],
            "occupation": ["engineer", "teacher", "retail"],
            "risk_rating": ["low", "low", "medium"],
            "kyc_status": ["verified", "verified", "verified"],
            "is_pep": [False, False, False],
            "expected_monthly_volume": [5000.0, 3000.0, 20000.0],
        }
    )
    ctx.customers = customers
    return ToolResult(df=df, notes=[f"loaded {len(df)} mock transactions, {len(customers)} mock customers"])


@tool(name="filter_data", description="Applies date/country/type/amount/entity filters.")
def filter_data(ctx: ToolContext, **kw) -> ToolResult:
    return ToolResult(df=ctx.df, notes=[f"filtered to {len(ctx.df)} of {len(ctx.df)} transactions (mock: no-op)"])


@tool(name="eda_profile", description="Profiling stats + charts for exploratory analysis.")
def eda_profile(ctx: ToolContext, **kw) -> ToolResult:
    return ToolResult(
        tables={"eda_summary": [{"metric": "txn_count", "value": len(ctx.df)}]},
        charts={"amount_distribution": {"mock": True, "data": []}},
        metrics={"txn_count": len(ctx.df), "customer_count": len(_MOCK_CUSTOMER_IDS)},
        artifacts={"eda": {"txn_count": len(ctx.df)}},
    )


@tool(name="feature_engineer", description="Computes AML features requested by the query's patterns.")
def feature_engineer(ctx: ToolContext, patterns: list[str] | None = None, **kw) -> ToolResult:
    features = pd.DataFrame(
        {
            "customer_id": _MOCK_CUSTOMER_IDS,
            "pct_just_below_threshold": [0.6, 0.0, 0.1],
            "txn_count_30d": [3, 1, 1],
        }
    ).set_index("customer_id")
    return ToolResult(
        artifacts={"features": features, "feature_list": list(features.columns)},
        notes=["computed mock features for structuring pattern scope"],
    )


@tool(name="rule_detect", description="Applies rule-based AML detectors R1-R6.")
def rule_detect(ctx: ToolContext, patterns: list[str] | None = None, **kw) -> ToolResult:
    hits = [
        {
            "entity_id": "C-04521",
            "rule_id": "R1",
            "evidence": {"txn_count": 3, "window_days": 7, "amounts": [9500, 9800, 9100], "total": 28400},
            "weight": 0.9,
        }
    ]
    return ToolResult(artifacts={"rule_hits": hits}, metrics={"rules_fired": len(hits)},
                       notes=["R1 structuring matched 1 mock customer in a 7-day window"])


@tool(name="ml_detect", description="IsolationForest/LOF anomaly scoring.")
def ml_detect(ctx: ToolContext, **kw) -> ToolResult:
    scores = [{"entity_id": cid, "score": 0.2, "percentile": 0.5, "top_features": ["pct_just_below_threshold"]}
              for cid in _MOCK_CUSTOMER_IDS]
    scores[0]["percentile"] = 0.92
    return ToolResult(artifacts={"ml_scores": scores}, notes=["mock ML scoring over 3 customers"])


@tool(name="aggregate_query", description="Direct group-by / threshold aggregation, no ML.")
def aggregate_query(ctx: ToolContext, **kw) -> ToolResult:
    return ToolResult(
        tables={"aggregate_result": [{"customer_id": "C-04521", "txn_count": 3, "under_threshold": True}]},
        metrics={"matching_customers": 1},
    )


@tool(name="entity_lookup", description="Single-entity profile + transaction summary.")
def entity_lookup(ctx: ToolContext, entity_id: str | None = None, **kw) -> ToolResult:
    eid = entity_id or (ctx.intent.entities[0] if ctx.intent and ctx.intent.entities else _MOCK_CUSTOMER_IDS[0])
    return ToolResult(
        artifacts={"entity_profile": {"customer_id": eid, "txn_count": 3, "total_volume": 28400.0}},
        notes=[f"looked up mock profile for {eid}"],
    )


@tool(name="risk_classify", description="Fuses rule + ML signals into a risk score and escalation.")
def risk_classify(ctx: ToolContext, **kw) -> ToolResult:
    rows = [
        {
            "entity_id": "C-04521",
            "risk_score": 78.0,
            "risk_level": "high",
            "escalation": "report",
            "patterns": ["structuring"],
            "triggered_rules": ["R1"],
            "evidence": [
                {"rule_id": "R1", "feature": None, "value": 3, "threshold": 3, "note": "3 txns in 9k-9999 band over 7 days"}
            ],
        }
    ]
    return ToolResult(artifacts={"risk_rows": rows}, metrics={"flagged_count": len(rows)})
