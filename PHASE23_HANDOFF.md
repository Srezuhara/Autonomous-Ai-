# Phase 23 Handoff

*Updated 2026-09-06 at the end of the THIRTEENTH session: the fifth row ran.
Every check fired correctly, including two that had never run live — and the row
is `unusable` anyway, with zero routes for a THIRD consecutive time from a third
unrelated cause. The row also caught a regression the twelfth session had
introduced: a 4xx that stopped retrying, when the 400 this system produces is
stochastic and was recovering. The blocker has moved from the checks to the
repairs. Earlier notes follow.*

*Updated 2026-09-05 at the end of the TWELFTH session: the fourth instance of
the misaimed-repair pattern is closed and proven live — `dead_events` reads
`verified` on the row that followed it. The row still failed: zero routes for a
second consecutive run, from a cause `dead_events` cannot see. The symptom has
now recurred where no cause has, and so has `feature_coverage`'s false green.
Earlier notes follow.*

*Updated 2026-09-02 at the end of the ELEVENTH session: row 3 ran again, failed
again, and the cause was again a repair the pipeline could not aim. It is fixed
and the fix is measured — 1/22 endpoints responding became 16/22 on the build
row 3 shipped, for 21,769 tokens instead of a rebuild. Earlier notes follow.*

*Updated 2026-08-31 at the end of the NINTH session, which spent no quota and
closed Part A of PHASE23_NEXT_SESSION_PLAN.md — every remaining Phase 23 item
now needs a live row. Earlier notes follow.*

*Updated 2026-08-31 at the end of the eighth session, which spent no quota:
it closed row 3's blocker and measured two more "obvious" fixes into the
ground. Earlier note follows.*

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

## 0.-15 The fifth row: every check fired, the phase still does not close

*Thirteenth session, 2026-09-06. `route_presence` and `feature_coverage`'s new
verdict both ran live for the first time and both were right. The row is
`unusable` anyway — **zero routes for a third consecutive row, from a third
unrelated cause**. And the row caught a regression this session had introduced
the day before.*

### The row

`51d80952`, `unusable`, 704.5s, **96,304 tokens**. Scores: debug 11/11,
review 7.2, test 9/10. `tools/assert_row.py`: 10 passed, 3 failed.

| check | result |
|---|---|
| `route_presence` | **failed** — "0 route(s) declared across 17 python file(s)". *First live run.* |
| `feature_coverage` | **not_run** — "a web API that declares no routes… matching words would prove nothing". *First live run of the new verdict.* |
| `dead_events` | verified |
| `module_ref` | verified — 16 modules |
| `schema_attr` | verified — 15 models |
| `sql_schema` | `not_applicable` — correct |
| `runtime_smoke` | **failed** — "boots and declares 0 routes" |

The three §B2 failures: the terminal state, `feature_coverage` being NOT_RUN,
and "at least one check executed the artifact". The second is **the new verdict
working as designed** — NOT_RUN is a hole, it is supposed to fail a row, and it
replaced a `verified` that was certifying a dead build.

### The third cause of the same symptom

| run | cause of 0 routes |
|---|---|
| `e3894a9e` | routers registered in an `on_event` a `lifespan` disables |
| `9733027d` | six routers declared and wired, no handlers written |
| `51d80952` | a `routers/` package containing **only `__init__.py`** — the modules were never written, and `main.py` holds a bare `router = APIRouter()` |

Three rows, three causes, one symptom. This is the case for the symptom-level
check made twice over: `route_presence` caught this one having been written from
the previous one, which is exactly what a cause-specific check cannot do.

### The repair fired live, and did not land

`🛣️  Declaring routes on 1 router(s): router` — the first time that channel has
run outside a stubbed clone. It generated handlers, grew `main.py` from 922 to
2,754 chars, the import check failed, and the guard restored the original. The
build was not made worse, and it was not fixed.

**And the log could not say why.** `code_executor` recorded "Command failed
(exit 1)" and `_repair_missing_routes` discarded `verify.stderr`, so nothing
recorded whether the reply named a schema that does not exist, imported a
missing module, or something else. Fixed — it now logs the trimmed error. This
is the same defect as the discarded 400 body below, one layer up: **a repair
that cannot say why it failed cannot be improved.**

### The regression this session introduced, and the row that caught it

§0.-14 changed `llm_client` so a 4xx stops instead of rotating keys, reasoning
that *"a 4xx is a problem with the REQUEST, so rotating keys cannot help"*. That
reasoning is true of a malformed request and **false of the 400 this system
actually produces.**

The same commit's other half is what exposed it. Logging the response body
printed the reason for the first time:

> `Groq HTTP 400 … Tool choice is none, but model called a tool`

That is the model emitting a tool call that was never offered — **stochastic**,
not malformed. Row 4's log settles it: every one of its four 400s was followed
by a successful 200 on the next attempt. Rotating was recovering.

It failed twice over:

1. **Giving up immediately** removed a working retry.
2. **`break` returned `None`** from a function whose callers were written
   against "returns text or raises" — exhausting the key pool has always raised.
   The `None` reached a regex three frames away, and row 5 lost an entire
   remediation pass to `expected string or bytes-like object, got 'NoneType'`,
   with the real cause invisible.

Fixed: a **bounded** retry (`GROQ_CLIENT_ERROR_MAX_RETRIES = 3`), which keeps the
recovery without walking all eight keys, and giving up now **raises** with the
server's reason in the message.

### The test that passed for the wrong reason

The check written for the original fix asserted `"rotating keys cannot help" in
llm_client.py`. After the behaviour was corrected it **still passed** — because
the new comment quotes the old wrong reasoning in order to explain it.

That is §[41]'s rule breaking in the wild: *do not let an assertion match its own
documentation*. Rewritten to assert behaviour — `GROQ_CLIENT_ERROR_MAX_RETRIES`
is between 1 and 8, and the give-up branch's control flow, read out of the AST,
contains `Raise` and not `Break`.

### Falsification

* `test_phase23.py`: **995/995**, up from 992.
* Corpus, 50 changes and all explainable: 47 are `route_presence` appearing,
  1 is row 5's build being new, and **2 are the intended
  `feature_coverage: verified -> not_run`**. No other check moved on any project.

### Where the phase stands

**Not closable.** Five rows, none passing. The criterion is >= 3 of 4 rows at
`done`/`done_with_context` with at least one check having executed the artifact.

But the blocker has moved, and that is worth stating plainly. **The checks now
catch this reliably; the repairs are what do not land.** Three of this session's
findings were repairs that were correct and were thrown away or cut short — the
guard refusing them (§0.-12), a 400 aborting a pass, and route handlers failing
their import with no logged reason. The first two are closed. The third now
logs enough for the next session to close it.

---

## 0.-14 The fourth defect closed, the fourth row run — and the symptom outlived the cause

*Twelfth session, 2026-09-05. One static fix shipped and proven live; one row
run and failed. `dead_events` is `verified` on the row. The row is `unusable`
anyway, with **zero routes for the second consecutive run and a completely
different cause**, which is the finding that should shape the next session.*

### The row

`9733027d`, `unusable`, 988.6s, **123,430 tokens** (prompt 94,064 / completion
29,366). Scores: debug 9/9, review 6.2, test 9/12.

| check | result |
|---|---|
| `runtime_smoke` | **failed** — "the app at backend/main.py boots and declares 0 routes" |
| `dead_events` | **verified** — 1 app built with a lifespan, 16 files. *New this session; first live run.* |
| `module_ref` | verified — 16 modules checked |
| `schema_attr` | verified — 14 models checked |
| `sql_schema` | `not_applicable` — correct, SQLAlchemy |
| `feature_coverage` | **verified, 6/6** — against `0 route(s)` |
| `generated_tests` | failed — 2 error, 21 failed, 8 passed (routed to manual) |

`tools/assert_row.py`: 11 passed, 2 failed. Both failures are the same fact as
row 3 — the terminal state, and "at least one check executed the artifact".

### The defect: routers that exist, are wired, and have no handlers

`backend/routes.py` shipped **23 lines**, and its own comment says what it is:

```python
# Define placeholder routers for each resource
suppliers_router = APIRouter()
products_router  = APIRouter()
...
router = APIRouter()
router.include_router(suppliers_router, prefix="/suppliers", tags=["Suppliers"])
...
__all__ = ["router"]
```

`grep -rE "@(router|app)\.(get|post|put|patch|delete)"` over the whole project,
excluding tests, returns **nothing**. Six routers defined, five wired into a
parent, zero route handlers anywhere. The application imports cleanly, boots
cleanly, and serves nothing.

**The generator diagnosed it correctly and nothing could act on it.** The
BackendDeveloper's own post-generation check said, in the log at 22:16:18:

> *this file creates an APIRouter but defines no route handlers, so the
> application exposes no endpoints at all. Define the actual
> @router.get/post/put/delete handlers here.*

It then attempted the repair, and `accept_generated_fix` **rejected it**:

> *rejecting repair — appears to contain multiple files or an oversized rewrite*

An empty router that must gain ~22 handlers can only grow, and the guard rejects
growth beyond 1.6x or +1800 chars by design. This is the same wall §0.-9 hit with
`module_ref` — which is precisely why definitions are **appended in batches**
rather than rewritten. The finding was correct, was raised by the right agent at
the right moment, and the one channel that could have acted on it was closed.

### The pattern the two rows actually show

This is the fourth session in a row to end with "the finding existed and nothing
could act on it", and the fifth instance overall. But the sharper lesson is a
different one:

| run | cause of 0 routes | would `dead_events` catch it? |
|---|---|---|
| `e3894a9e` | routers registered in an `on_event` a lifespan disables | **yes** |
| `9733027d` | routers declared and wired with no handlers at all | **no** |

**The symptom recurred; the cause did not.** `dead_events` is a cause-specific
check, written from one row, and it correctly stayed silent on a build with the
identical failure. The check that would have caught **both** is the symptom-level
one nobody has written: *a `web_api` build must declare at least one route.*

That check is trivially decidable and needs no execution. It was written the
same day — `tools/route_presence_check.py`, §0.-12 — and it fails three corpus
builds that `runtime_smoke` independently fails, two of which were not known
before.

**It does NOT supersede `dead_events`**, which an earlier draft of this section
claimed. Row 3's handlers are declared and merely never registered, so
`route_presence` passes that build correctly and `dead_events` is what catches
it. The symptom needed a check of its own *in addition* to the cause-specific
one, not instead of it.

### `feature_coverage` is the first defect to RECUR

It reported **`verified, 6/6, "0 route(s)"`** on a `web_api` build that serves
nothing — the same false green it gave `e3894a9e`. Its detail string even prints
the disproof next to the verdict.

The current headline in `SESSION_PROGRESS.md` — *"no defect has recurred, so the
repairs are generalising"* — is **no longer true**, and this is the exception.
It is also the worst kind to leave standing: a check actively vouching for a
build that serves nothing. §0.-1 routed it to manual rather than tightening it,
on the evidence that ~2/3 of its findings are false. That decision was about its
*findings*; this is about its *verdict*, and a verdict of `verified` on 0 routes
is indefensible regardless of how noisy its findings are.

### The build log worked, and two metrics are measured for the first time

`fe7465d` holds. The log ran to 75KB+ with the full agent trace, against the
1,567-byte stubs of the previous four sessions. Both long-unmeasured numbers now
have values:

| metric | value |
|---|---|
| phantom-defect count, `grep -c "does not parse"` | **0** |
| §4.41 `RATIO_LOG` near-miss lines | **1** — a test file rejected at ratio 0.50 |

The single near-miss is a *test* file, not application code, which is weak
evidence that the 0.6 threshold is not the thing costing repairs. The rejection
that mattered on this row was the `too_large` growth rule, not the shrink ratio.

### An unrelated defect the log exposed: a 400 rotates every key

