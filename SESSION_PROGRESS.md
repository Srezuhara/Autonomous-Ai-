# Session Progress — start here

**Last session: 2026-08-30 (Phase 23 — row 3 rebuilt a third time, row 4 run for
the first time, and the smoke test's write coverage found to be fictional).**
Committed on `main`, `55d9121`. `test_phase23.py` is **400/400**, up from 394.

> **Backend/pipeline work has its own state doc: `PHASE23_HANDOFF.md`.** Read it
> first if you are touching `llm_client.py`, the agents, the pipeline or the
> platform API — §4.x there is the per-defect detail this file summarises. This
> file remains the frontend and general entry point.

**The headline: `16/16` was not true, and no build score before today was.**
The runtime smoke test sent `json={}` to every POST and PUT, so validation
rejected the body with 422 *before the handler was entered* — and 422 counts as
"responded without a server error". **Every write endpoint in every build ever
run was scored green without executing a line of itself.** Row 3 was reported
16/16 while four routes raised `AttributeError` on every call. Fixed in
`55d9121` (§0.6); the same project now scores 12/16 and names all four.

**The second finding is the one to act on next.** Given those four failures and
the file they are in, the debugger **cannot repair them, and makes the code
worse trying** — it rewrote `prod.sku` as `data.get("sku")` in one of the four
handlers, turning a loud AttributeError into a silent `None` bound into a
`NOT NULL UNIQUE` column. §0.7 has the diagnosis: the repair is shown
`routes.py` and never `schemas.py`, so it cannot know whether to rename the read
or add the field, and silencing is the only move left to it.

**Row 4 (CLI) ran for the first time and behaved.** The smoke test skipped
cleanly (`no FastAPI entry point`), no scaffold placeholder survived, no phantom
parse defects. `done_with_context`, 882s, 105,999 tokens.

**Where things stand.** Row 3 was rebuilt twice. The first rebuild was aborted
deliberately once its log showed the pipeline burning one LLM call per generated
file on a defect that did not exist; the second completed. Between them, eight
fixes (§4.13-§4.21).

**The headline number: a row now costs half what it did.**

| | run 2 (old code) | run 3 (fixed) |
|---|---|---|
| tokens | 186,413 | **87,551** (−53%) |
| duration | 1694s | **729s** (−57%) |

**The headline finding is more important than the number.** Of the seven
verification failures traced end to end this session, **six were defects in the
pipeline's own checking, not in the code it generated.** The smoke test never
ran the app's lifespan; the import check could not see half the imports in a
file; a folder was made into a package that hid the real one; a test could not
import the app the way a user would write it; an audit reported on a step that
had not run yet. **The generated code has been better than the build reports
said it was.** Treat a red verification result as a hypothesis about the
pipeline first, and about the model second — that is now the cheaper bet.

**Earlier frontend work is unchanged and committed:** the landing restructure
(`FRONTEND_LANDING_PLAN.md`, fully executed — see §2.7/§2.8) and everything in
`FRONTEND_COMPLETION_PLAN.md`. Do not re-run either plan.

---

## 0. Next session — pick up here

**Restart the server before anything.** It runs `--no-reload` deliberately, so a
running process holds the code it started with — and the session of 2026-08-30
ended with a server still holding the *pre-fix* smoke probe. A row started
against it would score write endpoints green again.

```bash
venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1
venv/Scripts/python.exe run_live_matrix.py --dry-run
```

**Quota at the close of 2026-08-30 (13:45 IST):**

| Model | Left | Note |
|---|---|---|
| `openai/gpt-oss-120b` | ~129,500 | comfortable |
| `openai/gpt-oss-20b` | ~43,900 | **the bottleneck** — ~3.2h to the 70,000 gate |

**The token split has inverted, and planning must follow it.** The fast model
used to be the cheap one; it is now the one that runs out. Row 3 on 2026-08-29
spent 22K on 20b and 65K on 120b. The same row on 2026-08-30 spent **97.5K on
20b** and 38.5K on 120b, because the tester, the reviewer and every remediation
pass run on the fast model — and remediation is where the tokens now go.

`MIN_TOKENS_TO_START` gates on the *best* model (`run_live_matrix.py:183`), so
the driver will happily start a row the fast model cannot finish. **Check 20b by
hand before starting one.** From ~41,000 it needs ~3.5h to reach the 70,000 gate
and ~7h to be comfortable for a row.

### The order to work in

| # | Work | Quota | Why this order |
|---|---|---|---|
| 1 | ~~The repair that cannot repair~~ | **done** (`4e5f2de`) | §0.7. What remains is the deterministic checker it points to: compare attribute reads against the Pydantic model's fields, zero tokens, in the shape of `sql_schema_check` |
| 2 | **Row 2** | ~90-170K | Its three causes are fixed; needs 20b at 70K+. Never yet run against the fixed probe |
| 3 | **Row 3 or row 1 again** | ~90-140K | Row 3's real score is knowable for the first time |
| 4 | **Phase B1** | none | Start any time quota is short — see below |

### 1. What rows 3 and 4 proved on 2026-08-30

Eight of the nine assertions from the previous session held, and every one is
now *observed in a complete build* rather than inferred:

| Expect | Result |
|---|---|
| `grep -c "does not parse" server.log` → 0 | ✅ 0, both rows |
| smoke well above 7/19 | ✅ 16/16 reported — but see §0.6, it was really 12/16 |
| no `scaffold placeholder: README.md` | ✅ none, both rows |
| no `imports … inside a try/except that swallows` | ✅ none |
| no `alembic/env.py` in the failing list | ✅ — and the architect emitted **no `alembic/__init__.py`**, so §4.21's shadowing is fixed at the source |
| no `No module named 'main'` from a test | ✅ 0 |
| `🗄️ SQL schema check` fires or stays silent | ✅ silent — correct for the ORM shape row 3 produced |
| `🧬 pydantic V2 compat` silent, 0 `orm_mode` | ✅ |
| status `done`, not `done_with_context` | ❌ **still never observed, on any row, ever** |

Row 4 additionally proved the non-FastAPI path: `Runtime smoke test skipped (no
FastAPI entry point)` — a clean skip, not a false failure. `done_with_context`,
882s, 105,999 tokens, 2 unresolved issues (both ordinary test failures).

### 2. Row 3 cost 56% more than the run before it, and why

| | run 3 (2026-08-29) | run 4 (2026-08-30) |
|---|---|---|
| tokens | 87,551 | **136,043** |
| duration | 729s | **1142s** |
| first smoke | — | **0/16** |
| remediation passes | 0 | **2** |

`main.py`'s lifespan created the SQLite *file* and never the *tables* — it
assumed `alembic upgrade head`, which nothing runs. All 16 routes answered
`OperationalError`, and two full remediation passes were spent getting back to a
working app. **The architect chose the alembic shape and then nothing ran a
migration.** Either the lifespan must create tables regardless, or the build must
run the migration; today it does neither and the debugger pays for it. This is
the largest cheap saving available.

Note what the debugger's fix was: it rewrote `routes.py` onto raw `sqlite3` with
its own `CREATE TABLE IF NOT EXISTS`, so the shipped project declares its schema
**twice** — in `models.py` (SQLAlchemy + alembic) and again in `routes.py`. It
works, and it is exactly the drift §4.18 exists to catch.

### 3. Phase B1 — the no-quota track

Fully specified in `PHASE23_PLAN.md`. Auth needs migrations first, which is why
it is B1 and not B2. The load-bearing constraint: **keep
`api_platform/database.py`'s function signatures as the seam** — `get_project`,
`list_projects`, `update_project`, `add_build_step` are called from `runner.py`,
all five route modules and the tests, so reimplementing their bodies over
SQLAlchemy means zero call-site changes. Alembic's first revision must be
**stamped** against the existing DB so the live builds survive.

Note the irony worth remembering while doing it: §4.21 exists because a generated
project's `alembic/` folder was made into a package that shadowed the real
alembic. Do not repeat that in `api_platform/`.

---

## 0.1 The fixes, and which are proven

`test_phase23.py` sections 22-30 cover all of them offline. "Live" means it ran
against the real API on a real project, not that a full build was rebuilt.

| § | Fix | Live? | Evidence |
|---|---|---|---|
| 4.3 | `requirements.txt` no longer reads as a stub once filled; uvicorn added | ✅ | **confirmed on the 2026-08-29 build** — no marker, uvicorn added |
| 4.4 | A boot failure is repairable, not advisory | ✅ | row 2 aimed and repaired |
| 4.5 | Rewrite budgets sized to the code, no ceiling of their own | ✅ | the clamp fired live, 3992 → 3462 |
| 4.6 | Repair the failing block, not the whole file | ✅ | **fixed row 2** — replaced one class in a 4,234-char file |
| 4.7 | `reasoning_effort` on both models; retries that actually grow | ✅ | measured: 2× the code for 38% fewer tokens |
| 4.8 | The daily budget refills; it does not reset | ✅ | matches Groq's own 429 arithmetic to the second |
| 4.9 | A fault shared by many endpoints is not a block-level bug | ✅ | **fixed row 3** — 7/19 → 19/19 |
| 4.10 | A bad imported symbol is repaired where it is defined | ✅ | **fixed row 2** — dead app → 6/6 |
| 4.11 | The startup hook and non-Pydantic `response_model` are forbidden | ✅ | **confirmed on the 2026-08-29 build** — no `on_event`, lifespan used, every `response_model` a BaseModel |
| 4.12 | The driver's report merges and stops overstating | ✅ᵒ | deterministic, covered offline |
| 4.13 | A project-relative path resolves; unreadable ≠ unparseable | ✅ | **8 wasted calls per build → 0**, measured across two runs |
| 4.14 | `requirements.txt` is registered as a file that was written | ✅ᵒ | the false "never generated" todo is gone |
| 4.15 | A stdlib-only project can clear the scaffold marker | ✅ᵒ | row 4's shape; would have degraded it |
| 4.16 | Pydantic V1 config keys V2 ignores are renamed | ✅ | 6 `orm_mode` → `from_attributes` on the live project |
| 4.17 | The smoke test runs the app's lifespan | ✅ | **7/19 → 14/19** on the live project, nothing else changed |
| 4.18 | SQL that reads a column the schema lacks is caught | ✅ | found exactly the 2 real mismatches; **→ 19/19** |
| 4.19 | An audit no longer reports on a step that has not run yet | ✅ᵒ | README was 46 lines when it was called unfilled |
| 4.20 | An import hidden in a module-level try/except is seen | ✅ | "all clean" → **6 defects** on the file that shipped 0 routes |
| 4.21 | Three false verification failures: package shadowing, framework scripts, test sys.path | ✅ | `alembic/env.py` and `test_stock.py` both cleared |
| 4.22 | A write endpoint is probed with a body its model accepts, so the handler actually runs | ✅ | **16/16 → 12/16 on the shipped project**, naming 4 real defects; `POST /warehouses/` answers 201 |

### §4.13 — the one that was costing the most

`written` and `result.backend_files` hold **OUTPUT_DIR-relative** paths, because
that is what `create_file()` takes. `analyze_file()` used a bare `open()`, which
honours **cwd**. Same string, two resolution rules — so every relative caller
missed the file, and because `analyze_file` caught `FileNotFoundError` into
`parse_error`, a file that was *not found* was reported as a file that *does not
parse*.

`_verify_and_repair` then spent **one LLM call per generated Python file** asking
a model to fix a syntax error that did not exist, wrote the reply over the
correct original (`create_file` resolves what `open()` could not), re-scanned,
failed identically, and logged "defects remain after repair".

| | aborted run (old code) | clean run (fixed) |
|---|---|---|
| phantom "does not parse" | **8** | **0** |
| files sent to LLM repair | **8** (100% phantom) | **0** |
| "defects remain after repair" | **7** | **0** |

Eight of eight files — `main`, `models`, `routes`, `services` and all four test
files. The tester's route-aware mock guidance (`_build_mock_examples`), which its
own docstring calls the fix for todo_app's 1/9 test score, returned `""` on every
build for the same reason — silently, since it checks `parse_error` and bails.

Measured on the shipped row 2 project: **before**, all four backend files reported
the phantom defect; **after**, three are clean and `routes.py` surfaces the real
one that was masked — two unimplemented handler stubs. Phase 22 had never once
done its actual job.

### §4.17 — row 3's 7/19 was more than half our own bug

Starlette runs lifespan/startup **only** when `TestClient` is entered as a
context manager. `runtime_smoke` built the client without `with`, so an app that
creates its tables in an `asynccontextmanager` lifespan — precisely what
`prompts/backend_developer.txt` tells the generator to write — was probed
against a database with no tables. Every data route answered `no such table`,
and the blame landed on generated code that was correct.

**This also explains the §0.5 item about row 3's repair.** The debugger's earlier
"fix" was to open the database at module import, the one pattern the prompt
forbids. It was not the model being sloppy; it was routing around a broken probe.

### §4.18 — and the rest was real: the two files drift

`main.py` and `routes.py` are separate LLM calls and disagree on the schema:

```
main.py    CREATE TABLE supplier (id, name, contact_email)
routes.py  SELECT id, name, contact FROM supplier     -> no such column
```

Both import perfectly; nothing runs SQL until a request arrives, so no gate saw
it. `tools/sql_schema_check.py` collects every `CREATE TABLE` and checks every
SQL literal against it at zero tokens, built for **precision over recall** —
a false positive spends a call editing correct code. `SELECT *`, f-string
queries, subqueries, unknown tables and bare columns in multi-table queries are
all skipped; `alias.column` IS checked, because the alias resolves the table.

### The chain, proven end to end on the shipped project

| Stage | Routes |
|---|---|
| what the pipeline reported | **7/19** |
| §4.17 lifespan fix alone | **14/19** |
| plus exactly what §4.18 found | **19/19** |

Reached with the lifespan intact and **no module-level DB connection** — so the
repair no longer has to break the rule the prompt sets.

ᵒ offline-deterministic; there is nothing a live run would add.

### §4.20 — the build that passed every gate and served nothing

`routes.py` came out as *nothing but* five `try: from X import router / except
ImportError: pass` blocks, importing modules that were never generated. The
debugger, told to fix unresolvable imports, made them unreachable instead.

Nothing caught it, because `analyze_module` read imports from `tree.body` and
deferred imports from function bodies. **An import nested in a module-level
`try:` is in neither.** Phase 22 reported "all generated files clean"; the smoke
test found 0 routes of 0. Meanwhile the pipeline's own `_audit_python_imports`
*did* see them (it uses `ast.walk`) and classified them as unfixable — so the
same defect was invisible where it was cheap to fix and unfixable where it was
found.

A guarded import that *resolves* is still fine: guarding an optional dependency
is legitimate and is not reported.

### §4.21 — three failures that were never the model's fault

| Reported as | Actually |
|---|---|
| `alembic/env.py` fails import | the architect's `alembic/__init__.py` shadowed the installed `alembic`, so `from alembic import context` resolved to the project folder |
| …and still fails once that is fixed | `alembic.context` is a proxy populated only while alembic runs a migration. `env.py` can never be imported standalone — skip it, by directory |
| `tests/test_stock.py` fails import | `main.py` lives in `backend/`, which is not on the path for a test. `from main import app` raised `ModuleNotFoundError` for a test written exactly as a user would write it |

The third is the instructive one. Fixing it turned `No module named 'main'` into
`NameError: name 'engine' is not defined` — a **real** bug, where the debugger
had commented out `engine = create_engine(...)` and left three uses of it. The
false failure had been hiding the true one.

### Where the code lives

| File | Change |
|---|---|
| `tools/code_patcher.py` | **New.** Locate one top-level block from a traceback frame, splice a replacement back, refuse anything that does not parse; read a file's imports |
| `tools/requirements_builder.py` | Strips the scaffold placeholder once real packages are written — including when there is nothing to add (§4.15); adds uvicorn for a FastAPI app that never imports it |
| `tools/runtime_smoke.py` | An import-time failure reports its frame chain; **the TestClient is entered as a context manager so lifespan runs** (§4.17); **a write endpoint is probed with a body synthesised from its own request model, so the handler actually executes** (§0.6) |
| `tools/sql_schema_check.py` | **New.** Collects every `CREATE TABLE` and checks SQL literals against it, zero tokens, precision over recall (§4.18) |
| `tools/pydantic_compat.py` | **New.** Renames V1 config keys V2 silently ignores; leaves `.json()`, `.dict()` and `@validator` alone (§4.16) |
| `tools/code_introspect.py` | Project-relative paths resolve; `read_error` ≠ `parse_error` (§4.13); module-level `try/if/with` imports are seen and marked guarded (§4.20); `shadows_installed_package` (§4.21) |
| `tools/code_executor.py` | Sibling source dirs go on `sys.path`, so a test can import the app as a user would write it (§4.21) |
| `agents/pipeline.py` | A boot failure is repairable; blame is re-aimed at the defining file; the placeholder audit skips files a later step owns (§4.19); the phantom-import message no longer names the wrong mechanism |
| `agents/debugger.py` | Repairs the failing block with a full-file fallback; a shared cause skips the block path; budgets sized to the code; framework scripts (`alembic/`, `migrations/`) are not import-checked (§4.21) |
| `agents/architect.py` | No `__init__.py` for a folder named after an installed package (§4.21) |
| `agents/backend_developer.py` | `requirements.txt` is registered as written (§4.14); pydantic compat pass; SQL schema defects reach the querying file; a guarded phantom import and a router with no handlers are defects (§4.20) |
| `llm_client.py` | `reasoning_effort` on both models; retries double the *effective* cap; the TPM ceiling is known before the first response; the budget is a refilling bucket |
| `agents/documenter.py` | No midnight-reset advice; stale placeholder claims are re-checked against disk and narrowed; `_missing_files` treats the disk as authoritative (§4.19) |
| `prompts/backend_developer.txt` | The router startup hook and a non-Pydantic `response_model` are forbidden; pydantic V2 is required by name (§4.16) |
| `prompts/debugger.txt` | **Never silence an import** — the `try/except ImportError: pass` that shipped an app with zero routes (§4.20) |
| `run_live_matrix.py` | The results file merges instead of overwriting; the headline claims only what it measured |
| `test_phase23.py` | Sections 22-39d (182 → **394**) |

---

## 0.2 The four blame rules — the design worth carrying forward

Most of this session was one question in different disguises: *given a failure,
which file should the repair be aimed at?* Getting it wrong wastes a call and can
edit working code. All four rules are asserted in the suite.

| Failure | Repair belongs in | Why |
|---|---|---|
| 500 at request time, one endpoint | the **outermost** project frame | the caller handed a helper the wrong thing; repairing the helper would teach it to accept bad input |
| Import-time boot failure | the **innermost** project frame | the outermost is `main.py` doing nothing but `from routes import router` |
| Many endpoints, one exception type | **no frame — the whole file** | the cause is code that never ran, so no traceback names it |
| A bad symbol imported from elsewhere | **the file that defines it** | the file that raised is not the file that is wrong |

The last two came from live failures and each turned a broken build into a
working one. The evidence that they are about aim rather than model capability:
row 2's repair failed on *both* models while pointed at `routes.py`, and
succeeded on the fast model the moment it was pointed at `services.py`.

---

## 0.3 How to verify a repair without rebuilding

This is the technique that made the session cheap, and it is reusable for any
future repair work.

```python
# 1. Clone the broken project the matrix already produced — never mutate it.
shutil.copytree(OUT / "inventory_system_e9eac7be", OUT / "_probe")
# 2. Ask the pipeline what it thinks is wrong, exactly as a build would.
pl = Pipeline.__new__(Pipeline); br.architecture = {"root_folder": "_probe"}
pl._smoke_test_runtime(br)          # -> pl._smoke_runtime_errors
# 3. Run the real repair against the real API.
Debugger()._repair_runtime_error(path, err, FileDebugResult(...))
# 4. Smoke it again and compare.
```

| Verified | Cost | Time | A rebuild would cost |
|---|---|---|---|
| row 3: 7/19 → 19/19 | 6,539 tokens | 6s | 131,848 tokens, 22 min |
| row 2: dead app → 6/6 | 2,640 tokens | 3s | 171,914 tokens, 24 min |

Both repaired copies are kept as evidence: `generated_projects/_live_verify_row3b/`
and `_live_verify_row2_final/`.

**What it does not prove:** that a *fresh* build avoids the defect. Prompt changes
(§4.11) and generation-time audits (§4.3) are invisible to this technique — only
a rebuild exercises them.

---

## 0.4 Quota: what governs planning

**Groq's daily budget is a leaky bucket, not a calendar day.** It refills
continuously at `200000/86400 ≈ 2.315 tokens/second ≈ 8,333 per hour, per model`.
Confirmed against Groq's own 429s to within a second:

```
limit 200000, used 197225, requested 2885 -> "try again in 47.52s"
  short by 110 tokens;  110 / 2.315 = 47.5s
```

There is no reset to wait for, and the ledger now models this — `--dry-run`
reports what is actually available.

| To afford | Refill needed from empty |
|---|---|
| the driver's 70,000 gate | 8.4h |
| row 4 (CLI, est. 60K) | 7.2h |
| row 3 (131,848) | 15.8h |
| row 2 (171,914) | 20.6h |

**One row per ~16-21 hours is the honest ceiling**, and a whole matrix is
several days. Budget accordingly: prefer §0.3's technique for anything that does
not strictly need a rebuild.

---

## 0.5 Open, with what it would take

| Item | Cost | Notes |
|---|---|---|
| Row 2, then rows 3 and 1 against the fixed probe | ~170K / ~140K / ~60K | rows 3 and 4 are done (2026-08-30); **20b must be at 70K+ first**, see §0 |
| A1 assertion 2 — a build reaching plain `done` | falls out of the above | never once observed, on any row, ever |
| **The lifespan that creates no tables** | ~0 to diagnose | row 3 opened at 0/16 and burned 2 remediation passes and ~48K tokens getting back. The architect picks alembic and nothing runs a migration — §0 item 2 |
| Phase B1-B5 | none | `PHASE23_PLAN.md`; B1 first, and startable while quota refills |
| Phase C — vector memory | blocked | 18 diagnosed failures, all mechanical. Re-examine the premise before spending on it |
| **A debugger repair that makes a file worse** | small — §0.3 verifies for ~5K | **No longer hypothetical: caught in the act 2026-08-30.** It rewrote `prod.sku` as `data.get("sku")`, silencing an AttributeError into a `None` in a NOT NULL column. Diagnosis and the two-part fix are in §0.7 |
| The Reviewer's 600-token budget | none | it always received 1,600 from the reasoning floor; now that `gpt-oss-20b` takes `reasoning_effort` the floor no longer applies, so the table wants re-tuning against measurement |
| The ledger cannot see other processes | none | per-checkout; two servers sharing the file will under-count. One at a time |
| Running the suite during a live build | none | fixed for the one assertion that flaked (it read wall-clock against a seeded clock); if another flakes, suspect the same shape before suspecting the code |

~~Row 3's repair uses a module-level DB connection~~ — **resolved.** That was
the debugger routing around §4.17's broken smoke test, not a model failure. With
the lifespan actually running, the repair no longer needs the pattern the prompt
forbids.

## 0.6 The smoke test's write coverage was fictional

`RouteProbe.ok` is `status < 500`, which is right: a 4xx is a valid answer to an
unauthenticated, unparameterised probe. But the probe sent `json={}` to every
POST and PUT, so **every write route failed validation with 422 and was counted
as a pass** — the handler body never ran. There was no coverage of write paths at
all, in any build, ever, and the score said otherwise.

Row 3 on 2026-08-30 was reported `16/16` while four routes were dead:

```
routes.py   INSERT INTO supplier (name, contact) ...  reads sup.contact
schemas.py  class SupplierBase: name, contact_email   -> AttributeError

routes.py   INSERT INTO product (..., sku, ...)       reads prod.sku
schemas.py  class ProductBase: name, description, price, supplier_id
                                                      -> AttributeError
```

It is §4.18's two-files drift one layer up — a Pydantic attribute against a SQL
column rather than SQL against `CREATE TABLE` — and no gate could see it, because
nothing ever called the handlers.

**The fix (`55d9121`).** The probe now synthesises a minimal body from the route's
own request model: required fields only, resolving `Optional`, `List`, `Enum` and
nested models, on both pydantic v1 and v2. Measured on the shipped project with
the database deleted first:

| | old probe | fixed probe |
|---|---|---|
| score | 16/16 | **12/16** |
| defects named | 0 | **4**, all real, blame on `routes.py` |

Precision is protected two ways, in the spirit of `sql_schema_check`:

- a field that cannot be synthesised confidently falls back to `{}` and the old
  422 — `POST /stock_movements/` does exactly this and is not reported;
- a 5xx raised by a **database constraint rejecting the probe's invented row** (a
  `supplier_id` that does not exist, a name already taken) is not counted against
  the app, because that depends on data we made up.

