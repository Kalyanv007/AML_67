from datetime import date

import pytest

from backend.agent.intent_parser import parse_intent


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr("backend.agent.intent_parser.complete_json", lambda *a, **kw: None)


CASES = [
    ("Analyse this dataset for suspicious activity", "full_analysis"),
    ("Give me a full analysis of the transactions", "full_analysis"),
    ("Find structuring patterns in the last 30 days", "pattern_search"),
    ("Look for smurfing activity", "pattern_search"),
    ("Check for layering in wire transfers", "pattern_search"),
    ("Which customers made 10+ transactions under $10,000?", "threshold_query"),
    ("Find customers with at least 5 transactions under $9,000", "threshold_query"),
    ("Is customer ID 4521 suspicious?", "entity_investigation"),
    ("Investigate customer C-01187", "entity_investigation"),
    ("Top 10 highest-risk customers", "ranking"),
    ("Show me the top 5 riskiest accounts", "ranking"),
    ("Show transaction distribution by country", "eda"),
    ("Give me a breakdown of transactions by type", "eda"),
    ("Why was transaction T-8891 flagged?", "explain_flag"),
    ("Why is customer 4521 flagged?", "explain_flag"),
]


@pytest.mark.parametrize("query,expected_intent", CASES)
def test_intent_classification(query, expected_intent):
    result = parse_intent(query)
    assert result.intent == expected_intent, f"'{query}' -> {result.intent}, expected {expected_intent}"
    assert result.parsed_by == "rules"


def test_entity_extraction_bare_id():
    result = parse_intent("Is customer ID 4521 suspicious?")
    assert "C-04521" in result.entities


def test_entity_extraction_prefixed_id():
    result = parse_intent("Investigate customer C-01187")
    assert "C-01187" in result.entities


def test_entity_extraction_alphanumeric_real_id():
    """Real customer IDs aren't purely numeric (Track B's generator scheme:
    C-STR02, C-N0001, C-HUB01, ...) — the entity regex must recognise these,
    not just C-#####. Regression test for a bug found in Phase 7 hardening
    where 'Is customer C-STR02 suspicious?' misclassified as full_analysis
    because the ID failed to extract as an entity at all."""
    result = parse_intent("Is customer C-STR02 suspicious?")
    assert result.entities == ["C-STR02"]
    assert result.intent == "entity_investigation"


def test_date_filter_extraction():
    result = parse_intent("Find structuring patterns in the last 30 days")
    assert result.filters.date_from is not None
    assert result.filters.date_to is not None


def test_relative_date_anchored_to_dataset_not_wallclock():
    """'last 30 days' must resolve relative to the dataset's own max date
    (2025-03-31 in the committed sample), not date.today() — regression test
    for a bug found in Phase 7 hardening where this made the brief's own
    example query ('Find structuring patterns in the last 30 days') return
    zero results, since the real wall-clock date is nowhere near the
    dataset's 2025 date range."""
    result = parse_intent("Find structuring patterns in the last 30 days")
    assert result.filters.date_to < date(2026, 1, 1)
    assert result.filters.date_to != date.today()


def test_amount_and_count_filters():
    result = parse_intent("Which customers made 10+ transactions under $10,000?")
    assert result.filters.min_txn_count == 10
    assert result.filters.amount_max == 10000.0


def test_pattern_type_extraction():
    result = parse_intent("Find structuring patterns in the last 30 days")
    assert "structuring" in result.pattern_types


def test_top_n_extraction():
    result = parse_intent("Top 5 highest-risk customers")
    assert result.top_n == 5