Four `HTTP 400`s, on four *different* keys, all on `routes.py` repairs.
`llm_client.py:1879` handles 429 and 401/403 explicitly and lets everything else
fall through to `continue`, which rotates to the next key. A 400 is a *request*
problem: rotating keys retries the same malformed request against all eight in
turn, and the response body carrying the reason is discarded — only httpx's
generic string is logged, so the reason is currently unknowable.

Cheap to fix, and it spends real quota the ledger never records, which compounds
the known ~51K under-report.

---

## 0.-13 The fourth instance itself: a startup handler the framework never calls

`tools/dead_event_check.py`. Statically certain, zero tokens, and it reports the
defect that made row 3's third run `unusable` while four checks stood verified
on it.

### The rule, and why it is safe to act on

A FastAPI app built with `lifespan=` that also declares `@app.on_event(...)` is
always wrong: the two are alternative spellings of the same hook, not layers of
it, and the supplied lifespan wins. The handler never runs.

This was **measured against the pinned versions rather than argued from the
docs** (fastapi 0.136.1 / starlette 1.6.0), because the whole check rests on it:

| source | `/ping` | `app.routes` after startup |
|---|---|---|
| `FastAPI(lifespan=ls)` + `on_event("startup")` registering the route | **404** | empty |
| `FastAPI(lifespan=None)` + the same handler | **200** | the route is there |

The second row is why `lifespan=None` is a guard and not a defect — the
framework only swaps the event handlers out when the argument is truthy, so the
literal `None` is the documented way to say "no lifespan". A check that fired on
it would have failed working builds.

### What it gives up to be certain

Precision over recall, the same stance as the other static checks. It stays
silent unless the module imports fastapi, and unless the app name is bound
**exactly once** in the module — a name bound twice may be the app at one line
and something else at the next, and the decorator's target cannot then be
proved. A `lifespan` variable that happens to hold `None` reads as live; that is
the recall given up to keep the false-positive rate at zero.

### The falsification

46 corpus projects, through `tools/verify_corpus.py`:

| result | projects | what it means |
|---|---|---|
| `not_applicable` | 34 | no FastAPI app with a lifespan |
| `verified` | 11 | a lifespan app whose handlers are correctly placed |
| `failed` | 1 | `e3894a9e` — the build this was written for |
| a check newly firing on a working build | **0** | |
| an existing check changing status anywhere | **0** | |

The 11 `verified` are the number that matters: eleven builds that construct a
lifespan app, every one of them left alone.

### Two guards that were not predicted, and were found by driving the repair

The channel was written the way the other three were — publish `repair_targets`,
add a `Debugger.run(dead_events=...)` channel, rewrite the file. Then the real
repair was driven at a clone of `e3894a9e` with a stubbed reply, which cost
nothing and is what §0.-10 means by "measured on the build, not asserted". Two
defects came out of it, and **the first would have made the whole channel
inert**:

| trial | before | after |
|---|---|---|
| the correct fix — body moved into the lifespan | **rejected**: "it removes top-level `include_routers`" | applied, check `verified` |
| the handler deleted, routes lost | applied — reported a repair | **refused**, original restored, still `failed` |
| the `lifespan=` argument deleted instead | applied — check went `not_applicable` | **refused**, original restored |

1. **The correct fix necessarily deletes a top-level name.** Removing the
   now-empty handler *is* the repair, and `accept_generated_fix`'s rule 3
   refuses to remove any top-level name. Every correct rewrite was rejected.
   `allow_removed` now excuses the handlers named in the findings and nothing
   else — a per-call allowance of named symbols, so a reply that deletes the
   handler *and* something else is still refused. Without this the channel would
   have been inert in exactly the way `sql_schema`'s trailing `;` was: present,
   wired in, and incapable of ever doing anything.

2. **There are two ways to silence this check without fixing anything.**
   Deleting the handler is the obvious one, and the wiring count catches it.
   The other is deleting the `lifespan=` argument: `on_event` then works again
   and the check *correctly* reports `not_applicable` — while whatever the
   lifespan was doing sits in a function nothing calls. On the clone that left
   an app which registered its routes and never created its tables, and the
   repair called it a success. The lifespan count is now asserted too.

Both are the same lesson the corpus keeps teaching: the cheapest way to make a
finding go away is to delete the evidence, and a repair that is not verified
against the *defect* rather than the *finding* will take it.

### Wired everywhere, and asserted to be

`sql_schema` existed for months without ever running during a build. Every seam
is now pinned by a test rather than trusted: the pipeline's check list, the
repair-target capture, the debugger channel, the post-repair re-check, the
per-build clearing of stale targets, `verify_corpus`, and `assert_row`.
`assert_row` also re-runs it against the shipped tree rather than trusting the
record — row 3's third run is the reason that distinction exists.

`test_phase23.py`: **943/943**, up from 899.
`tools/verify_repairs.py`: unchanged against its baseline — 1 harmed file, the
known-open `ai_pdf_reader/backend/search.py`.

---

## 0.-12 The symptom, checked directly — and a claim in this file that was wrong

`tools/route_presence_check.py`. Shipped, falsified, and cross-checked against
the executing verifier. Written after row 4 on the same day, before the next row.

### The correction first

An earlier draft of this section said this check "catches both rows". **It does
not, and the mistake is worth keeping.** Run against `e3894a9e` it reports
`verified — 5 route(s) declared`, which is correct: row 3's handlers *are*
written, in `backend/routers/product.py`. Its defect is that they are never
**registered**, because the `on_event` that would have included them never runs.

| run | cause | `dead_events` | `route_presence` |
|---|---|---|---|
| `e3894a9e` | routers registered in an `on_event` a lifespan disables | **catches** | passes (correctly) |
| `9733027d` | routers declared and wired, no handlers anywhere | passes (correctly) | **catches** |

Two checks, two different questions, one symptom. Neither replaces the other,
and the tempting summary — "write the symptom-level check and retire the
cause-specific one" — is wrong. What is true is narrower: the symptom needed a
check of its own, *in addition*.

The claim was caught by running it, not by reading it. Which is the same lesson
as everything else in this file.

### The rule

A project whose shape is `web_api` and which declares no route handler anywhere
outside tests serves nothing. Counted over the AST: `@x.get/post/put/patch/
delete/head/options/route/api_route/websocket` decorators, plus `add_api_route`
/ `add_route` / `add_websocket_route` calls.

Guards, the same stance as the other static checks:

* **only when `BuildShapes.is_web`** — a library or CLI importing fastapi for
  something else is never judged by this.
* **a route registered in a loop counts.** A project doing
  `for path, fn in TABLE: app.add_api_route(path, fn)` declares routes this
  cannot enumerate; the call site is enough to answer the only question asked.
* **test modules never count**, and can never make it pass. Row 4's suite
  declared routes; the application did not.
* a module that does not parse is skipped.

### The falsification

48 projects, and the verdict spread is the point — not just the failures:

| result | projects |
|---|---|
| `verified` | 35 |
| `not_applicable` | 10 |
| `failed` | **3** |