The guarantee runs the other way too: `POST /warehouses/` answers **201**, so the
synthesised body is genuinely valid and the handler genuinely executed. A green
write route now means something.

`test_phase23.py` §40 asserts both halves — the drift is caught, *and* a correct
POST is executed rather than 422'd. §40a asserts the constraint tolerance.

---

## 0.7 The repair that silences what it cannot see — fixed, and what is left

Finding the drift is not fixing it. Verified with §0.3's technique against clones
of the shipped row 3 project, driving the real debugger against the real API.

**First, a measurement that was wrong, and why it matters.** The initial probe of
this reported "the debugger cannot repair it at all" — 12/16 → 13/16, with the
one gain fake (`PUT /products/{id}` returning 404 for a nonexistent id before
reaching the bug). That was **the harness's fault, not the debugger's.** The
error text was formatted across two lines, so `_shared_cause()` — which splits on
the first `": "` to find the exception type — parsed the *message* as the type,
saw two distinct "types", and took the block path. A real build formats one line
per failure (`agents/pipeline.py`, `_smoke_runtime_errors`), sees one
`AttributeError` across four functions, and correctly routes to the whole-file
prompt. **When reproducing a pipeline behaviour by hand, build the input the way
the pipeline builds it** — §4.9's routing is invisible otherwise.

