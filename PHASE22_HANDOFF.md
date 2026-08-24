# Phase 22 Handoff — Generation Quality & Runtime Verification

## Status Report | Last Updated: August 25, 2026

---

## 1. Executive Summary

Phase 21 made builds *honest* about broken output. Phase 22 attacks the output
itself: the pipeline now boots the generated app and calls its routes, and the
generators are stopped from emitting the defects that made those routes fail.

**Committed as `416a922` — "Restructured and Improved Pipeline for Quality
Generation" — and pushed to `origin/main`.**

| Metric | Result |
|--------|--------|
| Phase 22 suite (`test_phase22.py`) | ✅ **85/85** — new, offline, no LLM required |
| Phase 21 regression (`test_phase21.py`) | ✅ **77/77** — intact |
| Live build: test score | **1/9 → 6/6** on the one build that ran to completion |
| Working tree | ✅ clean, committed and pushed |

> [!IMPORTANT]
> The 6/6 is **one data point**, not proof. Of three completed live builds, one
> was good, one planned an alembic setup and fell apart, and one died on quota.
> Build quality remains high-variance. The durable improvements are the
> deterministic detectors and the runtime smoke test, not that single score.

---

## 2. The Core Problem Phase 21 Left Open

Its own closing warning named it:

> The scores measure the wrong thing. `debug 3/3` means files parse and import;
> it says nothing about whether the app runs.

Every gate asked a weaker question than the user's:

| Gate | Question it actually answers |
|------|------------------------------|
| import check | does `python routes.py` exit 0? (module-level code only) |
| debug score | the same question, retried |
| static audit (21.1) | does anything *look* wrong on disk? (never executes) |

Nothing sent a request. So a handler containing `from weather import
get_weather` — a module that was never generated — passed every gate and
returned 500 to the first real user.

---

## 3. What Was Built

### 3.1 Runtime smoke test — `tools/runtime_smoke.py`

Boots the generated FastAPI app in a subprocess and calls every route it
declares, filling path parameters with benign values. A 4xx is a pass (a valid
answer to an unauthenticated probe); a 5xx is the app breaking.

It reports the **real exception**, not the HTTP body:

```
AttributeError: '_GeneratorContextManager' object has no attribute 'query'
    (at backend/routes.py:35 in list_tasks)
```

Zero LLM tokens. Runs in a subprocess because importing generated code executes
arbitrary generated code. Findings are advisory: they mark the build degraded
and land in `SESSION_CONTEXT.md`.

### 3.2 Tester — the actual cause of the 1/9 score

`_build_mock_examples()` emitted, for **every** function in the file:

```
EXACT MOCK SYNTAX — copy-paste these:
  with patch('routes.get_todo_items') as mock_get_todo_items:
CRITICAL: ONLY use the function names above in ALL patch() calls.
```

For `routes.py` those names *are* the route handlers. **Patching a route handler
does nothing** — FastAPI captured the function object when the decorator ran and
stores it in `app.routes`, so rebinding the module global is never observed.
Every such test exercised the real, unimplemented handler and failed.

Guidance is now route-aware, drawing three distinct cases:

| Kind | Correct treatment |
|------|-------------------|
| Route handler | **Never patch.** It is the code under test. |
| `Depends(...)` target | `app.dependency_overrides[dep] = ...` |
| Imported helper the handler calls | `patch('routes.helper')` — resolved at call time |

When a file has handlers but no imported helpers, it now says so explicitly
rather than inviting the model to invent a target.

### 3.3 Deterministic introspection — `tools/code_introspect.py`

AST analysis shared by the generators. Zero LLM calls. Detects route handlers,
stub bodies, `Depends()` targets (including the bare `db: Database = Depends()`
form), function-body imports, phantom imports, `@contextmanager` misuse, and
dangling JS imports.

> [!NOTE]
> Stub detection matches TODO markers **inside comments only**. Substring
> matching over raw source flagged every `sqlite3.connect('todo_app.db')` —
> "todo_app" contains "todo" — so every `db.connect()` in a to-do app was
> reported as an unimplemented stub.

### 3.4 Backend generator — self-verification

After generation, each file is scanned for defects the import gate cannot see,
and **one** targeted repair call is spent per offending file. Zero tokens on a
clean generation.

| Defect | Why the import check misses it |
|--------|-------------------------------|
| Stub handlers (`return []` behind a TODO) | the file imports fine |
| Phantom imports | function-body imports never run at import time |
| Function-body imports of local modules | same |
| `@contextmanager` as a FastAPI dependency | fails only when a request arrives |

The last one caused **every** data endpoint in a live build to 500. FastAPI
injects the context-manager object rather than the yielded value. It is detected
both directly and through a wrapper (`def _get_db(): return get_db()`), which is
the form the build actually produced.

Also fills `.sql` schema files — no generator owned them before, so `schema.sql`
kept its scaffold placeholder into the shipped ZIP while `SETUP.md` told the
user to run it.

### 3.5 Frontend generator — dangling imports

Creates components that existing files import but the architecture never
planned. Guardrails refuse when the *import* is malformed rather than the file
missing: test-file importers are ignored, and targets escaping `src/` or the
project are rejected.

> [!WARNING]
> This guardrail exists because the first version lacked it. A generated
> `tests/test_frontend.js` imported `../todo_app/frontend/src/app.js` — a path
> duplicating the project name — and the resolver dutifully wrote a junk copy of
> the app to `todo_app/todo_app/frontend/src/app.js`.

---

## 4. Bugs Found While Validating

These were not planned work. They mattered more than the planned work.

### 4.1 The CLI ran a different pipeline than the API

