# TRACK A — Progress & Resume State

**Purpose:** if this project is picked back up later (by you or by a fresh coding-agent session), read
**only this file** plus [TRACK_A_ROADMAP.md](TRACK_A_ROADMAP.md) and [docs/CONTRACTS.md](docs/CONTRACTS.md).
Do not re-read the whole codebase to figure out where things stand — this file is kept accurate for
exactly that reason. Update it every time you finish a subtask or make a decision, not just at hour
boundaries.

**Last updated:** 2026-07-25, end of Phase 5 — the full mock pipeline is live and tested.

---

## Where we are right now

**Phases 0–5 done. Phase 6 (integrate Track B's real tools) not started — blocked on Track B's tool
files existing.** Everything in `backend/agent/**` and `backend/main.py` is real, working code now, not
stubs. `pytest tests/ -v` → **40/40 passing.** Manually boot-tested: `uvicorn backend.main:app` → curled
`/health`, `POST /query`, `/dataset/summary` — all correct, including the plan-divergence behaviour for
`"Is customer 4521 suspicious?"` (excludes `eda_profile`/`ml_detect`, returns a real explanation + SAR
draft for the HIGH-risk mock customer).

### Immediate next action
Nothing to build until Track B's tool files land (`backend/tools/{data_loader,filters,eda,features,rules,
ml_detect,aggregate,entity,risk}.py`, `data/sample/aml_sample.csv`). When they do: open
TRACK_A_ROADMAP.md **Phase 6**, set `AML_USE_MOCKS=0` in `.env`, run the suite against real data, and
watch for `artifacts` shape mismatches against the agreed keys table in `docs/CONTRACTS.md` Contract 2 —
fix the tool to match the contract, not the agent code.
Until then, optional/parallel work: `README.md` + `ARCHITECTURE.md` (Phase 6 also lists these, and they
can be drafted now against the mock pipeline's real behaviour).

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
- [ ] **Phase 6 — Integrate Track B's real tools.** Not started. Blocked on Track B.
- [ ] **Phase 7 — Hardening & demo prep.** Not started.

---

## What exists on disk right now (verified state, not aspirational)

### Fully implemented and tested
| File | State |
|---|---|
| `backend/schemas.py` | Complete — Contract 1, unchanged since Phase 0 |
| `backend/tools/base.py` | Complete — Contract 2, unchanged since Phase 0 |
| `backend/tools/_mocks.py` | Complete — unchanged since Phase 0. `C-04521` is the pre-wired "obviously flagged" customer (structuring, R1, risk 78/high/report) — used as the default fixture across all tests |
| `backend/agent/registry.py` | Complete — unchanged since Phase 0 |
| `backend/config.py` | Complete — unchanged since Phase 0 |
| `backend/llm/client.py` | Complete — `complete_json()`, Gemini/OpenAI behind `settings.llm_provider`, returns `None` on any failure. **Not exercised against a real API key in this session** — only tested with it monkeypatched to return `None` (see Known Gaps) |
| `backend/agent/intent_parser.py` | Complete — LLM-first + full regex fallback (7 intents, dates, amounts, counts, entities, patterns, top_n). Regex fallback is the only path actually tested |
| `backend/agent/planner.py` | Complete — intent → plan mapping matches Contract 4 exactly, `tools_considered_but_skipped` populated |
| `backend/agent/executor.py` | Complete — core loop, timing, error isolation, both re-planning branches, early-stop on empty filter result |
| `backend/agent/narrator.py` | Complete — template explanations from evidence `.note`, optional LLM polish (untested against a real key), escalation mapping, SAR draft for HIGH |
| `backend/main.py` | Complete — `/health`, `/query`, `/dataset/summary`, `/plan/{plan_id}` all live and working against mocks |
| `requirements.txt`, `.gitignore`, `.env.example`, `CLAUDE.md` | Unchanged since Phase 0 |

### Tests (all passing — `pytest tests/ -v` → 40 passed)
| File | Count | Covers |
|---|---|---|
| `tests/test_intent.py` | 21 | 15 phrasing→intent cases (parametrized) + entity/date/amount/count/pattern/top_n extraction |
| `tests/test_planner.py` | 8 | Plan-divergence assertions (all 3 brief-mandated queries), per-intent tool inclusion/exclusion, every step has a reason |
| `tests/test_executor.py` | 3 | Full end-to-end run on mocks, simulated tool failure isolation, entity-investigation scoping |
| `tests/test_api.py` | 7 | `/health`, `/query` (3 divergence cases + flag shape), `/dataset/summary`, `/plan/{id}` hit + miss |

### Not started (Track B's responsibility, tracked here only for context)
`backend/tools/{data_loader,filters,eda,features,rules,ml_detect,aggregate,entity,risk}.py`,
`frontend/**`, `data/generate_synthetic.py`, `data/sample/aml_sample.csv`, `DATA_CARD.md`, `AML_LOGIC.md`,
`DEMO_SCRIPT.md`. Do not build these — not your track.

### Not yet written (Track A, later phases)
`README.md`, `ARCHITECTURE.md` (Phase 6), `run_demo.py` (Phase 7).

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
   cache if this were long-lived.
4. **Executor re-planning is only proven against the mock tools' fixed fixture shapes.** Track B's real
   `rule_detect`/`filter_data` need to return `artifacts["rule_hits"]` and a `df` with the exact semantics
   assumed (row count reflects filtering, empty list means genuinely zero hits) for the re-planning logic
   to trigger correctly. Watch for this specifically in Phase 6.

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

---

## How to resume this session cheaply

1. Read this file top to bottom.
2. Check `git log --oneline -5` to confirm nothing has changed since "Last updated" above — if it has,
   treat this file as stale until reconciled.
3. Run `.venv/Scripts/python.exe -m pytest tests/ -v` to confirm the 40/40-passing baseline still holds
   before changing anything.
4. Go to TRACK_A_ROADMAP.md, find "Current phase" above (Phase 6), and start there. Don't re-derive the
   plan from WORKPLAN.md/CONTRACTS.md — unchanged, already reflected here.
5. When you finish a subtask: check the box, update "Last updated"/"Current phase", append a Decision Log
   entry for anything not already specified in the ROADMAP.