### What was actually wrong, and the fix

The repair is handed `routes.py` and never `schemas.py`. The exception names the
class but not its fields, and the project map lists class *names* only — so the
model cannot tell a rename from a missing field, and silencing is the only move
left to it.

`Debugger._definition_context()` now extracts the source of any class named in an
`AttributeError` and appends it to the project map for runtime repairs. It
follows base classes, which is where the fields usually are:
`class SupplierCreate(SupplierBase): pass` declares none of its own. Both runtime
prompts also forbid the silencing move, the way `prompts/debugger.txt` already
forbids `try/except ImportError: pass` (§4.20).

Measured on the same clone, same error, same model — one repair call each:

| | score | what it wrote |
|---|---|---|
| control, definitions suppressed | **15/16** | `data.get("contact")` — a silent `None` into the database |
| with definitions | **14/16** | `sup.contact_email` — the correct field name |

### The result worth remembering: the wrong fix scored higher

Before the tolerance was narrowed (below), the control scored **16/16** — a
perfect run — by writing `None` into every column it could not name. The correct
repair scored 14/16 because it fixed what it could and left the rest failing
honestly. **A smoke score cannot be the acceptance test for a repair.** The
silencer wins on it, every time, by construction.

The remaining 2 failures on the correct branch are real and not repairable in
`routes.py`: `ProductBase` genuinely has no `sku` field while the table has
`sku TEXT NOT NULL UNIQUE`. There is no attribute to rename to — the fix belongs
in `schemas.py`, which is §0.2's fourth blame rule pointing at a file this path
does not yet aim at.

