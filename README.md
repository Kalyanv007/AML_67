# AI-Powered Suspicious Activity Detection — AML Agent

An agentic system for AML compliance: a natural-language query goes in, the agent parses intent,
**builds a query-specific execution plan** (not a fixed pipeline), calls only the tools that plan needs,
and returns risk-scored, explained, escalation-tagged flags — with the plan itself shown to the user, so
a reviewer can see exactly what the agent decided to do and why.

Built for a 48-hour hackathon, Problem Statement 1 (AI-Powered Suspicious Activity Detection).

---

## Table of contents

1. [Problem statement](#problem-statement)
2. [Domain background](#domain-background)
3. [Solution approach](#solution-approach)
4. [Why this is agentic](#why-this-is-agentic)
5. [Architecture](#architecture)
6. [Tech stack](#tech-stack)
7. [Datasets](#datasets)
8. [Setup](#setup)
9. [Usage — example queries](#usage--example-queries)
10. [Results](#results)
11. [Limitations](#limitations)
12. [Team](#team)

---

## Problem statement

Traditional rule-based AML systems generate excessive false positives, overwhelming compliance teams.
Sophisticated laundering techniques — structuring, smurfing, layering — evade naive threshold rules. The
challenge: build an autonomous agent that parses a compliance query, dynamically decides which analysis
tools it needs, detects suspicious patterns (rule-based, ML, or hybrid), scores risk, explains every flag
in plain language, and recommends an escalation action — reducing false positives while staying
explainable enough for a human analyst to trust and act on.

## Domain background

- **The $10,000 threshold.** US banks must file a **Currency Transaction Report (CTR)** for any cash
  transaction ≥ $10,000 (Bank Secrecy Act). **Structuring** (31 U.S.C. § 5324) is the crime of splitting
  transactions to stay under that threshold — independent of whether the underlying funds are illicit.
  This is *why* our structuring rule watches the $9,000–$9,999.99 band specifically, not "large
  transactions" generally.
- **Smurfing** ("fan-out"): distributing funds through many accounts/couriers to obscure the money trail.
- **Layering**: moving funds through a chain of accounts/jurisdictions to sever the audit trail —
  laundering's obfuscation stage.
- **Rapid cash-out**: converting an inbound electronic transfer to physical cash quickly — laundering's
  integration stage.
- **FATF 40 Recommendations** (1, 3, 10) require enhanced due diligence on exactly these patterns.
- **SARs** (Suspicious Activity Reports, FinCEN Form 114) are filed regardless of amount when laundering
  is suspected — our agent drafts one automatically for every `HIGH`-risk flag.

Full regulatory citations, per-rule thresholds, and business justification: **[AML_LOGIC.md](AML_LOGIC.md)**.

## Solution approach

**Hybrid detection = rule-based (explainable, precise) + ML anomaly detection (recall, catches novel
patterns) + a fused risk score.**

- **Rules R1–R6** (structuring, smurfing, layering, rapid cash-out, velocity spike, dormant reactivation)
  — each with a documented regulatory rationale and threshold, emitting rule-specific evidence.
- **ML**: IsolationForest + LocalOutlierFactor over per-customer AML features (rolling sums,
  threshold-proximity ratio, self-deviation z-scores, velocity, pass-through ratios, ...).
- **Fusion** (`docs/CONTRACTS.md` Contract 5): `risk_score = 100 × (0.6 × rule_weight + 0.4 × ml_percentile)`,
  banded into `HIGH → report` / `MEDIUM → review` / `LOW → monitor` / `NONE → no_action`.
- **Explanation**: a deterministic template built from each rule's actual evidence (always accurate,
  always available, LLM-optional). An LLM polish pass rewrites `HIGH`-risk explanations into an
  analyst-facing paragraph — capped to `HIGH` only, both to protect a free-tier rate limit and because
  those are the flags that matter most (they're the ones getting a SAR draft).

## Why this is agentic

The system is graded on **not** being a fixed pipeline. The planner (`backend/agent/planner.py`) builds a
genuinely different tool sequence per query intent — verified by an automated test
(`tests/test_planner.py`, `tests/test_integration.py`) that asserts the plans for these three queries
*differ*:

| Query | Tools invoked | Tools explicitly skipped (and why) |
|---|---|---|
| *"Is customer 4521 suspicious?"* | `load_data → filter_data → entity_lookup → feature_engineer → rule_detect → risk_classify` | `eda_profile` (not exploring), `ml_detect` (one entity is too small a sample) |
| *"Which customers made 10+ transactions under $10,000?"* | `load_data → filter_data → aggregate_query` | `feature_engineer`, `ml_detect`, `eda_profile` (a deterministic count answers this exactly) |
| *"Analyse this dataset for suspicious activity"* | `load_data → eda_profile → feature_engineer → rule_detect → ml_detect → risk_classify` | — (full sweep) |

The executor also **re-plans mid-run**, not just at planning time:
- `rule_detect` returns 0 hits → appends `ml_detect` to widen the net
- filtered subset < 50 rows → drops a queued `ml_detect` (insufficient sample)
- `filter_data` returns 0 rows → stops early with an explanatory summary, not an empty crash

Every decision — what ran, what was skipped, what got added mid-run, and why — is logged to
`plan.decisions[]` / `plan.tools_considered_but_skipped[]` and shown directly in the UI's execution-plan
trace panel. That panel, not the ML, is the thing this project is actually graded on.

Full intent → tool mapping table: **[docs/CONTRACTS.md](docs/CONTRACTS.md) Contract 4**.

## Architecture

```
User query (NL)
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│ AGENT CORE  (backend/agent/)                             │
│  1. IntentParser  → QueryIntent {intent, filters,        │
│                     entities, pattern_types}              │
│     · LLM (JSON mode) primary, regex fallback always-on   │
│  2. Planner       → ExecutionPlan [ToolCall, ...]         │
│  3. Executor      → runs plan, threads ToolContext,       │
│                     conditional re-planning, decisions[]  │
│  4. Narrator      → explanation + escalation per flag      │
└─────────────────────────────────────────────────────────┘
      │  resolves tools through the auto-discovering REGISTRY
      ▼
TOOL LAYER (backend/tools/)
  load_data · filter_data · eda_profile · feature_engineer
  rule_detect · ml_detect · aggregate_query · entity_lookup
  risk_classify
      │
      ▼
AgentResponse (JSON) → FastAPI → HTTP → Streamlit UI
```

Component detail, the full Pydantic contract, and sequence diagrams: **[ARCHITECTURE.md](ARCHITECTURE.md)**.
The frozen interface both halves of this project are built against: **[docs/CONTRACTS.md](docs/CONTRACTS.md)**.
The two-person parallel build plan (for context on how this repo came together):
**[WORKPLAN.md](WORKPLAN.md)**.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI + uvicorn, Pydantic v2 |
| Agent core | Python — intent parser, planner, executor, narrator (no agent framework; the plan/execute/re-plan loop is hand-rolled and fully inspectable) |
| LLM | Gemini or OpenAI (configurable), behind one adapter, always with a regex fallback |
| Data / detection | pandas, numpy, scikit-learn (IsolationForest, LOF), networkx (layering chains) |
| Frontend | Streamlit + Plotly |
| Tests | pytest — 185 tests |

## Datasets

| Dataset | Role | Source | License / citation |
|---|---|---|---|
| **IBM Transactions for AML** (HI-Small) | Primary real-world base | [Kaggle: ealtman2019/ibm-transactions-for-anti-money-laundering-aml](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml) | Altman, Baeck, Gerlach — "Realistic Synthetic Financial Transactions for Anti-Money Laundering Models," NeurIPS 2023 Datasets and Benchmarks |
| **Synthetic overlay** (`data/sample/aml_sample.csv`) | Committed demo dataset — guarantees structuring/smurfing/layering/rapid-cashout patterns are present and labelled, no Kaggle download required to run the demo | `data/generate_synthetic.py`, fixed seed (42) | Ours — full schema, field definitions, and generation logic documented in [DATA_CARD.md](DATA_CARD.md) |

Both are adapted into one canonical schema (`docs/CONTRACTS.md` Contract 0) before any detection code
touches them — the datasets are fully swappable. Full field-by-field preprocessing decisions, raw dataset
statistics, and every assumption made by the synthetic generator: **[DATA_CARD.md](DATA_CARD.md)**.

## Setup

```bash
git clone <this repo>
cd soc

python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt

cp .env.example .env            # optional — see below

python run_demo.py              # starts backend (FastAPI) + frontend (Streamlit), opens the browser
```

The committed sample dataset (`data/sample/aml_sample.csv`) means the demo runs **with no Kaggle download
and no LLM API key** — `AML_USE_MOCKS=0` (the default in `.env.example`) points at the real detection
pipeline over that sample data; without an LLM key, intent parsing and explanations use the
always-available regex/template fallback, not a degraded mode.

**To use a real LLM** (optional, improves messy/informal query phrasing and polishes HIGH-risk
explanations): set `LLM_PROVIDER` and the matching key in `.env`. Free-tier rate limits are respected by
design — LLM calls happen at most once per query for intent parsing, and explanation polishing is capped
to `HIGH`-risk flags only (a `full_analysis` query can produce dozens of flags; polishing all of them
would exhaust a free-tier quota on a single request for no benefit, since the template text is already
accurate).

**To download the real IBM Kaggle dataset instead of the synthetic one**, `kaggle`/`kagglehub` credentials
are required — see [DATA_CARD.md](DATA_CARD.md) §1.1.

**Manual start** (equivalent to `run_demo.py`, useful for separate terminals / debugging):
```bash
uvicorn backend.main:app --port 8000       # terminal 1
streamlit run frontend/app.py               # terminal 2 (reads AML_API_URL, defaults to localhost:8000)
```

**Run the test suite:**
```bash
pytest tests/ -v
```

## Usage — example queries

Type a query, or click one of the UI's example buttons. Each of these exercises a different point in the
intent → plan mapping table above:

| Query | Intent | What you'll see |
|---|---|---|
| `Analyse this dataset for suspicious activity` | `full_analysis` | Full EDA + rule + ML sweep; dozens of flags across risk bands |
| `Find structuring patterns in the last 30 days` | `pattern_search` | Only structuring-scoped features/rules run; date filter applied (anchored to the dataset's own date range, not wall-clock "today") |
| `Which customers made 10+ transactions under $10,000?` | `threshold_query` | Direct aggregation, **no ML step at all** — visibly absent from the plan trace |
| `Is customer 4521 suspicious?` | `entity_investigation` | Single-entity scoring; a bare number is resolved against the real dataset's customer IDs (which aren't purely numeric — see [Limitations](#limitations)) |
| `Top 5 highest-risk customers` | `ranking` | Full sweep, truncated to the top 5 by risk score |
| `Show transaction distribution by country` | `eda` | Profiling only — no detection tools run |
| `Why was customer C-STR02 flagged?` | `explain_flag` | Scores just that one entity and returns its explanation directly |

Every response includes: the detected intent + extracted filters/entities, the full execution plan (steps
taken, steps skipped and why, any mid-run re-planning), the flagged entities with risk score/level/escalation/
explanation, and (for `HIGH` risk) a SAR draft.

## Results

Rule thresholds and their regulatory justification are documented per-rule in
[AML_LOGIC.md](AML_LOGIC.md) — e.g. R1 (structuring) requires **3 transactions in a 7-day window** in the
$9,000–$9,999.99 band, which is what separates it from a naive "flag any transaction over $9,000" rule
(the latter would flag every legitimate large transaction; ours requires a *pattern*, corroborated further
by the ML anomaly score before reaching `HIGH`/SAR territory — see Contract 5's fusion formula).

### Quantitative validation

Computed against the committed synthetic dataset's ground truth (`data/sample/aml_sample.csv`'s
`label_is_laundering` field — 202 of 2,002 transactions, injected by the generator across the
structuring/smurfing/rapid-cashout/layering cohorts; see [DATA_CARD.md](DATA_CARD.md)). Not validated
against the raw IBM Kaggle dataset — that requires a Kaggle download not run in this environment; the
synthetic set is the labelled ground truth actually available here.

**Methodology**: our system flags *customers*, not individual transactions, so ground truth is aggregated
to the customer level: a customer is a true positive if they are the **sender** of at least one labelled
transaction (51 of 270 customers) — chosen because our rules evaluate sender-side behavior (structuring,
fan-out, self-deviation), not because it's the number that looks best. The naive baseline
([AML_LOGIC.md](AML_LOGIC.md) §6: "flag any transaction with `amount > $9,000`") is translated the same
way, to a fair customer-level comparison: any customer who sent at least one such transaction.

| | Flagged | Precision | Recall | False-positive rate |
|---|---|---|---|---|
| **Naive baseline** (any txn > $9,000) | 259 / 270 | 0.197 | 1.000 | 0.950 |
| **Our system — any flag** (LOW/MEDIUM/HIGH) | 30 / 270 | 0.767 | 0.451 | 0.032 |
| **Our system — HIGH only** (the SAR-draft tier) | 23 / 270 | 0.913 | 0.412 | 0.009 |

The naive rule "catches everything" (recall 1.00) by flagging 96% of all customers — exactly the
compliance-team-drowning-in-false-positives problem the brief describes. Our system flags **8.8× fewer
customers** (30 vs. 259) while still catching 45% of true positives, at a **~30× lower false-positive
rate** (3.2% vs. 95.0%) — and at the `HIGH`/SAR tier specifically, a false-positive rate of under 1%.

**Honest limitation, not hidden**: using a broader ground truth (sender *or* receiver of a labelled
transaction, 114 customers) drops our recall to ~22%. The gap is 63 customers who only ever *receive*
funds in a labelled pattern (e.g. individual recipients in a fan-out/smurfing distribution) and never
exhibit outbound behavior themselves — our rules are sender/outbound-focused and correctly don't flag
them on senders-only signals, since they have none. This is a real, documented gap (no receiver-side/fan-in
detection yet), not a scoring artifact — see [Limitations](#limitations).

R5 (velocity) and R6 (dormant reactivation) never fire on this dataset (0 hits each) — the synthetic
generator doesn't inject cohorts for those two patterns, so they're implemented and rule-tested
(`tests/test_rules.py`) but unvalidated against real labelled data here.

## Limitations

- **LLM path is provider-agnostic and always has a working fallback**; live-verified against a real Gemini
  key (`gemini-flash-latest`) — correctly classifies messy/slang phrasing the regex fallback alone gets
  wrong (e.g. "who r my 3 sketchiest customers rn" → `ranking`, `top_n=3`). One nuance: the LLM returns
  relative-date shorthand rather than ISO dates for phrases like "last 30 days," which fails schema
  validation and safely falls back to the regex parser — so date-filter accuracy currently comes from the
  regex path regardless of which parser handled the rest of the query.
- **Entity-ID matching is numeric-only.** The real dataset's customer IDs follow the generator's own
  scheme (`C-N0001`, `C-STR02`, `C-HUB01`) rather than plain numbers. A query like "customer 2" resolves
  by matching digits against real IDs (picking the first match on ambiguity, which does occur — multiple
  IDs can share a numeric suffix across different prefixes, so it may occasionally resolve to the wrong
  one of several candidates); a query using a real ID directly (e.g. "C-STR02") always works precisely.
  There's no name-based lookup.
- **`explain_flag` re-scores the entity fresh** rather than reusing a cached prior run — simpler and
  always correct, but means it can't explain a flag from a run using different filters than "all data."
- **Detection is sender/outbound-focused; no receiver-side or fan-in detection.** Validated against the
  synthetic ground truth (see Results): recall is ~45% for customers who exhibit suspicious *outbound*
  behavior, but customers who only ever *receive* funds as part of a labelled pattern (e.g. individual
  recipients in a fan-out distribution) aren't caught, since no rule or feature currently evaluates
  inbound/fan-in patterns. Extending R2 (or adding a new rule) to also flag high fan-in receivers would be
  the natural next step.
- Batch analysis over a sample dataset, not live streaming — explicitly in scope per the brief.
- Synthetic data documents its own generation assumptions (seed, thresholds, ring sizes) in
  [DATA_CARD.md](DATA_CARD.md) — real-world deployment would need those revalidated against production
  transaction volumes and patterns.

## Team

- **Track A** (agent core, orchestration, API) — Kapilan Kathirvel
- **Track B** (data, detection, ML, UI) — Vasudevan Kalyan
  

Full division of labour, ownership matrix, and the anti-merge-conflict protocol used to build this in
parallel: **[WORKPLAN.md](WORKPLAN.md)**.
