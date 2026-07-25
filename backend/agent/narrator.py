"""
Narrator: turns risk_rows (artifact from risk_classify) into Flags with
human-readable explanations and escalation actions. Owner: Track A.

Implementation pending (WORKPLAN.md Track A, H16-H24):
  - Deterministic template per rule R1-R6, built from each hit's evidence dict
    (always accurate, always available).
  - Optional LLM rewrite into an analyst paragraph — never let the LLM invent
    numbers, pass it only computed facts.
  - Map risk band -> escalation (docs/CONTRACTS.md Contract 5) and draft a short
    SAR-style summary for HIGH risk flags.
"""

from backend.schemas import Flag


def build_flags(risk_rows: list[dict]) -> list[Flag]:
    raise NotImplementedError("Track A: implement explanation templates + escalation mapping, see WORKPLAN.md H16-H24")