### The hole this opened in the new probe, and the rule that closes it

§0.6's constraint tolerance excused `IntegrityError` wholesale. That excused
`NOT NULL constraint failed: product.sku` — the exact signature of a silenced
repair — and is what scored the corrupted code 16/16.

Narrowed: **a NOT NULL violation is never the probe's fault.** The synthesised
body carries every field the model declares, so a column that arrives NULL was
made NULL by the handler. UNIQUE and FOREIGN KEY violations stay excused, because
those genuinely can be the invented row — a duplicate `"test"`, a `supplier_id`
that does not exist. `test_phase23.py` §40a asserts both branches against a live
app rather than against the source text.

### Still open

A runtime probe cannot see a silenced write into a **nullable** column: the
control's `data.get("contact")` writes NULL to `supplier.contact`, which accepts
it, and nothing fails at request time. That is why the control still edges the
correct repair 15 to 14. Catching it needs a deterministic check in the shape of
`tools/sql_schema_check.py` — compare attribute reads on a Pydantic-typed
parameter against the model's declared fields, at zero tokens. That is the
natural next tool, and it would have caught both defects before a single LLM call
was spent.

---

---

---

Read this file first. Then:

| File | Role |
|---|---|
| `SESSION_PROGRESS.md` (this) | Current state, what to do next, how to verify |
| `PHASE23_HANDOFF.md` | The **backend/pipeline state** doc: what is fixed, what is proven live, what is still open, and what will bite you |
| `PHASE23_PLAN.md` | The backend **plan**. Phase A is done bar the matrix; Phases B and C are untouched |
| `run_live_matrix.py` | The four-build live matrix driver. `--dry-run` prints the plan and the quota without spending a token |
| `FRONTEND_REDESIGN_HANDOFF.md` | The **state** doc: locked design decisions (§3), chart palette (§4), measured results (§8), gaps (§9), skill conflicts (§10), traps (§11) |
| `FRONTEND_COMPLETION_PLAN.md` | The **plan**, fully executed. Kept as the record of what was decided and why. Do not re-run it. |
| `setup.md` | Setup and commands, rewritten and verified command-by-command |
| `frontend/src/lib/motion.ts` | The motion vocabulary. Every animation in the app imports from here — read it before adding one |
| `motion-audits/aiautonomous-2026-08-25.html` | Motion audit report, all 7 findings applied |

