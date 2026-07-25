# TRACK A — Phase-by-Phase Implementation Roadmap

Agent core, LLM, API. Companion to [WORKPLAN.md](WORKPLAN.md) (task assignment + ownership) and
[docs/CONTRACTS.md](docs/CONTRACTS.md) (the frozen interface). This file is the **detailed execution
plan** — WORKPLAN.md tells you what hour to be on which file; this tells you exactly what to build in it.

**For day-to-day resume/status, use [TRACK_A_PROGRESS.md](TRACK_A_PROGRESS.md) instead of this file** —
that one tracks what's actually done. This file doesn't change once work starts, except to fix mistakes.

Files you own, full list, in [WORKPLAN.md](WORKPLAN.md) §4.

---

## Phase 0 — Kickoff Scaffold ✅ DONE

Goal: contracts frozen, repo boots, Track B unblocked.

- [x] `backend/schemas.py` — full Pydantic contract (Contract 1)
- [x] `backend/tools/base.py` — `ToolContext`, `ToolResult`, `@tool` decorator (Contract 2)
- [x] `backend/agent/registry.py` — auto-discovery (Contract 3)
- [x] `backend/tools/_mocks.py` — mocks for all 9 tool names
- [x] `backend/config.py` — pydantic-settings
- [x] `backend/main.py` — FastAPI skeleton, `/health` live, `/query` returns 501 (not yet wired)
- [x] Stub files created (signature + docstring + `NotImplementedError`): `backend/llm/client.py`,
      `backend/agent/intent_parser.py`, `planner.py`, `executor.py`, `narrator.py`
- [x] `requirements.txt` (common, both tracks), `.gitignore`, `.env.example`, `CLAUDE.md`
- [x] Pushed to `main`

**Acceptance:** `pytest` collects with no import errors. `uvicorn backend.main:app` boots, `GET /health`
returns 200. *(Not yet re-verified after the stub-file changes — first item in Phase 1.)*

---

## Phase 1 — LLM Client + Intent Parser ✅ DONE

Implemented `backend/llm/client.py` (Gemini/OpenAI, returns `None` on any failure) and
`backend/agent/intent_parser.py` (LLM-first, full regex/keyword fallback covering all 7 intents, date/
amount/count/entity/pattern extraction). `tests/test_intent.py` — 21 tests, all passing, LLM stubbed out.

---

Goal: `raw_query: str` → a correctly-populated `QueryIntent`, LLM-first with a regex fallback that alone
is good enough to demo on.

**Files:** `backend/llm/client.py`, `backend/agent/intent_parser.py`, `tests/test_intent.py`

### 1.1 — `backend/llm/client.py`
- Implement `complete_json(prompt, schema_hint="") -> dict | None`.
- Branch on `settings.llm_provider` (`"gemini"` or `"openai"`); call the respective SDK in JSON mode.
- Wrap the whole call in try/except — **any** failure (no key, timeout, rate limit, malformed JSON)
  returns `None`. Set a short timeout (~10s) so a hung call can't stall the demo.
- No retries beyond the SDK's default — this is a fallback-covered path, not a critical one.

### 1.2 — `backend/agent/intent_parser.py`
- Build the LLM prompt: the 7 `Intent` values, the `Filters` shape, instruction to extract entities and
  `pattern_types`, told to return strict JSON matching `QueryIntent` minus `parsed_by`/`confidence`.
- On a `None` from the LLM (or a JSON payload that fails `QueryIntent` validation), fall through to the
  **regex/keyword parser** — this path must independently handle all 7 intents:
  - `full_analysis`: keywords "analyse", "analyze", "suspicious activity", no specific entity/pattern
  - `pattern_search`: pattern keyword present (structuring/smurfing/layering/cash-out/velocity) + no
    specific entity ID
  - `threshold_query`: "X+ transactions", "under $Y", "at least", "more than" phrasing without pattern words
  - `entity_investigation`: a bare or prefixed ID present (`4521`, `C-4521`, `customer 4521`) + question form
  - `ranking`: "top N", "highest risk", "riskiest"
  - `eda`: "distribution", "show me", "breakdown", "how many... by..."
  - `explain_flag`: "why was", references a transaction ID (`T-8891`)
  - default → `full_analysis` with `confidence` low, and expect the planner to log the fallback
