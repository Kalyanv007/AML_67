"""
Frozen contract — see docs/CONTRACTS.md Contract 1.

Owner: Track A. Read-only for Track B. Changes after the kickoff-hour freeze
require both people present (see WORKPLAN.md Section 4).
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

Intent = Literal[
    "full_analysis", "pattern_search", "threshold_query",
    "entity_investigation", "ranking", "eda", "explain_flag",
]
PatternType = Literal[
    "structuring", "smurfing", "layering", "rapid_cashout",
    "velocity", "dormant_reactivation", "unknown",
]
RiskLevel = Literal["high", "medium", "low", "none"]
Escalation = Literal["report", "review", "monitor", "no_action"]


class Filters(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    countries: list[str] = []
    txn_types: list[str] = []
    amount_min: float | None = None
    amount_max: float | None = None
    min_txn_count: int | None = None
    customer_segment: str | None = None


class QueryIntent(BaseModel):
    raw_query: str
    intent: Intent
    filters: Filters = Filters()
    entities: list[str] = []
    pattern_types: list[PatternType] = []
    top_n: int = 10
    confidence: float = 0.0
    parsed_by: Literal["llm", "rules"]


class ToolCall(BaseModel):
    tool: str
    params: dict = {}
    reason: str
    status: Literal["pending", "ok", "skipped", "error"] = "pending"
    duration_ms: int | None = None
    skip_reason: str | None = None


class ExecutionPlan(BaseModel):
    plan_id: str
    steps: list[ToolCall] = []
    decisions: list[str] = []
    tools_considered_but_skipped: list[str] = []


class Evidence(BaseModel):
    rule_id: str | None = None
    feature: str | None = None
    value: float | str
    threshold: float | str | None = None
    note: str = ""


class Flag(BaseModel):
    entity_type: Literal["customer", "transaction"]
    entity_id: str
    risk_score: float = Field(ge=0, le=100)
    risk_level: RiskLevel
    escalation: Escalation
    patterns: list[PatternType] = []
    triggered_rules: list[str] = []
    ml_score: float | None = None
    evidence: list[Evidence] = []
    explanation: str
    sar_draft: str | None = None


class AgentResponse(BaseModel):
    query: str
    intent: QueryIntent
    plan: ExecutionPlan
    flags: list[Flag] = []
    tables: dict[str, list[dict]] = {}
    charts: dict[str, dict] = {}
    metrics: dict[str, Any] = {}
    summary: str = ""
    warnings: list[str] = []