---

## 1. First commands in a new session

```bash
# Backend. MUST be the venv interpreter: system Python lacks `rich` and dies
# on import before the server starts.
venv/Scripts/python.exe start_server.py            # serves :8000

# Frontend dev server (separate terminal)
cd frontend && npm run dev -- --port 5173 --strictPort
```

Then open **http://localhost:5173**.

> **Use `localhost`, never `127.0.0.1`.** Vite binds to whatever `localhost`
> resolves to, which on this machine is IPv6 `::1` **only**. `127.0.0.1:5173`
> is refused at the socket, before CORS or any app code. `npm run dev -- --host`
> binds both if you need the literal IPv4 address.

### Verify nothing has rotted

```bash
cd frontend
npm run typecheck      # tsc -b across app / node / test projects
npm run lint           # eslint
npm run build          # vite build
npm run test           # 191 Vitest, ~15s
npm run test:e2e       # 80 Playwright + axe — needs BOTH servers up
                       # 79 pass, 1 skips, 0 fail (stable over 3 runs).
                       # 5 new: the dashboard status-filter guard, §2.8.

# Backend (test_phase17 needs the server running)
venv/Scripts/python.exe test_phase17.py                  # 58/58 (pinned to a fixture)
venv/Scripts/python.exe test_phase21.py                  # 77/77
venv/Scripts/python.exe test_phase22.py                  # 85/85
venv/Scripts/python.exe test_phase23.py                  # 394/394
venv/Scripts/python.exe test_groq_rate_limit_handling.py # OK
```

**Known-good baseline:** all clean, 191 unit + 74 E2E (1 skipped) + 216 backend
assertions, 0 npm vulnerabilities, 0 CVEs in any request-path Python package.

The E2E count went 64 → 74 in the motion pass: `e2e/motion.spec.ts` is new. The
one skip is conditional and correct — the step-log accordion test skips when the
fixture build recorded no step logs.

---

## 2. What changed, in one pass

### Frontend surfaces
Every screen is on the design system (`styles/app-shell.css` + `primitives.css`).
Dashboard, BuildCard, RebuildModal and Statistics were the ones finished this
session. `RebuildModal` lost a 260-line CSS-in-JS literal that was injected via
`<style>` on every mount, and gained `role="dialog"`, a focus trap, Escape and
focus restoration — none of which existed.

### One surface vocabulary
`.card` and `.viz-card` collapsed into `.panel`. That fixed a radius mismatch
(`--radius-xl` vs `--radius-lg`) visible wherever a chart sat beside a panel.
Ten dead selector groups pruned; last hardcoded colours tokenised into
`--gradient-accent` and `--text-on-accent`.

### Eight live bugs fixed
- Cancelled builds no longer claim "Build complete — your files are ready".
- Pipeline failures now render at all. The runner emits them on `step: -1`,
  outside the 1..9 range `StepTracker` drew, so a crashed pipeline previously
  showed nine pending rows and no explanation anywhere.
- Steps 5/8/9 no longer collide (each slot runs two agents).
- `completion_reason` replaces `project.error`, a column that does not exist.
- `pending` has a badge; the outcomes chart counts `queued`/`pending` so its
  percentages stop lying.
- Polling no longer drops step `data` — REST returns it as a JSON **string**
  while the socket sends an object; both were discarded.
- `done_with_context` renders as a warning, not "pending".
- Elapsed / ETA / queue position are surfaced (the API always returned them).

### Backend — 4 additive changes only
`agents/`, `tools/`, `prompts/`, `runner.py` and the DB schema are untouched.
1. `models.py` — prompt `max_length` 500 → 2000 (matches the composer).
2. `main.py` — `analytics_router` registered before `projects.router`, so
   `DELETE /projects/cleanup` stops being shadowed by `DELETE /projects/{id}`.
3. `main.py` — CORS gained `http://127.0.0.1:5173` (additive).
4. `main.py` — guarded SPA mount serving `frontend/dist` if present, last, with
   an Accept-header split so `/projects/{id}` returns the SPA to a browser and
   JSON to `fetch`.

### Tests, where there were none
- **Vitest + Testing Library**: 191 tests, 11 files. Behaviour, not snapshots.
- **Playwright + axe**: 64 tests. Overflow at 5 widths, reduced motion, loop
  count, drawer focus trap, keyboard traversal, contract tests, deep links.
- Guards were checked to actually **fail** when their bug is reintroduced.

### Security
npm 7 high → **0**. Python: every request-path package clean.

---

## 2.6 The motion pass

Motion.dev / `framer-motion@12` was already a dependency, and `lib/motion.ts`
already held a motion vocabulary — but it was wired into **only** Landing,
`primitives.tsx` and `RebuildModal`. Every app screen had nothing but a 150ms
CSS fade. This pass extended that existing vocabulary to the whole app rather
than inventing a second one.

