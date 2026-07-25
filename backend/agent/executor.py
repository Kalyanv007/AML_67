"""
Executor: runs an ExecutionPlan's steps against the tool registry. Owner: Track A.

Threads one ToolContext through all steps, times each step, isolates tool
failures (a failing tool marks its step "error" and the run continues), and
performs the conditional re-planning specified in docs/CONTRACTS.md Contract 4:
  - rule_detect returns 0 hits -> append ml_detect
  - filtered subset < 50 rows -> drop a queued ml_detect
  - filter_data returns 0 rows -> stop early with an explanatory summary
"""

import time
from typing import Any

from backend.agent import registry
from backend.agent.narrator import build_flags
from backend.config import settings
from backend.schemas import AgentResponse, ExecutionPlan, QueryIntent, ToolCall
from backend.tools.base import ToolContext

_TOOLS_CACHE: dict[str, Any] | None = None


def _get_tools() -> dict[str, Any]:
    global _TOOLS_CACHE
    if _TOOLS_CACHE is None:
        _TOOLS_CACHE = registry.load_tools(use_mocks=settings.aml_use_mocks)
    return _TOOLS_CACHE


def run_plan(intent: QueryIntent, plan: ExecutionPlan) -> AgentResponse:
    tools = _get_tools()
    ctx = ToolContext(df=None, customers=None, intent=intent, artifacts={})
    response = AgentResponse(query=intent.raw_query, intent=intent, plan=plan)

    steps = list(plan.steps)
    i = 0
    while i < len(steps):
        step = steps[i]
        fn = tools.get(step.tool)

        if fn is None:
            step.status = "error"
            response.warnings.append(f"unknown tool '{step.tool}' — skipped")
            i += 1
            continue

        t0 = time.perf_counter()
        try:
            result = fn(ctx, **step.params)
        except Exception as exc:  # isolate any tool failure, never let it 500 the API
            step.status = "error"
            step.duration_ms = int((time.perf_counter() - t0) * 1000)
            response.warnings.append(f"{step.tool} raised {type(exc).__name__}: {exc}")
            i += 1
            continue
        step.duration_ms = int((time.perf_counter() - t0) * 1000)

        if not result.ok:
            step.status = "error"
            response.warnings.append(result.error or f"{step.tool} returned ok=False")
            i += 1
            continue

        step.status = "ok"
        if result.df is not None:
            ctx.df = result.df
        ctx.artifacts.update(result.artifacts)
        response.tables.update(result.tables)
        response.charts.update(result.charts)
        response.metrics.update(result.metrics)
        plan.decisions.extend(result.notes)

        if step.tool == "filter_data" and ctx.df is not None:
            if len(ctx.df) == 0:
                plan.decisions.append("filter_data returned 0 rows — stopping execution early")
                response.summary = "No transactions matched the given filters."
                plan.steps = steps
                return response
            if len(ctx.df) < 50:
                remaining = steps[i + 1:]
                still_has_ml = any(s.tool == "ml_detect" for s in remaining)
                if still_has_ml:
                    steps[i + 1:] = [s for s in remaining if s.tool != "ml_detect"]
                    plan.decisions.append(
                        "sample too small for anomaly detection (<50 rows) — skipping ml_detect"
                    )

        if step.tool == "rule_detect":
            hits = ctx.artifacts.get("rule_hits", [])
            already_planned = any(s.tool == "ml_detect" for s in steps[i + 1:])
            if not hits and not already_planned:
                steps.insert(i + 1, ToolCall(tool="ml_detect", reason="no rule hits — widening to ML anomaly detection"))
                plan.decisions.append("no rule hits — widening the net with ml_detect")

        i += 1

    risk_rows = ctx.artifacts.get("risk_rows", [])

    if intent.intent in ("entity_investigation", "explain_flag") and intent.entities:
        # filter_data has no per-entity dimension (see planner.py), so risk_classify
        # scores the whole population — narrow to the requested entity/entities here.
        wanted = set(intent.entities)
        risk_rows = [r for r in risk_rows if r.get("entity_id") in wanted]

    if intent.intent == "ranking":
        # risk_classify has no top_n param (see planner.py) — rows arrive pre-sorted
        # descending by risk_score (backend/tools/risk.py), so a plain slice is correct.
        risk_rows = risk_rows[: intent.top_n]

    response.flags = build_flags(risk_rows)
    if not response.summary:
        response.summary = _summarise(intent, response)
    plan.steps = steps
    return response


def _summarise(intent: QueryIntent, response: AgentResponse) -> str:
    n = len(response.flags)
    if intent.intent == "entity_investigation":
        entity = intent.entities[0] if intent.entities else "the requested entity"
        if n:
            f = response.flags[0]
            return f"{entity} is flagged {f.risk_level} risk (score {f.risk_score:.0f}) — recommended action: {f.escalation}."
        return f"{entity} shows no flagged risk indicators in the current data."
    if intent.intent == "threshold_query":
        count = response.metrics.get("row_count", n)
        return f"{count} customer(s) matched the specified threshold."
    if n:
        return f"{n} entity(ies) flagged for review across the analysed data."
    return "No suspicious activity was flagged for this query."
