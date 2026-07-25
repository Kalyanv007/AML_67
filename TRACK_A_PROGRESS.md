# TRACK A — Progress & Resume State

**Purpose:** if this project is picked back up later (by you or by a fresh coding-agent session), read
**only this file** plus [TRACK_A_ROADMAP.md](TRACK_A_ROADMAP.md) and [docs/CONTRACTS.md](docs/CONTRACTS.md).
Do not re-read the whole codebase to figure out where things stand — this file is kept accurate for
exactly that reason. Update it every time you finish a subtask or make a decision, not just at hour
boundaries.

**Last updated:** 2026-07-25, Phase 7 done.

---

## Where we are right now

**Phases 0–7 all done**, plus two standalone fixes (entity-ID resolution, LLM call-volume capping) and
four bugs found and fixed during Phase 7 hardening (3 in the agent pipeline, 1 test-isolation bug found by
my own final verification step — see decision log #18). `pytest tests/ -v` → **185/185 passing**,
confirmed with a real `.env` on disk (`AML_USE_MOCKS=0`) — not just in a clean environment. All 11
representative demo queries manually verified against real data — 8 via direct Python calls, then the
final 2 (structuring/last-30-days, C-STR02 entity investigation) re-verified through the **actual live
HTTP API** (`uvicorn` + `curl`), not just Python-level calls, with that same real `.env` in place, matching
what a fresh clone actually runs.

### Phase 7 findings (all fixed, all in files Track A owns)
1. **Date-anchoring bug (critical — broke a brief-mandated example query)**: "last 30 days" resolved
   against `date.today()` (wall-clock), but the dataset is dated Jan–Mar 2025 — so "Find structuring
   patterns in the last 30 days" returned **zero flags** against real data despite working fine against
   mocks. Fixed: `intent_parser._dataset_reference_date()` anchors relative dates to the dataset's own
   max transaction date instead, cached per process.
2. **Entity-ID regex too narrow (critical)**: only recognized pure-digit IDs (`C-04521`); real IDs are
   alphanumeric (`C-STR02`, `C-N0001`). "Is customer C-STR02 suspicious?" — a real ID our own system would
   show a user — misclassified as `full_analysis` instead of `entity_investigation`. Fixed: `ENTITY_RE`
   now accepts `[CT]-[A-Z0-9]{2,8}`; normalization split into two paths (prefixed real-looking IDs pass
   through as-is, bare numbers still get the constructed-guess treatment for `_resolve_entities()` to
   reconcile later).
3. **`explain_flag` never actually worked** — asked the user how to handle it; chose "make it actually
   work." Its plan never called `load_data` (Contract 4 said "reuse a cached run," which was never wired
   to anything), so it always returned empty. Changed its plan to load data and score the entity fresh,
   same shape as `entity_investigation` minus `filter_data`. Documented the deviation from Contract 4's
   original text directly in the planner code comment.