**All three failures are independently confirmed by `runtime_smoke`**, which is
the strongest evidence available here (§0.-6's rule): agreement between a static
and a dynamic verdict.

| project | `route_presence` | `runtime_smoke` |
|---|---|---|
| `9733027d` | 0 routes | failed — "app loaded but declares no routes" |
| `e6a1da32` | 0 routes | failed — **"app loaded but declares no routes"**, the same sentence |
| `9600d11d` | 0 routes | failed — `ImportError: cannot import name 'supplier_router'` |

Two of these were **not** known before today. The defect is commoner than the
two rows suggested: three of the corpus's web builds ship an application with no
routes.

### The repair, and the third guard found by driving it at a clone

APPENDS, one router at a time, for the reason row 4 demonstrated live: the
BackendDeveloper diagnosed this exact defect itself and its whole-file repair
was refused by `accept_generated_fix` as *"an oversized rewrite"*. An empty
router gaining a full CRUD set can only grow.

A parent router that only aggregates others gets no handlers of its own — row
4's `router` existed solely to `include_router` the other five, and writing CRUD
onto it would have produced a duplicate set of paths.

Driven at a clone with stubbed replies before it ever ran live, which found two
defects — the second of which would have shipped a **fake fix**:

| reply | before | after |
|---|---|---|
| real handlers | rejected — `_accept_definitions` demands names from a `wanted` list, and this repair has none | applied, check `verified` |
| helpers, no route | applied | refused: "declares no route" |
| the whole file re-emitted plus one handler | **applied, check went green** | refused |

The third row is the one that matters. Row 4's `routes.py` **defines no
functions at all** — it is nothing but `x = APIRouter()` assignments — so a
clash rule that inspects only `def`/`class` had nothing to clash on. Appending
the re-emitted file rebinds every router name; the `include_router` calls above
have already run against the OLD objects, so the new handlers hang off routers
nothing includes. `count_routes` then reads 1, the check goes green, and the
application still serves nothing. The clash rule now covers assignments.

### `feature_coverage` no longer certifies a dead build

It read `verified, 6/6, "0 route(s)"` on **four** builds — rows 3 and 4, and
corpus builds `9600d11d` and `e6a1da32` — all of which `runtime_smoke`
independently found broken. It printed the disproof inside its own detail
string.

A `web_api` declaring no routes now returns **`NOT_RUN`**, not `FAILED`, and the
distinction is deliberate: `route_presence` already reports the defect, and
filing one fact twice under two check names is how a clean build acquires
phantom findings. What is true here is exactly what NOT_RUN means — the check
should have had something to say and could not, because matching feature words
against an artifact with no endpoints proves nothing either way. A hole in the
evidence, and a hole is never a pass.

Counted with `route_presence`'s AST scan rather than `feature_coverage`'s own
regex, so the two cannot drift into disagreeing about how many routes exist.

Corpus effect, and it is the whole diff: **`9600d11d` and `e6a1da32` go
`verified -> not_run`, and nothing else changes on any project.**

### A 400 no longer burns every key

`llm_client` handled 429 and 401/403 explicitly and let everything else fall
through to `continue`, which rotates to the next key and re-sends the identical
request. Row 4 spent four keys on four 400s for the same `routes.py` repair, and
every one was doomed: rotating cannot fix a request the server refuses to parse,
and each retry spends quota **the ledger never records**, because it counts only
2xx calls — which is part of the known ~51K under-report.

A 4xx that is not 401/403/429 now stops. And the reason is logged: the body was
being discarded, so only httpx's "Client error '400 Bad Request'" reached the
log. `_error_body` reads Groq's own message — which model is decommissioned,
which parameter is out of range — and never raises, because a diagnostic that
throws during error handling is worse than none.

`test_phase23.py`: **992/992**, up from 943.

---

## 0.-11 The third row: every fix held, and it failed on a fourth thing

`e3894a9e`, `unusable`, 1,153s. Run on the fixed code, and the fixes are not why
it failed.

| check | result |
|---|---|
| `module_ref` | **verified** — and the repair fired again: `1 name(s) other modules read are not defined in .../backend/main.py`, `main.py` repaired |
| `schema_attr` | **verified** |
| `sql_schema` | `not_applicable` — correct: this build used SQLAlchemy, and the ORM guard is exactly what should fire |
| `runtime_smoke` | **failed** — "the app boots and declares 0 routes" |

`tools/assert_row.py`: 7 passed, 2 failed, and both failures are the same fact —
the terminal state, and "at least one check executed the artifact".

### The defect

```python
app = FastAPI(lifespan=lifespan)

@app.on_event("startup")
def include_routers():
    from routers import product
    app.include_router(product.router)
```

**Starlette ignores `on_event` when a `lifespan` is supplied.** The routers are
never registered, and the application serves nothing. Only one of the four
requested entities got a router module at all — the generated README says so
itself: *"Routers are referenced in `main.py` … but not implemented."*

This is a fourth instance of the pattern §0.-9 named, and the sharpest one yet:
the finding says "declares 0 routes", the file that must change is `main.py`, and
nothing connects the two. `main.py` WAS a repair target here (for the import
error) and was repaired — the repair fixed what it was told about and left the
dead `on_event` alone, because nothing told it.

It is also cheaply detectable and worth doing before the next row: a FastAPI app
constructed with `lifespan=` that also declares `@app.on_event(...)` is always
wrong, statically, with no execution required.

### What every static check said about a build that serves nothing

`feature_coverage`: **verified, 6/6, "5 route(s)"** — against an app with zero
routes at runtime. `module_ref`, `schema_attr`: verified. `debug_score` 8/8,
`review_score` 7.0, `test_score` 10/12.

Only the executing check caught it. That is the whole argument for the "at least
one check must EXECUTE the artifact" criterion, demonstrated by a build that
would otherwise have shipped as sound.

### Architect variance is now the dominant obstacle

Three runs, three architectures:

| run | shape | how it failed |
|---|---|---|
| `d1b98d57` | single router, raw sqlite3, flat `services.py` | 23 undefined service functions |
| `c2d4a4d4` | multi-file, raw sqlite3 | missing model field, 2 tables never created |
| `e3894a9e` | SQLAlchemy, `routers/` package | routers registered in a dead `on_event` |

Each row is a different program. No single defect has recurred across two runs,
which is the good news and the bad news: the repairs generalise, and the surface
they must cover keeps moving.

### The log problem, finally diagnosed — and the two wrong answers before it

Every log line the platform emits after its startup migration was being
discarded. The startup sequence proves it, because it logs five lines around the
migration:

```
🚀 Starting AI App Builder Platform v2.2.0     present
initialize_db()                                 runs alembic
✅ Database initialized                         MISSING
🔧 Worker pool: 3 workers ready                 MISSING
✅ Platform ready                               MISSING
```

`alembic/env.py` calls `fileConfig(config.config_file_name)`, which replaces the
root handlers with alembic.ini's and disables every logger already created. The
server runs migrations at startup, so this happened before a single build ran.
The five 1,567-byte logs in this repo all stop at that exact line, and every
272KB log that does contain agent output predates Alembic landing on 2026-08-31.

Both earlier answers were wrong, and each was disproved by its own fix:

| diagnosis | fix tried | how it was disproved |
|---|---|---|
| block buffering | `line_buffering=True` | the log was the same size **after the process exited** — a buffer would have flushed |
| the detached launch | `--log-file`, a FileHandler the server owns | it stopped at the **same line** |
| `fileConfig` (correct) | alembic's `configure_logger` attribute | the three missing lines appear |

`disable_existing_loggers=False` alone is not enough either — it stops loggers
being *disabled* while `fileConfig` still *replaces* the root handlers. Both
changes are in: `env.py` honours `configure_logger`, and
`api_platform/database.py` sets it to False, which is alembic's documented way
for an embedded caller to keep its own logging.

**Consequence:** the next row gets a readable build log for the first time in
four sessions, which is also the first chance to measure
`grep -c "does not parse"` and §4.41's `RATIO_LOG`. Both are still unmeasured.

### The quota fallback, proven live

Started deliberately below the driver's 90,000 fast floor (49,894 left) by
posting the build directly. The fast model ran dry and `generate_text` moved the
remaining work to the heavy model, which went 149,741 -> 45,091. **The row
completed rather than dying at the wall** — the first live exercise of that
branch, which until yesterday had no test at all.

---

## 0.-10 The other two instances, closed — and a check that had been silent for months

§0.-9 closed one instance of "the repair is aimed at the file the traceback
names, not the file that must change" and named two more. Both are now closed,
and each was measured on the build row 3 actually shipped rather than argued.

### `schema_attr` — the identical gap, one check over

Its evidence was `{"undeclared": [...]}`: the finding names the model that must
gain the field and nothing could act on it. It now publishes `repair_targets`
the same way `module_ref` does, built from a model→file map collected while the
sources are already in hand (`find_model_definition` stays for its single-model
callers). The repair is `Debugger.run(missing_fields=...)`, and it **rewrites**
rather than appends — a field belongs inside an existing class, so there is
nothing to append to the end of the file, and `accept_generated_fix` applies
again because its `too_large` rule is no obstacle to adding one line.

### `sql_schema` — which had never run during a build, and could not have worked if it had

Two defects, one on top of the other.

**It was never wired into the pipeline.** It existed only in
`tools/verify_corpus.py`, over projects that had already shipped. The one check
that can see a query and a schema disagree had never run during a build.

**And it was inert.** `_CREATE_TABLE` ended in `\)\s*;` — it required a
semicolon after the closing bracket. A statement passed to
`cursor.execute("CREATE TABLE ...")` has none and needs none, so `parse_schema`
returned `{}`, and with no schema **not one column was ever checked**. It
reported nothing rather than reporting that it could not run. Replaced with a
bracket-matching scan, which also handles `price DECIMAL(10, 2)` — the case the
semicolon was there for. Four corpus projects went `not_applicable -> verified`
the moment it could read their DDL: they had never been checked at all.

**Then the new report.** A queried table that no `CREATE TABLE` creates. The
module's standing rule is to stay silent on this, because "the schema may live
in a migration or an ORM" — right in general, and wrong in the checkable case
where the project creates its *other* tables inline three lines up. Guarded on
both sides: an ORM marker or a `migrations/` directory anywhere in the project
silences it, and so does a project that creates no tables at all.

### The falsification, which is the part that matters

Across all 48 corpus projects, **7 changes and no false positives**:

| change | projects | what it means |
|---|---|---|
| `not_applicable -> verified` | 4 | the inert parser fixed; these had never been checked |
| `not_applicable -> failed` | 1 | `c2d4a4d4`, with both missing tables named — the true positive |
| a check going quiet on a broken build | **0** | |
| a check newly firing on a working build | **0** | |

### Measured on the build, not asserted

Driving the real debugger at a clone of `c2d4a4d4`, three probe runs at ~4,200
tokens each:

| | before | after |
|---|---|---|
| endpoints responding | 13/22 | **20/22** |
| `schema_attr` | failed | **verified** |
| `sql_schema` | failed | **verified** |

Two findings came out of the probe that no amount of reading would have given:

1. **The first version half-worked.** It created the tables and the endpoints
   traded `no such table` for **`no such column: movement_type`** — the repair
   had invented a plausible schema. `MissingTable` now carries the columns the
   queries actually read, so the finding describes the table the code expects.
2. **The field repair was flaky** — with the prose finding alone it returned a
   file that did not declare the field about half the time. The post-check
   caught it every time and restored the original, which is the correct outcome
   and a wasted call. The prompt now leads with `- add \`price\` to class
   \`ProductCreate\`` and the reasoning follows. Three runs, three landings.

The remaining 2 of 22 are ordinary code bugs with clean tracebacks — a NOT NULL
insert and a `sqlite3.Connection` passed as a query parameter — which is the
channel that already existed, and the real pipeline re-smokes and gets another
pass at them where the probe does not.

### What is still not proven

**A row.** Everything above is a clone plus 48 static projects. A clone cannot
exercise generation, the tester, or the second remediation pass, and the fast
model was at ~47,000 when this was written against a ~114K row. `test_phase23.py`
is **899/899**.

---

## 0.-9 The eleventh session (2026-09-02) — row 3 ran, and the finding that named its own repair was advisory text

Row 3 (`d1b98d57`) reached **`done_with_context`** in 997s for **117,191
tokens** — against `unusable` and 222,068 the day before. The repair-loop fixes
of the tenth session held: two remediation passes, no thrash, and `_preflight_fix`
did not collapse anything. It still failed its row: **21 of 22 endpoints
returned 500**.

### The cause, which is one layer out from the last one

`backend/routes.py` called 23 functions in `backend/services.py`. `services.py`
defined three. `module_ref` caught this exactly and said what to do, 23 times:

> `backend.services.get_suppliers` is read at line 20 … **Add `get_suppliers` to
> `backend.services`** — do NOT delete the reference or point it at a different
> name.

Then nothing could act on it. `_verify_other_shapes` returns finding **strings**,
which land in `advisory` — "issues the repair passes cannot fix". The only thing
that produces a repair *target* is a failed import or a 5xx traceback, **and a
traceback names the caller**. So both LLM passes repaired `routes.py`, which was
correct. `SESSION_CONTEXT.md` says so on its face: *"Files repaired:
`backend/routes.py`"*.

The build's own progress record settles it without inference — this is what the
pipeline wrote for itself at step 8, and it survives in `build_progress`:

```
failed_files: ['inventory_system_d1b98d57/backend/routes.py']
issues:       'Generated tests fail for 2 file(s)…'
              '1 file(s) raise at request time: …/backend/routes.py'
advisory:     33 items — 23 of them naming `backend.services`
```

One repair target, and it is the correct file. Twenty-three findings naming the
broken one, all in the list that by definition drives nothing.

The information was all present. `RefIssue` carries the module that must define
the name, and `collect_modules` already returns a module→file map; the map was
discarded one layer before the layer that needed it.

### The fix, and the three measurements that shaped it

`module_ref` now publishes `evidence["repair_targets"]` — `{defining file:
[findings]}`, OUTPUT_DIR-relative, excluding test modules (§4.26), open modules,
and modules with no file of their own. The pipeline merges those into
`failed_paths` beside the runtime errors and hands them to
`Debugger.run(missing_definitions=...)`, re-asking between passes so a second
pass never pays to re-add what the first one added.

In the debugger it needed **its own channel**, because such a file *imports
cleanly*: `run_python` succeeds, `_debug_file` returns success on attempt 1, and
every existing hook on that path was for a runtime traceback. A static finding
has none.

Then the probe — the real debugger against a clone of the build row 3 shipped —
falsified the first two designs before a row was spent:

| # | What was tried | What the probe measured |
|---|---|---|
| 1 | Rewrite the whole file | Groq bills prompt and completion against one 8,000-token minute. 23 functions clamped the output to 2,626 tokens; three truncated replies, **19,749 tokens, nothing written**. |
| 2 | — | A reply that *had* fitted would still have been rejected: `accept_generated_fix`'s `too_large` rule is `len(fixed) > max(len(current) * 1.6, len(current) + 1800)`, and a file gaining 23 functions trips it **by design**. Correct rule, wrong repair. |
| 3 | Append in batches of 5, judged by `_accept_definitions` | 18/23 names. Batch 1 was refused by a size heuristic **I had just written** — five supplier CRUD functions are legitimately about as long as the 3,630-character file they belong to. Removed; the clash rule already catches a whole-file return exactly, and size never could. |
| 4 | Same, plus the call sites | **23/23, `module_ref` VERIFIED, `routes.py` untouched.** |

### And the assertion the name existing does not carry

Run 3 added every name and the endpoints still returned 500:
`create_supplier(name, contact_email)` against a route calling
`services.create_supplier(supplier)` with one Pydantic model. AttributeError had
become TypeError. **`module_ref` only ever asked whether the name exists.** The
prompt now carries the actual call lines and says the parameters must match
them, which is what run 4 measured:

| probe run | endpoints responding | names added |
|---|---|---|
| before any repair (the shipped row 3) | **1/22** | — |
| run 4, after the definition repair | **16/22** | 23/23 |

The six that still fail are ordinary request-time bugs with clean tracebacks
naming `services.py` — the channel that was already there, and the pipeline
re-smokes after this repair, which the probe does not.

### Also closed

**The 1,567-byte log, diagnosed three times. Only the third was right — see
§0.-11's commit `fe7465d`: `alembic/env.py`'s `fileConfig()` replaces the ROOT
handlers during the startup migration, so the platform silenced itself before it
had built anything. What follows is the second diagnosis, kept because it is how
the third was reached.**

Five session logs in this repo are exactly 1,567 bytes: the startup banner and
nothing else. Two live rows have now been assessed without their build log
because of it. The first diagnosis was block buffering, and `line_buffering=True`
was added to `start_server.py` on that theory. **It was wrong.** The next row's
log was still 1,551 bytes while the build ran — and still 1,551 bytes *after the
process exited*. A buffer would have flushed. The output never reached the file
at all, which is also why uvicorn's own access lines for every request were
missing.

It is the launch, not the process. Started detached from a shell that then exits
(`nohup ... &` from a tool call, which is how an agent starts a server), the
inherited stdout stops being written once that shell is gone. Sessions that ran
the server in a terminal that stayed open have 272KB and 135KB logs of exactly
the same output — so the older note that "`server.log` never receives it" is
also wrong.

Fixed properly: **`start_server.py --log-file PATH`** attaches a `FileHandler` to
the root logger, so the log belongs to the server rather than to whatever shell
started it. Verified by running with stdout pointed at `/dev/null` and watching
the file fill. Use it for any run whose log you intend to read. `line_buffering`
was kept — it is correct and free — but it is not what fixes this.

Consequences for both rows: `grep -c "does not parse"` is **unmeasured**, not 0,
and §4.41's `RATIO_LOG` still has no live data after three sessions of waiting
for one.

**A test fixture leaked into the corpus and was caught by the corpus.**
`Debugger.run` resolves paths against `config.OUTPUT_DIR` and *creates* files
(`_ensure_init_files`), so a probe that forgets to point OUTPUT_DIR at its own
scratch writes into `generated_projects/`. `verify_corpus` reported `app59` as a
new corpus member on the next run. Removed, and the test now sets OUTPUT_DIR for
the whole block — the same defect that put `_pristine_f3` into a baseline once.

### The re-run: the fix worked, and the row still failed

Row 3 ran again (`c2d4a4d4`) on the fixed code: **`done_with_context`, 114,240
tokens, 873s.**

| | first run `d1b98d57` | re-run `c2d4a4d4` |
|---|---|---|
| `module_ref` | **failed**, 23 findings | **verified**, 0 findings |
| endpoints responding | 1/22 | **13/22** |
| unresolved issues | 34 | **10** |
| generated tests | 6/12 | **12/12** |
| debug score | 8/8 | 5/5 |

**The repair fired live**, and the build's own record says so rather than the
log — which is fortunate, because the log was lost again:

```
failed_files:   [.../backend/main.py, .../backend/routes.py, .../backend/services.py]
issues:         '1 name(s) other modules read are not defined in .../backend/services.py'
repaired_files: [.../backend/main.py, .../backend/routes.py, .../backend/services.py]
```

`services.py` — the file that had to *define* the name — is in both lists. On the
first run it was in neither. Note the scale, though: the generator left **one**
missing name this time, not 23, so the live exercise was far smaller than the
probe's.

### Why it still failed, and the pattern underneath

Two things, and both are the same shape as the defect just fixed.

**1. `schema_attr`, which is `module_ref` one check over.** `product.price` is
read at `routes.py:84` but `ProductCreate` declares description, name, sku,
supplier_id. The finding names the model that must gain the field; its evidence
is `{"undeclared": [...]}` — **no repair target** — so it is advisory text that
nothing can act on. `find_model_definition(root, class_name)` already exists and
already returns the model's defining file. The gap is the same one, unclosed.

**2. Eight of the nine 500s are `no such table`.** `main.py` creates `supplier`
and `warehouse`; it never creates `product` or `stock_movement`. The tracebacks
name `services.py:102`, where the query runs — **the fix belongs in `main.py`,
where the DDL is.** The file the traceback names is the wrong file, for the third
time. And no checker reports it: `sql_schema` deliberately stays silent on a
table with no `CREATE TABLE` anywhere, because "the schema may live in a
migration or an ORM" — sound in general, wrong for a project that creates its
other tables inline three lines up.

So the pattern is systemic and this session closed one instance of three.

### What was deliberately NOT shipped, and why

Both fixes above are tempting, cheap-looking, and were **declined**:

- Neither can be validated by a live row — the fast model was at 34,502 after
  the re-run and a row costs ~114K.
- The one that *was* shipped needed **~80K of probe runs** and was wrong twice
  offline before it worked, including a size guard written for it that refused a
  legitimate repair on its first real input.
- This phase's own record: 4 of 6 new verifiers once reported defects that did
  not exist.

Shipping two more unvalidated repairs would be the mistake this phase keeps
catching. They are specified above instead, with the machinery each would use.

### `tools/assert_row.py`

The §B2 assertion table, executable — three handoffs have asked a reader to run
it by hand. Reads the record from the API *and* re-checks the artifact on disk,
so neither is trusted alone. Calibrated against both rows: it fails `module_ref`
on `d1b98d57` and passes it on `c2d4a4d4`.

It also produced a false positive on first use, which is worth recording because
the cause was invisible: it flagged `include_router(router)` in a **single**-router
build, where that is correct — the §4.38 defect was a *multi*-router build whose
five aliases were all rewritten to the bare name. The assertion is now "every
included name is bound in the file that includes it". The reason it survived a
first fix is that the patch script wrote a literal **backspace character** into
the regex (`` in a non-raw string), so the pattern read `.*<BS>router<BS>` and
could never match, and `grep` could not show it.

### Verification

| | |
|---|---|
| `test_phase23.py` | **881/881**, up from 854 — 27 new, word-level |
| probe, 4 runs | 1/22 → **16/22** endpoints; `module_ref` FAILED(23) → **VERIFIED(0)** |
| live re-run `c2d4a4d4` | `module_ref` **verified**; endpoints 1/22 → **13/22**; unresolved 34 → **10** |
| `verify_corpus` | re-recorded with both new builds; no change on re-check |
| cost of proving it | **~80K on the fast model**, against 117K for a row. The plan said 2-7K; that estimate was for a single-file repair, not 23 names over five batches, four times. It put the fast model below its 90,000 floor, so the re-run of row 3 waits for refill. |

**Still open — the phase does not close.** Its criterion is a row whose record
carries positive evidence: zero `not_run`, at least one check that *executed* the
artifact, and the §B2 assertions. The re-run gets 7 of 9 and misses the two that
matter most: `schema_attr` failed, and no executing check verified, because
`runtime_smoke` is 13/22. The next row needs the two defects above closed first;
neither is quota-gated to *fix*, only to *prove*.

---

## 0.-8 The 21 harmed files, fixed — and one that is not

`tools/verify_repairs.py` reported 21 corpus files that imported cleanly and
stopped importing after the deterministic repairs. **21 -> 1.** Each was bisected
rather than guessed at; the priority was backend soundness, with frontend
verification explicitly out of scope.

### 0.-8.1 The shim was putting *this repo* on generated code's import path

The worst of the three, and it had nothing to do with the symptom.

`SYSPATH_BLOCK` is fixed at three levels — `_here`, `_parent`, `_grandparent`.
That is right for `<project>/backend/x.py`. For a file at the **project root**,
`_grandparent` is `<OUTPUT_DIR>/..` — **the AI builder's own repo root** — and
the shim inserts it at `sys.path[0]`.

`inventory_system_f3dbcc61` has a root `__init__.py`, so importing
`tests.test_main` executed it first, put `C:\...\Aiautonomous` at the front of
the path, and `from main import app` resolved to **our `main.py`** rather than
the project's `backend/main.py`. Seven files, every one of them correct code.

The general form is worse than the instance: **any generated module whose name
collides with one of ours — `main`, `config`, `tools`, `agents`, `llm_client` —
was resolvable to our copy**, in every project with a root-level `.py`.

Fixed by `_syspath_block(rel_path)`, which emits only as many levels as stay
inside the project: depth 0 gets `_here` alone, and the three-level form is
unchanged from two deep down, which is where it was doing its job.

### 0.-8.2 Two rules removed a binding without checking its uses

- the `services.py` sibling-import stripper deleted `from auth import Token`
  while `Token` was still referenced — `llm_api_key_dashboard` (9),
  `bookmark_manager_a3ca5c18` (3);
- `_preflight_fix` commented out `engine = create_engine(...)` and left
  `SessionLocal = sessionmaker(bind=engine)` on the next line — `ai_pdf_reader`.

Both now ask first, through a shared `_name_is_used()` — AST where the file
parses, a word-boundary scan where it does not, because this runs on files
mid-repair. Removing a binding that is still read cannot help any build: it
converts a *possible* problem into a *certain* `NameError`.

### 0.-8.3 One fix tried and dropped, which is the point of measuring

The shim inserts at position 0 while iterating `[_here, _parent]`, so the
project root ends up **ahead** of the file's own directory — the reverse of
what `run_python` carefully arranges. Reversing it is obviously right and it was
wrong: the single file it was aimed at resolved identically (`run_python` puts
the project root ahead of `backend/` before the shim ever runs) and **34 files
became non-idempotent.** Reverted, with the measurement recorded in the code so
the next reader does not spend the same hour.

### 0.-8.4 Still open: 1 file

`ai_pdf_reader/backend/search.py`. `from ai_pdf_reader.backend.ocr import
extract_text` is flattened to `from ocr import extract_text`, which collides
with a root `ocr/` **package** whose `__init__.py` does not re-export it. The
flattening rule checks that `ocr` is a sibling of the importing file — it is,
`backend/ocr.py` — but not that the flat name is unambiguous project-wide.
Recorded in `repair_baseline.json`; not guessed at.

### 0.-8.5 `feature_coverage` is routed, not tightened and not widened

Widening the vocabulary was **measured before being written**: module file
stems, called attribute names (`pd.read_csv`), and JS/JSX declarations, against
all 34 findings.

| candidate | findings it would fix |
|---|---|
| module stems | **0** |
| called attributes | 3 |
| JS declarations | 3 |
| all three together | **6 of 34** |

So it is not a tuning problem, and no vocabulary change ships. What made this
urgent is where the findings *go*: a `failed` verifier feeds the remediation
advisory, which drives an LLM — roughly 23 false findings would spend real
tokens telling the repairer to build what already exists, the same misdirection
§0.-5.2 fixed in `module_ref`.

**`feature_coverage` joins `_MANUAL_WHEN_WORKING`.** When something *executed*
the artifact and found it sound, its findings are handed to the reader instead
of counted — the §4.26 mechanism, unchanged. When nothing executed it, they
still count, and they must: `bookmark_manager_de756d20` is an empty build of
architect stubs, and a static check is then the only signal there is. Both
directions are tested.

`run_live_matrix.MANUAL_CHECKS` was updated in the same change. A test already
pins the two lists equal — §4.39 is exactly what happens when the record and its
consumer disagree.

### 0.-8.6 Verification

| | |
|---|---|
| `test_phase23.py` | **854/854** |
| `verify_repairs.py` | **1 file harmed, down from 21**; 46 targets, 8 non-idempotent |
| `verify_corpus.py --baseline` | **no change** — no verifier regressed |

Two debugging clones (`_pristine_f3`, `_bisect_f3`) leaked into
`generated_projects/` during the bisect and were probed as if they were corpus
members. Removed, and dropped from the baseline before recording — a probe
measuring its own scratch space is how a corpus stops being evidence.

---

## 0.-7 The non-quota plan, executed — a harness for the half nothing tested

Row 3's two defects both sat in the same blind spot, and it is worth stating
plainly because it governs everything below:

> `tools/verify_corpus.py` replays **verifiers** over finished projects. It never
> invokes `_preflight_fix`, the debugger's repair loop, or the tester. The corpus
> covers checkers, not the agents that write and repair code.

### 0.-7.1 `tools/verify_repairs.py`

Replays the deterministic, zero-LLM prefix of `Debugger.run()` — the file
filter, `_ensure_init_files`, `_preflight_fix`, `_rewrite_dotted_imports`,
`_inject_syspath`, `_apply_structural_import_repairs` — stopping immediately
before `_debug_file`, where the LLM starts. Three properties:

- **P1 do no harm** — a file that imported cleanly before must import after.
- **P2 idempotence** — running the sequence twice equals running it once.
- **P3 a reviewed diff** — every modification attributed to the rule that made it.

`--baseline repair_baseline.json` turns it into a regression test, the same
contract `verify_corpus.py` has. Costs nothing: no LLM, no tokens.

### 0.-7.2 The design changed on evidence: `repair_fixtures/`

The first full run found **zero** harm — and that was almost a false negative.
**Every build in the corpus is single-router** (`from routes import router`),
so replaying the repairs over the corpus alone **would not have caught the
defect that cost row 3 either.** A blind spot inside a blind spot.

Hence `repair_fixtures/` — small hand-written projects, correct and importable
as they stand, for shapes the corpus lacks: `multi_router`, `multi_model_pkg`,
`single_router_legacy`. **Three of the four repair defects below were found
there and nowhere else.** When a repair rule is fixed, the shape that broke it
belongs in that directory.

### 0.-7.3 Three defects fixed, each measured

**`_inject_syspath` grew a blank line on every pass.** It stripped the shim's
code lines but not the blank line it re-inserts, and wrote unconditionally.
Measured: **531 of 531 corpus files modified, 535 non-idempotent** — it *was*
the entire non-idempotence signal, which is to say it hid every other. After:
319 modified, and corpus-wide non-idempotence fell to **8**.

**`from models import X` was retargeted at `glob("*.py")[0]`** — whichever file
the filesystem returned first, regardless of which module defined X, and `glob`
is not sorted so it was not stable across machines. Now a line is retargeted
only when exactly one module supplies every name it asks for, and a package
whose `__init__.py` re-exports the names is left alone.

**`_is_sibling` was case-insensitive.** `Path.is_file()` answers True for
`Supplier.py` when only `supplier.py` exists — on Windows and macOS both. So the
imported *name* `Supplier` resolved to the *module* `supplier`, and
`from supplier import Supplier` was rewritten to `import Supplier`: a class
imported as a module. This is the one-class-per-module convention, so it is
broadly reachable, and no build in the corpus has the shape that shows it.

### 0.-7.4 The harness was falsified before it was believed

A harness that only ever prints 0 has proved nothing. Reverting each fix, one at
a time, and re-running the fixtures:

| state | harmed |
|---|---|
| all three fixes in place | **0** |
| router collapse reverted | **1** — CAUGHT |
| `_is_sibling` case fix reverted | **4** — CAUGHT |

It catches the defect that cost 222,068 tokens.

### 0.-7.5 What it found that is NOT fixed: 21 harmed files, all pre-existing

The full corpus run reports **21 files that import cleanly and stop importing
after the repairs**. Measured with the three fixes reverted: **also 21**. They
are pre-existing, not regressions — newly visible, not newly caused.

| # | Project | Symptom | Cause |
|---|---|---|---|
| 9 | `llm_api_key_dashboard` | `NameError: Token` | `_apply_structural_import_repairs` step 2 deletes `services.py`'s sibling imports **without checking whether the names are still used** — `from auth import Token` removed, `Token` still referenced. |
| 7 | `inventory_system_f3dbcc61` | `ImportError: cannot import name 'app' from 'main'` — and the path names **this repo's own `main.py`** | flattening `from backend.main import app` to `from main import app` for a file in `tests/`, where `backend/` is not on the path, so it resolves against the builder's own tree. |
| 3 | `bookmark_manager_a3ca5c18` | `NameError: BookmarkCreate` | same shape as the first. |
| 2 | `ai_pdf_reader` | `NameError: engine` | `_preflight_fix` comments out `engine = create_engine(...)` and leaves `bind=engine` on the next line. |

**Three of the four are one bug**: *a rule removes a binding without checking
its uses.* §Phase 22 already fixed this rule once, for multi-line statements;
use-after-removal was never considered. That is the next repair defect to fix,
and `repair_baseline.json` now records these 21 so a fix has to move the number.

**Caveat on the baseline**: `clean_before` depends on a 30s import timeout, so a
heavily loaded machine could shrink the asserted set and mask a harm. Diffs are
compared on file names, not counts, but treat a *reduction* in harm with the
same suspicion as an increase until a diff explains it.

### 0.-7.6 `feature_coverage` — measured, and synonyms were never the blocker

§4.40 called synonyms "the single remaining blocker" on the strength of **five**
anchor projects. `corpus_intents.json` is now **39 projects / 167 features**,
hand-authored from the 75 prompts `platform.db` already stores — zero quota,
since the IntentAnalyzer is an LLM call and these were written by reading the
prompt.

Two numbers end the tightening:

- **69 of 126 covered features (55%) hang on a single word.** Any "require two
  words" rule converts them into findings at a stroke.
- Of the 34 features now reported missing, roughly **23 are false**, in two
  clusters that have nothing to do with synonyms:
  - **the AI-report builds (14)** — the evidence is in `pd.read_csv`, string
    literals and `data_analysis` vs "analyze". The vocabulary collects *defined
    names*, not called ones, string content, or morphology.
  - **the React task managers (9)** — the evidence is in 15 `.js` files, from
    which only HTML tag names are collected.

The remaining findings are genuine and worth having: `bookmark_manager_de756d20`
is an **empty build** whose files are all architect placeholder stubs, and
`todo_app_4fe8055a` really does implement neither habits nor daily tasks. Both
were invisible before, because `feature_coverage` answered `not_applicable` for
every project but five — checking nothing, and reading as fine.

**Verdict: do not tighten the threshold. The work, if it is done, is vocabulary
coverage — called names, string literals, JS identifiers — not a synonym table
and not embeddings.** That is a different change with its own risk, and it is
not started here.

**What the corpus baseline now means for this check.** `feature_coverage` moved
from `not_applicable` on 34 projects to `verified` on 17, `failed` on 15 and
`not_run` on 2 (the two are empty directories with no `.py` at all, which is the
honest answer). Those 34 findings are recorded in `verification_baseline.json`
**as what the check currently says, not as truth** — roughly two thirds are the
false positives measured above. The baseline's job is to detect change. Do not
read that file as a defect list until the vocabulary is fixed.

### 0.-7.7 Verification

- `test_phase23.py` **850/850** (§4.45 tester filter, §4.46 the three repairs).
- `verify_corpus.py --baseline` clean after re-recording; **every diff was
  `feature_coverage`, and zero verifier outcomes changed** — the debugger work
  touched no checker.
- `verify_repairs.py --baseline repair_baseline.json` clean; fixtures 0 harmed.
- Falsification passed for both fixes that have a fixture (§0.-7.4).

---

## 0.-6 Phase C's premise, re-examined — the verdict is NO-GO

`PHASE23_PLAN.md:339-343` made this a precondition of any Phase C spend: *"If
the live matrix shows build quality is dominated by architect variance rather
than by missing precedent, vector memory is the wrong lever."* It was never
done. It is done here, and it costs nothing: the catalogue is already written.

### The classification

Every defect catalogued in §4.22-§4.46 — 24 of them — sorted by what would have
prevented it:

| Cause | Count | Examples |
|---|---|---|
| **Pipeline mechanics** — plumbing, ordering, a verifier's semantics | 16 | §4.22 ledger, §4.25 findings never re-read, §4.31 "verified" meant inspected, §4.39 record written before routing, §4.40/§4.42/§4.43 verifier logic |
| **The pipeline broke correct code** | 5 | §4.33 shim outranked `__future__`; §4.46 the router collapse, the `models/` retarget, `_is_sibling`'s case-blindness; §4.44 the tester testing a test |
| **Generation quality** — the model wrote something wrong | 3 | §4.34 ignored the import convention, §4.35 routes against undefined schemas, §4.38 the unstated contract |
| **Missing precedent** — a similar prior build would have helped | **0** | — |

### What that means

**Not one defect in the catalogue would have been prevented by the build having
seen a similar build.** Phase C's premise is not merely unsupported; the second
row inverts it. In five cases the *generator was correct* and the pipeline
destroyed its output — better precedent would have produced better code for the
same machinery to break.

And where generation genuinely was at fault, precedent was not what fixed it.
§4.34 is the clearest: the prompt "could not be plainer" and the model ignored
it anyway, 39 violations across 10 builds. What worked was deterministic
enforcement after the fact. §4.38 was fixed by stating the contract in the
prompt. Both are cheaper than a vector store and neither needs one.

### Decision

**Do not build Phase C.** The named alternative is the right spend:
`PHASE22_HANDOFF.md` §6 Step 3 — constraining the architect for simple and
medium apps — which targets the variance the catalogue actually shows.

The honest caveat: the catalogue is 24 diagnosed defects across ~43 builds of
four shapes, all from one project's history. It cannot prove precedent would
*never* help. It is decisive about priority rather than about possibility —
nothing here is bottlenecked on precedent, so precedent is not what to buy next.
Revisit only if a failure ever appears that a similar prior build would plainly
have prevented. None has yet.

---

## 0.-5 The tenth session (2026-09-01) — row 3 ran, and failed

**Row 3 is red. Phase 23 does not close.** Build `885804e4`, `unusable`,
222,068 tokens (157,242 fast / 64,826 heavy), 1863s. Corpus after: one diff,
the new build itself, no regressions.

**Quota was never 21 hours out.** Part 0's snippet summed a hard rolling 24h
window, the model `llm_client.py:531-548` discarded in favour of a leaky bucket.
Its own output was the tell — 225,254 used against a 200,000 limit. Fixed in
`1b8793c`. The row started the moment the bucket was read instead.

### The symptom

`app/main.py` shipped importing five routers under aliases and then ignoring all
five:

```python
from routers.suppliers import router as suppliers_router   # ...and 4 more
...
app.include_router(router)   # x5, the bare name, never bound
```

`NameError` at import: every endpoint unreachable, and all four test modules
error on collection because they import `app.main`.

**The generator did not write this.** That was the obvious reading and it is
wrong — the pipeline's own deterministic "repair" produced it. See §0.-5.1a.

### 0.-5.1 ~~Remediation found the right file and repaired the wrong ones~~

> **WITHDRAWN — this was wrong, and it was my hypothesis, not a measurement.**
> I claimed the repair budget was spent in `failed_files` order and that nothing
> ranked the list by causality. Reading `agents/pipeline.py:1818` disproves it:
> `self.debugger.run(failed_paths, ...)` is handed **every** failing path, so
> `app/main.py` got the full budget — three attempts, a second pass, and two
> remediation passes. Ordering was never the problem.
>
> Kept rather than deleted because the correction is the point: the record
> *looked* exactly like a prioritisation bug, and the fix for a prioritisation
> bug would have changed nothing. See [[a-checker-is-a-hypothesis]] — it applies
> to a diagnosis as readily as to a verifier.

### 0.-5.1a The actual root cause: a deterministic "fix" that was the defect

`agents/debugger.py::_preflight_fix` carried a single-router rule from the
`weather_router` era:

```python
if filename == "main.py":
    new = re.sub(r'from routes import \w*router\w*', 'from routes import router', content)
    new = re.sub(r'app\.include_router\(\w*router\w*\)', 'app.include_router(router)', new)
```

The second substitution rewrites **every** `include_router(<alias>)` to
`include_router(router)`. A multi-entity build imports one router per entity
under distinct aliases, so this collapses five distinct names into one that is
bound nowhere — and reports it as `"fixed router import name"`.

Proven directly, at zero token cost: feed it correct multi-router code and it
emits exactly the file that killed row 3.

**It did the damage twice.**

1. `_preflight_fix` runs over every file in `Debugger.run()` *before* any
   debugging, so the generator's correct output was broken before it was ever
   checked. The `NameError` was manufactured by the pipeline.
2. `_debug_file` calls `self._preflight_fix(file_to_fix)` **immediately after**
   `create_file(file_to_fix, fixed)`. So each accepted LLM repair was written
   and then reverted in the next statement. Reproduced live: three writes per
   attempt — `1206 chars` (the correct fix), then `1146`, then `1147`, the
   broken original. `repair_guard` had **accepted** the fix both times
   (`RATIO_LOG: [(True, 1.0514, 1147, 1206), ...]`).

That is where 222,068 tokens went: the debugger re-fixing a file this function
re-broke after every success.

**Fixed.** The collapse now only rewrites a name that cannot already resolve —
the file does not bind it, and it does bind `router`:

```python
bound = top_level_symbols(new)
if "router" in bound:
    ... rewrite only names not in `bound`
```

The `routes.py` half carried the same assumption and now skips the rename when
`router` is already defined, which would otherwise put two routers on one name.

**Verified:**

- 8 new tests (§4.44). **5 of them fail against the old code**; the other 3
  encode the behaviour that must *not* regress and pass in both directions.
- Suite **829/829**. Corpus re-recorded and clean.
- End to end on the real broken file, with the real debugger and a real LLM
  call: **`success: False` after 3 attempts and 3,252 tokens → `success: True`
  on attempt 2 for 1,711 tokens**, with all five aliases restored. That verdict
  change is the evidence; the corpus alone could not have supplied it, because
  the corpus verifies finished projects and never invokes `_preflight_fix`.

**The lesson, and it is new:** every previous defect in this phase was a
verifier reporting something false. This one was a *repair* silently undoing a
correct fix — invisible to the corpus by construction, invisible to 829 tests,
and indistinguishable in the build record from "the LLM could not fix it". The
only thing that found it was watching the file being written three times.

### 0.-5.2 `module_ref` also misdescribed it — real, but not the cause

Secondary, and downgraded from what I first wrote: this misled the repair agent,
it did not kill the row. `tools/module_ref_check.py` emitted

> "(the application itself is unaffected)"

**purely on whether the *reading* module is a test file**, with no knowledge of
whether the *referenced* module is broken. On row 3 that sentence went into the
remediation advisory while `app.main` was dead, next to "Add `router` to
`app.main` — do NOT ... point it at a different name", which is the opposite of
this defect's correct repair.

**Fixed narrowly.** The routing is untouched — `in_test` still gates fatality
(`module_ref_check.py:682`) and manual routing, which is §4.26 and is right. Only
the false health claim is gone; the finding now scopes itself to what the checker
knows ("a finding about the test module, not about the application"). Corpus
effect: **28 findings reworded, 28 NEW/GONE pairs on identical
`(project, reference, line)`, zero verdict changes.**

### 0.-5.2a The tester wrote a test for a test

Row 3 also shipped `tests/test_test_suppliers.py`. Remediation repaired the
failing `tests/test_suppliers.py`; `_retest_files` handed the repaired paths
straight back to `Tester.run()`; and `_discover_testable_files` accepted one —
the file has a `def` in it, so it looked testable. It excluded `__*`,
`config.py` and `conftest.py`, but nothing said "this is already a test".

It cost twice: LLM calls to write something worthless, and a **spurious failing
test file** — it errored on collection with `TypeError: 'mappingproxy' object
...`, which was one of the five errors counted against `generated_tests` and so
drove further repair. It fires on any build where remediation repairs a test
module, which is the common case.

**Fixed** with `_is_already_a_test()`, placed *before* the `TESTABLE_FILES`
name match — that match claims a file by bare name and would otherwise take
`tests/models.py`. It follows pytest's own convention (`test_*.py`, `*_test.py`)
plus the directory, since a helper beside the tests is not a subject either.

**Verified.** 12 new tests (§4.45), suite **840/840**. Falsified by disabling
just the filter and re-running discovery on the row 3 shape:

```
WITHOUT fix: app/main.py, app/routers/suppliers.py, tests/models.py, tests/test_suppliers.py
WITH fix   : app/main.py, app/routers/suppliers.py
```

A directory merely *containing* "test" (`latest/`) is not a tests directory, and
that is asserted rather than assumed.

**The corpus says nothing here, and that is not a pass** — it verifies finished
projects and never invokes the tester, exactly as it never invokes
`_preflight_fix` (§0.-5.1a). Two defects in one session that the corpus cannot
see by construction is the pattern worth carrying forward: **the corpus covers
verifiers, not the agents that write and repair code.**

### 0.-5.3 The §B2 assertions, honestly

| Assertion | Result |
|---|---|
| `module_ref` is `verified` | **NO** — `failed`, but legitimately: the app really is broken. Not the old phantom `*Create` findings. |
| `schema_attr` reports, and is not `not_applicable` | **PASS** — `verified`, 14 models field-by-field, 0 skipped. §4.37 holds live. |
| A write endpoint returns 201 | **NOT REACHED** — the app never started. |
| Zero `not_run` | **PASS** — no `not_run` outcomes. |
| `grep -c "does not parse"` is 0 | **PASS**, but read it from the build record: `server.log` was 26 lines (block-buffered), so grepping *it* is vacuous. |
| Test-only routing reads as a pass | **Correctly did NOT apply** — `module_ref` had one test-module finding *and* real app findings; per-finding routing kept the row red. §4.39 behaved. |

### 0.-5.4 Cost

**222,068 tokens against a planned ~87-98K** — more than double; the fast model
went 29,653 → 150,944 in one row. The overrun is remediation: two passes plus a
degraded third across six files. Budget future rows on this figure, not the
2026-08-30 one.

---

## 0.-4 The ninth session (2026-08-31) — Part A of the plan, complete

Zero tokens. **820/820** tests, up from 765. Every no-quota item in
`PHASE23_NEXT_SESSION_PLAN.md` Part A is closed, so **what remains for Phase 23
needs a live row**. `SESSION_PROGRESS.md` §0.0 is the summary; this is the
per-defect detail.

**§4.39 — the record said `failed` after the pipeline had concluded
`verified`.** `_verify_other_shapes` assigned `result.verification_outcomes`
*before* the manual-routing loop, so a check whose every finding had been handed
to the user as manual testing was still recorded FAILED.

Nothing inside the pipeline noticed, because the routing itself was right: the
findings reached `_manual_checks`, the build was not degraded, and
`collect_findings(counted)` returned the correct list. The damage was one layer
out. That record is what `GET /jobs/{id}/status` serves and what
`run_live_matrix.verification_verdict` judges a matrix row on, and the driver's
`MANUAL_CHECKS` names only `generated_tests`. **A build that works, shipping one
test file with a bad import, failed its row** — §4.26's decision undone by the
driver rather than by the pipeline.

Reproduced before fixing: a project with a verified `runtime_smoke` and a single
undefined name in `tests/` recorded `module_ref: failed` and the driver read
`FAIL -- failed: module_ref`.

The write now happens after routing, mapping each recorded outcome through the
rewrite. **Only a *partly* routed check is rewritten.** A wholly routed one
(`generated_tests`) deliberately stays FAILED, because the driver excludes it by
name and prints `"; for manual testing: generated_tests"` — the shape §4 of the
runbook documents as a *passing* row with a broken suite. Rewriting it would
delete that signal.

Sixteen tests, driving the real `verification_verdict` rather than comparing
check-name tuples. That distinction is the point: three existing tests asserted
that `Pipeline._MANUAL_WHEN_WORKING`, `RemediationReport.manual_checks` and
`run_live_matrix.MANUAL_CHECKS` "agree", and **all three compared the constants,
not the record**, so none of them could have caught this.

> This was introduced by the eighth session, was green in 765 tests and in every
> corpus sweep, and was found by **planning the live run** — by asking what the
> driver would read out of the API. See §0.-4.1 below.

**§4.40 — `feature_coverage` was matching on the wrong word.** It reported 5/5
corpus projects verified and four of those five passes were on a word unrelated
to the evidence:

| requested | passed on | the actual evidence |
|---|---|---|
| "tag filtering" | `tag` | `filter_bookmarks` — `_normalise` never stripped `-ing` |
| "a frontend that lists bookmarks" | `bookmark` | a `frontend/` directory, never collected |
| "adds a bookmark through a form" | `bookmark` | a form written by `app.js`, never read |
| "reverse a rename" | `rename` | `undo_log` — a synonym |

Three of the four are fixed. `-ing` stripping is guarded to leave five
characters, so `string` cannot become `str`. Directory names join the
vocabulary, but only for directories that contain a file — the architect
scaffolds empty ones, and an empty `frontend/` must not satisfy "a frontend
that...". Structural HTML elements are read before the markup is discarded, and
read out of `.js` too, because a plain-JS frontend ships a page that is one
empty div and writes its form at runtime. Only tag *names* come out of
JavaScript, never free words.

**The threshold tightening still does not ship.** Re-measured after these fixes,
requiring a word not shared with another requested feature flips 5 features down
to 2 — but both survivors are still wrong, and they sit on
`bulk_file_renamer_912f9b22`, the first plain `done` in this project's history.
**Synonyms are now the single remaining blocker.**

**§4.41 — `repair_guard`'s floor measured, its ratio made self-answering.**
`_SMALL_FILE_CHARS = 120` now has evidence: of 551 generated `.py` files
(median 1,024, p90 2,472) it exempts 109, and those are 91 `__init__.py`, 16
ungenerated stubs and exactly **two** real files. It exempts files containing
nothing worth deleting, which is what its docstring claimed. The number does not
move.

The 0.6 ratio could not be validated the same way and was **not** moved on a
second guess: a repair's before/after pair exists nowhere in this checkout —
`generated_projects/` is untracked, there are no `.orig` files, and the `files`
table stores paths, not content. `RATIO_LOG` now records every decision in both
directions (a threshold that only sees its rejections cannot be told it is too
strict), so the next live build produces the distribution this one cannot.

**§4.42 — the commonest reason a build missed `done` was a complete file.** The
gate is `degraded = bool(report.unresolved)`. Its four file-based conditions,
measured across all 42 saved projects:

| condition | projects | findings |
|---|---|---|
| **placeholders** | **23** | **23** |
| python_imports | 5 | 5 |
| js_imports | 1 | 1 |
| stub_functions | 2 | 2 |

`_audit_placeholders` fires more than the other three together. Asked whether it
described the product or the scaffolding, the answer was neither: **14 of the 42
files it reported were fully written** — every one a `requirements.txt` holding
real packages that `requirements_builder` had appended while leaving the
scaffold comment on line 1. Those 14 spanned 14 projects, most with no other
placeholder finding, so a finished file was the entire reason they could not
reach `done`. `_has_substance` asks the direct question instead; 23 projects
reporting drops to 10, and all 10 survivors were read back as genuine two-line
stubs.

The root cause upstream is already handled — `requirements_builder` calls
`_strip_scaffold_placeholder` on both write paths, and the corpus files predate
it — but the audit rule was wrong independently, and for every file type it
reads.

**Settled by the same audit, needing no change: "100% of generated tests
passing" is no longer a `done` condition in practice.** Both test conditions
feed `_test_suite_issues`, and `_hand_over_test_suite_findings` removes them
once something has executed the artifact. §4.26 already routes them correctly.
Item 10 in §0.-0.5 is answered.

**§4.43 — the template literals `web_asset_check` was skipping.** The skip is
documented precision-over-recall, so the question was whether it hid anything.
42 fetch/axios call sites across the corpus, 34 recognised, 8 skipped, all 8 the
same shape — and **one of the eight is a real defect**:
`task_manager/src/components/Board.js` calls `/boards/${board.id}/tasks` against
a backend serving only `/tasks/` and `/tasks/{task_id}`.

Now checked by collapsing each `${...}` to one path segment and reusing
`_route_matches`, which already treats a declared `{item_id}` as a wildcard.
Still skipped, because these would be guesses: a relative template, one opening
with an interpolation (the `${BASE}` shape, already handled), and one whose
interpolation is named like a path (`${routePath}`, `${endpoint}`) since it
could expand across a slash. The corpus diff is exactly that one finding.

### 0.-4.1 The thing this session should be remembered for

**The corpus cannot see the layer above it.** §4.39 was green in 765 tests and
in every corpus sweep. `tools/verify_corpus.py` checks a *verifier's verdict*;
it does not check what the pipeline **records**, what the API **serves**, or
what a consumer **does with it**.

When a change alters a verdict, trace the value to its consumer and assert
there. For a check, that means driving `run_live_matrix.verification_verdict()`
on the recorded outcome — not comparing constants, which is what the three
"these three places agree" tests were doing while the bug sat between them.

Two smaller lessons, both about what a measurement is for:

- **A measurement can say "leave it alone."** §4.41's floor was confirmed and
  kept; its ratio was instrumented rather than moved, because nothing here can
  measure it.
- **A measurement can find what a code review would not.** §4.42's defect was
  invisible in the code — the rule reads correctly — and obvious the moment the
  conditions were counted across real builds.

---

## 0.-3 The eighth session (2026-08-31) — row 3's blocker, and two non-changes

Zero tokens. 765/765 tests. `SESSION_PROGRESS.md` §0.0–§0.2 is the summary;
this is the per-defect detail.

**§4.35 — a name the other file never defined.** New
`tools/module_ref_check.py`, registered in `_verify_other_shapes` and in
`verify_corpus.py` as `module_ref`. It reports a reference to a name that a
project module does not define: `from X import Y` where `Y` is absent, and
`mod.Name` where `mod` is a project module without a `Name`.

Row 3 is the case it was written for. `backend/routes.py` reads
`models.SupplierCreate` in a function signature, in a file with no
`from __future__ import annotations`, so the annotation is evaluated eagerly and
the module dies at import — the whole API, not one endpoint.

What it will not say anything about, and why each one is load-bearing:

| skipped | because |
|---|---|
| a module doing `from x import *`, `globals()[...]`, `setattr`, `__getattr__` | it can grow names the source does not show |
| a file that does not parse | it may define anything; another check reports the parse failure |
| an import spelling two files could both claim | resolution would be a guess |
| a local rebound anywhere in the reading file | the binding no longer certainly names the module |
| a read inside `try/except AttributeError` (or `ImportError`, or bare) | the author is probing on purpose |

That last row is not a precaution, it is a **measured false positive**. The
first corpus sweep reported `inventory_system_90ee973f`, whose `routes.py` opens

    try:
        LowStockReport = schemas.LowStockReport
    except AttributeError:
        class LowStockReport(BaseModel): ...

reading a name that really is absent from `schemas.py` and then supplying it.
The code is correct and the route serves. Reporting it would have told a working
build it was broken and spent an LLM call "fixing" a fallback.

A second gap was found by its own test rather than the corpus: a submodule
reached through its package (`from . import open_mod`) was bound without ever
consulting the open-module index, so a module doing `import *` was checked
anyway. Both directions now go through one `resolve`.

**The corroboration.** Of the 8 builds `module_ref` calls fatal, every one
independently fails to boot under `runtime_smoke` or `cli_smoke`, and three of
those runtime errors name the very same missing symbol. No static check in this
repo has had better evidence behind it.

**§4.36 — fatality is scoped to the application, and routing had to get
finer.** A test module that cannot import is a broken suite; §4.26 settled that
this is not a broken build. So `module_ref` never marks fatal from a test file,
its test-file findings say in their own text that the application is unaffected,
and it offers them for manual routing via `evidence["manual_findings"]`.

`Pipeline._verify_other_shapes` now honours that per-finding. `_MANUAL_WHEN_WORKING`
routes a whole check, and one check can now report both kinds — the same
undefined name is fatal in `backend/routes.py` and advisory in
`tests/test_routes.py`. Whole-check routing could only have hidden the first or
degraded a working build for the second. When every finding is routed the
outcome becomes `verified`; when only some are, the rest still count.

**§4.37 — `schema_attr` stops shrugging.** A project with POST/PUT/PATCH routes
and zero pydantic models is a `failed`, not a `not_applicable`. Measured before
it was written: of 32 `web_api` builds in the corpus, exactly one matches, and
it is row 3. A read-only API legitimately needs no schemas and still answers
`not_applicable`.

**§4.38 — the prompt states the contract it broke.** `MODELS RULE` in
`prompts/backend_developer.txt` was one line ("models.py is a flat file with
Pydantic classes only") against a failure mode that reads nothing like it. It
now carries the shipped failure and a ❌/✅ pair, matching every other rule in
that file, and says the thing the model actually got wrong: *every name another
file reads off models must exist in models.py*, an ORM class cannot be a body
annotation or a `response_model`, and an API with write routes and no Pydantic
models is always wrong.

### The two changes that were measured and dropped

Both were on the open-defect list. Detail in `SESSION_PROGRESS.md` §0.1; the
short version is that neither survived the corpus.

**`feature_coverage`'s "distinctive word" tightening** would have flipped five
features from covered to missing, and **four of the five flips are wrong** —
"tag filtering" is implemented as `filter_bookmarks` (the normaliser does not
strip `-ing`), "reverse a rename" as `undo_log` (a synonym), and two more on
vocabulary the check never collects. The real finding is sharper than the one
on the list: the check passes 5/5 corpus projects and **four of those passes are
on the wrong word.** Fix the vocabulary and the normaliser before the threshold.

**A `node --check` pass over generated JavaScript** finds 1 failure in 31 files,
and it is a two-line placeholder the placeholder audit already covers. Not worth
its false-positive surface (JSX in a `.js` file fails it legitimately).
Executing a plain-JS frontend still needs a DOM and stays open.

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

> **That decision has been made (2026-08-31): a broken test suite is not a
> broken build.** `generated_tests` is reported everywhere and decides nothing.
> When another check has executed the artifact and found it sound, its findings
> are routed to the user as **manual testing** rather than counted against the
> build — so a build that serves 7/7 routes finishes `done`, not
> `done_with_context`, and its row passes. With no such positive evidence the
> findings stay advisory and still count, because then they corroborate what the
> other checks already suspect.
>
> Three places implement the one rule, and a test asserts they agree:
> `Pipeline._MANUAL_WHEN_WORKING` routes the findings,
> `RemediationReport.manual_checks` carries them, and
> `run_live_matrix.MANUAL_CHECKS` keeps them out of the row verdict. The shipped
> `SESSION_CONTEXT.md` grows a **"Worth Checking By Hand"** section, separate
> from "Remaining Work", which says the application was executed and verified
> and that these are the things the automated checks could not confirm.

**§4.33 — the sys.path shim outranked `__future__`, and killed row 3.**
Row 3 (`inventory_system_3322017e`) shipped **`unusable`** with its entire API
unimportable. `backend/models.py` was generated *correctly*, with
`from __future__ import annotations` on line 1. `Debugger._inject_syspath` then
prepended its `sys.path` block above it, pushing the future import to line 10 —
and Python refuses the file outright: *"from __future__ imports must occur at
the beginning of the file"*. The generated code was right and the pipeline broke
it, which is this phase's recurring lesson: **a red verification result is a
hypothesis about the pipeline first.**

`_inject_syspath` accounted for a shebang and a module docstring, but not for
the one import the language requires to come first. It now finds the insertion
point with `ast` — handling multi-line `from __future__ import (a,
 b)` and
repeated future imports — with a conservative line-scan fallback for files that
do not parse, which is exactly when this runs. Six variants are tested; five of
them were `SyntaxError` before.

This could break **any** generated file using `from __future__ import
annotations`, which modern generated Python uses constantly. It is the highest
-value thing waiting on the next live row.

### What row 3 proved, and what it cost

Three of this session's changes fired live for the first time, all correctly:

| | |
|---|---|
| **§4.22** ledger reconciliation | A real 429 arrived and re-anchored the ledger by **+102,730 tokens** |
| **§4.31** `EXECUTING_CHECKS` | The only VERIFIED check was `feature_coverage`, which is *static* — correctly **not** counted as evidence the app works |
| **§4.26** manual-check routing | Because nothing executed the artifact, the `generated_tests` failures were **counted against the build** rather than handed over as manual testing |

`static_smoke` was correctly `not_applicable` (no HTML page), the phantom-defect
count was **0**, and the `unusable` verdict fired instead of the build shipping
as `done_with_context`. The driver recorded
`verified: NO — failed: runtime_smoke; for manual testing: generated_tests`.

**On the ledger, a number worth keeping.** The build's own accounting says it
spent **19,031** tokens on `20b`; the ledger moved ~121K and the 429 added
102,730. Those reconcile, which means the ~103K was **accumulated drift, not
this row's spend**. The "121,484 left" that authorised the row was substantially
wrong, and the fast model ran dry after ~19K of recorded consumption. Treat
`--dry-run` as even weaker evidence than §0.-1 already says.

**§4.34 — one import convention, enforced rather than requested.** Row 3's
second blocker, now diagnosed and fixed. `backend/main.py` used the forbidden
`from backend import models` beside a correct `from routes import router`, while
`routes.py` used `from . import models`. Either convention alone works — the
flat one is what the sys.path shim exists to support — but the mixture cannot:
loading `routes` flat breaks its relative import, and the shim is what makes the
flat load happen.

**This is the model disobeying an explicit instruction, not a pipeline defect.**
`prompts/backend_developer.txt` says "All backend/ files are siblings ... NEVER:
from backend.x  from ..x". Measured across the saved builds: **39 violations in
10 of them** — 28 package-qualified, 11 relative. Systemic, not a row-3 fluke,
so `Debugger._normalise_sibling_imports` now enforces it deterministically
(zero-token) as step 0 of `_apply_structural_import_repairs`.

Conservative by construction: a line is rewritten only when the module it names
resolves to a real sibling file beside the importer, so a third-party package
called `backend` is untouched; an unparseable file is left for another pass
rather than regexed; and a second pass is a no-op.

### Still open from row 3 — a third, deeper defect

Normalising the imports on a clone gets the app past both blockers and straight
into a **third**: `routes.py` references `models.SupplierCreate`,
`models.ProductCreate`, `models.WarehouseCreate` and
`models.StockMovementCreate`, and **`models.py` defines none of them** — it
holds only SQLAlchemy ORM classes (`Base`, `Supplier`, `Warehouse`, `Product`,
`StockMovement`). The prompt required the opposite: *"models.py is a flat file
with Pydantic classes only. No database code."*

No import fix reaches this. It also explains a signal that was easy to skim
past: `schema_attr` reported `not_applicable — this project declares no pydantic
models`, which for a FastAPI build with 18 routes is not a neutral fact. **A
FastAPI project with zero Pydantic models is itself suspicious**, and the check
currently says nothing about it. That is the next thing to look at.

**§4.32 — a static page had to be served to count as verified.**
`§4.31` raised the obvious question: is `runtime_smoke` reaching everything it
should? Measured, not assumed — and **it is**. Of the 30 builds with no verified
executing check, 22 had `runtime_smoke` *run and fail* on real 5xx, 6 had
`cli_smoke`/`package_smoke` run and fail, and 2 (`project`, `todo_app`) contain
no code at all, only handoff markdown. A per-shape matrix confirms every real
shape already has an applicable executing check, **so `runtime_smoke` was not
extended.**

What the measurement did expose is a gap `§4.31` created. `build_shape` can
report `static_frontend`, and for a project that is *only* a static page every
executing check answered `not_applicable` — `web_asset_check` parses the page
and runs nothing. So a legitimate static-page build could no longer show
evidence of working at all, and the architect is no longer forced to emit a
FastAPI backend, so "build me a landing page" produces exactly that shape.

`tools/static_smoke.py` serves the project over real HTTP on an ephemeral port
and fetches the page plus every local asset it references. Deliberately **no
headless browser**: the claim it makes is exact — the page and the files it asks
for are served, not that the JavaScript behaves. Remote URLs are skipped, so a
CDN being down never fails a build, and the server is always torn down.

Validated across all 41 builds before it was wired to anything: 32
`not_applicable`, 7 `verified`, 2 `failed` — and **both failures confirmed real
by hand** (`llm_api_key_dashboard` and `task_manager` ship pages loading an
`index.js` that is not there).

> **On overlap, which is worth stating.** `web_asset_check` already reports
> those two, so `static_smoke` finds no *new* defect in the corpus. Its value is
> the execution evidence — 7 builds now have a verified check that actually ran
> them. Where the two do overlap, the finding **defers** ("`web_assets` names it
> in full") rather than filing one defect twice under two check names. The case
> only execution can reach — a file that exists but is unreachable from the
> page's directory — is reported in full.

Two honesty fixes found on the way:

- `runtime_smoke` skipped with `"no FastAPI entry point found"` while actually
  searching via `detect_shapes`, which understands Flask and `create_app()`
  factories too. A skip message that names a narrower search than the one
  performed is how a miss reads as a legitimate skip — which is what happened to
  row 4. It now says what it looked for. A `test_phase22` assertion pinned to
  the literal phrase now asserts the substance instead.
- `sql_schema` returned `verified` for a project with no SQL — the vacuous pass
  that was the *only* verified check `project` and `todo_app` had. It now reports
  `not_applicable`, as `schema_attr` and `web_assets` already did.

Baseline re-recorded deliberately: 69 changes, all of them either a new
`static_smoke` entry (41) or a `sql_schema` flip to `not_applicable` (28), and
nothing else.

**§4.31 — "verified" meant "inspected", not "executed".**
`is_evidence_of_working` returned True for any VERIFIED outcome, but half the
checks never run what they inspect: `feature_coverage`, `web_assets`,
`schema_attr` and `sql_schema` read the source and nothing else. A green static
check was therefore read as proof the artifact runs.

Measured on the baseline: **27 of 41 builds have a verified static check and no
verified executing one**, and two of them — `project` and `todo_app` — **passed
the row criterion on `sql_schema` alone**, with nothing ever having been run.
The criterion's own sentence, "at least one check actually executed it", was
implemented as `status == "verified"`.

`tools/verification.EXECUTING_CHECKS` now names the four checks that run the
artifact (`runtime_smoke`, `cli_smoke`, `package_smoke`, `generated_tests`), and
both `is_evidence_of_working` and `run_live_matrix.verification_verdict` require
membership. A row verified only statically now fails, and says so: *"nothing
executed the artifact — it was only read statically (sql_schema)"*.

This also repairs §4.26, which was shipped earlier the same day: the
manual-testing gate keys off the same property, so a failing test suite could
have been handed over as "the application was verified" on the strength of a
static check. It cannot now.

**§4.30 — telling a broken test from broken code, before repairing either.**
The pipeline repaired in two directions at once and consulted no evidence about
which side had failed:

| Path | Rewrites | Wrong when |
|---|---|---|
| `Tester._test_file` (`_fix_tests`, 3 attempts) | the **test** | the source is wrong — it teaches the test to accept a real bug |
| `Pipeline._diagnose` → debugger | the **source** (`TestResult.file_path`) | the test is wrong — repairs a file that was never at fault |

The second is wasted tokens; the first is worse, because a test rewritten to
match buggy behaviour removes the only evidence the bug exists. `accept_test_reply`
catches a repair that *deletes* a failing test, not one that edits an assertion
to expect the wrong value.

`tools/test_blame.py` classifies each failure by the **deepest frame of the
traceback** — where the exception was finally raised, which is not the same as
the file being imported. `ai_report_generator` fails `NameError: name 'List' is
not defined` while importing a test, but raises it in the source: a real defect.
Row 2's `conn.close()` on the `None` from `init_db()` raises in the fixture: a
test defect.

Three verdicts, and the third is the load-bearing one. **Assertions are
AMBIGUOUS, not test defects** — an assertion always executes in the test file,
but the expectation can be right and the code wrong. So is anything unparseable.
Ambiguity anywhere leaves both repairs enabled, exactly as before.

Measured over all 41 saved builds before it was wired to anything: 65 source
defects, 41 test defects, 40 ambiguous. **18 builds stop rewriting the test, 7
stop repairing the source, 9 are unchanged, and no build appears in both lists.**
Row 2 is deliberately *not* among the 7: its two assertion failures sit beside
four fixture errors, so the ambiguity holds it back.

> **The catch that justifies the corpus run.** The first version parsed only
> `File "...", line N`, which is `--tb=native`. The tester runs `--tb=long`,
> whose frames read `tests/test_api.py:6: AttributeError`. Against real pipeline
> output it attributed nothing and changed no behaviour — it failed safe and did
> nothing, and only running it against the corpus showed that. Both formats are
> parsed now, and both are tested.

**§4.29 — the tester keeps working; only its residue is handed over.** The
`tester` step runs the generated suite with real pytest and a failing test is
often the only sign that the code *under* test is wrong, so it must keep driving
repair — `TestResult.file_path` names the file to fix, and it still reaches the
debugger. What changed is the ending. Once the build has been verified and
repair has had every pass it gets, a suite that still does not run is not a
defect in a working application: `_hand_over_test_suite_findings` moves it to
manual testing. With no evidence the artifact works it stays outstanding.

Both exits from `_remediate` route, not just the one that runs repair — the
advisory-only exit is exactly how a build whose only finding is "no executable
backend tests were generated" reaches the user, and it was missing the routing
at first. The finding list is rebuilt on every `_diagnose`, so a second
diagnosis that finds nothing clears a finding the first one recorded rather than
carrying it into the shipped document.

> **A correction to what §4.24 said.** It claimed nothing executed the generated
> tests. That was wrong: `agents/tester.py` has always run them with real
> pytest, per file, and failures have always reached the checklist — row 2's own
> shipped checklist said "Generated tests fail for 1 file(s): tests/test_api.py
> (1/3)". The real gap was narrower: no entry in the **verification record**, so
> `verified: yes` could sit beside a dead suite. What `generated_tests` adds is
> running the suite *as a whole, from the project root, the way a user would*,
> which is how it found 4 fixture errors where the per-file tester scored 1/3.

~~A cost this leaves open, deliberately.~~ **Addressed by §4.30 above**, and
the framing there was backwards: the tester rewrites the *test*, so its three
attempts are right when the test is wrong and actively harmful when the source
is. The cause is now split rather than the attempts capped — `MAX_TEST_FIXES`
is still 3, but the attempts are spent only when the test is the thing that can
be fixed. Tokens remain recorded per build rather than per step, so the exact
saving is still not separable without new instrumentation; what is measurable is
that 18 of 34 failing builds no longer spend rewrites on a source defect, and 7
no longer spend debugger passes on a test defect.

**§4.27 — the shipped document described a mid-build state.** `issues` and
`diag_advisory` came from the diagnosis that ran *before* remediation and were
reused verbatim at the end, so the re-scan below only half-worked: the checklist
still described the build as it had been, not as it shipped. The final re-audit
now re-runs `_diagnose` in full. It is a static re-scan and costs no tokens.

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

### Phase B1 done (2026-08-31) — persistence on SQLAlchemy + Alembic

The plan's first sub-phase, and the one auth was blocked behind. Storage is
SQLAlchemy (`api_platform/db/`), schema changes are Alembic revisions, and
**nothing above the seam changed**: `runner.py`, all five route modules,
`main.py` and three test suites call the same functions, which return the same
dicts with the same keys and the same types. Only the bodies moved.

| | |
|---|---|
| `api_platform/db/models.py` | `Project` / `ProjectFile` / `BuildProgress`, mirroring the DDL column for column |
| `api_platform/db/__init__.py` | Lazy per-URL engines, `DATABASE_URL` or the current `DB_PATH` |
| `alembic/versions/0001_baseline` | The schema as it stood at the end of Phase 23. Meant to be **stamped**, not run |
| `alembic/versions/0002_indexes` | `build_id` on files and build_progress, `created_at` on projects |

**The live database was migrated and every row survived**: 73 projects, 1,164
files, 1,023 progress rows, now stamped at `0002_indexes`. A status poll's query
plan reads `SEARCH build_progress USING INDEX ix_build_progress_build_id`
where it used to be a full scan of all 1,023 rows.

Four things worth carrying forward:

- **`created_at` is `String`, not `DateTime`, deliberately.** Every writer stores
  `.isoformat()` and every reader treats it as a string. Declaring `DateTime`
  would make SQLAlchemy hand back `datetime` objects — a change to the type every
  route returns, wearing the costume of a schema definition.
- **File-backed SQLite uses `NullPool`.** A pool holds the file open, and on
  Windows an open handle makes it undeletable; three suites point `DB_PATH` at a
  temp database and delete it, and they failed with `PermissionError [WinError 32]`
  the moment this pooled. SQLite gains nothing from pooling anyway. The
  `pool_size=3` the plan asked for applies to Postgres, where it earns its keep.
- **The engine resolves lazily, per URL.** An engine bound at import would ignore
  a reassigned `DB_PATH` and quietly read and write the *real* `platform.db`
  while the tests still passed — the worst available outcome.
- **`stamp` and `upgrade` are both needed.** Stamping alone leaves a database at
  the baseline forever, and `create_all` cannot help: it creates indexes only for
  tables it creates, so the live database had none of them.

`datetime.utcnow()` is gone from `database.py` and from `runner.py` (8 calls),
replaced by `datetime.now(timezone.utc).replace(tzinfo=None)` — aware for the
deprecation, naive on the way to disk so the ~1,000 existing timestamps still
sort and compare against new ones.

**B2 (JWT auth + multi-tenant isolation) is now unblocked**: it needs an
`owner_id` column on `projects` and a `users` table, which is a revision now
rather than another `ALTER TABLE ... except OperationalError`.

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
7. ~~**`web_asset_check` skips what it cannot resolve confidently**~~ —
   **closed 2026-08-31 (ninth session), §4.43.** Measured first: 8 of 42
   fetch/axios call sites were skipped, all one shape, and one of the eight was
   a real defect. Template literals with a recoverable static shape are now
   checked; genuinely dynamic ones are still skipped. Original note: a URL built
   from an unknown base, a template literal that does not start with a base
   constant. Deliberate (precision over recall), but it is a recall gap.
8. ~~**`_functional_verdict` matches strings in findings.**~~ **Fixed
   2026-08-30 (evening).** A verifier that establishes the artifact does not run
   calls `outcome.mark_fatal(reason)`, and the verdict reads the field. The
   string markers remain as a fallback for findings that reach `unresolved` from
   paths with no outcome, and when they fire with nothing structured behind them
   the log says so — that gap is how this silently stops working. §49.
9. ~~**`repair_guard`'s thresholds are judgment, not measurement**~~ —
   **addressed 2026-08-31 (ninth session), §4.41.** The 120-char floor is now
   measured against the corpus and kept (of 551 files it exempts 109: 91
   `__init__.py`, 16 stubs, 2 real). The 0.6 ratio is **not** measurable here —
   no before/after pair exists in this checkout — so it is instrumented via
   `RATIO_LOG` rather than moved on a second guess, and the next live build
   produces the distribution. Original note: a 0.6
   shrinkage ratio above 120 chars. Better than the old 0.5-above-400, still
   unvalidated against a corpus.

### Older, still open

10. ~~**The nine-condition `done` gate is reachable but unexamined.**~~ —
    **audited 2026-08-31 (ninth session), §4.42, and it found a real defect.**
    `_audit_placeholders` dominates the gate (23 of 42 projects, against 5/2/1
    for the other three file-based conditions) and **14 of its 42 findings were
    on files that were fully written**. Fixed. Also settled: "100% of generated
    tests passing" is no longer a condition in practice — §4.26 already routes
    those findings to manual testing once something has executed the artifact.
    Original note: It ANDs
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
