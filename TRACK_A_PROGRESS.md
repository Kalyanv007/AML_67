# TRACK A — Progress & Resume State

**Purpose:** if this project is picked back up later (by you or by a fresh coding-agent session), read
**only this file** plus [TRACK_A_ROADMAP.md](TRACK_A_ROADMAP.md) and [docs/CONTRACTS.md](docs/CONTRACTS.md).
Do not re-read the whole codebase to figure out where things stand — this file is kept accurate for
exactly that reason. Update it every time you finish a subtask or make a decision, not just at hour
boundaries.

**Last updated:** 2026-07-25, end of Phase 6 — integrated against Track B's real tools and real data.

---

## Where we are right now

**Phases 0–6 done. Phase 7 (hardening & demo prep) not started.** Track B pushed their real tools
(`data_loader`, `filters`, `eda`, `features`, `rules`, `ml_detect`, `aggregate`, `entity`, `risk`) and the
real sample dataset (2,002 transactions, 270 customers) between sessions. Integration against them found
and fixed **5 real bugs** — 4 in Track A's own planner/executor/narrator (param-name mismatches against
what the real tools actually expect, an evidence-shape assumption that didn't hold, missing entity/top-N
scoping), and 1 in the tool registry itself (a global-dict staleness bug that only manifested when
switching between mock and real mode within one process — i.e., across a test session, not in normal
single-mode operation). Full detail and root-cause narrative in TRACK_A_ROADMAP.md Phase 6.

`pytest tests/ -v` → **175/175 passing** (168 from Phases 0–5 + 7 new in `tests/test_integration.py`),
confirmed stable across three different file/test orderings — the registry bug was order-sensitive, so
re-running under different orderings was the actual verification, not just one green run.

### Immediate next action
Open TRACK_A_ROADMAP.md **Phase 7**: harden all 10 demo queries end-to-end (real data, not just the 5
tested so far), write `run_demo.py`, rehearse with the LLM key unset. `README.md`/`ARCHITECTURE.md` are
also part of Phase 7 and can be drafted now against real, verified pipeline behavior.

