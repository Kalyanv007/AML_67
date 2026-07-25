"""
Planner: QueryIntent -> ExecutionPlan. Owner: Track A.

Implements the intent -> tool mapping table in docs/CONTRACTS.md Contract 4
exactly. Every step carries a `reason`; every deliberately-omitted tool is
logged in `tools_considered_but_skipped` with a reason of its own.
"""

import uuid

from backend.schemas import ExecutionPlan, QueryIntent, ToolCall


def build_plan(intent: QueryIntent) -> ExecutionPlan:
    steps: list[ToolCall] = []
    skipped: list[str] = []
    decisions: list[str] = []

    def add(tool: str, reason: str, **params) -> None:
        steps.append(ToolCall(tool=tool, params={k: v for k, v in params.items() if v is not None}, reason=reason))

    def skip(tool: str, reason: str) -> None:
        skipped.append(f"{tool}: {reason}")

    filters_dict = intent.filters.model_dump()

    if intent.intent == "full_analysis":
        add("load_data", "full analysis requires the complete working dataset")
        add("eda_profile", "broad exploration requested — profile the dataset before detection")
        add("feature_engineer", "compute all AML features for a full sweep")
        add("rule_detect", "apply all rule-based detectors")
        add("ml_detect", "apply anomaly detection to catch patterns the rules miss")
        add("risk_classify", "fuse rule + ML signals into a final risk score")

    elif intent.intent == "pattern_search":
        add("load_data", "load the working dataset")
        add("filter_data", "narrow to the requested filters before detection", filters=filters_dict)
        add("feature_engineer", f"compute only the features needed for {intent.pattern_types or 'the requested pattern'}",
            patterns=intent.pattern_types)
        add("rule_detect", "apply rule-based detectors scoped to the requested pattern(s)", patterns=intent.pattern_types)
        add("ml_detect", "widen the net with anomaly detection alongside the targeted rules")
        add("risk_classify", "fuse rule + ML signals")
        skip("eda_profile", "user asked for a specific pattern, not exploration")

    elif intent.intent == "threshold_query":
        add("load_data", "load the working dataset")
        add("filter_data", "apply the query's explicit filters", filters=filters_dict)
        add("aggregate_query", "a deterministic count/threshold answers this query directly",
            min_txn_count=intent.filters.min_txn_count, amount_max=intent.filters.amount_max)
        skip("feature_engineer", "no derived features needed for a direct count")
        skip("ml_detect", "a deterministic count answers this exactly — no anomaly detection needed")
        skip("eda_profile", "user asked a specific aggregation question, not exploration")

    elif intent.intent == "entity_investigation":
        entity_id = intent.entities[0] if intent.entities else None
        add("load_data", "load the working dataset")
        add("filter_data", "narrow to the requested entity's transactions", entity_ids=intent.entities)
        add("entity_lookup", "fetch the entity's profile and transaction summary", entity_id=entity_id)
        add("feature_engineer", "compute features scoped to this single entity", patterns=intent.pattern_types)
        add("rule_detect", "check this entity against rule-based detectors", patterns=intent.pattern_types)
        add("risk_classify", "compute this entity's risk score")
        skip("eda_profile", "single-entity investigation, not exploration")
        skip("ml_detect", "one entity is too small a sample for anomaly detection")

    elif intent.intent == "ranking":
        add("load_data", "load the working dataset")
        add("filter_data", "apply any filters before ranking", filters=filters_dict)
        add("feature_engineer", "compute features across the population to rank on")
        add("rule_detect", "apply rule-based detectors")
        add("ml_detect", "apply anomaly detection to catch patterns the rules miss")
        add("risk_classify", f"fuse signals and rank the top {intent.top_n}", top_n=intent.top_n)
        skip("eda_profile", "ranking query, not exploration")

    elif intent.intent == "eda":
        add("load_data", "load the working dataset")
        add("filter_data", "apply any filters before profiling", filters=filters_dict)
        add("eda_profile", "user asked to look at the data, not to flag it")
        skip("feature_engineer", "no detection requested")
        skip("rule_detect", "no detection requested")
        skip("ml_detect", "no detection requested")
        skip("risk_classify", "no detection requested")

    elif intent.intent == "explain_flag":
        entity_id = intent.entities[0] if intent.entities else None
        add("entity_lookup", "look up the cached flag for this entity/transaction", entity_id=entity_id)
        skip("load_data", "reusing a cached run instead of loading fresh data")
        skip("eda_profile", "explaining an existing flag, not exploring")
        skip("ml_detect", "explaining an existing flag, not re-scoring")

    else:
        add("load_data", "unrecognised intent — falling back to full analysis on a sample")
        add("eda_profile", "fallback full analysis")
        add("feature_engineer", "fallback full analysis")
        add("rule_detect", "fallback full analysis")
        add("ml_detect", "fallback full analysis")
        add("risk_classify", "fallback full analysis")
        decisions.append(f"intent '{intent.intent}' unrecognised — defaulted to full_analysis")

    if intent.confidence and intent.confidence < 0.4:
        decisions.append(f"low parser confidence ({intent.confidence:.2f}) — plan may be revised if results look sparse")

    return ExecutionPlan(
        plan_id=uuid.uuid4().hex[:12],
        steps=steps,
        decisions=decisions,
        tools_considered_but_skipped=skipped,
    )
