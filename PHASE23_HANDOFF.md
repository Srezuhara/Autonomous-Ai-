# Phase 23 Handoff

*Updated 2026-08-30 at the end of the sixth session. The fifth found that the
pipeline was reporting success it had not earned, built verification for every
build shape, and reached the first plain `done` in the project's history. The
sixth spent no quota at all: it made the checkers testable against every build
already on disk, and closed four of the open defects below.*

**Read `SESSION_PROGRESS.md` §0 first** — it is the entry point and carries the
current state. This file is the per-defect detail behind it, and
**`PHASE23_QUOTA_RUNBOOK.md`** is the procedure for spending the next refill.

Full evidence for the earlier sessions: **`PHASE23_LIVE_VALIDATION.md`**.
Original plan: **`PHASE23_PLAN.md`** (Phases B and C are still untouched).

---

## 0.-2 The seventh session (2026-08-31) — row 2, and the ledger

Row 2 ran and **passed** (`bookmark_manager_e045ca2d`, `done_with_context`,
verified: yes, 173,307 tokens). Full record in `SESSION_PROGRESS.md` §0.

**§4.22 — the ledger only counted successful calls.** `_add_tokens` sits after
`raise_for_status()` at both call sites, so a 400, a 429-rejected attempt or an
attempt retried after a per-minute wait spends real budget and records nothing.
Measured: the ledger said 145,967 used on `gpt-oss-20b` when Groq's 429 said
`used 197323`. ~51,000 tokens, a quarter of the daily limit, all optimistic.
`_mark_model_daily_limited` now parses `limit N, used M` from the 429 and calls
`reconcile_ledger_from_groq(model, used)`, which anchors the leaky bucket to
that figure and then drains normally. **Upward only** — an over-count costs a
wait, an under-count costs a dead build. 18 new tests.

Note the scope: this corrects the estimate *when a model hits the wall*, not
continuously. Between 429s the number is still optimistic. Even rebuilding from
the database's own build rows came out 21,923 short, so the gap is structural,
not a slip in one path.

**§4.23 — `cli_smoke`'s 30s budget masked its own diagnosis.**
`ai_report_generator_c60361c0` really fails with
`ImportError: cannot import name 'run_streamlit_ui'`, but its module-level
`import streamlit` costs ~36s cold, so the check reported "timed out after 30s"
and buried the real reason. Same verdict, useless text. `CLI_TIMEOUT` is now 90s
and reads `CLI_SMOKE_TIMEOUT` from the environment. A slow `--help` is still a
defect and still fails; it now fails saying why.

### Closed later the same session (2026-08-31)

**§4.24 — nothing executed the suite the build ships.** New
`tools/generated_tests.py`, registered in `_verify_other_shapes` and in
`verify_corpus.py`. It runs the project's own tests in a throwaway copy (they
write files — row 2's suite creates a SQLite database in the working directory)
and separates the verdicts that matter: a project with no tests is
NOT_APPLICABLE, a suite that errors before executing reads differently from one
that runs and disagrees, and a suite that collects zero tests is called inert.