- Date parsing: "last N days/weeks/months", "since <date>", "in <month>" → `Filters.date_from/date_to`
  relative to a fixed "today" for the dataset (use the max timestamp in the loaded data, not `date.today()`
  — the sample CSV's dates won't be "recent" relative to wall-clock time).
- Entity ID normalisation: bare digits → `C-0####` (zero-padded to 5) per the schema in
  `docs/CONTRACTS.md` Contract 0; transaction refs → `T-######`.
- Set `parsed_by: "llm"` or `"rules"` accordingly — this is surfaced in the UI, don't skip it.

**Acceptance:** `tests/test_intent.py` — a table of ~20 phrasings (at least 3 per intent, including the 3
brief-mandated examples) each asserted against expected `intent` + key `filters`/`entities` fields, run
**with the LLM path stubbed to return `None`** so the test suite doesn't need real API keys or network.

---

## Phase 2 — Planner ✅ DONE

Implemented `backend/agent/planner.py` per Contract 4's mapping table exactly, including
`tools_considered_but_skipped` reasons. `tests/test_planner.py` — 8 tests including the exact
plan-divergence assertions, all passing.

---

Goal (reference, already met): `QueryIntent` → `ExecutionPlan` that exactly matches the mapping table in
[docs/CONTRACTS.md](docs/CONTRACTS.md) Contract 4.

**Files:** `backend/agent/planner.py`, `tests/test_planner.py`

### 2.1 — `build_plan(intent: QueryIntent) -> ExecutionPlan`
- One `if/elif` (or a small dict of intent → step-builder function) per `Intent` value. Resist the urge to
  make this "clever" or data-driven before the straightforward version works — 7 branches is fine.
- Every `ToolCall.reason` should read like a sentence a judge can screenshot, e.g. *"entity filter applied
  first — narrows 200,000 transactions to one customer's history before any detection runs"*.
- Populate `tools_considered_but_skipped` for every tool NOT in the plan, one reason each — this list, not
  just the steps, is what makes the "decided, not piped" claim visible.
- `plan_id`: a short uuid or hash of `(raw_query, timestamp)`, used later by `/plan/{plan_id}`.

### 2.2 — Tests, write these before or alongside the planner
- `tests/test_planner.py` must include the **exact plan-divergence assertions** from WORKPLAN.md §8:
  - `"Is customer 4521 suspicious?"` → plan tool names exclude `eda_profile` and `ml_detect`
  - `"Which customers made 10+ transactions under $10,000?"` → excludes `ml_detect`
  - `"Analyse this dataset for suspicious activity"` → includes both
- One test per intent asserting the tool sequence matches Contract 4's table exactly.

**Acceptance:** all of the above pass. This is the single most-scrutinised test in the project — don't
let it slip in scope-cutting.

---

## Phase 3 — Executor ✅ DONE

Implemented `backend/agent/executor.py`: core loop, per-step timing, error isolation, both conditional
re-planning branches (widen to `ml_detect` on 0 rule hits; drop `ml_detect` on <50 rows), early-stop on
an empty filtered set. `tests/test_executor.py` — 3 tests including a simulated tool failure, all passing.

Goal (reference, already met): run an `ExecutionPlan`'s steps against the registry, produce a populated
`AgentResponse`, never crash on a bad tool, and re-plan mid-run when the contract says to.

**Files:** `backend/agent/executor.py`, `tests/test_executor.py`