### Known correctness caveat to carry into Phase 7 (not a bug, but worth designing around)
The real dataset's customer IDs follow Track B's synthetic generator's own scheme (`C-N0001`,
`C-STR02`, `C-HUB01`, ...), not simple zero-padded numbers. The intent parser normalizes a bare number
like "4521" to `C-04521` (per `docs/CONTRACTS.md` Contract 0's stated convention), which will never match
a real record — confirmed live: `entity_investigation` on a nonexistent ID degrades gracefully (0 flags,
sensible summary, no crash) rather than erroring, so it's not broken, but a user typing a plausible-looking
number will always get "no risk indicators found" against the real data. This is a demo-data / UX
consideration (how would a user ever know or guess `C-STR02`?), not something to silently patch — flag it
to the user before Phase 7 demo-query work assumes numeric IDs work end-to-end.

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
- [ ] **Phase 7 — Hardening & demo prep.** Not started.

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
| `backend/llm/client.py` | Complete — `complete_json()`, Gemini/OpenAI behind `settings.llm_provider`, returns `None` on any failure. **Not exercised against a real API key in this session** — only tested with it monkeypatched to return `None` (see Known Gaps) |
| `backend/agent/intent_parser.py` | Complete — LLM-first + full regex fallback (7 intents, dates, amounts, counts, entities, patterns, top_n). Regex fallback is the only path actually tested |
| `backend/agent/planner.py` | Complete — intent → plan mapping matches Contract 4; params now match Track B's *actual* tool signatures (fixed in Phase 6 — see roadmap for the 3 mismatches found), `tools_considered_but_skipped` populated |
| `backend/agent/executor.py` | Complete — core loop, timing, error isolation, both re-planning branches, early-stop on empty filter result, plus Phase 6 additions: post-`risk_classify` entity scoping and ranking top-N truncation |
| `backend/agent/narrator.py` | Complete — `_build_evidence()` (added Phase 6) adapts Track B's rule-specific raw evidence dicts into the frozen `Evidence` shape; template explanations from `.note`, optional LLM polish (untested against a real key), escalation mapping, SAR draft for HIGH |
| `backend/main.py` | Complete — `/health`, `/query`, `/dataset/summary`, `/plan/{plan_id}` all live, verified against both mocks and real tools |
| `requirements.txt`, `.gitignore`, `.env.example`, `CLAUDE.md` | Unchanged since Phase 0 |

### Tests (all passing — `pytest tests/ -v` → 175 passed, 168 Track A + Track B combined from Phase 5, +7 new)
| File | Count | Covers |
|---|---|---|
| `tests/test_intent.py` | 21 | 15 phrasing→intent cases (parametrized) + entity/date/amount/count/pattern/top_n extraction |
| `tests/test_planner.py` | 8 | Plan-divergence assertions (all 3 brief-mandated queries), per-intent tool inclusion/exclusion, every step has a reason |
| `tests/test_executor.py` | 3 | Full end-to-end run on mocks, simulated tool failure isolation, entity-investigation scoping |
| `tests/test_api.py` | 7 | `/health`, `/query` (3 divergence cases + flag shape), `/dataset/summary`, `/plan/{id}` hit + miss |
| `tests/test_integration.py` | 7 | Same plan-divergence set but against real tools + real data: full_analysis, pattern_search feature/rule scoping, threshold_query, entity_investigation (real ID + nonexistent ID), ranking top-N, eda |

### Track B's files (now real, no longer just planned — for context, still not yours to edit)
`backend/tools/{data_loader,filters,eda,features,rules,ml_detect,aggregate,entity,risk}.py`,
`data/generate_synthetic.py`, `data/sample/aml_sample.csv` (+ `aml_sample_customers.csv`), `DATA_CARD.md`,
plus their own test files (`test_eda.py`, `test_features.py`, `test_filters.py`, `test_ml.py`,
`test_rules.py` — 128 tests, all passing, not written by Track A). `frontend/**` and
`AML_LOGIC.md`/`DEMO_SCRIPT.md` not yet seen as of this update.

### Not yet written (Track A, Phase 7)
`README.md`, `ARCHITECTURE.md`, `run_demo.py`.

---

## Known gaps / honest caveats (don't assume these are solved)

1. **The LLM path has never actually been called.** Every test stubs `complete_json` to return `None`
   (no API key is set in `.env`). The regex fallback is what's actually verified working. If/when a real
   `GEMINI_API_KEY` or `OPENAI_API_KEY` is added, do a manual smoke test of `parse_intent()` and
   `narrator._explain()` against the real API before trusting that path in a demo — the JSON-parsing and
   prompt-following behaviour of a live model is the one thing that couldn't be tested here.
2. **No `tests/test_narrator.py`.** Narrator logic is only exercised indirectly through executor/API
   tests using the one mock risk row (`C-04521`, rule `R1`). Untested paths: multiple triggered rules on
   one entity, an ML-only flag with no rule hit, LOW/MEDIUM/NONE risk levels (mock only ever produces
   HIGH). Low risk given it's simple template code, but worth a direct test file if time allows.
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
5. **Real customer IDs don't match the parser's numeric-ID normalization scheme** — see "Known correctness
   caveat" at the top of this file. Not a bug, but will affect any Phase 7 demo query that references a
   customer by a plain number.
6. **The registry fix (`TOOLS.clear()` + `importlib.reload()`) is untested for thread-safety.** Fine for
   this project (single-process, no concurrent mock/real switching in production — `AML_USE_MOCKS` is set
   once at process start and never toggled at runtime), but if the server were ever made multi-worker or
   the mode toggled live, this would need a lock. Not in scope for a hackathon demo.

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

---

## How to resume this session cheaply

1. Read this file top to bottom.
2. Check `git log --oneline -5` to confirm nothing has changed since "Last updated" above — if it has,
   treat this file as stale until reconciled.
3. Run `.venv/Scripts/python.exe -m pytest tests/ -v` to confirm the 175/175-passing baseline still holds
   before changing anything. If it's flaky or order-dependent again, suspect `backend/tools/base.py`'s
   global `TOOLS` dict first (see decision log #10) before assuming new test code is wrong.
4. Go to TRACK_A_ROADMAP.md, find "Current phase" above (Phase 7), and start there. Don't re-derive the
   plan from WORKPLAN.md/CONTRACTS.md — unchanged, already reflected here.
5. When you finish a subtask: check the box, update "Last updated"/"Current phase", append a Decision Log
   entry for anything not already specified in the ROADMAP.