4. **Minor polish**: `_summarise()` had generic fallback text for `eda` ("No suspicious activity was
   flagged") that didn't fit a non-detection query, and no case at all for `explain_flag`. Added
   intent-specific summaries for both.

### Also done in Phase 7
- `run_demo.py` — starts backend + frontend together, opens the browser, clean Ctrl+C shutdown.
- `.env.example` fixed: `AML_API_BASE_URL` (never read by anything) → `AML_API_URL` (what
  `frontend/app.py` actually reads); `AML_USE_MOCKS` default flipped `1→0` now that real tools exist.
- `requirements.txt`: added `kagglehub` (imported by `backend/tools/data_loader.py`, was missing — a
  clean-clone install would have `ImportError`'d on the IBM loader path). Installed into `.venv` and
  confirmed.
- `README.md` and `ARCHITECTURE.md` written (see file list below).
- 6 new tests locking in the above (2 in `test_intent.py`, 1 in `test_planner.py` rewritten, 2 in
  `test_integration.py`, plus the doc-driven verification wasn't a separate test file).

### Immediate next action
No Track A phase work remains in the original 7-phase plan. Open items, none blocking:
- **Live LLM-key smoke test** (Known Gaps #1) — still waiting on the user to obtain a
  Gemini/OpenAI key. Do this before depending on the LLM path in an actual judged demo.
- **Quantitative precision/recall/FP table** against the IBM label — flagged in README as "not yet done,"
  arguably Track B's analytical work per WORKPLAN §6, not built here; ask before doing it.
- Rehearsing the full demo script end-to-end 2-3 times before presenting (README's Setup section is the
  closest thing to a script; no dedicated `DEMO_SCRIPT.md` from Track B seen yet as of this update).

---

## Phase checklist (mirrors TRACK_A_ROADMAP.md — keep numbers in sync)

- [x] **Phase 0 — Kickoff scaffold.** Contracts frozen, repo boots, Track B unblocked.
- [x] **Phase 1 — LLM client + intent parser.** `backend/llm/client.py`, `backend/agent/intent_parser.py`.
      21 tests passing (`tests/test_intent.py`).
- [x] **Phase 2 — Planner.** `backend/agent/planner.py`, matches Contract 4 exactly. 8 tests passing
      (`tests/test_planner.py`), including the plan-divergence assertions.
- [x] **Phase 3 — Executor.** `backend/agent/executor.py`, both re-planning branches implemented. 3 tests
      passing (`tests/test_executor.py`).
- [x] **Phase 4 — Narrator.** `backend/agent/narrator.py`, template + optional LLM polish + SAR draft.
      No dedicated test file — covered indirectly via executor/API tests. *(Gap: no direct
      `tests/test_narrator.py` yet — low priority since it's exercised end-to-end, but note it as a gap.)*
- [x] **Phase 5 — Wire `/query` end-to-end on mocks.** `backend/main.py` fully wired. 7 tests passing
      (`tests/test_api.py`). Manually boot-verified with real `curl` calls, not just pytest.
- [x] **Phase 6 — Integrate Track B's real tools.** Found + fixed 5 real bugs (narrator evidence-shape
      crash, 3 planner param-name mismatches, missing entity/top-N scoping in executor, a registry
      global-state bug). 7 tests passing (`tests/test_integration.py`), plus manual verification against
      the real 2,002-row dataset. Full suite 175/175, stable across 3 orderings.
- [x] **Post-Phase-6 fix — Entity-ID resolution.** `_resolve_entities()` in `executor.py` matches
      parser-normalized IDs to real customer IDs by numeric id. 3 tests passing. Caught and fixed a
      decisions-logging bug in the process (see decision log). Full suite 178/178.
- [x] **Post-Phase-6 fix — LLM call volume capped to HIGH-risk flags.** `narrator._explain()` skips the
      LLM entirely for MEDIUM/LOW/NONE flags — avoids one call per flag exhausting free-tier rate limits
      on a single multi-flag query. Added `tests/test_narrator.py` (4 tests, closing Known Gap #2 as a
      side effect). Full suite 182/182.
- [x] **Phase 7 — Hardening & demo prep.** Found + fixed 3 real bugs while live-testing 11 demo queries
      against real data (date anchored to wall-clock instead of dataset date — broke the brief's own
      "last 30 days" example; entity regex too narrow for real alphanumeric IDs; `explain_flag` never
      wired to any data source), plus 1 test-isolation bug found by the final verification step itself
      (mock-dependent tests broke once a real `.env` existed on disk — see decision log #18). Wrote
      `run_demo.py`, fixed `.env.example` (wrong var name, stale mocks default), added `kagglehub` to
      `requirements.txt`, wrote `README.md` + `ARCHITECTURE.md`. 6 new tests + 2 hardened with an
      explicit `force_mocks` fixture. Full suite 185/185, confirmed with a real `.env` present. Final live
      verification through the actual HTTP API, not just Python-level calls.

---

## What exists on disk right now (verified state, not aspirational)

### Fully implemented and tested
| File | State |
|---|---|
| `backend/schemas.py` | Complete — Contract 1, unchanged since Phase 0 |
| `backend/tools/base.py` | Complete — Contract 2, unchanged since Phase 0 |
| `backend/tools/_mocks.py` | Complete — unchanged since Phase 0. `C-04521` is the pre-wired "obviously flagged" customer (structuring, R1, risk 78/high/report) — used as the default fixture across all tests |
| `backend/agent/registry.py` | Complete — fixed in Phase 6: `TOOLS.clear()` + `importlib.reload()` on every call so `load_tools()` is deterministic in its requested mode regardless of prior calls in-process |
| `backend/config.py` | Complete — unchanged since Phase 0 |
| `backend/llm/client.py` | Complete — `complete_json()`, Gemini/OpenAI behind `settings.llm_provider`, returns `None` on any failure. **Still not exercised against a real API key** — only tested with it monkeypatched to return `None` (see Known Gaps) |
| `backend/agent/intent_parser.py` | Complete — LLM-first + full regex fallback. **Phase 7 fixes**: entity regex now accepts real alphanumeric IDs (`[CT]-[A-Z0-9]{2,8}`, not just digits); relative dates anchor to the dataset's own max date (`_dataset_reference_date()`) instead of wall-clock `date.today()` |
| `backend/agent/planner.py` | Complete — intent → plan mapping matches Contract 4; params match Track B's actual tool signatures (Phase 6). **Phase 7 fix**: `explain_flag` now loads data and scores the entity fresh (deviates from Contract 4's original "reuse cached run" text, which was never wired to anything — documented inline) |
| `backend/agent/executor.py` | Complete — core loop, timing, error isolation, re-planning branches, `_resolve_entities()` (post-Phase-6). **Phase 7 fix**: `_summarise()` now has dedicated, accurate messages for `explain_flag` and `eda` (previously fell through to a detection-flavoured generic message that didn't fit either) |
| `backend/agent/narrator.py` | Complete — `_build_evidence()`, template explanations, LLM polish capped to HIGH-risk flags only (untested against a real key, see Known Gaps #1), escalation mapping, SAR draft for HIGH |
| `backend/main.py` | Complete — `/health`, `/query`, `/dataset/summary`, `/plan/{plan_id}` all live, verified against both mocks and real tools, and against the real HTTP API with `AML_USE_MOCKS=0` |
| `requirements.txt` | `kaggle` + `kagglehub` added (Phase 6 / Phase 7 respectively — `kagglehub` is what `data_loader.py` actually imports; missing before, would have `ImportError`'d on the IBM loader path on a clean clone) |
| `.env.example` | **Phase 7 fix**: `AML_API_BASE_URL` (dead — nothing read it) → `AML_API_URL` (what `frontend/app.py` actually reads); `AML_USE_MOCKS` default `1→0` now that real tools exist |
| `run_demo.py` | New (Phase 7) — starts backend + frontend together, opens browser, clean Ctrl+C shutdown |
| `.gitignore`, `CLAUDE.md` | Unchanged since Phase 0 |
| `README.md`, `ARCHITECTURE.md` | New (Phase 7) |

### Tests (all passing — `pytest tests/ -v` → 185 passed)
| File | Count | Covers |
|---|---|---|
| `tests/test_intent.py` | 23 | 15 phrasing→intent cases (parametrized) + entity/date/amount/count/pattern/top_n extraction + Phase 7 regressions: alphanumeric real-ID recognition, relative-date anchored to dataset not wall-clock |
| `tests/test_planner.py` | 8 | Plan-divergence assertions (all 3 brief-mandated queries), per-intent tool inclusion/exclusion, every step has a reason, `explain_flag` now asserts it scores the entity (rewritten in Phase 7, was asserting the old broken behavior) |
| `tests/test_executor.py` | 3 | Full end-to-end run on mocks, simulated tool failure isolation, entity-investigation scoping |
| `tests/test_narrator.py` | 4 | LLM polish capped to HIGH-risk only, LLM-failure template fallback, SAR draft gating, escalation defaulting |
| `tests/test_api.py` | 7 | `/health`, `/query` (3 divergence cases + flag shape), `/dataset/summary`, `/plan/{id}` hit + miss |
| `tests/test_integration.py` | 11 | Real-data plan-divergence set + 3 entity-ID resolution tests + Phase 7's `explain_flag` real-data test (asserts it loads data, scores the right entity, skips eda/ml) |

### Track B's files (now real — for context, still not yours to edit)
`backend/tools/{data_loader,filters,eda,features,rules,ml_detect,aggregate,entity,risk}.py`,
`data/generate_synthetic.py`, `data/sample/aml_sample.csv` (+ `aml_sample_customers.csv`), `DATA_CARD.md`,
`AML_LOGIC.md`, `requirements-data.txt` (overlaps with `requirements.txt` — harmless duplication, not
merged), plus their own test files (`test_eda.py`, `test_features.py`, `test_filters.py`, `test_ml.py`,
`test_rules.py` — 128 tests, all passing, not written by Track A). `frontend/**` (fully built — 6 example
query buttons, plan-trace panel, flag cards, FIXTURE-mode fallback when the API is down). No
`DEMO_SCRIPT.md` seen yet as of this update.

---

## Known gaps / honest caveats (don't assume these are solved)

1. **The LLM path has never actually been called against a real key.** Still true — user doesn't have a
   Gemini/OpenAI key yet. Every test stubs `complete_json` to return `None`. **Blocked, not forgotten**:
   do a manual smoke test of `parse_intent()` and `narrator._explain()` against the real API the moment a
   key is available, before trusting that path in a demo — JSON-parsing and prompt-following behaviour of
   a live model is the one thing that can't be verified without one.
2. ~~No `tests/test_narrator.py`~~ — **resolved**: added, 4 tests. Covers the HIGH-risk-only LLM-polish
   cap (below), LLM-failure fallback, SAR draft gating, escalation defaulting. Multi-rule-per-entity and
   ML-only-flag explanation paths still untested directly, but low risk (simple template code, same
   pattern already proven for the single-rule case).
3. **`/dataset/summary` re-calls `registry.load_tools()` on every request** instead of reusing
   `executor._get_tools()`'s cache. Harmless for a hackathon's traffic volume; would be worth sharing the
   cache if this were long-lived. *(Now also re-runs `TOOLS.clear()` + reload every call after the Phase 6
   registry fix — still harmless at this traffic volume, just worth knowing it's not free.)*
4. ~~Executor re-planning only proven against mock fixture shapes~~ — **resolved in Phase 6**:
   `test_integration.py`'s `test_pattern_search_scopes_features_and_rules` confirms `rule_detect` widening
   and feature/rule scoping both work against real `artifacts["rule_hits"]`. The 0-hits→widen-to-ml_detect
   and <50-rows→drop-ml_detect branches specifically are *still* only proven against mocks, though — no
   real-data test forces either condition. Low priority (logic is simple and shared, not per-tool) but
   flagging so it isn't assumed covered.
5. ~~Real customer IDs don't match the parser's numeric-ID normalization scheme~~ — **fixed post-Phase-6**
   via `_resolve_entities()` in `executor.py`. Remaining limitation: resolution is by *numeric id only*
   (strip non-digits, compare as int), so it can't help with non-numeric queries like "the customer named
   Acme Corp" — that would need a name-lookup path, not built and not requested.
6. **The registry fix (`TOOLS.clear()` + `importlib.reload()`) is untested for thread-safety.** Fine for
   this project (single-process, no concurrent mock/real switching in production — `AML_USE_MOCKS` is set
   once at process start and never toggled at runtime), but if the server were ever made multi-worker or
   the mode toggled live, this would need a lock. Not in scope for a hackathon demo.
7. **No quantitative precision/recall/false-positive table against the IBM `Is Laundering` label.**
   `AML_LOGIC.md` §6 documents the *qualitative* false-positive-reduction argument; nobody has computed
   actual numbers. README states this honestly rather than fabricating a table. This is arguably Track B's
   analytical work per WORKPLAN §6 (H40-44) — ask before doing it, don't just build it.
8. **Entity-ID resolution is still numeric-only** (see gap #5's resolution note) — Phase 7's regex fix
   (accepting alphanumeric IDs like `C-STR02`) means a *typed* real ID always works precisely now; the
   numeric-matching fallback for a *bare number* still can't disambiguate perfectly (multiple real IDs can
   share a numeric suffix across prefixes — picks the first, logs it). Not fixed further; flagged as a
   known limitation in README rather than over-engineered.

---

## Environment state

- **`.venv/` is now the active environment — reinstalled cleanly per `requirements.txt`.** Command used:
  `.venv/Scripts/pip.exe install -r requirements.txt` (ran once, completed successfully in the
  background). All test runs and the manual boot test in this session used
  `.venv/Scripts/python.exe` explicitly — **use that interpreter, not global `python`, from now on.**
  (Earlier sessions had accidentally installed into global Python — that inconsistency is now resolved;
  global Python may still have stray newer versions installed but nothing in this repo depends on them
  anymore.)
- The venv already had `kaggle` and `jupyter`-family packages present before this session's install (very
  likely from Track B's earlier work on the same machine, or a shared venv) — harmless, `requirements.txt`
  doesn't conflict with them.
- No `.env` file created yet (only `.env.example`). LLM keys unset → `llm_available: false` in `/health`,
  confirmed live. `AML_USE_MOCKS` defaults to `True` in `config.py` — confirmed via `/health`'s
  `"mocks": true`.
- Boot smoke test **completed and confirmed working** this session (see Phase 5 entry above) — the
  outstanding item from the previous progress-file version is resolved.

---

## Decision log

Keep this append-only, most recent last. Each entry: what was decided, why, and what it overrides.

1. **Common `requirements.txt` instead of split files** (WORKPLAN.md §2 Rule 4 override) — user request.
   When adding a dependency, add only your own line under the relevant section comment, never reorder.
2. **Nested stray git repo `AML_67/` deleted** — empty, 0 commits, confirmed safe before deletion.
3. **Phase 0 scaffold was deliberately bare stubs**, deferring the WORKPLAN.md H0-2 exit criterion to
   what became Phase 5 of this roadmap. *(Superseded by entry 6 below — that criterion is now met.)*
4. **`kaggle==1.6.17` added to `requirements.txt`** at Track B's request, one line, correct section.
5. Mock data deliberately makes `C-04521` the one "interesting" customer (structuring, R1, high risk) so
   manual testing and early UI work have an obvious positive case without needing real data.
6. **Phases 1–5 implemented in one session** (LLM client, intent parser, planner, executor, narrator, API
   wiring), all with real logic (not further stubs), all test-covered, and manually boot-verified with
   live `curl` calls against a running `uvicorn` instance — not just `pytest`. This closes the gap left
   by decision #3: the original WORKPLAN.md H0-2 exit criterion (`POST /query` → valid mocked
   `AgentResponse`) is now genuinely satisfied, just five phases later than the original plan assumed.
7. **`.venv` reinstalled cleanly from `requirements.txt`** and confirmed as the interpreter used for all
   testing in this session, resolving the earlier global-vs-venv drift noted in decision-log entry (prior
   session). Use `.venv/Scripts/python.exe -m pytest` / `.venv/Scripts/python.exe -m uvicorn ...` going
   forward, not a bare `python`/`pytest` command that might resolve to a different interpreter.
8. **Intent-classification precedence rule, undocumented elsewhere so noting it here:** in
   `intent_parser._classify()`, checks run in a fixed order (explain_flag → entity_investigation →
   ranking → threshold_query → pattern_search → eda → full_analysis fallback) and the first match wins.
   This matters if you extend the regex fallback later — e.g. a query mentioning both an entity ID and a
   pattern keyword currently resolves to `entity_investigation`, not `pattern_search`, because that check
   runs first. This was a deliberate ordering choice (a named entity is a stronger, more specific signal
   than a pattern keyword) but isn't written down anywhere except here and in code comments-by-omission —
   if it ever needs to change, update `TRACK_A_ROADMAP.md` Phase 1 too so the two docs don't drift.
9. **Phase 6 done in one session, immediately after being told "phase by phase, no scope creep" for
   Phases 1–5.** Interpreted "build this phase" as strictly Phase 6 only — did not start Phase 7 (README,
   run_demo.py) even though some of that could have been drafted alongside. Found 5 real bugs while
   integrating (see roadmap Phase 6 for detail); all fixed in files Track A already owned
   (`narrator.py`, `planner.py`, `executor.py`, `registry.py`, `_mocks.py`) — zero edits to any Track B
   file. The registry bug (entry below) was the one surprise that took real investigation, not a
   quick fix — worth remembering if a similar "works alone, fails in the full suite" symptom shows up
   again: suspect global mutable state shared across test files before suspecting test logic.
10. **`backend/agent/registry.py`'s `TOOLS` dict is a global, process-wide singleton that only updates via
   first-import decorator side effects.** Discovered because `load_tools(use_mocks=True)` then later
   `load_tools(use_mocks=False)` in the same process left some tool names on stale (mock) bindings while
   others correctly updated to real — depending on which test file happened to import which real tool
   module first, at collection time vs. execution time. Fixed by clearing `TOOLS` and
   `importlib.reload()`-ing on every `load_tools()` call. If a future contract change moves tool
   registration to a different mechanism, re-verify this class of bug doesn't reappear — the underlying
   risk (decorators only run once per process) is inherent to the `@tool` pattern, not just this bug.
11. **Entity-ID resolution built as a standalone task, explicitly not bundled into Phase 7.** User chose
    to push Phase 6 first (correct call — the ID gap degrades gracefully, not a Phase 6 blocker), then
    asked for this fix specifically afterward. Implemented in `executor.py`: `_resolve_entities()` matches
    by numeric id (digits-only, int comparison) rather than substring, to avoid short numbers
    false-matching many IDs. On ambiguity (multiple real customers sharing a numeric id — happened for
    "2", 6 candidates across different ID prefixes), picks the first deterministically and logs it.
12. **Caught a real bug while testing decision 11**: the resolution notes (`resolve_notes`, including the
    "no real customer found" message) were only appended to `plan.decisions` inside the
    `if resolved != intent.entities:` branch — meaning the no-match case silently dropped its own
    explanatory note, even though `_resolve_entities()` correctly computed it. A test written for exactly
    this case (`test_entity_resolution_leaves_out_of_range_id_unresolved`) caught it immediately. Fixed by
    always appending notes and re-syncing `entity_lookup` params, unconditionally. **Lesson for future
    work in this file**: when a helper returns "notes to log" alongside "the actual result," don't
    conditionally gate the logging on whether the result changed — the notes are often most valuable
    exactly when nothing changed (the "why not" case).
13. **User asked, before starting Phase 7, whether to test with a real LLM key now or later, whether free
    tier would be enough, and when to address Known Gaps.** Recommended testing now (standalone, cheap,
    de-risks Phase 7) but deferred pending the user getting a key — not blocked on me. While reasoning
    through "will free tier be enough," found a real design problem, not just a hypothetical one:
    `narrator._explain()` was calling the LLM once per flag, so a 30-flag `full_analysis` result meant 30
    LLM calls for a single query — well past Gemini free tier's ~15 req/min. User chose to cap LLM polish
    to HIGH-risk flags only (cheapest fix, keeps the "LLM adds value" story where it matters most — HIGH
    flags are also the ones getting a SAR draft). Implemented in `_explain()`: a `row.get("risk_level") !=
    "high"` early-return before the `complete_json` call. Also wrote `tests/test_narrator.py` (4 tests) —
    this closes decision-log-adjacent Known Gap #2 (no narrator test file) as a side effect of this fix,
    not a separately-scoped task.
14. **User confirmed Phase 7 could start now, independent of the still-pending LLM key test** — correct
    read: Phase 7's own acceptance criterion is "rehearse with the LLM key unset," which is the state
    we're already in. Before writing any docs, ran all 11 planned demo queries live against real data
    first — this is what actually found the date-anchoring bug, the entity-regex bug, and confirmed
    `explain_flag`'s brokenness, rather than discovering them after the README had already claimed they
    worked. **Lesson reinforced**: for "hardening," running the real thing before writing about it caught
    3 bugs that unit tests alone had not caught (the plan-divergence tests check *which tools ran*, not
    *whether the answer was non-empty and correct* — both kinds of test are needed).
15. **`explain_flag` fix asked as a question, not silently decided** — Contract 4's text explicitly
    described "reuse a cached run," and changing that is a real design deviation, not just a bug fix, per
    the file-ownership/behavior-change discipline this repo has followed throughout (see
    `ANTI_HALLUCINATION_A.md` rule 13). User chose "make it actually work." The deviation is documented
    inline in `planner.py`'s comment, not just here, so a future reader of the code (not just this log)
    understands why the plan doesn't match the contract doc's literal words.
16. **`.env.example`'s `AML_USE_MOCKS` default flipped `1→0`** as part of Phase 7, on the reasoning that
    the template should reflect "how to actually run the demo" now that real tools exist, not "how Track A
    developed in isolation before Track B's tools existed." This changes what a fresh `cp .env.example
    .env` gives a new user — worth knowing if that surprises anyone expecting mocks-by-default.
17. **`kagglehub` added to `requirements.txt`, distinct from Phase 6's `kaggle` addition.** Confirmed via
    `grep` that `backend/tools/data_loader.py` imports `kagglehub` specifically (not the `kaggle` CLI
    package), and that it was missing from `requirements.txt` (only present in Track B's separate,
    non-canonical `requirements-data.txt`, which overlaps with but was never merged into the common file
    per the Phase 0 decision override). Installed into `.venv` and confirmed importable before adding it,
    not just added on the strength of the grep hit.
18. **Found a real test-isolation bug via my own final verification step.** Created a real `.env`
    (`AML_USE_MOCKS=0`) to boot-test the actual demo defaults end-to-end. This broke 6 previously-passing
    tests in `test_api.py`/`test_executor.py` — they asserted against mock fixture data (`C-04521`, 5-row
    fixture, `mocks: true`) but never *forced* mock mode; they just relied on `settings.aml_use_mocks`
    defaulting to `True` in the absence of a `.env`. Once a real `.env` existed on disk, `Settings()`
    (pydantic-settings, reads `.env` at import time) picked up `AML_USE_MOCKS=0`, and every test in those
    two files silently ran against real tools instead of mocks. **Fixed properly, not worked around**:
    added an `autouse` `force_mocks` fixture to both files (`monkeypatch.setattr(settings, "aml_use_mocks",
    True)` + reset `executor._TOOLS_CACHE`), mirroring the `real_tools` fixture `test_integration.py`
    already had for the opposite direction. **Lesson**: any test that asserts against mock-specific data
    must force mock mode explicitly — never assume "no `.env` exists" as an implicit precondition, because
    a working local `.env` is exactly what Phase 7 was trying to produce. The `.env` file itself is
    gitignored and won't propagate to Track B or CI, but the test fragility it exposed was real and now
    fixed regardless of whose machine has a `.env`.

---

## How to resume this session cheaply

1. Read this file top to bottom.
2. Check `git log --oneline -5` to confirm nothing has changed since "Last updated" above — if it has,
   treat this file as stale until reconciled.
3. Run `.venv/Scripts/python.exe -m pytest tests/ -v` to confirm the 185/185-passing baseline still holds
   before changing anything. If it's flaky or order-dependent, suspect either `backend/tools/base.py`'s
   global `TOOLS` dict (decision log #10) or ambient `.env`/`settings.aml_use_mocks` state leaking into
   tests that assume mock mode without forcing it (decision log #18) before assuming new test code is wrong.
4. All 7 phases are complete (see checklist above) — there is no "current phase" left in
   TRACK_A_ROADMAP.md's original plan. Check this file's "Immediate next action" (top of file) for what's
   actually outstanding — likely just the pending live LLM-key test, and possibly the quantitative
   detection-quality table if the user asks for it.
5. When you finish a subtask: check the box, update "Last updated"/"Current phase", append a Decision Log
   entry for anything not already specified in the ROADMAP.
