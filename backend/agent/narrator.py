"""
Narrator: turns risk_rows (artifact from risk_classify) into Flags with
human-readable explanations and escalation actions. Owner: Track A.

Template layer always runs and is always accurate (built from each hit's
evidence). LLM polish is optional and only rewrites — it is never given
license to invent a number.
"""

from typing import Any

from backend.llm.client import complete_json
from backend.schemas import Escalation, Evidence, Flag, RiskLevel

RULE_NAMES = {
    "R1": "Structuring",
    "R2": "Smurfing",
    "R3": "Layering",
    "R4": "Rapid cash-out",
    "R5": "Velocity spike",
    "R6": "Dormant reactivation",
}

ESCALATION_BY_LEVEL: dict[RiskLevel, Escalation] = {
    "high": "report",
    "medium": "review",
    "low": "monitor",
    "none": "no_action",
}


def build_flags(risk_rows: list[dict[str, Any]]) -> list[Flag]:
    flags: list[Flag] = []
    for row in risk_rows:
        evidence = [e if isinstance(e, Evidence) else Evidence(**e) for e in row.get("evidence", [])]
        explanation = _explain(row, evidence)
        risk_level: RiskLevel = row["risk_level"]
        escalation: Escalation = row.get("escalation") or ESCALATION_BY_LEVEL[risk_level]
        flags.append(
            Flag(
                entity_type=row.get("entity_type", "customer"),
                entity_id=row["entity_id"],
                risk_score=row["risk_score"],
                risk_level=risk_level,
                escalation=escalation,
                patterns=row.get("patterns", []),
                triggered_rules=row.get("triggered_rules", []),
                ml_score=row.get("ml_score"),
                evidence=evidence,
                explanation=explanation,
                sar_draft=_sar_draft(row, explanation) if risk_level == "high" else None,
            )
        )
    return flags


def _explain(row: dict[str, Any], evidence: list[Evidence]) -> str:
    parts: list[str] = []
    for rule_id in row.get("triggered_rules", []):
        ev = next((e for e in evidence if e.rule_id == rule_id), None)
        if ev and ev.note:
            parts.append(ev.note)
        else:
            parts.append(f"{RULE_NAMES.get(rule_id, rule_id)} rule triggered.")

    if not parts and row.get("ml_score") is not None:
        parts.append(
            f"Flagged by anomaly detection (percentile {row['ml_score']:.0%}) — no single rule matched, "
            "but the transaction pattern deviates significantly from this entity's baseline."
        )
    if not parts:
        parts.append("Flagged for review based on the query's risk criteria.")

    text = " ".join(parts)
    polished = complete_json(
        f"Rewrite this AML compliance evidence into one clear analyst-facing paragraph. "
        f"Use only the facts given, never invent numbers: {text}",
        schema_hint='Return JSON: {"paragraph": "..."}',
    )
    if polished and isinstance(polished.get("paragraph"), str) and polished["paragraph"].strip():
        return polished["paragraph"].strip()
    return text


def _sar_draft(row: dict[str, Any], explanation: str) -> str:
    patterns = ", ".join(row.get("patterns", [])) or "unspecified pattern"
    rules = ", ".join(row.get("triggered_rules", [])) or "anomaly detection"
    return (
        f"Suspicious Activity Report (draft) — Entity {row['entity_id']}. "
        f"Risk score {row['risk_score']:.0f}/100 (HIGH). Pattern(s): {patterns}. "
        f"Detection basis: {rules}. {explanation} Recommended action: file SAR / escalate to compliance for review."
    )