**What it found is the reason it exists: 34 of the 41 saved builds ship a test
suite that does not pass. 1 passes, 6 ship no tests.** The failures are real and
specific — `assert 422 == 201` (the API rejects its own test's payload),
`KeyError: 'id'`, `NameError: name 'List' is not defined` (a missing import in
the *source*), `AttributeError` on a None returned by `init_db()`. There were
**zero** `ModuleNotFoundError`, which is what a wrong sandbox PYTHONPATH would
have produced, so this is not the checker misreading the corpus. Row 4 —
`bulk_file_renamer_912f9b22`, the first plain `done` in the project's history —
ships a `test_cli.py` that loads `parent.parent / "cli.py"` when the file is at
`bulk_file_renamer/cli.py`. It fails in the user's checkout exactly as it fails
here.

> **A decision this forces, deliberately left open.** The matrix criterion is
> "every check either verified the artifact or correctly did not apply". Under
> that rule `generated_tests` turns almost every row red, including row 2, which
> passed everything else. The check is **not** marked fatal — a failing suite
> does not mean the artifact cannot run, and `_functional_verdict` stays narrow
> — but it does contribute findings, so rows will read `done_with_context`.
> Either the criterion counts this check or it tracks it separately; that is a
> product call, not a bug, and it should be made rather than drifted into.

**§4.25 — a finding recorded once was never re-read.**
`BackendDeveloper.rescan_unrepaired_defects` re-runs exactly the scans that
produced `unrepaired_defects` (per-file scan + `check_project_sql` +
`check_project_attributes`) against what is on disk now, and `_diagnose` calls
it before assembling the issue list. Verified against the real row-2 build:
both recorded `description` defects clear, because the debugger had fixed them
in the file that declares the field.

Two things that fix got wrong first, both caught by the suite and worth keeping
in mind for the next re-scan-shaped change:

- A file that could not be read scanned as "no defects" and **cleared a real
  finding** — silence read as a pass, this codebase's oldest mistake. Only a
  file that is present and actually scanned may clear one.
- The existence check resolved against the CWD, not `OUTPUT_DIR`. That is the
  two-path trap that once turned every generated file into "does not parse".

### Still open, found by row 2

~~A finding is recorded once and never re-read.~~ **Fixed, §4.25 above.**

~~Nothing executes the generated tests.~~ **Fixed, §4.24 above** — and the fix
found that 34 of 41 saved builds ship a suite that does not pass.

**Live-unproven.** Neither fix has run inside a build. `generated_tests` has
been run against all 41 saved builds, which is the strongest evidence available
without quota; the re-scan has been run against the real row-2 project. What
neither has done is run *in the pipeline*, where `_diagnose` calls the re-scan
twice and the verifier runs on a project the build just wrote. That is the
first thing the next live row proves.

---

## 0.-1 What changed in the fifth session (2026-08-30)

**The one-line version: an empty findings list meant four different things, so a
build nobody had verified and a build that passed verification were the same
value.** Everything below follows from that.

`Pipeline._smoke_test_runtime` returned `[]` when the check passed, when there
was no web app to check, when there *was* one and the probe could not find it,
and when the tester crashed so verification never ran at all.

**Matrix row 4 is what that cost.** It shipped `done_with_context` with a valid
ZIP, containing a FastAPI app at `bulk_file_renamer/main.py` that was never
probed — entry discovery searched only `backend/`, `src/` and the project root
for the literal string `"FastAPI("` — beside a CLI that nothing executed. The
log line `Runtime smoke test skipped (no FastAPI entry point)` was written into
`SESSION_PROGRESS.md` as evidence the non-web path worked. **It was a miss, not
a skip.** Probed for the first time, that app serves exactly one route:
`GET /health`.

Worse, the product had been bent to fit the verifier: `prompts/architect.txt`
forced a FastAPI backend into every project "NO EXCEPTIONS", justified in its
own text as *"required for the testing and debugging pipeline to function."*

### The seven new tools, all zero-token

| Tool | What it does |
|---|---|
| `tools/verification.py` | Four answers instead of an empty list: VERIFIED / NOT_APPLICABLE / **NOT_RUN** / FAILED. NOT_RUN is never `ok` and contributes an explicit "this build is unverified" finding |
| `tools/build_shape.py` | The one detector every verifier keys off. Finds a web app anywhere in the tree, Flask as well as FastAPI, a `create_app()` factory as well as a module-level binding |
| `tools/cli_smoke.py` | **Runs the tool.** `--help` must exit 0 and print something; each subcommand must describe itself; a tool with required arguments must print usage rather than raise. Temp sandbox, never the project |
| `tools/web_asset_check.py` | Parses the page: local assets resolve, no bare specifier in a module, no `import` in a classic script, and `fetch()` paths match declared routes |
| `tools/package_smoke.py` | Imports the library as a user would, so `__init__.py` re-exports and `__all__` promises actually execute |
| `tools/feature_coverage.py` | Compares `intent["features"]` against routes, function names and CLI flags. It reached only the README before |
| `tools/repair_guard.py` | One acceptance rule, shared by the three agents that overwrite files — two of which had none |

### The live result

Row 4 rebuilt: **`done`** in 932s, 109,206 tokens. The first plain `done` on any
row, ever. The architect produced a pure CLI — no `backend/`, no routes, zero
FastAPI — and the record carries positive evidence (two VERIFIED checks, two
correct not-applicables, zero NOT_RUN) rather than four blanks.

Suite: **394 → 491**, all offline.

---

## 0.-0.5 The issues that exist right now

Ordered by what should be looked at first. Nothing here is speculative — each
was either verified in the code this session or is a measured gap.

### The sixth session (2026-08-30, evening) — zero quota spent

Seven changes, none of which cost a token, detailed in `SESSION_PROGRESS.md` §0.
Two are worth stating here because they change what this document's other
entries mean:

- **`tools/verify_corpus.py`** runs every verifier against all 40 saved builds
  and diffs the result against a committed `verification_baseline.json`. Every
  claim below about what a checker says on a given fixture is now testable in
  one command, for free.
- **`tools/schema_attr_check.py`** reads a defect class no probe can reach. On
  the shipped row 3 it names three undeclared field reads, one more than the
  runtime probe found; on `_live_verify_row2_final` — a build the probe scores
  **6/6 green** — it names three more, all real.

Suite: **491 → 541**.

### Live-unproven work

0. **Nothing from the sixth session has run inside a build.** Items 2-6 of that
   list change what a build reports about itself, and only a live row exercises
   that. `PHASE23_QUOTA_RUNBOOK.md` §4 says what to assert when one does.

1. **Rows 2 and 3 have not been rebuilt.** The frontend contradiction fix, the
   persistence pinning and the forced-backend removal are prompt-and-generation
   changes, and §0.3's clone technique explicitly cannot exercise those — only a
   rebuild can. Row 2 is the shape `web_asset_check` was written for and has
   never run on a fresh build.

### Real defects, unfixed

2. ~~**`MIN_TOKENS_TO_START` gates on the best model.**~~ **Fixed 2026-08-30
   (evening).** Two floors, `MIN_FAST_TOKENS_TO_START = 90,000` and
   `MIN_HEAVY_TOKENS_TO_START = 70,000`, each checked against its own model.
   The roles are read from `llm_client`, not `config` — `config` only knows a
   single `GROQ_MODEL`, and reading it from there would leave both models
   "unclassified" at the low floor with no symptom at all. §50.
3. **A plain-JS frontend still gets no execution or lint.** `frontend_debugger`
   (`:122`) and the tester's Vitest path (`:478`) both require
   `frontend/package.json`, which this shape does not have, so both still skip.
   `web_asset_check` parses it statically, which is a large improvement over one
   regex, but nothing runs the JavaScript. **Still open.**
4. ~~**`BackendDeveloper._verify_and_repair` keeps a rewrite whose defects
   remain.**~~ **Fixed 2026-08-30 (evening).** `accept_rescan` in
   `tools/repair_guard.py` is the shared rule: strictly fewer defects and no new
   ones, or the original goes back. Equal counts are a rejection — a rewrite
   that swaps one defect for another is a different file with the same problem,
   and the original is at least the file every other check in the build ran
   against. What could not be repaired is now named with its path and reaches
   `_diagnose`, so remediation can aim at it. §48.
5. ~~**The debugger still cannot repair drift that belongs in another file.**~~
   **Fixed 2026-08-30 (evening).** The 500 loop now applies blame rule 4. The
   discriminator is the model itself: a *close* field name means a misspelling
   and the repair stays where the read is (`contact`/`contact_email`, 0.70 —
   the case §0.7 proved works in place), and nothing close means the field is
   genuinely absent and the repair goes to the file that defines the class
   (`sku`, 0.29). A first attempt used the SQL schema as the discriminator and
   was wrong: the table has a `contact` column, so it would have redirected the
   one case that is known to repair correctly in place. §47a.

   **Unproven live.** It is asserted against the real row 3 project, but no
   build has run through it.

### Design gaps in the new checks

5b. **`schema_attr`'s rename threshold is judgment, not measurement.** A 0.6
    difflib ratio separates "misspelt" from "missing". It is calibrated against
    the three live cases it has to separate and asserted in §47a, so a change to
    it has to face them — but three cases is not a corpus.

6. **`feature_coverage` is a floor, not a ceiling.** It matches on ANY content
   word, so "email notifications when stock runs low" matches a project with a
   `/low_stock/` route and no notifications anywhere. It catches the feature
   nobody built at all; it cannot tell you a feature was built badly.
7. **`web_asset_check` skips what it cannot resolve confidently** — a URL built
   from an unknown base, a template literal that does not start with a base
   constant. Deliberate (precision over recall), but it is a recall gap.
8. ~~**`_functional_verdict` matches strings in findings.**~~ **Fixed
   2026-08-30 (evening).** A verifier that establishes the artifact does not run
   calls `outcome.mark_fatal(reason)`, and the verdict reads the field. The
   string markers remain as a fallback for findings that reach `unresolved` from
   paths with no outcome, and when they fire with nothing structured behind them
   the log says so — that gap is how this silently stops working. §49.
9. **`repair_guard`'s thresholds are judgment, not measurement** — a 0.6
   shrinkage ratio above 120 chars. Better than the old 0.5-above-400, still
   unvalidated against a corpus.

### Older, still open

10. **The nine-condition `done` gate is reachable but unexamined.** It ANDs
    nine things including 100% of generated tests passing and no `TODO`
    substring in any function body. Row 4 satisfied it; whether it is the right
    gate is a separate question nobody has asked.
11. **Phase C's premise.** Its memory gate (`status == done`) is now
    satisfiable for the first time, but the premise — that build quality is
    limited by missing precedent — is contradicted by a catalogue in which
    almost every diagnosed failure was mechanical. Re-examine before spending.
12. **The ledger cannot see other processes.** Per-checkout; two servers sharing
    the file will under-count. One at a time.
13. **A step can take 30 minutes.** `STEP_TIMEOUT_SECONDS=900` with one retry.

### Consequences of this session's choices, worth watching

14. **Removing the forced backend changes product output.** A vague prompt that
    used to yield an API may now yield only a CLI or a library. That is what was
    asked for, but it is user-visible and untested across prompt shapes — only
    row 4 has been run since.
15. **New checks surface failures that were always shipping.** Scores will look
    worse before they look better; row 3 going 16/16 → 12/16 was the fix
    working, not a regression.

---

## 0.0 What changed in the third session (2026-08-28)

**The matrix is three rows deep and the runtime-repair path has now run live.**
Rows 1, 2 and 3 all built; row 4 was refused by the driver because neither model
had 70,000 tokens left, which is the refusal working as designed. Both daily
budgets are spent — `gpt-oss-120b` 103%, `gpt-oss-20b` 96%. **There is no reset
to wait for**: the budget refills continuously at ~8,333 tokens/hour per model
(§4.8), so the question is how long, not until when.

| Row | Shape | Status | Tokens | Boots? | Smoke | After the fixes (§4.9) |
|---|---|---|---|---|---|---|
| 1 | simple FastAPI + SQLite CRUD | `done_with_context` | 94,576 | yes | ✅ **5/5 routes** (was 2/5) | — |
| 2 | medium FastAPI + JS frontend | `done_with_context` | 171,914 | **no** | 🚨 app never loads | ✅ **6/6** (§4.10) |
| 3 | complex / multi-entity | `done_with_context` | 131,848 | yes | 🚨 **7/19 routes** | ✅ **19/19** |
| 4 | non-FastAPI (CLI) | ⬜ refused — quota | — | — | — | — |

Every row that ran reached a terminal state with a valid ZIP, so the *first*
half of A2's criterion holds three times over. The **0-5xx half fails**: only
row 1 meets it. Two new mechanical defects explain rows 2 and 3, both now fixed
and covered offline (§4.4, §4.5).

### Row 1 confirms the §4.1 fix's premise

`🔥 Runtime smoke test: 5/5 routes responded without a server error` — the same
prompt that shipped three dead endpoints last session now ships none. Row 1 is
still `done_with_context`, but for a different and much smaller reason: a
generated-test failure, and a `requirements.txt` the audit wrongly called empty
(§4.3).

### Row 3 is the first live run of the request-time repair path ✅

The log shows the whole §4.1 chain firing on a real build for the first time:

```
🩺 Verification found 2 repairable issue(s)
    • 1 file(s) raise at request time: inventory_system_.../backend/routes.py
🔥 [.../backend/routes.py] Repairing a request-time failure
🧠 LLM repairing runtime failure: .../backend/routes.py
```

A 5xx was classified as repairable, blamed on the right file and sent to the
debugger — none of which happened before. **The repair itself then failed**, and
the reason is §4.5: the file was 10,775 characters and the reply cap was 1,600
tokens.

---

## 0.0.1 Ten fixes — and row 3 is now repaired end to end, live

**Seven of the ten are confirmed live** — not by rebuilding, but by cloning
the broken projects the matrix already produced and driving the real debugger
against the real API for ~11K tokens instead of ~300K (§4.9). Row 3 went from
**7/19 routes to 19/19**. Row 2's repair is correctly aimed and still does not
land; §4.10 says exactly why — a missing blame rule. With it added, **row 2
boots too: 6/6 routes.** Between them the two builds that the matrix left broken
are now repaired live for **~14K tokens**, where rebuilding them would have cost
~300K. Two further mistakes the live run exposed are fixed as well (§4.11,
§4.12), neither of which needed quota.

| # | Fix | What it removes | Tests |
|---|---|---|---|
| 1 | `requirements.txt` no longer reads as a stub once filled (§4.3) | A complete file degrading a build to `done_with_context` | §22, 11 assertions |
| 2 | A boot failure is repairable, not advisory (§4.4) | Row 2: the app never loads and **nothing tries to fix it** | §23, 11 assertions |
| 3 | Rewrite budgets sized to the code (§4.5) | A flat cap smaller than the file it must reproduce | §24, 7 assertions |
| 4 | **Repair one block, not the whole file (§4.6)** | Row 3: a 10.7KB repair that could not fit the minute it was sent in | §25-26, 37 assertions |
| 5 | `reasoning_effort` on both models; retries that grow (§4.7) | 13 completions that returned **zero characters** and were billed anyway | §27, 9 assertions |
| 6 | The budget refills, it does not reset (§4.8) | A ledger and a shipped handoff that both overstated the wait by ~14h | §28, 22 assertions |
| 7 | A shared fault is not repaired block by block (§4.9) | Row 3 stuck at 7/19 while a repair edited innocent code | §29, 8 assertions |
| 8 | A bad imported symbol is repaired where it is defined (§4.10) | Row 2's repair aimed at the file that was right — **now 6/6 live** | §23/§30, 8 assertions |
| 9 | Two defects forbidden at generation time (§4.11) | Needing either repair at all | §30, 5 assertions |
| 10 | The driver's report merges and stops overstating (§4.12) | A results file that erased the run before it | §30, 8 assertions |

`test_phase23.py` is **312 / 312** (was 182). Every other suite is unchanged and
green: phase 21 77/77, phase 22 85/85, phase 17 58/58, rate-limit 4/4, frontend
typecheck clean and 191 unit tests.

---

## 0. What changed in the second session

Everything is **committed** on `main`, as eleven commits named `groq api fixes…` (nine of substance, two documentation), newest `f67bf9a`.

| Commit | What it does |
|---|---|
| `groq api fixes` | the first session's six fixes plus the capacity work |
| `…: seed the token ledger from build history` | the ledger no longer under-reports after a restart |
| `…: the SPA fallback must not answer for the API` | unmatched GETs 404 instead of returning the shell with 200 |
| `…: pin test_phase17 to a fixture build` | 58/58 on any database instead of a count that moved with the data |
| `…: make the handoff's quota table readable` | every row names its model; the daily budget is in the table |
| `…: add the A2 live-matrix driver to the repo` | `run_live_matrix.py`, so the matrix survives the session |
| `…: record the files a build produced` | the `files` table was empty for all 58 builds |
| `…: the ZIP download was broken in a browser` | and the live E2E suite could never run at all |
| `…: send request-time failures to the repair passes` | a 5xx the smoke test found was filed as unfixable and never repaired |

**Two defects found live that nothing offline could have caught:**

1. **The ZIP download did nothing in a browser.** `window.open` on
   `/projects/{id}/download` is an HTML navigation, and both the backend's SPA
   middleware and the Vite proxy divert those to the app shell — so the click
   saved 1.5KB of HTML, in dev and in production. Every test to date had called
   the API directly, where it worked.
2. **The live E2E suite could never run.** Its `live` project was declared from
   `process.argv`; Playwright workers re-load the config without the runner's
   argv, so every invocation died with *"Project 'live' not found in the worker
   process"* before starting a build.

Both are fixed, with tests.

---

## 0.1 Where to resume

| # | What | Needs quota |
|---|---|---|
| 1 | **Phase B, starting with B1 (SQLAlchemy + Alembic)** — the only item that can start now | no |
| 2 | Re-run row 3, then row 2, to verify the §4.3-§4.7 fixes on a live build | yes — ~13h of refill for row 3 |
| 3 | Row 4, the one shape never yet built: `run_live_matrix.py --rows 4` | yes |
| 4 | A1 assertion 2 — a clean build reaching `done` with no `SESSION_CONTEXT.md`. §4.3 removes the reason all three rows missed it | falls out of 2-3 |

**Both daily budgets are spent** (120b 103%, 20b 96%), and refilling at ~8,333
tokens/hour each. `run_live_matrix.py --dry-run` reports what is actually
available and costs nothing; item 1 needs no quota at all and is fresh-session
sized.

Phase C stays blocked until the matrix is complete — see §3.6.

---

## 1. State of the tree

Committed on `main`. Working tree clean apart from `frontend-screenshots/`,
which is deliberately untracked.

### Suite status

| Suite | Result |
|---|---|
| `test_phase23.py` | ✅ 182 / 182 (78 → 182; sections 17-21 are new) |
| `test_phase21.py` | ✅ 77 / 77 |
| `test_phase22.py` | ✅ 85 / 85 |
| `test_phase17.py` | ✅ 58 / 58 — now pinned to a fixture, so the count no longer moves |
| `test_groq_rate_limit_handling.py` | ✅ 4 / 4 |
| frontend `typecheck` / `test` | ✅ 191 unit tests, clean |
| frontend E2E default | ✅ 80 tests, `live` excluded |
| frontend E2E **live** | ✅ **4 / 4 — executed against a live backend for the first time** |

---

## 2. What was fixed (the first session's six, each red-first)

| # | Fix | Symptom it removes |
|---|---|---|
| 1 | Package-relative import check (`code_executor.py`) | Debugger rewriting correct package code to satisfy a check that could not validate `from .models import X` |
| 2 | CLI token reporting (`main.py`) | CLI builds measured their token cost and discarded it at exit |
| 3 | Truncation retry (`llm_client.py`) | `finish_reason="length"` was never read; half-written files returned as complete code |
| 4 | Repair-shrinkage guard (`debugger.py`) | A "repair" deleting the file it repaired — an empty module imports perfectly |
| 5 | Quota error type (`llm_client.py`) | Quota already exhausted at build start → `failed`, NULL reason, no handoff doc, HTTP 400 download |
| 6 | Entry point exempt from cap (`architect.py`) | The deployability cap deleting `main.py`, shipping apps with no `app = FastAPI()` |

**Fix 6 is now confirmed end to end** — see §3.1.

### Capacity work (the follow-on)

| Change | Effect |
|---|---|
| Per-model daily token ledger, rolling 24h, in `/health` + `get_quota_snapshot()` | The 200K/day limit is reported by Groq **only** inside the 429 that enforces it; now it can be seen beforehand |
| **Ledger seeding from build history** (second session) | The ledger counted only calls it watched, so a restart made earlier spend invisible: it read `gpt-oss-20b` at 3.6% while Groq said 99.9%. It now rebuilds from `projects` rows — recovering 105,121 tokens on the first boot, moving `120b` from 39% to 65% |
| Per-model split stored per build (`tokens_by_model`) | Seeding is exact rather than an even-split estimate; older rows are split evenly and reported as estimates |
| Codegen agents moved to `gpt-oss-120b` | Unlocks the second, separate 200K/day budget **and** uses the stronger model |
| Codegen caps 950 → 2000 | 950 is the budget that truncated live; caps are not spend |
| Debugger prompt bounded | 44% of calls, previously with no cap of any kind |
| Fast→heavy quota fallback | A build survives one model running out — verified live |

---

## 3. Live validation results

### 3.1 — Fix 6 produces a booting app ✅ **confirmed**

Build `3d57d0b8`, a simple FastAPI + SQLite CRUD prompt, on the fixed code:

```
🔥 Runtime smoke test: 2/5 routes responded without a server error
```

Not `ℹ️ skipped (no FastAPI entry point)` and not `🚨 App failed to boot`. The
generated `backend/main.py` defines `app = FastAPI()` and survived alongside
`models.py`, `routes.py` and `crud.py` — the exact architecture that used to
lose its entry point. **Fix 6 is verified.**

### 3.2 — A2 matrix: row 1 only, and it does not pass the criterion

> **Superseded by §0.0.** Rows 1-3 have since run on the fixed code; row 1 now
> reports 5/5. The table below is the second session's result, kept because it
> is the baseline §0.0's numbers are measured against.

| Row | Shape | Status |
|---|---|---|
| 1 | simple FastAPI + SQLite CRUD | ⚠️ `done_with_context`, valid ZIP, **but 3 of 5 routes return 500** |
| 2 | medium FastAPI + JS frontend | ⬜ never run — quota |
| 3 | complex / multi-entity | ⬜ never run — quota |
| 4 | non-FastAPI (CLI/Streamlit) | ⬜ never run — quota |

A2's criterion demands **0 5xx** from any build that boots, so row 1 fails it.
The cause is diagnosed, reproduced and specific (§4.1). The driver now lives in
the repo: `venv/Scripts/python.exe run_live_matrix.py --rows 2,3,4`.

### 3.3 — A1 assertion 2: still never observed

That a **clean** build reaches `done` and writes **no** `SESSION_CONTEXT.md`.
Row 1 was `done_with_context`, because of the 500s. Still open.

### 3.4 — The post-fix baseline, measured ✅

| | Before the fixes (`c95501b4`) | After (`3d57d0b8`) |
|---|---|---|
| Total tokens | 98,490 | **82,835** |
| LLM calls | 41 | **29** |
| **Debugger calls** | **18** | **3** |
| Wall time | 810s | 735s |

The Debugger dropping from 18 calls to 3 is the truncation→gutting cascade
disappearing, which is exactly what Fixes 3 and 4 predicted. Split by model:
`{"openai/gpt-oss-20b": 56487, "openai/gpt-oss-120b": 26348}` — read straight
out of the new `tokens_by_model` column.

### 3.5 — The live E2E suite ✅ **all four pass**

After fixing the gating bug that stopped it running at all:

- WebSocket step transitions reach `StepTracker`, with the pill on `Live`, not
  the 5s poll fallback.
- Cancel yields `cancelled` and never claims the build completed.
- The ZIP downloads through the UI and is a valid archive — **after** fixing the
  navigation bug it exposed.
- With the quota simulation on, the handoff banner renders and the download
  stays enabled.

The cancel tests cost 500-1,500 tokens each; the suite is cheap to re-run.

### 3.6 — Risk 1 (architect variance vs. missing precedent)

Unchanged: still two builds' worth of evidence, and row 1's failure is again a
mechanical defect rather than variance. **Complete the matrix before Phase C.**

---

## 4. Known issues

### 4.1 — Request-time failures now reach the repair passes ✅ **fixed and confirmed live** (row 3, §0.0)

Row 1's 500s were an ordinary bug: `routes.py` re-declared the `get_db`
dependency and yielded the result of *calling* crud's generator function, so
every handler received a generator where it expected a connection.

```
AttributeError: 'generator' object has no attribute 'execute'
  (at backend/routes.py:53 in list_tasks_endpoint -> backend/crud.py:68 in get_tasks)
```

What made it worth fixing was not the bug but everything that missed it: the
import check passed, the generated unit tests passed (they call `crud` directly,
never through the dependency), the reviewer scored it 6.0, and the one stage
that caught it — the runtime smoke test — filed its finding as advisory, "issues
the repair passes cannot fix". So remediation reported *"no files were repaired
this pass"* about a build with three dead endpoints.

Now:

- the probe records every project frame in call order (excluding itself, or it
  is the outermost frame and gets blamed for everything);
- a 5xx whose traceback names a generated file becomes a **repairable** issue,
  targeted at the outermost project frame — the handler, not the helper it blew
  up in;
- the debugger repairs files that import cleanly but fail on a request, and
  rolls the repair back if it breaks the import check;
- the app is re-run after each repair pass, which costs no tokens and is the
  only thing that can confirm a request-time fix;
- `prompts/backend_developer.txt` forbids the exact shape that was generated.

The repair-shrinkage guard needed one distinction to allow the correct fix:
a name a file **defines** versus one it **re-exports**. Deleting a duplicated
local `get_db` and importing the real one is right, and the guard read it as
deleting `get_db`.

**Confirmed live on 2026-08-28.** Row 3 classified a 5xx as repairable, blamed
the right file and sent it to the debugger — the whole chain, on a real build.
The repair itself did not land, for a reason that had nothing to do with this
mechanism: the file was 10,775 characters and the reply cap was 1,600 tokens.
See §4.5. Row 1, re-run on the same code, went from 2/5 routes to **5/5**.

### 4.3 — A filled-in `requirements.txt` read as an empty scaffold ✅ *fixed, unverified live*

The architect scaffolds `requirements.txt` with a comment block ending in
`will be generated by the code generation agents`. `tools/requirements_builder.py`
then appends the real packages **below** that comment and leaves it in place, so
`pipeline._audit_placeholders` — which looks for exactly that marker — reported a
complete file as never filled in. Rows 1, 2 and 3 were all degraded by it.

The builder now strips the placeholder block whenever it writes real packages,
and leaves it alone when it writes nothing, so a genuinely empty scaffold is
still reported. While in there: a FastAPI app that nothing starts with
`uvicorn.run` never imports uvicorn, so the import scan never added it and the
shipped `requirements.txt` could not serve the app SETUP.md tells you to run.
`_implied_packages()` adds it.

### 4.4 — An app that never boots must reach the repair passes ✅ *fixed, unverified live*

Row 2's `routes.py` used a plain class as a `response_model`:

```
FastAPIError: Invalid args for response field! Hint: check that
typing.List[services.BookmarkOut] is a valid Pydantic field type.
```

FastAPI raises that while the module is imported, so the app never loaded and
not one endpoint existed. The pipeline filed it under *"issues the repair passes
cannot fix"* — while in the same build a single broken route, strictly less
damage, was repaired. §4.1 routed request-time 5xx into repair and stopped there;
a total boot failure still fell through, because the probe reported only the
exception's type and message with no frames to aim a repair at.

Now the probe describes an import-time exception with the same frame chain it
already gave a 500, and `SmokeResult.blame_file` names the file to repair.

**The two failures need opposite blame rules, and both are asserted:**

| Failure | Blame | Why |
|---|---|---|
| 500 at request time | **outermost** project frame | The caller handed a helper the wrong thing; repairing the helper teaches it to accept bad input |
| Import-time boot failure | **innermost** project frame | The outermost frame is `main.py` doing nothing but `from routes import router`; the module that raised is the one to fix |

One trap found on the way: `traceback` yields pseudo-frames like
`<frozen importlib._bootstrap_external>`, which have no directory, so
`abspath()` resolved them *inside the project* and they passed the "is this a
project file" test. Three of them sat between `main.py` and the module that
actually raised, and the chain is capped at four frames, so the real frame was
pushed out of the report. Frames whose filename starts with `<` are now skipped.

### 4.5 — A full-file rewrite could not be longer than its cap ✅ *fixed, unverified live*

Every repair prompt in `agents/debugger.py` ends *"Return ONLY the complete
fixed Python code"*, and all four sent that request under the Debugger's flat
1,600-token cap. Row 3's `routes.py` is 10,775 characters — roughly 3,300 tokens
of output. What happened is exactly what the arithmetic predicts:

```
✂️  hit its output budget (finish_reason=length, 5302 chars).
    Retrying with max_tokens 1600 → 3200 (attempt 1/2)
Rejecting LLM fix for .../backend/routes.py: it removes top-level startup
    — a repair must not delete the definitions other modules import.
⚠️  Runtime repair rejected or empty
```

Fix 3's truncation retry doubled the cap once, 3,200 tokens still did not fit
the file, the abridged reply lost a top-level name, and Fix 4's shrinkage guard
correctly rejected it. Both guards did their job; the build still shipped with
twelve endpoints returning 500, because the request that was sent could not have
succeeded.

`_rewrite_budget()` now sizes the cap from the text it must reproduce —
`len(code)/3 + 400`, floored at the agent's own budget.

> **Superseded in part by §4.6.** The 8,000-token ceiling this originally carried
> has been removed: Groq's real limit is 8,000 tokens *per minute* covering
> prompt and completion together, `llm_client` already clamps to it, and a second
> ceiling here could only be wrong. Sizing the budget alone also does not rescue
> row 3 — the request was clamped back to where it started. §4.6 is the fix that
> actually lands.

> The four call sites are asserted by count in §24, so a fifth rewrite prompt
> added without a sized budget fails the suite rather than quietly reintroducing
> this.

### 4.6 — A repair could not be larger than the window it was sent in ✅ *fixed, unverified live*

Row 3's repair was rejected for deleting `startup`, and the first diagnosis —
that the Debugger's flat 1,600-token cap was too small for a 10,775-character
file — was only half of it. Sizing the cap to the file does not help, because
**the cap was never the binding constraint.**

Groq allows **8,000 tokens per minute on this tier, covering prompt AND
completion together.** `llm_client._fit_output_budget_to_model_limit` already
discovers that from the `x-ratelimit-limit-tokens` header and clamps every
request to `limit − prompt − 800`; the matrix log shows it working:

```
✂️  Reducing [gpt-oss-20b] max_tokens from 6400 to 5459
    to fit the known Groq TPM limit (8000).
```

Row 3's arithmetic: the file costs ~2,700 prompt tokens, plus map, error and
rules ≈ 3,500. That leaves ~3,700 for the reply — so a request for 3,991 is
clamped straight back to where it started. **A full-file rewrite pays for the
file twice, which makes it impossible above roughly 11KB, and row 3's file is
10.7KB.** No cap value fixes that.

So the repair stopped asking for the whole file.

| | Before | After |
|---|---|---|
| Prompt | the entire 10,776-char file | **2,351 chars** — one block plus a digest |
| Reply | the entire file again | the block, ~400 chars |
| Budget | 3,992 tokens, clamped to ~3,700 | 1,600, comfortably inside the window |
| Names that must survive re-typing | all 22 | **none** |

`tools/code_patcher.py` (new) locates the top-level block a traceback frame
points at and splices a replacement back, refusing anything that does not parse.
The anchor was already there and unused: `runtime_smoke._parse_frames` reports
`backend/routes.py:53 in list_tasks_endpoint`.

Three details that decide whether this works:

1. **The block starts at the decorator, not at `def`.** Row 2's bug was *in* the
   decorator, and splicing below it would duplicate whatever came back.
2. **A `<module>` frame still resolves.** Row 2 failed at import time, so its
   frame names no function; the line lands inside the enclosing block anyway.
3. **The frame chain is a suffix, and the old trim cut from the head.**
   `probe.error[:400]` would silently delete the anchor on any long message,
   downgrading every such repair to a whole-file rewrite.
   `Pipeline._trim_keeping_frames` keeps both ends.

It declines in three cases, each falling back to the untouched full-file path:
a file under 2,000 characters (the block prompt's own scaffolding costs more
than the body it saves — measured at 1,414 vs 1,356 chars on a 322-char file), a
block that is more than 60% of its file, and any reply that does not splice.

### 4.7 — Paying full price for reasoning that returned nothing ✅ *fixed, measured live*

The 2026-08-28 matrix logged **thirteen completions with `finish_reason=length`
and zero characters of content** — Debugger 5, Reviewer 4, Tester 2. The entire
budget went on hidden reasoning, nothing came back, and each was then retried at
double the budget and billed again.

The cause was a stale exclusion. `gpt-oss-20b` used to reject `reasoning_effort`
with HTTP 400, so it was excluded and given a 1,600-token floor instead. **Groq
has since fixed it.** Re-measured on 2026-08-28, same prompt, same 600-token cap:

| | reasoning | content | completion tokens |
|---|---|---|---|
| no effort param | 1,614 chars | 254 chars | 442 |
| `reasoning_effort=low` | 578 chars | **582 chars** | **276** |

Twice the code for 38% fewer tokens. `_REASONING_EFFORT_SUPPORTED` now includes
both models.

**And the retry that resent an identical request.** The Reviewer asks for 600
tokens; `_apply_reasoning_budget` floors a non-effort reasoning model at 1,600.
The truncation retry doubled the *requested* 600 → 1,200 — which the floor
raised to 1,600 again. A byte-identical call, billed in full, twice in one build:

```
hit its output budget (finish_reason=length, 0 chars). Retrying 600 → 1200 (1/2)
hit its output budget (finish_reason=length, 0 chars). Retrying 1200 → 2400 (2/2)
still truncating after 2 budget increases (max_tokens=2400)
```

It now doubles the **effective** cap, so every retry is strictly larger than the
call that failed. A zero-content completion is also logged as its own failure
rather than hiding inside the truncation warning — it is not truncated code, it
is no code at all.

> **`ModelRateState.limit_tokens` is now seeded** from `GROQ_TPM_LIMIT_DEFAULT`
> (8000, env-overridable) instead of starting at `None`. An unknown ceiling is
> not the same as no ceiling, and treating it as none let the first call of every
> process skip the fit entirely.

### 4.8 — The daily budget refills; it does not reset ✅ *fixed, measured live*

Chasing *when* §4.3-§4.7 could be verified turned this up, and it was worth more
than the answer to the original question.

Groq's TPD is a **leaky bucket**. Its own 429s carry the arithmetic, and both
reproduce to within a second at `GROQ_DAILY_TOKEN_LIMIT / 86400`:

| Groq's 429 | short by | Groq said | `short ÷ 2.315` |
|---|---|---|---|
| used 197,225, requested 2,885 | 110 | `47.52s` | **47.5s** |
| used 196,757, requested 4,131 | 888 | `6m23.616s` | **6m23s** |

**≈ 2.315 tokens/second, ≈ 8,333 per hour, per model.** Two things followed from
believing in a midnight reset instead:

1. **We shipped the false claim to users.** "Groq free-tier daily quotas reset at
   00:00 UTC" went into the `SESSION_CONTEXT.md` of every quota-interrupted
   build, sending people away for a day when the wait was a few hours.
2. **The ledger blocked us longer than Groq did.** Summing a rolling 24h window
   only returns budget as individual calls age out, so after this matrix it read
   0 remaining until 06:08 the next morning — while Groq would have accepted a
   70K build from ~16:25 the same afternoon. `run_live_matrix.py` refuses below
   70,000, so it would have idled ~14 hours for nothing.

`get_daily_usage` now drains a running total in call order. Reading it back on
the real ledger immediately recovered **12,791 tokens on 120b** (reported as 0)
and **26,395 on 20b** (7,749).

> Decaying each entry independently would look similar and be wrong: it refunds
> the same elapsed seconds once per entry, so a build of 40 calls would appear to
> repay itself 40 times over. §28 asserts that specifically.

`used` is rounded and `remaining` floored — both err towards reporting less
budget than there is. Truncating `used` lost a token to sub-second decay between
two calls in one build, which is the one direction this number must not move.

### 4.9 — Live verification without rebuilding: rows 3 and 2 both repaired ✅ **confirmed live**

A matrix row costs 95-172K tokens. The two repair paths can be exercised on the
same two failures for a couple of thousand, by cloning the broken project the
matrix already produced and driving the real debugger against the real API. The
whole verification below cost **~11K tokens**; the equivalent two rebuilds would
have cost ~300K and taken 45 minutes.

| Row | Was | Now | Cost | Fixed by |
|---|---|---|---|---|
| 3 | 7/19 routes | ✅ **19/19** | 6,539 tokens, 6s | the shared-cause guard below |
| 2 | app never loads | ✅ **6/6** | 2,640 tokens, 3s | the fourth blame rule (§4.10) |

**The chain that has been broken since Phase 22 now completes end to end, on
both builds.**

The first attempt did not fix it, and why is the finding. All twelve 500s were
`OperationalError: no such table`. The traceback blamed a different handler each
time, and every one of them was innocent — the generated `routes.py` registers
its schema creation on:

```python
@router.on_event("startup")
def startup():
    conn = sqlite3.connect(DB_PATH); init_db(conn); conn.close()
```

**Router-level startup events do not fire for an included router.** `init_db()`
never ran, no tables existed, and every read endpoint 500d. The block repair
aimed at `list_suppliers`, was *applied*, and fixed nothing — worse than
nothing, because it edited working code.

So a fault shared by many endpoints is not a block-level bug, and §29 encodes
the test: **more than one endpoint, one exception type, more than one distinct
blamed function** → the cause is somewhere no failure names, and only the
whole-file prompt can see it. The last clause is what separates a shared cause
from one handler probed twice.

The rule generalises backwards: row 1's three endpoints all raised
`AttributeError: 'generator' object has no attribute 'execute'` from a
duplicated `get_db`, and it would have aimed that repair correctly too.

With the guard, the repair added table creation at import, kept all 31 top-level
names, survived the shrinkage guard and the import check, and every route
answered.

> **One caveat, recorded rather than fixed.** The model's fix opens a database
> connection at module level, which the debugger's own prompt rules forbid
> ("No module-level DB connections"). It works and preserves everything, but the
> better fix is an app-level lifespan handler. The rule and the repair disagree.

### 4.10 — Row 2's repair is aimed at the wrong file ✅ **fixed and confirmed live**

The boot-failure plumbing of §4.4 is confirmed live: the smoke test reports the
failure, it is classified repairable, and the repair is aimed at
`backend/routes.py`. **The repair itself does not land, on either model.**

The reason is not the model. `routes.py` does:

```python
from services import BookmarkOut          # a PLAIN class, defined in services.py
@router.get("/bookmarks/", response_model=List[BookmarkOut])
```

FastAPI raises at import because `BookmarkOut` is not a Pydantic model. **The fix
belongs in `services.py`** — and the repair is aimed at `routes.py`, whose prompt
says in as many words:

> The bug is in THIS file. The traceback may end in another module because this
> file passed it the wrong value — fix the call here, do not make the other
> module tolerate it.

That instruction is right for the failure it was written for (§4.1, a handler
mis-calling a helper) and wrong here, where the type is simply defined wrongly
somewhere else. The model is being told not to do the only thing that works.

Both models were tried. `gpt-oss-20b` returned a gutted file — every handler
replaced with `return []` or a 404, and the broken `response_model` left in
place. `gpt-oss-120b` returned something that failed the import check. Both were
correctly rejected and rolled back, so the guards are doing their job.

**Fixed** in `Pipeline._redirect_blame_to_definition`: when the blamed file
merely *imports* a name the error complains about, and that name resolves to
another generated module, the repair is aimed at the module that defines it.
Confirmed against row 2's own project — the repair now targets
`backend/services.py` instead of `backend/routes.py`.

It fires narrowly on purpose. A genuine in-file bug keeps the frame-based rule,
and a complaint naming `List` or `BaseModel` never chases a repair out into
`typing` or `pydantic`, because only modules that exist as generated files
qualify.

That completes the set. Which rule applies is decided by the shape of the
failure, and all four are now asserted:

| Failure | Repair belongs in | Why |
|---|---|---|
| 500 at request time, one endpoint | the outermost project frame | the caller handed a helper the wrong thing |
| Import-time boot failure | the innermost project frame | the outermost is `main.py` doing nothing but importing |
| Many endpoints, one exception type (§4.9) | **no frame — the whole file** | the cause is code that never ran |
| A bad symbol imported from elsewhere | **the file that defines it** | the file that raised is not the file that is wrong |

**Row 2 now boots: `app failed to load` → 6/6 routes, 2,640 tokens, 3 seconds.**
Given the right target the model did the obvious thing:

```python
-class BookmarkOut:                        +class BookmarkOut(BaseModel):
-    def __init__(self, id, url, ...):     +    id: int
-        self.id = id                      +    url: str
                                           +    tags: List[str]
```

All nine top-level names in `services.py` survived. Nothing about the model
changed between this attempt and the two that failed — only where the repair was
pointed.

> **This is also §4.6's first landed repair.** `services.py` is 4,234 characters,
> over the 2,000 threshold, so the block-level path handled it: it replaced the
> `BookmarkOut` class and nothing else. The mechanism is no longer just proven to
> aim correctly — it is proven to fix a build.

### 4.11 — Two defects are now forbidden at generation time ✅ *fixed, unverified live*

Repairing a defect costs an LLM call and can fail. Not generating it costs
nothing, and both of the matrix's structural failures were preventable.

`prompts/backend_developer.txt` gained two rules, in the style of the existing
`get_db` rule that came out of row 1:

- **STARTUP RULE.** `@router.on_event("startup")` does not fire for a router
  included with `app.include_router(...)`, which is why row 3 shipped twelve
  endpoints returning `no such table` alongside a perfectly good `init_db()`
  that nothing ever called. The prompt shows the `lifespan` handler instead —
  and says not to create tables at module level either, which is precisely what
  the winning repair did (§4.9's caveat, now covered by the rule that would have
  prevented needing the repair at all).
- **RESPONSE MODEL RULE.** Anything named in `response_model=` must subclass
  `BaseModel`. A plain class raises `FastAPIError` during import and takes the
  whole app down — not one endpoint, all of them. That is row 2.

Both rules name the failure they prevent, so neither reads as arbitrary.

### 4.12 — The matrix driver overwrote its own results ✅ *fixed*

Listed as a trap twice and better fixed than documented. `--rows 1` followed by
`--rows 2,3` left a report describing rows 2 and 3 with no trace of row 1, which
is exactly what happened on 2026-08-28. Rows are now carried forward from the
previous report, labelled *(earlier run)* so nothing is passed off as fresh, and
a row that is re-run wins over the record of it.

Its headline also read `N of N rows pass` while counting only status and ZIP.
Row 3 was counted as passing while shipping twelve dead endpoints. It now says
what it measured — *reach a terminal state with a valid ZIP* — and points at the
half that lives in the server log.

### 4.2 — Still open

- **The ledger cannot see other processes.** It is per-checkout: two processes
  sharing the file each rewrite it whole, so a concurrent write can drop the
  other's newest entries. Seeding no longer writes when nothing changed, which
  removes the common case, but the race remains.
- **8 keys do not multiply the daily quota.** All rotate inside
  `org_01kjhb2kvxft0s58tg3tz9mg0p` and share one 200K pool per model.
- **`file_count` was 0 for every build until now.** Fixed, and the 35 builds
  that still have their output directory were backfilled (944 files) — but any
  build whose directory was deleted stays at 0, permanently.

### 4.3 — Closed since the last handoff

- ~~The ledger starts cold~~ → seeded from build history at boot.
- ~~`test_phase17.py`'s assertion count is data-dependent~~ → pinned to a fixture.
- ~~The SPA catch-all returns 200 + HTML for any unmatched GET~~ → 404 unless the
  client asked for HTML. `/` now serves the landing page to a browser and the
  info JSON to everything else; it used to return JSON to both, leaving the
  built SPA with no reachable entry point at the origin root.
- ~~The handoff document's key table reads as a contradiction~~ → every row names
  its model, and the daily budget is in the table.

---

## 5. Things that will bite you

1. **The `curl` model-liveness check in `PHASE23_PLAN.md` A0.1 does not work.**
   Every key returns HTTP 403 / Cloudflare `error code: 1010` — a client
   fingerprint block that looks exactly like "all keys are dead". Use the SDK:
   ```python
   from groq import Groq
   sorted(m.id for m in Groq(api_key=key).models.list().data if 'gpt-oss' in m.id)
   ```
2. **The real database is `generated_projects/platform.db`.** The `platform.db` in
   the repo root is a stale, corrupt file from April and will not open.
3. **CLI builds (`main.py`) persist nothing** — no DB row, so no `/downloads`,
   no status. Use `POST /projects/` when you need the run recorded.
4. **Restart the server after editing `llm_client.py` or the agents.** It runs with
   `--no-reload` (deliberately — reload watches `generated_projects/` and kills
   builds mid-flight), so changes do not take effect until restart.
5. **Run tests with the venv.** System Python lacks `rich`.
6. **The download route is `GET /projects/{id}/download`.** There is no
   `/downloads/{id}`. A wrong path used to answer 200 with the SPA shell; it now
   404s for anything that did not ask for HTML, but check the `PK` magic
   rather than the status code anyway — `run_live_matrix.py` does.
7. ~~`run_live_matrix.py` overwrites its results file~~ — **fixed, §4.12.** It
   merges now, and its headline no longer implies the smoke test was checked.
   The smoke-test line is still only in the server log.
8. **The server holds the code it started with.** Every fix in §4.3-4.5 was made
   while a build was running, so the process that produced rows 2 and 3 never
   had them. Restart before reading anything into a re-run.
9. **The live E2E suite spends real quota**, so it is opt-in:
   `cd frontend && npm run test:e2e:live` with the backend already running. Test
   4 additionally needs `LIVE_QUOTA_SIM=1` on the runner and the backend started
   with `GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS=6` — and **restart the backend
   without that variable afterwards**, or every later build hands itself a
   simulated quota wall.