### 3.1 — Core loop
```
ctx = ToolContext(df=<loaded df>, customers=<loaded customers>, intent=intent, artifacts={})
for step in plan.steps:
    fn = registry[step.tool]
    t0 = now()
    try:
        result = fn(ctx, **step.params)
    except Exception as e:
        step.status = "error"; response.warnings.append(f"{step.tool} failed: {e}")
        continue
    step.duration_ms = elapsed(t0)
    if not result.ok:
        step.status = "error"; response.warnings.append(result.error or f"{step.tool} returned ok=False")
        continue
    step.status = "ok"
    if result.df is not None: ctx.df = result.df
    ctx.artifacts.update(result.artifacts)
    response.tables.update(result.tables); response.charts.update(result.charts)
    response.metrics.update(result.metrics); plan.decisions.extend(result.notes)
```
(Pseudocode — implement properly with real typing, this is the shape, not the literal code.)

### 3.2 — Conditional re-planning (append to `plan.steps`, log to `plan.decisions`)
- After `rule_detect`: if `len(ctx.artifacts.get("rule_hits", [])) == 0` and `ml_detect` isn't already
  queued, append it with `reason="no rule hits — widening to ML anomaly detection"`.
- After `filter_data`: if `len(ctx.df) < 50` and `ml_detect` is queued later in `plan.steps`, remove it
  and log `"sample too small for anomaly detection (<50 rows) — skipping ml_detect"`.
- After `filter_data`: if `len(ctx.df) == 0`, stop executing remaining steps, set
  `response.summary = "No transactions matched the given filters (...)"`, return early.

### 3.3 — Final assembly
- `ctx.artifacts.get("risk_rows", [])` → pass to `narrator.build_flags()` → `response.flags`.
- `response.summary` — one paragraph answering the literal question asked (not a generic template);
  varies by intent (e.g. `threshold_query` states the count directly, `entity_investigation` states the
  verdict for that one entity).
- Cache the finished `AgentResponse` in `main.py`'s `_RUN_CACHE[plan.plan_id]`.

**Acceptance:** `tests/test_executor.py` — a plan with a deliberately-raising mock tool still returns a
valid `AgentResponse` with a warning, not an exception. Both re-planning branches covered.

---

## Phase 4 — Narrator ✅ DONE

Implemented `backend/agent/narrator.py`: template layer keyed off each hit's `evidence` (uses the note
field the rule/mock already provides), optional LLM polish (facts-only prompt, falls back to template
text on any LLM failure), escalation mapping, SAR draft for HIGH. Covered indirectly via
`tests/test_executor.py` and `tests/test_api.py` (every flag has a non-empty explanation).

Goal (reference, already met): `risk_rows` (from `risk_classify`) → `list[Flag]` with real explanations
and escalations, LLM-off safe.

**Files:** `backend/agent/narrator.py`

### 4.1 — Template layer (always runs, always correct)
- One template string per rule ID R1–R6, filled from that hit's `evidence` dict, e.g.:
  `"R1 Structuring: 3 transactions totaling $28,400 in amounts just below the $10,000 CTR reporting "
  "threshold ($9,500, $9,800, $9,100) within a 7-day window."`
- If a customer has multiple triggered rules, join their templates into one paragraph.
- If only an ML hit (no rule), template off `top_features`: `"Flagged by anomaly detection — deviates most "
  "on: velocity (3.2x baseline), night-hours ratio, new-counterparty ratio."`

### 4.2 — Optional LLM polish
- Pass the assembled template text + evidence facts to `llm.client.complete_json` (or a plain completion
  call) asking for a one-paragraph analyst rewrite. **Give it the facts, never let it compute or invent
  a number.** On `None`, ship the template text unchanged — this must be invisible in a demo.

### 4.3 — Escalation + SAR draft
- Map `risk_level` → `escalation` per Contract 5 (`high`→`report`, `medium`→`review`, `low`→`monitor`,
  `none`→`no_action`).