### The rule that shapes all of it

`lib/motion.ts` is split into two halves, and the split is the design:

| Half | Surfaces | Budget |
|---|---|---|
| Marketing (pre-existing) | Landing | 300–600ms, blur reveals, heavy glide easing |
| **App (new, below the divider)** | Dashboard, BuildProgress, ProjectDetail, NewBuild, Statistics | enters ≤180ms, exits ≤120ms, throw ≤8px, **no blur**, stagger 0.03 |

No blur on app surfaces is deliberate: the defocus that sells a hero reveal is
paid on every repaint, and on a 50-row build list it is visible jank.

### New exports in `lib/motion.ts`

`appItem`, `appStagger()`, `popIn`, `disclose`, `routeTransition`, `liftable`,
`layoutSpring`, `NAV_RAIL_ID`, `CHIP_ID` — plus **`appListExit`**, added later by
§2.8. Read that entry before giving any AnimatePresence child `exit="exit"`.

### Where motion now lives

| Surface | What moves | Why it earns its place |
|---|---|---|
| `App.tsx` | Route transitions, `AnimatePresence mode="wait"` | Sequential, not cross-fade: pages are normal-flow documents of unknown height, and stacking them absolutely collapses the scroll container mid-navigation |
| `Sidebar.tsx` | Active rail as a single `layoutId` node | One element travels; it is no longer a `::before` (a pseudo-element has no node for Framer to hold) |
| `Dashboard.tsx` / `Statistics.tsx` | Filter + range chip tint, shared `layoutId` | The eye follows the selection instead of re-finding it |
| `BuildCard.tsx` | `layout="position"` + 2px hover lift | Rows surviving a filter change slide rather than teleport. Lift, never scale — scale resamples 11px mono figures and they blur mid-transition |
| `StepTracker.tsx` | Marker spring on status change; meter `scaleX` from zero | A step turning green is the only event on a screen watched for minutes |
| `BuildProgress.tsx` | WS pill, verdict, step count, outcome notes | All keyed to real state changes, not to the dozens of re-renders per build |
| `ProjectDetail.tsx` | Two height-to-auto accordions, rotating chevrons | 9 step logs is several hundred px of movement to absorb |
| `FloatingStatus.tsx` | Pill entry, dot pop keyed on `tone` | Keyed on tone so the 5s poll does not retrigger it |
| `MobileBar.tsx` | Menu ↔ X, quarter-turn crossfade | One control changing meaning, not two trading places |

### Reduced motion

`<MotionConfig reducedMotion="user">` in `main.tsx` is the single switch, so a
new animation cannot forget to opt in. **Verified by measurement that it covers
`layout` / `layoutId` projection too**, not only the animate props — see the
note at the foot of `lib/motion.ts`. Do not add per-component opt-outs; a
`useLayoutTransition` hook was written for this during the pass and then removed
as redundant once measured.

### Three real bugs the verification caught

These were fixed, not tested around:

1. `.chip__active` at `inset: 0` resolved against the **padding** box, so the
   travelling tint stopped short of the chip's 1px border and the pressed chip
   read a shade light around its edge. Now `inset: -1px`.
2. Wrapping the charts for staggering broke `viz-frame--wide`'s full-bleed
   span — the wrapper became the grid item, so the span had to move onto it.
3. The first reduced-motion test used a `test.use({ reducedMotion })` fixture
   that **never reached the page** (`matchMedia` reported `false`). It was a
   test that could not fail, guarding the accessibility behaviour it was named
   after. It now asserts the emulation is live before testing anything.

### `e2e/motion.spec.ts` — what it actually guards

10 tests asserting measured boxes and computed transforms, never "the component
rendered". Route wrapper settles opaque and untransformed; exactly one route
wrapper survives a navigation; one chip tint exists and lands on the pressed
chip; one nav rail lands inside the active link; the meter is `scaleX` (not
width) and agrees with `aria-valuenow`; the accordion opens to exact content
height and closes to zero; and a full walk of every animated surface produces
no console errors.

This is complementary to `layout.spec.ts`, which guards the two motion *rules*
(nothing loops; reduced motion is honoured) by scanning computed CSS. That scan
cannot see Framer at all — Framer writes inline style per frame from JS — so
without `motion.spec.ts` every animation could be broken with both files green.

---

## 2.7 The landing restructure

`FRONTEND_LANDING_PLAN.md`, all three phases. Frontend only; no backend change.
The plan's locked decision — **real data everywhere, nothing fabricated** — held
throughout, and it is what most of the work consists of.

### The bug the plan was right about
`PIPELINE_AGENTS` carried **eight** entries (Architect was missing) while the page
claimed a "9-agent pipeline" in four places. The list is now nine, named exactly as
`STEP_NAMES_FALLBACK` in `StepTracker.tsx` names them.

### A second contradiction, surfaced by the live data
The hero asserted `<8min` average build and the lede said "in under eight minutes"
— while the proof rail three screens down now reads **11.6m** off this instance.
The static claim is gone: the hero's fourth stat is `formatBuildTime(stats)` with
the label "Avg build here", the lede no longer quotes a duration, and the first FAQ
answer explains that the figure is computed from the database rather than written
into the page. `NewBuild.tsx:281` still says "Typical run is 3-8 minutes" — that is
an app screen and was out of this plan's scope, but it is the same claim.

### What is new on the page

| Section | Data behind it |
|---|---|
| Prompt preview (§3) | The real `PromptComposer`. Text carries to `/build` via router state |
| Stage-card artifacts | `top_app_types` and `average_review_score` from `/stats`; a fixed deliverables list |
| Agent topology SVG | Static — 9 nodes and the conditional repair branch. `components/landing/AgentTopology.tsx` |
| Key pool | `health.llm.keys[]` — real count, real per-key state |
| Hero health footer | `worker_pool`, `groq_keys_available/total`, `llm.status` |
| Recent builds feed | `useBuilds()` → the real `BuildCard`, last 5, failures included |
| Analytics | `StatusBreakdown` + four figures; absorbed the old `Proof` rail |

### Three decisions worth keeping

1. **`ChartFrame` and `StatusBreakdown` moved to `components/charts/frame.tsx`.**
   Both are pure DOM and CSS, but `charts/index.tsx` imports Recharts at the top
   level, so importing either one from Landing would have pulled the whole library
   into the entry chunk. `charts/index.tsx` re-exports them, so no call site changed.
   **Entry chunk went 147 → 150.94 kB gzip.** A jump toward ~250 kB means Recharts
   leaked back in.
2. **Key suffixes are not rendered.** `/health` returns the tail of each live API
   key. The card shows `Key 01…Key 08` with real states instead: the argument —
   this many keys, this many holding quota — survives the redaction intact, and the
   page does not publish fragments of live credentials.
3. **Empty means absent, not skeletal.** With no builds, the feed renders nothing
   at all and the analytics block does not appear; the proof rail falls back to em
   dashes. Verified against a mocked-empty `/stats` and `/projects`.