`main.py` re-implemented the nine steps as a flat loop of direct agent calls.
It silently bypassed **everything** `Pipeline.run()` wraps around those calls:

- the `frontend_debugger` step (never ran from the CLI at all)
- the forbidden-file purge
- Phase 21's `_refine_and_remediate` and static audit
- Phase 22's runtime smoke test
- the quota interception that writes `SESSION_CONTEXT.md`

So a CLI build and an API build were different products. This is why a
quota-exhausted CLI build crashed with `💥 Pipeline failed` and no handoff
document — precisely the failure Phase 21 claimed to have fixed. The CLI now
drives `Pipeline.run()` and renders its progress callbacks; a regression test
asserts every step the pipeline emits has a CLI label.

### 4.2 The debugger corrupted files it was asked to fix

Disabling a module-level DB connection used `[^\n]+`, which matches to end of
line. A multi-line call:

```python
engine = create_engine(
    os.getenv("DATABASE_URL"), connect_args={"check_same_thread": False}
)
```

became `# engine = create_engine(` followed by orphaned arguments — a
`SyntaxError`. The debugger then burned its whole retry budget failing to fix a
file it had broken itself. It now follows bracket depth and comments the whole
statement.

### 4.3 Misleading build status

The summary panel was binary, so a quota-paused build that generated **zero
files** displayed as `✅ SUCCESS`. It now reports the four-state Phase 21
vocabulary plus the runtime result. `LOG_LEVEL` was documented in `.env` but
ignored by the CLI — it is honoured now, so a build can actually be watched.

---

## 5. Groq Model Migration (forced)

`llama-3.3-70b-versatile` and `llama-3.1-8b-instant` **no longer exist on
Groq**. Every key returns HTTP 404, which the retry loop reported as:

```
All 8 usable Groq keys tried for [] without success.
```

— indistinguishable from a quota or auth failure. Check
`GET /openai/v1/models` before ever debugging keys again.

Replacements are **reasoning models**: they spend part of the completion budget
on a private chain of thought returned in a separate `reasoning` field, leaving
the remainder for `content`. Measured at the project's ~950-token budgets with a
four-endpoint prompt:

| Model | `reasoning_effort` | Outcome |
|-------|--------------------|---------|
| gpt-oss-20b | none | `finish_reason=length` — **code truncated** |
| gpt-oss-120b | none | `finish_reason=length` — **code truncated** |
| gpt-oss-120b | `low` | `stop`, 3541 chars, **849 tokens** |
| gpt-oss-20b | `low` | **HTTP 400** — rejects the parameter |

Truncated code is worse than useless: it is a syntax error the debugger then
burns retries on. `_build_groq_payload()` sends `reasoning_effort=low` to models
that accept it and raises `max_tokens` to a 1600 floor for those that do not.

**Current config:** `GROQ_MODEL_HEAVY=openai/gpt-oss-120b`,
`GROQ_MODEL_FAST=openai/gpt-oss-20b`.

> [!CAUTION]
> Keep the two models **distinct**. Setting both to the same model collapses the
> dual-model quota fallback and fails two Phase 21 tests. Avoid
> `qwen/qwen3.6-27b` entirely — it leaks `<think>` blocks into `content`.

---

## 6. How to Proceed

### Step 1 — Confirm on fresh quota (the open thread)

The daily token limit (200,000 TPD) was exhausted during validation, so the
final end-to-end run never completed. Run one clean build and confirm:

```bash
LOG_LEVEL=INFO venv/Scripts/python.exe main.py "Build a todo app with a REST API ..."
```

1. The `🔥 Runtime smoke test` line appears and reports **N/N routes**.
2. A clean build reaches `done` with no `SESSION_CONTEXT.md`.
3. A degraded build shows the amber panel and stays downloadable.

> [!NOTE]
> Always use `venv/Scripts/python.exe`. The system Python lacks `rich`, so
> `python main.py` dies before the build starts.

### Step 2 — Make the smoke test drive repair

Smoke findings are currently advisory. A 500 caused by a phantom import or a
misused dependency *is* repairable, and the exception now carries file, line and
function — enough to target a fix. Feeding it into `_refine_and_remediate` is
the natural next step.

### Step 3 — Reduce architecture variance

The weakest remaining link is step 3. One run planned an alembic migration
setup for a to-do app and the build never recovered. Constraining the architect
for simple/medium apps is likely worth more than further generator tuning.

### Step 4 — Then Stage 4, production hardening

JWT auth and multi-tenant isolation, API rate limiting, PostgreSQL with
connection pooling, containerisation, monitoring. Still worth doing after
generation quality, not before.

---

## 7. Known Limitations

- **Build quality is high-variance.** One good build is not evidence the
  generators improved; treat the 6/6 as encouraging, not settled.
- The smoke test only probes **FastAPI** apps. CLI tools, Streamlit apps and
  plain-Python projects skip it silently and gain nothing.
- It probes at most 25 routes, sends `{}` as the body for writes, and fills path
  params with `1`/`"test"` — so a 422 is counted as a pass. It proves the app
  *responds*, not that it is *correct*.
- Stub handlers that return `[]` still answer **200**. The smoke test cannot see
  them; the backend generator's stub detector is what catches those.
- `.gitignore` is corrupted — `PROGRESS3rdphase.md` and `test_phase17.py` were
  concatenated into one line containing UTF-16 null bytes, which is why git
  reports it as a binary file. Those two ignore rules do not work. Harmless
  today (both files are already tracked), but worth repairing.
- `test_phase17.py` still requires a running server; it is not part of the
  offline suites.

---

*Status Report Version: Phase 22 · 85/85 · 77/77 · committed `416a922` · pushed*
*Project Workspace: `c:\programes\comppython\Aiautonomous`*
