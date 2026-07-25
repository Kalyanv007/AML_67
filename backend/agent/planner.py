"""
Planner: QueryIntent -> ExecutionPlan. Owner: Track A.

Implementation pending (WORKPLAN.md Track A, H8-H16). Follow the intent -> tool
mapping table in docs/CONTRACTS.md Contract 4 exactly: which tools run for each
of the 7 intents, and which are deliberately skipped (with a `reason` on every
ToolCall and an entry in `tools_considered_but_skipped` for each omission).
This mapping is the specification of the project's core "agentic" claim and is
covered by the plan-divergence test in WORKPLAN.md Section 8.
"""

from backend.schemas import ExecutionPlan, QueryIntent


def build_plan(intent: QueryIntent) -> ExecutionPlan:
    raise NotImplementedError("Track A: implement intent -> ExecutionPlan mapping, see docs/CONTRACTS.md Contract 4")