### Verified
- typecheck / lint / 191 Vitest / `npm run build` — all clean.
- Landing at 1440×900 in three data states (populated, empty, `/health` blocked):
  **0 axe violations, 0 console errors, no horizontal overflow** in each.
- Prompt hand-off asserted end to end: typing on `/` and pressing the button lands
  on `/build` with the composer prefilled; an empty field carries nothing.
- The no-loop law holds — the only infinite animation on the page is the hero
  StepTracker's in-flight spinner, which is the sanctioned exception.

### The E2E suite is green again — and why it was not

Two `motion.spec.ts` tests were failing (route-transition residual opacity, and
the sidebar rail). They failed on the committed baseline too, so they were not
caused by the landing work — but they were **not** the test-timing flakes they
looked like. They were the same defect as §2.8: animations that never completed
left Framer with pending work, so the route wrapper really was still mid-opacity
when the test sampled it. Fixing the exit deadlock fixed both.

**79 pass, 1 skips, 0 fail**, stable across three consecutive full runs.

## 2.8 The dashboard status filter was dead — root cause and fix (most recent work)

Reported after the landing work and **present in `48d3ae7`**, so it predates it.
Clicking any status chip left all fifty rows of every status on screen.

### Everything upstream of the DOM was correct
The chip fired, `useBuilds(filter)` requested `?status=failed`, the backend
returned exactly the seven failed builds, and the component re-rendered with
them — instrumented and confirmed: `{filter:"failed", n:7, first:"failed"}` while
the DOM still held 50 rows. The count pill beside the chips even updated to
"7 builds", because it sits outside the list's `AnimatePresence`.

### The cause
`Dashboard.tsx` gave the list wrapper `exit="exit"`. That is a variant **label**,
and Framer propagates a label down the entire variant subtree — so all fifty
`BuildCard` rows began their own exit animation. Those per-row exits stall partway
(the rows carry `layout`, and the projection freezes their value animations while
the subtree is being removed; measured: parent reached `opacity: 0`, the last row
reached `0`, the first row sat at `1` forever). The wrapper's exit therefore never
reported completion, and the enclosing `AnimatePresence mode="wait"` waited on it
indefinitely: the outgoing list was never removed and the incoming one was never
mounted.

Without `mode="wait"` the same defect showed differently — the stale list *and*
the new list *and* the loading skeletons all stacked in the DOM at once.

### The fix
`lib/motion.ts` — `appStagger()` no longer carries an `exit` variant (it was the
trap), and exports **`appListExit`**, an explicit prop object. `Dashboard.tsx`
uses `exit={appListExit}` on both list wrappers, so the exit stays on the wrapper:
one opacity animation, one completion, ~90ms. That is also the correct motion
call — fifty rows leaving one after another is a 750ms wipe, well past the
≤120ms exit budget.

Every other `exit="exit"` in the app was audited: they all sit on single elements
using `disclose` or `popIn`, with no staggered children, and are unaffected.

### The guard
`e2e/integration.spec.ts` → "the dashboard status filter": five tests asserting
that every badge visible after a filter click is that status, and that exactly one
`.dash-results` is mounted. **Verified to fail when the bug is reintroduced** —
all five go red on `exit="exit"`.

Its first version was itself wrong in an instructive way: it polled
`count() <= before`, which the *stale* list satisfies on the first sample, so it
passed alone and failed under a loaded parallel run. It now polls the assertion
itself — the set of statuses actually on screen.

### Not fixed, deliberately
Each filter is its own react-query key, so switching filters has no cached data
and flashes the loading skeletons before the rows arrive. `placeholderData:
keepPreviousData` on `useBuilds` would remove the flash. It is a separate UX
change touching a hook Landing also uses, so it was left out of a bug fix.

## 3. What is NOT done

### 3.0 ~~Blocker~~ RESOLVED — `.gitignore` was hiding `frontend/src/lib/`

> **Fixed in `48d3ae7`.** `lib/` was anchored to `/lib/`, the UTF-16 corruption on
> the final line was repaired, and all six `frontend/src/lib/*` files are committed
> and pushed. The rest of this section is kept as the record of what was wrong.

The root `.gitignore` carried a Python
packaging rule at line 57:

```gitignore
lib/
```

It is unanchored, so it matches **any** directory named `lib` at any depth —
including `frontend/src/lib/`. Confirm it yourself:

```bash
git check-ignore -v frontend/src/lib/motion.ts
# .gitignore:57:lib/   frontend/src/lib/motion.ts
```

That directory has **never been committed**, and it holds `motion.ts` (which
every animated component now imports), plus `pricing.ts`, `scores.ts` and
`prompt.ts`. A fresh clone does not build. The directory is invisible to plain
`git status` — you need `git status --ignored` to see it at all, which is why
it went unnoticed across several sessions.

Two candidate fixes, both one line — **the choice is the maintainer's**, which
is why it was left undone:

```gitignore
/lib/                     # anchor it to the repo root (matches Python intent)
# — or —
!frontend/src/lib/        # negate it for the frontend specifically
```

Anchoring is the cleaner of the two: the rule came from a Python packaging
template and was only ever meant to match a build artefact at the root.

### 3.1 Everything else

1. **The landing restructure is not committed.** It sits in the working tree
   (`git status`: Landing.tsx, landing.css, NewBuild.tsx, charts/index.tsx, plus
   the new `charts/frame.tsx` and `components/landing/`). Review and commit is
   the obvious next step. Everything before it is committed as `48d3ae7`.
2. **`chromadb` and `langchain` are declared in `requirements.txt` and never
   imported.** Verified: "chromadb" occurs twice, both as a *string* and both
   about **generated** projects, not this app — `_HEAVY_IMPORT_PACKAGES` in
   `tools/code_executor.py` (an import-timeout heuristic) and a name→pip-spec
   map in `tools/requirements_builder.py`. "langchain" appears nowhere in the
   Python source at all. There is no `import chromadb` or `import langchain`
   anywhere. They pull in torch, pillow, nltk, gitpython and ecdsa, which
   account for **all 66 remaining venv CVEs**. Deleting the two lines from
   `requirements.txt` takes the Python audit to zero. Not done: it is a
   dependency change outside the plan's scope and wants a clean reinstall to
   confirm.
3. **Landing has no real images.** `design-taste-frontend` flags a text-only
   marketing page as incomplete. No image-generation tool was available, and
   inventing stock photography for a developer tool would be worse than the gap.
4. **Only Chromium** is in the Playwright matrix.
5. **Token pricing is hardcoded** in `lib/pricing.ts` ($0.59/$0.79 per 1M). The
   API sends no pricing field. One module now, so it cannot drift between
   screens, but still an assumption.
6. **`dist/` is current** as of the landing restructure — `npm run build` was
   the last thing run against it. Rebuild after any further source change if you
   use the one-command path at :8000.

7. **The skeleton flash on filter change** is unfixed by choice — see §2.8.

---

## 4. Traps — read before debugging anything