- For `high` only, draft `sar_draft`: 2–3 sentences, entity ID, total flagged volume, patterns, rules
  triggered, in a tone suitable to hand to a compliance analyst (i.e. read AML_LOGIC.md's own SAR-language
  guidance from Track B once it exists, but don't block on it — a plain factual draft is fine).

**Acceptance:** every `Flag` has a non-empty `explanation`; run once with LLM keys unset and once with a
stubbed LLM success, both produce sane output.

---

## Phase 5 — Wire the API end-to-end (mocks) ✅ DONE

`backend/main.py` now runs the real pipeline: `parse_intent` → `build_plan` → `run_plan`, caches by
`plan_id` for `GET /plan/{plan_id}`, and `GET /dataset/summary` calls `load_data` through the registry.
`tests/test_api.py` — 7 tests, all passing. **Manually verified live**: booted
`uvicorn backend.main:app`, curled `/health`, `/query` (entity_investigation case — confirmed the plan
excludes `eda_profile`/`ml_detect` and the flag has a real explanation + SAR draft), and
`/dataset/summary`. All 40 tests across the suite pass (`pytest tests/ -v`).

Goal (reference, already met): `POST /query` fully live against `AML_USE_MOCKS=1`, satisfying the H0–H2
exit criterion that Phase 0 originally deferred.

**Files:** `backend/main.py`, `tests/test_api.py`

- `main.py`: replace the `501` in `/query` with `intent_parser.parse_intent` → `planner.build_plan` →
  `executor.run_plan` → return. Load the tool registry once at startup via
  `registry.load_tools(use_mocks=settings.aml_use_mocks)`, not per-request.
- `GET /dataset/summary`: once `data_loader` exists (Track B, may not be ready yet — mock a minimal version
  here using the mock `load_data` tool output, replace when B's loader lands).
- `tests/test_api.py`: `TestClient(app).post("/query", json={"query": "..."})` for the 3 plan-divergence
  queries + a couple more, asserting 200 and a valid `AgentResponse` shape.

**Acceptance:** the WORKPLAN.md H0–H2 exit criterion, now actually met:
`AML_USE_MOCKS=1 uvicorn backend.main:app` → `POST /query` returns a valid, non-mocked-501
`AgentResponse`.

---

## Phase 6 — Integrate Track B's real tools ✅ DONE

Found and fixed 5 real issues, all in files Track A owns — none required touching Track B's tool files:

1. **`narrator.py` crash**: `risk_classify`'s real `evidence` field is a list of *rule-specific* raw dicts
   (structuring's fields differ from layering's), not the fixed `Evidence` shape — documented in Track B's
   own `risk.py` comment. Added `_build_evidence()`: passes through already-conformant dicts (mocks),
   synthesizes a valid `Evidence` from raw dicts otherwise, pairing `evidence[i]` with `triggered_rules[i]`
   positionally (matches how `risk.py` builds them).
2. **`planner.py` param-name mismatches, all silent (no crash, just no-ops)**: `filter_data` was called
   with a single nested `filters={...}` dict; the real tool takes flattened kwargs
   (`date_from`, `amount_max`, etc. — mirrors `schemas.Filters` field-for-field). `feature_engineer` was
   called with `patterns=`; the real tool's param is `pattern_types=`. `aggregate_query` was called with
   invented `min_txn_count=`/`amount_max=` kwargs that don't exist on the real tool at all (its real
   signature is `group_by`/`agg_col`/`agg_func`/`threshold`/`top_n`) — `threshold_query` was silently
   non-functional against real data. Added `_filter_kwargs()` helper; rewrote the `threshold_query` and
   pattern-scoping calls to match the real signatures.
3. **`executor.py` missing scoping logic**: `filter_data` has no per-entity dimension, so
   `entity_investigation` queries were returning risk rows for *every* entity, not just the one asked
   about; `risk_classify` has no `top_n`, so `ranking` queries returned the whole population. Added
   post-`risk_classify` filtering (`entity_investigation`/`explain_flag` → filter to `intent.entities`;
   `ranking` → slice to `intent.top_n`, rows already arrive sorted descending).
4. **`executor.py` metric key**: `_summarise()` read `metrics["matching_customers"]`; the real
   `aggregate_query` emits `metrics["row_count"]`. Fixed, and renamed the mock's key to match for
   consistency.
5. **`registry.py` — a real bug, not a test artifact**: `TOOLS` is a global dict; a module's `@tool`
   decorator only runs on its *first* import. Calling `load_tools()` more than once with different
   `use_mocks` values in the same process (which happens across a pytest session, not in a normal
   single-mode server run) left stale entries — whichever module registered a name *last*, in whatever
   mode that happened to be, won, regardless of the mode requested on a later call. Fixed by clearing
   `TOOLS` and `importlib.reload()`-ing already-imported modules on every `load_tools()` call, so each
   call is deterministic in its requested mode regardless of call history. Found via a full-suite test
   failure that only reproduced in specific file combinations — root-caused by bisecting file
   combinations, not guessed at.

**Manually verified against the real 2,002-row sample dataset** (not just pytest) for all 5 of
WORKPLAN.md's plan-divergence-relevant queries — `full_analysis` (30 flags across HIGH/MEDIUM/LOW),
`pattern_search` structuring (16 flags, only R1/9 features evaluated, not all 6/18), `threshold_query`
(16 qualifying customers, correct `ml_detect` exclusion), `entity_investigation` against both a real ID
(`C-STR02` — 1 correctly-scoped flag) and a nonexistent one (`C-04521`, the mock-only ID — 0 flags,
graceful, not a crash), and `ranking` top-5 (exactly 5, correctly sorted). `tests/test_integration.py`
(7 tests) locks all of this in. Full suite: **175/175 passing**, confirmed stable across three different
file orderings (the registry bug was order-sensitive, so this mattered).

Goal (reference, already met): flip `AML_USE_MOCKS=0`, same pipeline, real data and detection.

- Nothing in `backend/agent/**` should need to change — if it does, the mismatch is almost always because
  a Track B tool's `artifacts` shape drifted from Contract 2's agreed keys table. Fix the tool to match the
  contract; don't bend the agent to match the tool.
- Debug against the real sample CSV, not just the mocks' 5-row fixture — row counts, dtypes, and NaNs
  behave differently at scale.
- Write `README.md` + `ARCHITECTURE.md` once the real pipeline is stable enough to describe truthfully.

**Acceptance:** all 10 demo queries (see WORKPLAN.md §6, Track B's list) work against real data.

---

## Standalone fix — Entity-ID resolution ✅ DONE

Not part of Phase 6's original scope (deliberately deferred, then requested separately once Phase 6 was
pushed) — recorded as its own item so it doesn't get conflated with either phase.

Real customer IDs (`C-N0001`, `C-STR02`, ...) don't match the parser's numeric normalization of a bare
number ("4521" → `C-04521`). Added `_resolve_entities()` in `executor.py`: after `load_data` populates
`ctx.customers`, matches unresolved entities against real `customer_id`s by numeric id (digit-only,
integer comparison — not substring, which false-positives on short numbers), takes the first candidate on
ambiguity (logged to `plan.decisions`), and re-syncs the already-plan-built `entity_lookup` step's
`entity_id` param. Leaves genuinely out-of-range numbers unresolved — same graceful no-match as before.

Caught a real bug while testing it: resolution notes were only logged when the entity list actually
changed, so the "no real customer found" message silently disappeared for the no-match case. Fixed by
always logging, unconditionally. `tests/test_integration.py` — 3 new tests (bare-number match, ambiguous
match, out-of-range no-match, real-ID passthrough). Full suite: **178/178 passing**.

---

## Phase 7 — Hardening & Demo Prep

- Every demo query has a graceful, specific answer for the empty-result case.
- `run_demo.py` starts backend + frontend with one command.
- **Rehearse with the LLM key unset** — this is a demo-day risk, not a nice-to-have.
- Fill in the remaining README sections: setup, example queries + expected plans, screenshots, limitations.

---

## Notes for whoever (human or agent) picks this file up

- Don't reorder or renumber phases — TRACK_A_PROGRESS.md references them by number.
- If a phase's approach turns out to be wrong, fix it here **and** log the change in
  TRACK_A_PROGRESS.md's decision log — don't silently diverge from the written plan.
- Contract changes (schemas.py, tools/base.py, docs/CONTRACTS.md) still require the standup protocol in
  WORKPLAN.md §2 Rule 1 / §7, even mid-Phase.
