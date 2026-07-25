"""
Intent parsing: natural-language query -> QueryIntent. Owner: Track A.

LLM path first (backend.llm.client.complete_json); on any failure or invalid
response, falls back to a deterministic regex/keyword parser that alone must
cover all 7 intents well enough to demo on (see docs/CONTRACTS.md Contract 4).
"""

import re
from datetime import date, timedelta

from backend.llm.client import complete_json
from backend.schemas import Filters, PatternType, QueryIntent

PATTERN_KEYWORDS: dict[str, PatternType] = {
    "structuring": "structuring",
    "smurfing": "smurfing",
    "smurf": "smurfing",
    "layering": "layering",
    "rapid cash": "rapid_cashout",
    "cash-out": "rapid_cashout",
    "cash out": "rapid_cashout",
    "velocity": "velocity",
    "dormant": "dormant_reactivation",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

ENTITY_RE = re.compile(r"\b(?:customer|cust|account|acct)?\s*(?:id\s*)?(C-?\d{3,6}|T-?\d{3,6})\b", re.I)
BARE_ID_RE = re.compile(r"\b(\d{4,6})\b")
COUNT_RE = re.compile(r"(\d+)\s*\+?\s*(?:or more\s*)?transactions?", re.I)
AMOUNT_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
TOPN_RE = re.compile(r"top\s+(\d+)", re.I)
LAST_N_RE = re.compile(r"last\s+(\d+)\s+(day|week|month)s?", re.I)
SINCE_RE = re.compile(r"since\s+(\d{4}-\d{2}-\d{2})", re.I)
IN_MONTH_RE = re.compile(r"\bin\s+(" + "|".join(MONTHS) + r")\b", re.I)

_SCHEMA_HINT = (
    "Return JSON with keys: intent (one of full_analysis, pattern_search, threshold_query, "
    "entity_investigation, ranking, eda, explain_flag), filters (object with optional date_from, "
    "date_to, countries, txn_types, amount_min, amount_max, min_txn_count, customer_segment), "
    "entities (list of customer/transaction IDs mentioned, normalised like C-04521 or T-008891), "
    "pattern_types (list from structuring, smurfing, layering, rapid_cashout, velocity, "
    "dormant_reactivation), top_n (int, default 10), confidence (0-1 float)."
)


def parse_intent(raw_query: str, reference_date: date | None = None) -> QueryIntent:
    reference_date = reference_date or date.today()

    llm_result = complete_json(f'Classify this AML compliance query: "{raw_query}"', _SCHEMA_HINT)
    if llm_result is not None:
        try:
            return QueryIntent(raw_query=raw_query, parsed_by="llm", **llm_result)
        except Exception:
            pass  # malformed LLM output -> fall through to the regex parser

    return _parse_with_rules(raw_query, reference_date)


def _parse_with_rules(raw_query: str, reference_date: date) -> QueryIntent:
    q = raw_query.lower()
    filters = Filters()
    confidence = 0.6

    m = LAST_N_RE.search(q)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n if unit == "day" else n * 7 if unit == "week" else n * 30
        filters.date_from = reference_date - timedelta(days=days)
        filters.date_to = reference_date

    m = SINCE_RE.search(q)
    if m:
        filters.date_from = date.fromisoformat(m.group(1))

    m = IN_MONTH_RE.search(q)
    if m:
        month = MONTHS[m.group(1).lower()]
        year = reference_date.year
        filters.date_from = date(year, month, 1)
        next_month = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
        filters.date_to = next_month - timedelta(days=1)

    if "$" in q and any(w in q for w in ["under $", "below $", "less than $"]):
        dollar_idx = q.find("$")
        am = AMOUNT_RE.search(q[dollar_idx:])
        if am:
            filters.amount_max = float(am.group(1).replace(",", ""))

    m = COUNT_RE.search(q)
    if m:
        filters.min_txn_count = int(m.group(1))

    top_n = 10
    m = TOPN_RE.search(q)
    if m:
        top_n = int(m.group(1))

    entities: list[str] = [_normalise_entity(m.group(1)) for m in ENTITY_RE.finditer(raw_query)]
    if not entities:
        entities = [_normalise_entity(m.group(1)) for m in BARE_ID_RE.finditer(raw_query)]

    pattern_types: list[PatternType] = []
    for kw, pt in PATTERN_KEYWORDS.items():
        if kw in q and pt not in pattern_types:
            pattern_types.append(pt)

    intent = _classify(q, filters, entities, pattern_types)
    if intent == "full_analysis" and not any(
        w in q for w in ["analyse", "analyze", "suspicious activity", "full analysis", "overview"]
    ):
        confidence = 0.3  # true fallback, not a confident full_analysis read

    return QueryIntent(
        raw_query=raw_query,
        intent=intent,
        filters=filters,
        entities=entities,
        pattern_types=pattern_types,
        top_n=top_n,
        confidence=confidence,
        parsed_by="rules",
    )


def _classify(q: str, filters: Filters, entities: list[str], pattern_types: list[PatternType]) -> str:
    if q.startswith("why") or "why was" in q or "why is" in q:
        return "explain_flag"
    if entities and any(w in q for w in ["suspicious", "risk", "investigate", "flagged", "flag"]):
        return "entity_investigation"
    if TOPN_RE.search(q) or any(w in q for w in ["highest risk", "riskiest", "top risk"]):
        return "ranking"
    if filters.min_txn_count is not None:
        return "threshold_query"
    if pattern_types:
        return "pattern_search"
    if any(w in q for w in ["distribution", "breakdown", "show me", "chart", "how many", "by country", "by type"]):
        return "eda"
    return "full_analysis"


def _normalise_entity(raw_id: str) -> str:
    raw_id = raw_id.upper()
    prefix = "T" if raw_id.startswith("T") else "C"
    digits = re.sub(r"\D", "", raw_id)
    width = 6 if prefix == "T" else 5
    return f"{prefix}-{digits.zfill(width)}"