| Symptom | Cause |
|---|---|
| `127.0.0.1:5173` refuses to connect | Vite is IPv6-only here. Use `localhost`. |
| `/stats` or `/projects/{id}` blank in dev, 404 on `/assets/index-*.js` | The proxy forwarded an HTML navigation to the backend, which returned the **built** index.html whose asset hashes don't exist on the dev server. Fixed via `SPA_ROUTE_PREFIXES` in `vite.config.ts`; check that if it recurs. |
| A CSS class was pruned and nothing failed | Typecheck, lint, build and component tests all stay green on a dangling class. `src/test/classes.test.ts` catches it. It strips CSS comments first — the first version was fooled by the comment explaining the removal. |
| A control has no focus ring | `.composer__input`'s outline is suppressed **only** under `.panel`, because the panel's border is the indicator. Rendering the composer without one previously left zero focus indication in the rebuild dialog. |
| Backend dies on import | You used system Python. Use `venv/Scripts/python.exe`. |
| A file under `frontend/src/lib/` never shows in `git status` | The root `.gitignore`'s unanchored `lib/` rule swallows it. See §3.0. `git status --ignored` reveals it. |
| A reduced-motion E2E test passes but proves nothing | `test.use({ reducedMotion: 'reduce' })` did **not** reach the page here — `matchMedia` returned `false`. Use `page.emulateMedia({ reducedMotion: 'reduce' })`, and assert the query is actually on first. |
| An animation "looks broken" only under reduced motion | It probably is not. Check the emulation is real before touching the animation — see the row above. |
| A `layoutId` assertion fails by 1–2px at random | You sampled a mid-flight frame. Layout springs take longer under a loaded parallel run; poll to settlement rather than measuring once. |
| A `height: auto` disclosure collapses to a sliver, not to nothing | The animated element has its own padding/border. A border-box element at `height: 0` still paints them. Animate a bare wrapper instead (`.nb-error-slot`, `.pd-logs__reveal`). |
| E2E fails with connection errors | The backend isn't running. Playwright starts Vite but deliberately not the backend (it owns a DB and worker pool). |
| A list ignores a filter: the request is right, the response is right, React re-renders with the right rows, and the DOM keeps the old ones | `exit="exit"` on an `AnimatePresence` child that holds many `variants` children. The label propagates to every child, those exits stall, the wrapper's exit never completes, and `mode="wait"` waits forever. Use an **object** (`exit={appListExit}`). See §2.8. |
| An animation elsewhere "settles late" for no reason | A stalled exit anywhere leaves Framer with work that never completes. Two `motion.spec.ts` tests failed for months on exactly this and looked like sampling flakes. |
| A UI test passes while the screen is visibly wrong | It asserted the component's inputs, not the rendered DOM. The filter guard in `integration.spec.ts` asserts the badges actually on screen, and was checked to fail when the bug is put back. |

---

## 5. Locked decisions — do not re-roll

These survived four skill passes. Where a skill disagreed, the locked decision
won; the conflicts are recorded in `FRONTEND_REDESIGN_HANDOFF.md` §10 so they
are not "fixed" by a later session.

- **Archetypes**: Ethereal Glass (`#050507`, radial mesh, hairline borders) +
  Asymmetrical Bento.
- **Type**: Geist / Geist Mono / Instrument Serif italic accent.
- **Palette**: the CVD-validated chart palette. Blue stays out, violet is the
  brand, `cancelled` stays achromatic. Do not re-derive.
- **Motion**: Landing may be polish-forward. App screens get restraint —
  sub-200ms or nothing, and nothing loops except the in-flight spinner. This is
  now *implemented*, not just stated: `lib/motion.ts` is split into a marketing
  half and an app half, and §2.6 lists what moves on each surface. Import from
  there rather than hand-writing a transition.
- **Surfaces**: one class, `.panel`, at `--radius-lg`. Flat on app screens by
  design: blur on a scrolling column repaints every frame.
- **Icons**: `lucide-react`, one family, used consistently.

`--text-tertiary` was changed this session from `#55555F` to `#80808B`. That was
not taste: the old value measured **2.57:1** against the elevated surface, so
every mono micro-label in the system failed WCAG AA. The new value is 4.93:1
worst case and is the smallest step that clears 4.5:1 on all three backgrounds.

---

## 6. Useful live fixtures

| build_id | status | exercises |
|---|---|---|
| `fb3e4b24-5491-4925-bdb2-4a096df4735f` | `done_with_context` | handoff banner, scores, tokens |
| `fa7533e1-26bc-4ce6-9f0f-502d823e6632` | `failed` | failure path |
| `d715e3f9-ac30-4d62-947c-97976c75d87e` | `cancelled` | the "Build complete" bug that was fixed |

The DB now holds **66 builds**: 21 done, 21 cancelled, 10 failed, 10
done_with_context, 4 running. The running ones exercise the live WebSocket spine.

### Broken-on-purpose projects, and their repaired copies

The most useful fixtures in the tree are the two builds the matrix shipped
broken, because each reproduces a distinct failure class on demand and costs
nothing to re-run against (§0.3).

| Project | Reproduces | Repaired copy |
|---|---|---|
| `inventory_system_e9eac7be` | 12 endpoints 500 on one shared cause — `@router.on_event("startup")` never fires | `_live_verify_row3b` (19/19) |
| `bookmark_manager_2323e41f` | the app never boots — a plain class used as a `response_model`, defined in another file | `_live_verify_row2_final` (6/6) |
| `task_manager_7167454c` | row 1's baseline, 5/5 routes | — |

Sections 25, 26 and 30 of `test_phase23.py` use the first two as offline
fixtures; do not mutate the originals.

---

## 7. Where the new code lives

```
frontend/src/
  styles/app-shell.css          the app-side design system (.panel/.ulabel/.figure/.meter/.chip/.empty)
  components/shared/
    PromptComposer.tsx/.css     the ONE prompt field — NewBuild and RebuildModal share it
    StatTile.tsx/.css           the ONE KPI tile — Dashboard and Statistics share it
    RebuildModal.tsx/.css       rewritten; was 437 lines with 260 of injected CSS
  components/landing/
    AgentTopology.tsx           the pipeline as a shape: 9 nodes + the repair branch
  components/charts/
    frame.tsx                   ChartFrame + StatusBreakdown, Recharts-free on purpose
  components/layout/
    MobileBar.tsx/.css          the <900px top bar; drawer toggle lives here
  hooks/
    useFocusTrap.ts             shared by the modal and the drawer
    useMediaQuery.ts            useSyncExternalStore; no setState-in-effect
  lib/                          tracked since 48d3ae7 — §3.0 is resolved
    motion.ts                   the motion vocabulary; marketing half + app half
                                `appListExit` — read §2.8 before using exit="exit"
    prompt.ts                   the 2000-char contract + readout state machine
    scores.ts                   one interpretation of the three score formats
    pricing.ts                  token rates, formatting, cost
  test/
    harness.tsx                 renderPage() + API-shaped fixtures
    classes.test.ts             every className cross-checked against the stylesheets
frontend/e2e/                   layout / a11y / integration specs + helpers.ts
  motion.spec.ts                animations verified as behaviour — see §2.6
```
