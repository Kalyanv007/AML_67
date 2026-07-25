"""
Executor: runs an ExecutionPlan's steps against the tool registry. Owner: Track A.

Implementation pending (WORKPLAN.md Track A, H8-H16):
  - Thread one ToolContext through all steps; merge each ToolResult's df/artifacts.
  - Time each step (ToolCall.duration_ms); isolate errors (a failing tool marks its
    step "error" and appends a warning, the run continues — never let one tool's
    exception 500 the API).
  - Conditional re-planning, logged to ExecutionPlan.decisions:
      * rule_detect returns 0 hits -> append ml_detect
      * filtered subset < 50 rows -> drop ml_detect, note why
      * filter_data returns 0 rows -> stop, explain which filter emptied the set
"""

from backend.schemas import AgentResponse, ExecutionPlan, QueryIntent


def run_plan(intent: QueryIntent, plan: ExecutionPlan) -> AgentResponse:
    raise NotImplementedError("Track A: implement plan execution against the tool registry, see WORKPLAN.md H8-H16")
