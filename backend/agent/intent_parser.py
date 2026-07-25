"""
Intent parsing: natural-language query -> QueryIntent. Owner: Track A.

Implementation pending (WORKPLAN.md Track A, H2-H8):
  - LLM path: prompt backend.llm.client.complete_json for the 7 Intent values,
    Filters, entities, pattern_types (see backend/schemas.py, docs/CONTRACTS.md).
  - Regex/keyword fallback covering all 7 intents when the LLM returns None,
    including relative dates ("last 30 days"), entity IDs, amount thresholds,
    counts ("10+ transactions"), countries, transaction types, top_n.
"""

from backend.schemas import QueryIntent


def parse_intent(raw_query: str) -> QueryIntent:
    raise NotImplementedError("Track A: implement LLM + regex-fallback intent parsing, see WORKPLAN.md H2-H8")
