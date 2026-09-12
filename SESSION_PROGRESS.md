# Session Progress — start here

**UPDATE 2026-09-12, later the same day — the matrix is 3 of 4 and row 2 is
`done`.** `test_phase23.py` is **1131/1131**. A checker bug, not a model, was
the blocker. Full detail in `PHASE23_CLOSEOUT.md` §5.

> ## ▶ What changed, and the one thing that is still wrong
>
> **`sql_schema` counted generated TEST fixtures as application schema.** A
> table created only in a fixture masked a table the app never creates, and
> because the Tester rewrites fixtures every remediation pass, the mask lifted
> and fell between passes — so row 2's `bookmarks_tags` defect only became
> visible after both repair passes were spent. Fixed by applying the existing
> `_is_test_file` to the schema scan. Falsified: with the guard off the mask
> returns. Corpus: **zero** `sql_schema` diffs; rows 1 and 3 unchanged.
>
> **Row 2 `3aea19e3`: 0/11 routes -> 11/11 after ONE remediation pass**, status
> `done`, 93,797 tokens. First time row 2 has reached `done`. It declares 11
> routes including the `by_tag` filter the previous build omitted entirely, and
> its responses now carry `id` and `tags`, which the previous build dropped.
>
> **But `done` + verified OVERSTATES this artifact, and the reason is new.**
> Hand-run: `POST /bookmarks/` with the optional `tags` field returns **500**.
> Two causes, both worth carrying forward:
>
> 1. The `schema_attr` repair declared `tags: List[TagRead]` on
>    `BookmarkCreate` to satisfy the checker, while the handler iterates those
>    entries as tag NAMES (`SELECT id FROM tags WHERE name = ?`). Every shape a
>    caller can send is rejected or 500s. **The repair made the finding go away
>    rather than the defect** — the standing first-order defect, again.
> 2. **`runtime_smoke` sends REQUIRED FIELDS ONLY**, by design
>    (`_example_model`: "the smallest body the model will accept"). A defect
>    reachable only through an optional field is structurally invisible to it.
>    That is a real hole, and it is why an 11/11 build ships a 500.
>
> Also still true of this build: `description` is accepted and silently
> dropped — `INSERT INTO bookmarks (url, title)` never stores it.

---


**Last session: 2026-09-12 (Phase 23 — the SEVENTEENTH session). PHASE 23 IS
CLOSED.** `test_phase23.py` is **1122/1122**. Read **`PHASE23_CLOSEOUT.md`**
first — it is the judgement on the phase and supersedes the ▶ block below,
which described work that is now done.

> ## ▶ Phase 23 closed — what a next session needs to know
>
> **The phase closed on the bar the user set on 2026-09-12**: the generated app
> need not be perfect, but the structure must be there and the handoff must say
> honestly what to do by hand. **All four rows meet that.** Under the driver's
> stricter criterion the matrix is 2 of 4 (rows 1 and 3); under the written
> criterion read literally it is 4 of 4. All three readings are recorded in
> `PHASE23_CLOSEOUT.md` §0 — do not re-derive them.
>
> **Both re-run rows improved, and both were hand-verified against the running
> artifact, not just read off the record.**
>
> * **Row 4** (`bc9d1317`, `done_with_context`, 80,093 tokens) is the **first
>   row-4 build ever to satisfy the whole prompt** — rename, pattern, dry-run
>   and undo all work through `cli.py`. It still ships a second, redundant
>   `main.py` that crashes (`'str' object has no attribute 'rglob'`), which is
>   why `cli_smoke` failed it, correctly.
> * **Row 2** (`464da0fb`, `done_with_context`, 90,937 tokens) went from
>   `unusable` at 0/6 routes to **6/6 responding**. The prompt thread rule and
>   `_repair_db_paths` both landed live. Tag filtering was never wired to a
>   route, and its one open `sql_schema` finding is **latent dead code** — real,
>   but nothing calls it.
>
> **The blocker remains generation quality, not verification.** Every check that
> fired this session was correct and none fired on working code.
>
> **The next concrete task, with the clearest evidence it has ever had:**
> `call_arity` compares argument COUNTS, not TYPES. Row 4's `main.py` passed it
> with the right count and the wrong type. Falsify on the corpus first — 4 of 6
> new verifiers have reported defects that did not exist.

### §0.-20 The handoff document lied in two directions, and both are fixed

Found by reading what a real build shipped, not by reasoning about the code.

1. It asserted *"The application itself was executed and verified"* for every
   build with any manual-check item — including `01cde425`, whose every endpoint
   returned 500. Now conditional on `unresolved`. Missing tests deliberately do
   not trip it. **Confirmed live** on row 2's new build.
2. It listed only defects, so a build serving all five CRUD endpoints read as
   broken. A **What Already Works** section is now built from
   `verification_outcomes`, using only checks that EXECUTED the artifact and
   passed — `not_applicable`, `not_run` and `failed` excluded, section omitted
   entirely when nothing qualifies. **Takes effect on the next build**; the two
   builds above predate the wiring and their docs were deliberately not
   hand-edited.

---


**Last session: 2026-09-08 (Phase 23 — the fourteenth session).**
`test_phase23.py` is **1049/1049**. **All four rows have now run against this
code.** The matrix stands at **2 of 4** — rows 1 (`156f73a3`, `done`, 5/5) and 3
(`1134f369`, 21/21). Rows 2 and 4 both recorded `unusable`, for entirely
different reasons: row 2 earned it, row 4 did not.

> ## ▶ Next session: re-run row 4, then row 2
>
> **RESTART THE SERVER FIRST, and confirm it is newer than the code.** The row 4
> re-run (`fd473b61`, **78,530 tokens**) was spent for nothing: the server began
> at 21:05, `tools/cli_smoke.py` was fixed at 22:27, and `--no-reload` means the
> process was still running the pre-fix check. It failed for the identical
> reason the fix addressed. The tell: the build recorded `cli_smoke: failed`
> while running the fixed check by hand against that same artifact returned
> `verified`. **When a live build and a hand-run of the same check disagree,
> suspect the server's code age first.** This is trap #2 in
> `PHASE23_QUOTA_RUNBOOK.md` §5 — read that session and violated anyway.
>
> ```bash
> venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1 --log-file row.log
> # then prove the server is newer than every file you edited:
> ls -la --time-style=+%m-%d\ %H:%M tools/ agents/ llm_client.py | sort -k6
> venv/Scripts/python.exe run_live_matrix.py --dry-run
> venv/Scripts/python.exe run_live_matrix.py --rows 4      # ~88K — do this first
> venv/Scripts/python.exe run_live_matrix.py --rows 2      # ~129K
> ```
>
> **Quota at hand-off: the fast model is at 0**, heavy at ~75,000. From empty
> the fast model needs ~10.8h to clear its 90,000 floor, so this session opens
> with a real wait. The server has been restarted and IS holding the fixed code.
>
> **Row 4 first: its artifact is already known to be sound.** Every check was
> verified or correctly not-applicable and `generated_tests` **passed** — the
> first time in this phase. It was recorded `unusable` only because `cli_smoke`
> ran it under a cp1252 stdout and a non-breaking hyphen (U+2011) in its
> argparse description crashed `print_help()`. Fixed; re-running `cli_smoke` on
> the untouched artifact returns **verified**. The build record cannot be edited
> into a pass, so the row needs one clean run to count.
>
> **Row 2's cause is now detectable and its repair is unproven.** It created its
> tables in `bookmark.db` and served every request from `bookmarks.db`, so all
> nine endpoints answered 500 `no such table` while `sql_schema` reported
> "3 table(s) created, 3 queried — verified". `sql_schema` now compares the
> database each module opens as well. Whether the repair *lands* is exactly what
> the re-run measures.
>
> **Two things in row 2 have no repair channel at all**, so expect them to
> survive the re-run:
> - `static_smoke`/`web_assets` publish no `repair_targets`. The `/static/*`
>   404s come from `os.path.abspath("../frontend/static")` resolving against the
>   CWD, in a file that computes `_parent` two lines above.
> - `delete_tag` was targeted-repaired twice without converging. The cause is
>   not the arity channel: `module_ref` generated the three missing service
>   functions from their **call sites** (`get_all_tags(db)`) while every
>   original function in that module opens its own connection
>   (`delete_tag(tag_id)`), leaving one file with two calling conventions.
>   `module_ref` was deliberately left alone — it works, and validating a change
>   to it needs a live build.
>
> **Operational, learned this session.** `--rows 4,2` runs in MATRIX order, not
> the order typed — row 2 went first and its 93K on the fast model then blocked
> row 4 at the 90,000 floor. And `--dry-run` printing "no daily figures
> available" means **no spend in the window** (a full bucket), not missing data.

### §0.-19 The row 4 re-run, and what it did and did not prove

`fd473b61` — **78,530 tokens, wasted.** See the restart warning above. The
artifact itself is sound: running the fixed `cli_smoke` against it returns
`verified`, and every other check was verified or correctly not-applicable.
`generated_tests` failed here (3 failed / 9 passed) where the earlier build
passed 12 — so that check is not reliably green on this shape, and it does not
decide the row either way.

**What it did prove, and this is worth keeping.** The fast->heavy fallback now
has a demonstration under *real* exhaustion rather than near-exhaustion. Both
earlier instances began with 73-76K on the fast model; this row began with
**29,053 fast / 114,183 heavy**, deliberately far below the floor, and the
fallback fired mid-build:

```
23:01:48 WARNING llm_client: Fast model [openai/gpt-oss-20b] is quota-exhausted
         for [Tester]; retrying on heavy model [openai/gpt-oss-120b], which has
         its own daily budget.
```

Twice, both for the **Tester** as predicted, and the build completed on heavy:
37,479 fast / 41,051 heavy, the fast model ending at literally 0.
`llm_client.py:2166` is the branch. The rule that follows: starting below the
fast floor is survivable when the heavy model holds more than the row's FULL
two-model cost, because heavy can absorb all of it — that is the number to
check, not the fast shortfall. It stays an informed exception, since the run
still ends the day's fast budget.

### §0.-18 What the fourteenth session fixed — commit `4308acc`

1. **`cli_smoke` judged a working CLI by its own console.** It ran
   `subprocess.run(text=True)` with no encoding and no `PYTHONIOENCODING`, so
   both the child's stdout and the parent's decoding defaulted to cp1252.
   `tools/assert_row.py` had the identical bug. Now UTF-8 on both sides. Corpus
   after the fix: 5 CLIs still fail (one hand-checked — a real
   `ModuleNotFoundError`), 5 verified, 38 not applicable.
2. **`sql_schema` compares databases, not just statements.** Anchored on the
   entry module, because row 2 had a `CREATE TABLE` in *both* files and
   anchoring on the schema fell silent on the very build it was written for.
   Falsified across 47 projects: exactly 1 flagged, the true positive.
3. **The driver polled finished builds for 45 minutes.** It omitted `unusable`
   from its copy of the server's terminal statuses; it imports
   `api_platform.runner.TERMINAL_STATUSES` now.
4. **The driver silently deleted rows it had carried.** Its merge pattern could
   not read back the `yes *(earlier run)*` marker it writes itself, and a
   non-matching line is skipped rather than raised on. This had already erased
   row 3 — a passing row — from the matrix. Restored from the API record.

**The corpus baseline is 149 diffs stale and was deliberately not re-recorded.**
All but two are `route_presence`/`call_arity`/`await_sync` never baselined after
an earlier session added them; the two real ones are the documented
`feature_coverage: verified -> not_run` pair. Re-record only after reading them.

---

**Last session: 2026-09-06 (Phase 23 — the thirteenth session).**
`test_phase23.py` is **1029/1029**. Four rows ran. The last one is the **first
row in this project's history to PASS its own criterion**: `1134f369`,
`done_with_context`, **21/21 routes responding**, all six §B2 assertions green,
`driver verdict: PASS`.

**The phase still does not close, and the reason is not a defect.** The criterion
is >= 3 of 4 rows, and only row 3 has run against this code.

> ## ▶ Next session: run rows 1, 2 and 4
>
> **This is now a matter of running, not of finding defects.** Five defect
> classes were found and closed across four rows; the checks catch every failure
> mode seen so far and none of them fires on a working build.
>
> **Quota: ~1 day.** Three rows at ~130K each. Check with
> `run_live_matrix.py --dry-run`, which is the authority, and note the ledger
> under-reports by ~51K.
>
> ```bash
> venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1 --log-file row.log
> venv/Scripts/python.exe tools/verify_repairs.py --baseline repair_baseline.json
> venv/Scripts/python.exe run_live_matrix.py --dry-run
> venv/Scripts/python.exe run_live_matrix.py --rows 1,2,4
> venv/Scripts/python.exe tools/assert_row.py <FULL-UUID> row.log     # per row
> ```
>
> **What each row exercises that row 3 does not.** Row 2 is the only one with a
> frontend (`web_assets`, `static_smoke`); row 4 is the only CLI (`cli_smoke`,
> and `route_presence`/`dead_events`/`await_sync` should all report
> `not_applicable` — confirm that rather than assume it). Row 1 is the simple
> shape and should be the cheapest pass.
>
> **Then, if a row still fails:** `generated_tests` fails on essentially every
> build and has never had a repair channel. Measure before building one —
> `tools/test_blame.py` exists to say whether the failures are test defects or
> source defects. And the repair-guard contract (§0.-17) is the standing
> structural item.
>
> Full detail: `PHASE23_HANDOFF.md` §0.-16 (both rows), §0.-17 (the decisions
> taken, and what remains).

## §0.-4f Seven rows, and what each one cost to learn

| run | outcome | endpoints | the defect it exposed |
|---|---|---|---|
| `d1b98d57` | `done_with_context` | 1/22 | 23 undefined service functions → `module_ref` repair targets |
| `c2d4a4d4` | `done_with_context` | 13/22 | a model field never declared; 2 tables never created |
| `e3894a9e` | **`unusable`** | 0 routes | routers in an `on_event` a `lifespan` disables → `dead_events` |
| `9733027d` | **`unusable`** | 0 routes | routers declared and wired, no handlers → `route_presence` |
| `51d80952` | **`unusable`** | 0 routes | the `routers/` package held only `__init__.py`; route repair made to land |
| `78097ea4` | `done_with_context` | 3/22 | a call arity mismatch AND an await on a `def` → `call_arity`, `await_sync` |
| `1134f369` | `done_with_context` | **21/21** | — **PASS** |

**Five defect classes, none visible at import time, every one found by measuring
a build rather than reasoning about it.**

## §0.-4g What the passing row does and does not prove

**It passed because the architect produced a working program.** `call_arity`
checked one call and passed; `await_sync` was `not_applicable`. Both correctly
stayed silent. Claiming the new checks caused the pass would be the same
reasoning error this file keeps recording.

**What IS established:** no check fires on a working build — the property whose
failure costs an LLM call and tells a user their working build is broken — and
the verdict is trustworthy in both directions now. `feature_coverage` can no
longer read `verified, 6/6` against 0 routes, which it did on four builds.

**What is NOT established:** anything about rows 1, 2 and 4. One row is not the
criterion.

## §0.-4h The measurement that mattered most

Row 6 shipped with EVERY static check verified and 3 of 22 endpoints working.
Fixing the two defects one at a time, on a clone:

| fixed | endpoints |
|---|---|
| nothing | 3/22 |
| the awaits only | 3/22 |
| the one call only | 3/22 |
| **both** | **17/22** |

Neither alone moves it, which is why two remediation passes achieved +1. **A
defect that does not improve the number when fixed alone is not thereby the
wrong defect** — and the only way to know was to fix them one at a time and
re-run the probe.

## §0.-4d Five rows, and the symptom that will not go away

| run | architecture | outcome | cause |
|---|---|---|---|
| `d1b98d57` | single router, raw sqlite3 | `done_with_context`, 1/22 | 23 undefined service functions |
| `c2d4a4d4` | multi-file, raw sqlite3 | `done_with_context`, 13/22 | a model field never declared; 2 tables never created |
| `e3894a9e` | SQLAlchemy, `routers/` package | **`unusable`**, 0 routes | routers in an `on_event` a `lifespan` disables |
| `9733027d` | SQLAlchemy, single `routes.py` | **`unusable`**, 0 routes | six routers declared and wired, **no handlers written** |
| `51d80952` | SQLAlchemy, `routers/` package | **`unusable`**, 0 routes | the `routers/` package holds **only `__init__.py`** |

**Zero routes, three consecutive rows, three unrelated causes.** No cause has
ever recurred. The symptom has now recurred twice.

**Every closed defect still holds.** `module_ref`, `schema_attr` and
`dead_events` all verified on row 5; `sql_schema` correctly `not_applicable`.

**The checks are no longer the gap.** On row 5 `route_presence` fired, named the
file, and published a working repair target; `feature_coverage` returned NOT_RUN
instead of the `verified, 6/6` it used to give a dead build. Both ran live for
the first time and both were right.

**The repairs are the gap.** The route repair fired
(`🛣️  Declaring routes on 1 router(s)`), generated handlers, and they failed the
import check — restored, correctly, but not fixed. Two other correct repairs
were lost the same day: one to the guard, one to a regression below.

## §0.-4e The regression the row caught, which this project introduced itself

The twelfth session changed `llm_client` so a 4xx stops instead of rotating keys.
The reasoning — *"a 4xx is a problem with the request, so rotating cannot help"* —
is true of a malformed request and **false of the 400 this system produces**.

The same commit's other half proved it. Logging the response body printed the
reason for the first time: **"Tool choice is none, but model called a tool"** —
the model emitting a tool call that was never offered, which is stochastic. Row
4's log settles it: all four of its 400s recovered on the very next attempt.

It cost row 5 a whole remediation pass, twice over — the `break` also returned
`None` from a function whose callers expect "text or raises", and that `None`
reached a regex three frames away.

Fixed: a bounded retry (3), and giving up now raises with the server's reason.

**And the test for it passed for the wrong reason.** It asserted a comment
string, and the corrected code still contained that string — in a comment
quoting the old reasoning to explain it. Rewritten to read the branch's control
flow out of the AST. This is the "do not let an assertion match its own
documentation" rule failing in the wild.

## §0.-4c What the twelfth session shipped, and what each was falsified against

| change | what it does | falsification |
|---|---|---|
| `tools/dead_event_check.py` | an `@app.on_event` a supplied `lifespan=` disables | 46 projects: 11 verified, 1 true positive, **0 false positives**. **Proven live: `verified` on row 4.** |
| `tools/route_presence_check.py` | a `web_api` that declares no route at all | 48 projects: 35 verified, **3 failed — `runtime_smoke` independently fails all 3**, and 2 were unknown before |
| `feature_coverage` verdict | stops reporting `verified` against 0 routes | the entire corpus diff is 2 builds going `verified -> not_run`; nothing else moved |
| `llm_client` 4xx handling | a 400 stops instead of rotating all 8 keys, and the body is logged | unit-tested; row 4 burned 4 keys on 4 doomed 400s |

**The two checks are complementary, not redundant** — and an earlier draft of the
handoff got this wrong. `route_presence` reports row 3's build as `verified`,
correctly: its handlers ARE declared, in `routers/product.py`, and merely never
registered. `dead_events` is what catches that one. The symptom needed a check
of its own *in addition to* the cause-specific one, not instead of it.

## §0.-4b The four rows, and the thing that changed at row 4

| run | architecture | outcome | why |
|---|---|---|---|
| `d1b98d57` | single router, raw sqlite3 | `done_with_context`, 1/22 endpoints | `routes.py` called 23 functions `services.py` did not define |
| `c2d4a4d4` | multi-file, raw sqlite3 | `done_with_context`, 13/22 | a model field never declared; 2 tables never created |
| `e3894a9e` | SQLAlchemy, `routers/` package | **`unusable`**, 0 routes | routers registered in an `on_event` that a `lifespan` disables |
| `9733027d` | SQLAlchemy, single `routes.py` | **`unusable`**, 0 routes | six routers declared and wired, **zero route handlers anywhere** |

**Every fix still holds.** `module_ref`, `schema_attr` and `dead_events` all read
`verified` on row 4; `sql_schema` correctly `not_applicable`. No closed defect
has ever come back.

**But the SYMPTOM recurred, and that is new.** Rows 3 and 4 both shipped an
application with zero routes, from causes with nothing in common. Until row 4
the honest headline was "no defect has recurred, so the repairs are generalising";
that is now only true of *causes*. The repairs generalise and the checks do not,
because each check was written from the one row that produced it.

**`feature_coverage` recurred too, and it is a check, not a build.** It read
`verified, 6/6, "0 route(s)"` on both rows — printing its own disproof beside its
verdict. It is the one component that has now vouched for two builds that serve
nothing.

**The finding existed and nothing could act on it — for the fourth session
running.** On row 4 the BackendDeveloper diagnosed the empty router exactly
("this file creates an APIRouter but defines no route handlers") and its repair
was thrown away by `accept_generated_fix` as *"an oversized rewrite"*. An empty
router gaining ~22 handlers can only grow, and the guard forbids growth. That
guard has now blocked a *correct* repair three times (§0.-12).

**The build log works and is measured.** 75KB+ of full agent trace, against the
1,567-byte stubs of four sessions. `grep -c "does not parse"` is **0**;
§4.41's `RATIO_LOG` has **1** near-miss, and it is a test file — weak evidence
that the 0.6 shrink threshold is not what is costing repairs. The growth rule is.

## §0.-4 The three rows, and what each one proved  *(superseded by §0.-4b)*

> **Superseded 2026-09-05 by §0.-4b, and kept.** Its closing claim — *"no
> defect has recurred"* — was true of the three rows it describes and is no
> longer true of four: row 4 repeated row 3's **symptom** from an unrelated
> cause, and `feature_coverage` repeated its false green outright. How that
> conclusion looked right on three rows is the useful part, so it stands.

| run | architecture | outcome | why |
|---|---|---|---|
| `d1b98d57` | single router, raw sqlite3 | `done_with_context`, 1/22 endpoints | `routes.py` called 23 functions `services.py` did not define |
| `c2d4a4d4` | multi-file, raw sqlite3 | `done_with_context`, 13/22 | a model field never declared; 2 tables never created |
| `e3894a9e` | SQLAlchemy, `routers/` package | **`unusable`**, 0 routes | routers registered in an `on_event` that a `lifespan` disables |

**Each fix held on the following run.** `module_ref` went failed → verified and
its repair fired again in row 3. `schema_attr` and `sql_schema` came back
verified / correctly `not_applicable`. Every row then failed on a defect the
previous one did not have.

**Architect variance is now the dominant obstacle.** Three runs, three different
programs; no defect has recurred. The repairs generalise — the surface they must
cover keeps moving.

**Every static check passed a build that serves nothing.** Row 3's
`feature_coverage` read `verified, 6/6, "5 route(s)"` against an app with zero
routes at runtime; `debug_score` 8/8, `review_score` 7.0. Only the executing
check caught it, which is the entire argument for the "at least one check must
EXECUTE the artifact" criterion.

**The quota fallback is proven live.** Row 3 was started deliberately below the
90,000 fast floor (49,894 left); the fast model ran dry, `generate_text` moved
the rest to heavy (149,741 → 45,091), and the row completed instead of dying at
the wall. Until 2026-09-03 that branch had no test at all.

## §0.-3 What that session changed, in one table

| | |
|---|---|
| **The pattern** | Three defects, one shape: the repair goes to the file the traceback names, which is the *caller*. The file that must change is named only in the finding, and findings were advisory strings. |
| **`module_ref`** | Publishes `repair_targets`; repaired by `Debugger.run(missing_definitions=...)`, which **appends in batches** — a whole-file rewrite cannot fit Groq's 8,000-token minute and `accept_generated_fix` rejects growth by design. Proven live: row 2 of 2. |
| **`schema_attr`** | Same gap, same fix; repaired by `missing_fields`, which **rewrites**, because a field belongs inside an existing class. |
| **`sql_schema`** | Had **never run during a build** — it lived only in `verify_corpus`. And it was **inert**: its regex required a trailing `;`, which `cursor.execute("CREATE TABLE ...")` never has, so it parsed no schema and checked no column. Fixed, wired in, and taught to report a queried table nothing creates. |
| **Falsification** | 48 corpus projects: 4 `not_applicable → verified` (never checked before), 1 true positive, **0 false positives**, 0 checks going quiet. |
| **`start_server.py --log-file`** | The 1,567-byte logs were not buffering — that diagnosis was wrong. Output never reached the file; it is the detached launch. |
| **`tools/assert_row.py`** | The §B2 assertion table, executable. |

## §0.-2 The first half of that session, in one table

| | |
|---|---|
| **Row 3, run 1** | `d1b98d57`, `done_with_context`, 117,191 tokens, 21/22 endpoints 500. `routes.py` called 23 functions `services.py` did not define. |
| **The finding named the repair; nothing could act on it** | `module_ref` said "Add `get_suppliers` to `backend.services`" 23 times. Shape findings are advisory strings, and the only channel producing a repair *target* is a 5xx traceback — which names the caller. Both LLM passes rewrote the correct file. |
| **`evidence["repair_targets"]`** | New. `module_ref` publishes the file that must DEFINE each name; the pipeline repairs that file. |
| **`Debugger.run(missing_definitions=...)`** | New channel — such a file *imports cleanly*, so every existing hook, which needs a traceback, passed it. Appends in batches of 5: a whole-file rewrite cannot fit Groq's 8,000-token minute and `accept_generated_fix` rejects growth by design. |
| **Call sites in the prompt** | The name existing is not the call working: a probe added all 23 names and still 500'd on `create_supplier(name, contact_email)` versus a route passing one Pydantic model. |
| **Row 3, run 2** | `c2d4a4d4`, 114,240 tokens. `module_ref` **verified**, endpoints **13/22**, unresolved **10**, tests **12/12**. The repair fired live — `services.py` is in `failed_files` *and* `repaired_files`. |
| **Two defects of the same shape remain** | `schema_attr` (advisory-only, same gap) and a queried table never created (traceback names the reader, not the DDL). Specified, deliberately **not** shipped without a row to prove them. |
| **`start_server.py --log-file`** | The 1,567-byte logs were never a buffering problem — the first diagnosis was wrong. Output never reached the file; it is the detached launch. |
| **`tools/assert_row.py`** | The §B2 assertion table, executable, calibrated against both rows. |

## §0.-1 What the tenth session changed, in one table

| | |
|---|---|
| **Row 3 ran and failed** | `885804e4`, `unusable`, 222,068 tokens. Cause: `_preflight_fix` collapsed five router aliases onto one unbound name, *and* re-broke the file after every accepted LLM repair. The generator was correct. |
| **`tools/verify_repairs.py`** | New. Replays the debugger's zero-LLM repair sequence and asserts a file that imported before still imports after. Found 4 defects; 21 harmed corpus files are now **1**. |
| **`repair_fixtures/`** | New. Every corpus build is single-router, so the corpus alone could not have caught the router defect. Three of the four defects were found only here. |
| **`feature_coverage`** | Measured across 39 projects instead of 5: ~2/3 of its findings are false, and widening its vocabulary would fix only 6 of 34. Routed to manual rather than tightened. |
| **Phase C** | **NO-GO.** 24 catalogued defects, 0 attributable to missing precedent. |

**Known-open, and not a blocker for row 3:** one harmed file
(`ai_pdf_reader/backend/search.py` — a flattened import colliding with a root
`ocr/` package), recorded in `repair_baseline.json`.

## §0.0 The five defects closed, in the order they were found

**§4.39 — the record said `failed` after the pipeline concluded `verified`.**
`_verify_other_shapes` assigned `result.verification_outcomes` *before* the
manual-routing loop, so a check whose every finding had been handed to the user
as manual testing was still recorded `failed`. Nothing inside the pipeline
noticed: the routing was correct, the build was not degraded, the findings
reached the user. The damage was one layer out — that record is what
`GET /jobs/{id}/status` serves and what `run_live_matrix.verification_verdict`
judges a row on, and the driver's `MANUAL_CHECKS` does not name `module_ref`.

**A build that works, shipping one test file with a bad import, failed its row.**
§4.26's decision undone by the driver rather than by the pipeline. Reproduced
before fixing, then fixed by writing the record after routing. Only a *partly*
routed check is rewritten; `generated_tests` deliberately stays `failed`,
because the driver excludes it by name and prints "for manual testing:
generated_tests", which is the shape a passing row with a broken suite takes.

This is the one that mattered: it was introduced by the eighth session and it
would have failed row 3 on a correct build.

**§4.40 — `feature_coverage` was matching on the wrong word.** It reported 5/5
corpus projects verified and **four of those five passes were on a word that had
nothing to do with the evidence**: "tag filtering" passed on "tag" while the
handler is `filter_bookmarks`; "a frontend that lists bookmarks" passed on
"bookmark" while the evidence is a `frontend/` directory; "adds a bookmark
through a form" passed on "bookmark" while the form is written by `app.js`.
Right by accident, four times out of five, and no verdict-level test could see
it because the verdict was correct.

Three vocabulary gaps closed: `-ing` stripping (guarded so `string` cannot
become `str`), directory names (only for directories containing a file, since
the architect scaffolds empty ones), and structural HTML elements read before
the markup is discarded — and read out of `.js` too, because a plain-JS frontend
ships a page that is one empty div and writes its form at runtime.

**The threshold tightening still does not ship.** Re-measured after the fixes it
flips 5 features down to 2, but both survivors are still wrong, and they are on
`bulk_file_renamer_912f9b22` — the first plain `done` in this project's history.
**Synonyms are now the single remaining blocker** (`reverse` vs `undo_log`),
which is a sharper answer than the one this started with.

**§4.41 — `repair_guard`'s floor measured, its ratio made self-answering.**
`_SMALL_FILE_CHARS = 120` now has evidence: of 551 generated `.py` files it
exempts 109, and those are 91 `__init__.py`, 16 ungenerated stubs and exactly
**two** real files. It exempts files containing nothing worth deleting, which is
what its docstring claimed. The number does not move.

The 0.6 ratio could not be validated the same way and was **not** moved on
another guess: a repair's before/after pair exists nowhere in this checkout —
`generated_projects/` is untracked, there are no `.orig` files, and the `files`
table stores paths, not content. It is instrumented instead. `RATIO_LOG` records
every decision in both directions, so the next live build produces the
distribution this one cannot.

**§4.42 — the commonest reason a build missed `done` was a file that was
complete.** The gate is `degraded = bool(report.unresolved)`. Its four
file-based conditions, measured across 42 projects:

| condition | projects | findings |
|---|---|---|
| **placeholders** | **23** | **23** |
| python_imports | 5 | 5 |
| js_imports | 1 | 1 |
| stub_functions | 2 | 2 |

`_audit_placeholders` fires more than the other three together. Asked the
audit's question — product or scaffolding? — the answer was neither: **14 of the
42 files it reported were fully written.** Every one a `requirements.txt` holding
real packages that `requirements_builder` had appended while leaving the scaffold
comment on line 1. Those 14 spanned 14 projects, most with no other placeholder
finding, so a finished file was the entire reason they could not reach `done`.

`_has_substance` asks the direct question instead. 23 projects reporting drops
to 10, and all 10 survivors were read back: genuine two-line stubs.

Also settled, needing no change: **"100% of generated tests passing" is no longer
a `done` condition in practice.** Both test conditions feed `_test_suite_issues`,
and `_hand_over_test_suite_findings` removes them once something has executed the
artifact. §4.26 already routes them correctly.

**§4.43 — the template literals `web_asset_check` was skipping.** The skip is
documented precision-over-recall, so the question asked was whether it hid
anything. 42 fetch/axios call sites, 34 recognised, 8 skipped, all 8 the same
shape — and **one of the eight is a real defect**:
`task_manager/src/components/Board.js` calls `/boards/${board.id}/tasks` against
a backend serving only `/tasks/`. Now checked by collapsing each `${...}` to one
path segment and reusing `_route_matches`, which already treats a declared
`{item_id}` as a wildcard. The corpus diff is exactly that one finding.

## §0.1 How much of this is evidence

Every change was measured against all 41-42 saved builds before being wired in,
and every corpus diff was explained in both directions:

- §4.39: no verdict moved. The 148-line diff was 74 findings out and the same 74
  back in — a wording fix — with identical (project, symbol) sets.
- §4.40: no verdict moved, **and that is the expected result** — every corpus
  feature was already passing, just for the wrong reason. The change is
  verifiable by the flip count (5 → 2) and by word-level assertions, not by a
  verdict.
- §4.42: 23 projects → 10, survivors read back by hand.
- §4.43: exactly one new finding across 41 builds, and it is real.

**What none of it proves.** Nothing here has run inside a live build. That has
now been true for four sessions, and row 3 remains the standing proof that it
matters: both of its blockers were invisible to all 41 saved builds, and one
fresh build found both. §4.39 is the sharpest example yet — it was found by
*planning* against the live-run path, not by any test or corpus sweep, and it
had been green in 765 tests.



---

## §0.2 The eighth session (2026-08-31)

**Zero tokens.**
`test_phase23.py` is **765/765**, up from 735. Row 3's actual blocker is closed,
and two changes that looked obviously worth making were **measured and not
shipped**, which is the more useful half of the session.

> **The executable plan for the next two sessions is
> [`PHASE23_NEXT_SESSION_PLAN.md`](PHASE23_NEXT_SESSION_PLAN.md).** Part A is
> the no-quota work in priority order — it opens with a defect this session
> introduced that would fail a *correct* live row. Part B is what to spend the
> refill on. Quota was ~22 h out when it was written.

## §0.0 What closed: the name the other file never defined

Row 3 (`inventory_system_3322017e`) shipped `unusable`. `backend/routes.py` was
written against `models.SupplierCreate`, `ProductCreate`, `WarehouseCreate` and
`StockMovementCreate`; `backend/models.py` defined **none of them** — only
SQLAlchemy ORM classes. Nothing in the pipeline looked for that. `schema_attr`
answered `not_applicable — this project declares no pydantic models`, which for
a FastAPI build with 18 routes is a red flag reported as a shrug: the models
were missing, and their absence is exactly what made the check decline to run.

Three things now:

**`tools/module_ref_check.py` (`module_ref`)** reads it off the source. One
level up from `schema_attr`: that one checks the *fields* of a class both files
agree exists, this one checks that the name exists at all. It resolves both
import conventions the pipeline produces — package-relative, and the flat
sibling form the debugger's `sys.path` shim creates — and skips everything it
cannot settle (a module doing `import *` or reaching through `globals()`, an
unparseable file, a spelling two files could claim, a rebound local).

**`schema_attr` no longer shrugs.** POST/PUT/PATCH routes and zero pydantic
models is a finding. Measured first: of 32 `web_api` builds in the corpus,
**exactly one matches, and it is row 3.**

**`prompts/backend_developer.txt`** states the cross-file contract the model
broke, with the failure that shipped, like every other rule in that file. The
`MODELS RULE` was a single line; it is now the same shape as the RESPONSE MODEL
and PYDANTIC VERSION rules beside it.

### How much of that is actually evidence

`module_ref` was run against all 41 saved builds before it was wired in.

* It reports **13**. The first sweep contained **one false positive**:
  `inventory_system_90ee973f` probes for a name it knows may be absent inside
  `try/except AttributeError` and supplies it. That code is correct and its
  route serves. A guarded read is now never a finding.
* Of the **8** builds it calls fatal, **every one independently fails to boot**
  under `runtime_smoke` or `cli_smoke` — and three of those runtime errors name
  the very same missing symbol (`ReportConfig`, `supplier_router`,
  `run_streamlit_ui`). That is the strongest corroboration a static check in
  this repo has had.
* Spot-checked by hand where the reasons differ: `ai_report_generator_cf00d934`
  really does have `from app import get_db` against an `app.py` defining only
  `main`; `ai_report_generator_941887e1`'s missing `get_weather` is a second,
  real defect the runtime probe never reached because the app died earlier.

**Fatality is scoped to the shipped application.** A test module that cannot
import is a broken suite, and §4.26 settled that a broken suite is not a broken
build. Those findings are reported, say in their own text that the application
is unaffected, and are handed to the pipeline for manual routing.

That needed a new mechanism: **per-finding manual routing**
(`evidence["manual_findings"]`). `_MANUAL_WHEN_WORKING` routes whole checks, and
one check can now report both kinds — an undefined name in `backend/routes.py`
stops the application, the identical defect in `tests/test_routes.py` stops only
that test. Whole-check routing could only have hidden the first or degraded a
working build for the second.

The corpus diff is the one intended `schema_attr` change and nothing else. The
baseline is re-recorded.

## §0.1 What was measured and deliberately NOT shipped

Both of these were on the open-defect list and both looked obviously worth
doing. Neither survived contact with the corpus. **Read this before picking
either back up.**

### `feature_coverage` — the tightening that would have broken four builds

The known gap: it matches on *any* content word, so "email notifications when
stock runs low" passes on a project with a `/low_stock/` route and no
notifications. The obvious fix is to require a match on a word **not shared with
another requested feature** — {email, notification} rather than {stock, low}.

Measured against `corpus_intents.json`: five features flip from covered to
missing, and **four of the five flips are wrong**:

| feature | flips because | actually implemented as |
|---|---|---|
| "tag filtering" | "filtering" ∉ vocab | `filter_bookmarks` — `_normalise` does not strip `-ing` |
| "reverse a rename" | "reverse" ∉ vocab | `undo_log`, `--undo-log` — a synonym |
| "a frontend that lists bookmarks" | "frontend" ∉ vocab | `frontend/` — directory names are not in the vocabulary |
| "adds a bookmark through a form" | "form" ∉ vocab | the page builds inputs without a literal `<form>` |

So the tightening would convert a documented recall gap into four fresh false
"you didn't build this" findings **on builds known to work** — precisely what
that module's docstring exists to prevent.

**The sharper statement of the defect**, which is what the next session should
carry: `feature_coverage` reports 5/5 corpus projects verified, and **four of
those passes are on the wrong word**. It is right by accident. The vocabulary
and the normaliser have to be fixed *first* — `-ing` stripping, directory names,
and something for synonyms — and only then can any tightening be trusted.

The two safe halves (`-ing`, directory names) were written and then dropped as
well: every corpus feature already passes, so they change **no verdict**, which
makes them an unverifiable change justified by reasoning alone. That is the
category this phase keeps getting burned by.

### A JavaScript check — one hit, and it was a stub

"A plain-JS frontend is never executed" is real: `frontend_debugger` and the
tester's Vitest path both require `frontend/package.json`, which that shape
lacks. Node 25 is on this machine, so `node --check` on every `.js` file was the
cheap candidate.

Measured across the corpus: **31 JS files, 1 failure**, and it is
`llm_api_key_health_dashboard/frontend/App.js`, a two-line placeholder
(`# Root React component`) that the placeholder audit already covers. A checker
earning one already-known hit is not worth its false-positive surface — and it
has one, since JSX in a `.js` file fails `node --check` legitimately.

**Executing a plain-JS frontend still needs a DOM**, and a hand-rolled `document`
shim would be a false-positive generator against exactly the code it is meant to
check. This stays open, and it stays a browser-or-nothing problem.

## §0.2 What is still open

Unchanged from the seventh session except where noted:

* **`feature_coverage`'s vocabulary is wrong before its threshold is** — see
  above. This is now the top no-quota item.
* **A plain-JS frontend is never executed** — measured, still open, needs a
  browser.
* `web_asset_check` skips URLs it cannot resolve confidently (recall gap).
* `repair_guard`'s thresholds are judgment, not measurement.
* The nine-condition `done` gate is reachable but unexamined.
* `node_frontend` has no executing verifier.

**And the part that is not on any list.** `module_ref`, the `schema_attr`
change and the prompt tightening have all been validated against 41 saved
builds and **none of them has run inside a live build.** Row 3 is the standing
proof that this matters: both of its blockers were invisible to all 41. The
corpus is free and it caught a real false positive again this session, but
"nothing left to fix" remains a claim no amount of offline work can support.

**The next row should be row 3 re-run.** It is the one build whose blockers are
now all supposedly closed — the `__future__` shim (§4.33), the sibling imports
(§4.34), and now the missing schemas — and it is the cheapest way to find out
whether any of that is true.



---

## §0.3 The seventh session (2026-08-31)

**Was the last session before the eighth.**
`test_phase23.py` is **705/705**, up from 541. Row 2 was rebuilt and **passes
the matrix criterion**, Phase B1 is done, and six defects were closed. The
session's most important results are not the row but what it exposed.

**The four findings worth carrying, in order of how much they change:**

1. **The token ledger under-reports by ~51,000** — a quarter of the daily limit,
   all optimistic. It records only calls that returned 2xx, so every 400, every
   429-rejected attempt and every retry is invisible. The start floors were
   therefore denominated in a unit that could not do their job. A 429 now
   re-anchors the ledger to Groq's own figure. **Between 429s the number is
   still optimistic: start a row with real margin over the floor, not just
   above it.**
2. **"Verified" meant "inspected", not "executed".** Half the checks never run
   what they inspect. 27 of 41 builds had a verified static check and no
   verified executing one, and two passed the row criterion on `sql_schema`
   alone with nothing ever having run. `EXECUTING_CHECKS` now gates it.
3. **A broken test suite is not a broken build** — the product decision, now
   implemented end to end. See below.
4. **34 of 41 saved builds ship a test suite that does not pass.** Nothing had
   noticed, because nothing ran them as a user would.

**The one-line version.** The token ledger only ever recorded calls that came
back 2xx, so it under-reported `gpt-oss-20b` spend by ~51,000 tokens — a
quarter of the daily limit — and the two start floors added the session before
were therefore denominated in a unit that could not do their job. Row 2 cleared
the 90,000 floor at "151,303 left" and ran the fast model dry mid-tester. The
429 that stops a build states Groq's own counter exactly; it is now fed back
into the ledger instead of into a log line. **Details and the two consequences
for planning: `PHASE23_QUOTA_RUNBOOK.md` §0.-1.**

### Phase B1 is done — persistence on SQLAlchemy + Alembic

The no-quota work item from the runbook. `api_platform/db/` holds the models and
engine, `alembic/` holds the revisions, and **no call site changed** — the
function signatures in `api_platform/database.py` were the seam and they still
are. The live database was migrated with every row intact (73 projects, 1,164
files, 1,023 progress rows) and now carries the lookup indexes the old
`ALTER TABLE ... except OperationalError` block could never add: a status poll
now does an index search instead of scanning all 1,023 progress rows.
`datetime.utcnow()` is gone from both `database.py` and `runner.py`.

Detail, and the four decisions worth knowing about, in `PHASE23_HANDOFF.md`.
**B2 (auth) is unblocked** — it needs a schema change, which is now a revision.

### A static page is now executed, not just read

`§4.31` made "verified" mean something ran the artifact. Measuring whether
`runtime_smoke` reached far enough showed it does — every real shape already has
an applicable executing check, so it was **not** extended. But a project that is
*only* a static page had no executing check at all, so `§4.31` left it unable to
demonstrate it works. `tools/static_smoke.py` serves the page over real HTTP and
fetches every local asset it references (no headless browser; it proves the
files are served, not that the JS behaves).

Validated across all 41 builds before wiring: 32 n/a, 7 verified, 2 failed, both
failures real. Also fixed two vacuous signals: `runtime_smoke`'s skip message
named a narrower search than it performs, and `sql_schema` returned `verified`
for projects containing no SQL.

### Repair now knows which side broke

`tools/test_blame.py` reads the deepest frame of each pytest traceback and says
whether the failure came from the test or from the code under test. The tester
no longer rewrites a test when the source is at fault (which would teach the
test to accept the bug), and `_diagnose` no longer hands the source to the
debugger when the test is at fault. Assertions and anything unparseable stay
ambiguous, so both repairs run exactly as before.

Validated against all 41 saved builds before being wired to anything: **18
builds stop rewriting the test, 7 stop repairing the source, none both.** The
first version of the parser handled only `--tb=native` while the tester uses
`--tb=long`, so it silently did nothing — the corpus run is what caught it.

### Row 2 — the result the runbook asked for

`bookmark_manager_e045ca2d`, `done_with_context` in 1752.5s, 173,307 tokens
(20b 100,673 / 120b 72,634). Driver verdict: **verified: yes**. ZIP 23,911
bytes, `PK` magic. Shape detected as `web_api+static_frontend`.

| Check | Verdict |
|---|---|
| `runtime_smoke` | verified — 7/7 routes, no 5xx |
| `web_assets` | **verified** — 1 page parsed, 3 frontend calls matched to 3 declared routes |
| `feature_coverage` | verified — 4/4 features |
| `schema_attr` | verified — 7 models, 0 undeclared reads |
| `cli_smoke`, `package_smoke` | correctly not_applicable |

Zero NOT_RUN. Phantom-defect count (`grep -c "does not parse"`) **0**. This is
the first time `web_assets` has run on a fresh build of the shape it was
written for, and **the React-vs-plain-JS prompt fix holds**: the generated
`app.js` has no bare specifier, no React and no axios, and `index.html` loads
it as a classic script.

Three of the sixth session's changes fired inside a live build for the first
time: `schema_attr_check` caught a real `AttributeError`-on-every-POST at
generation time, `repair_guard` rolled back a rewrite that fixed nothing rather
than shipping the churn, and the debugger repaired the defect in the file that
*declares* the field rather than the one that reads it.

### Two defects row 2 exposed, both since fixed

1. **A finding is recorded once and never re-read.** The shipped
   `SESSION_CONTEXT.md` tells the user to fix `bookmark.description` — a defect
   the debugger had already fixed by the end of the run, as `schema_attr`
   (verified, 0 undeclared reads) confirms. The build ships a checklist sending
   its reader after work that is already done.
2. **Nothing runs the generated tests.** The shipped `tests/test_api.py` is
   entirely dead — `reset_db()` does `conn = init_db(); conn.close()` and
   `init_db()` returns `None`, so all 4 tests error at fixture setup. The build
   is legitimately `verified: yes` at the same time, because no check in the
   six-check record executes the generated test suite.

**Both are now fixed** (`PHASE23_HANDOFF.md` §4.24-4.27), and the second fix
turned up something larger: **34 of the 41 saved builds ship a test suite that
does not pass.** Nothing had noticed because nothing ran them.

**A correction worth carrying:** the claim that "nothing executes the generated
tests" was wrong. `agents/tester.py` has always run them with real pytest and
its failures always reached the checklist. The real gap was that they had no
entry in the verification record, so `verified: yes` could sit beside a dead
suite. The tester still runs, still repairs, and is worth keeping.

**The rule that follows from it: a broken test suite is not a broken build.**
`generated_tests` is reported everywhere and decides nothing. When another check
has executed the artifact and found it sound, its findings are handed to the
user as manual testing — the shipped `SESSION_CONTEXT.md` grows a "Worth
Checking By Hand" section — and the build finishes `done` with its row passing.
With no positive evidence that the artifact works, they still count.

The same rule now covers the tester's own findings: it keeps running and keeps
driving repair during the build, but if the suite still does not run once the
build is verified, that goes to manual testing rather than degrading a working
product. And the shipped document describes the **final** state: the last
re-audit re-runs the whole diagnosis instead of reusing the one taken before
remediation.


**Last session: 2026-08-30, evening (Phase 23 — the zero-quota session).**
Committed on `main`, `76b331d`..`e47a79a`. `test_phase23.py` is **541/541**, up
from 491. Nothing in it spent a token; the plan for the next refill is
`PHASE23_QUOTA_RUNBOOK.md`.

*The session before it (`55d9121`..`94d52c4`) is the one described below: the
pipeline was reporting success it had not earned, and now does not.*

> **Backend/pipeline work has its own state doc: `PHASE23_HANDOFF.md`.** Read it
> first if you are touching `llm_client.py`, the agents, the pipeline or the
> platform API. This file remains the frontend and general entry point.

**The one-line version.** An empty list meant four different things — it passed,
it does not apply, it could not run, and there was nothing to look at — so a
build nobody had verified and a build that passed verification were the same
value. Every other defect this session hangs off that.

**A correction to what this file said yesterday.** Row 4's
`Runtime smoke test skipped (no FastAPI entry point)` was recorded here as proof
the non-web path worked. It was a **miss**: the architect had put a FastAPI app
in `bulk_file_renamer/main.py` and entry discovery only searched `backend/`,
`src/` and the project root. Row 4 shipped an unprobed web app *and* a CLI that
nothing executed, and passed the matrix criterion doing it.

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

**Everything about spending quota now lives in `PHASE23_QUOTA_RUNBOOK.md`** —
when a row can start, which row to start, what to assert when it finishes, and
the traps. Read it instead of re-deriving any of that here.

**Restart the server before anything.** It runs `--no-reload` deliberately, so a
running process holds the code it started with.

```bash
venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1
venv/Scripts/python.exe run_live_matrix.py --dry-run
```

~~**Check the FAST model by hand.**~~ **Fixed 2026-08-30 (evening).** The gate
took `max()` across models, so a row started whenever *either* was rich, while
`gpt-oss-20b` — which carries the tester, the reviewer and every remediation
pass — is the one that runs out. There are two floors now, 90,000 fast and
70,000 heavy, and `--dry-run` refuses per model against its own. The start that
went wrong on 2026-08-30 (20b at 73,286) is now refused.

### Row 3 ran, and the pipeline broke its own output

`inventory_system_3322017e` shipped **`unusable`**: `models.py` was generated
correctly with `from __future__ import annotations` first, and the debugger's
`sys.path` shim was injected above it, which Python refuses. **Fixed** (§4.33) —
the insertion point is found with `ast` now. This could break any generated file
using `from __future__`, and it is the top thing the next live row must prove.

Three changes fired live and correctly: the ledger reconciled from a real 429
(**+102,730**), `EXECUTING_CHECKS` refused to count a static `feature_coverage`
as evidence, and the test-suite findings were counted rather than excused
because nothing had executed the artifact.

A second blocker remains open: `main.py` mixes package and top-level imports for
sibling modules. See `PHASE23_HANDOFF.md`.

### Next session — start here

**The highest-value work needs no quota.** Row 3 dies on a defect nothing
checks for: `backend/routes.py` references `models.SupplierCreate`,
`ProductCreate`, `WarehouseCreate` and `StockMovementCreate`, and
`backend/models.py` defines none of them — it holds only SQLAlchemy ORM classes,
where `prompts/backend_developer.txt` demanded *"Pydantic classes only. No
database code."* `inventory_system_3322017e` is on disk and reproduces it for
free.

Two things follow, both zero-token:

1. **Make `schema_attr` say something.** It currently reports
   `not_applicable — this project declares no pydantic models`, which for a
   `web_api` shape with 18 routes is a red flag reported as a shrug. A FastAPI
   build with routes and no Pydantic models should be a finding.
2. **Tighten the prompt**, since the model put ORM classes where schemas were
   explicitly required — the same disobedience §4.34 had to enforce
   mechanically for imports.

Everything else still open is listed in `PHASE23_HANDOFF.md` §0.-0.5, in value
order, and summarised in memory (`pipeline-open-defects`).

**And the caveat that matters more than the list:** ten of the last eleven
changes have never run inside a live build, and row 3 showed why that is not a
formality — *both* of its blockers were invisible to all 41 saved builds. The
corpus caught neither §4.33 nor §4.34; one fresh build found both in a single
run.

### The quota picture



**Quota has refilled: `20b` ~121K, `120b` ~150K, and `--dry-run` says start.**
But read `PHASE23_QUOTA_RUNBOOK.md` §0.-1 first: the ledger is optimistic
between 429s, and 121K against a 90K floor is only ~31K of margin against an
error that has been measured at ~51K. Row 3 is the next row in the order and
costs ~87.5-140K with a high 20b share, so it is affordable but not comfortably.
Either wait a few hours for more margin, or start it knowing the dual-model
fallback may have to carry the tail.

**Everything below has been validated against saved builds and NOTHING has run
inside a live build.** That is what the next row is for:

| Waiting on a live row | Where |
|---|---|
| The ledger reconciling from a real 429 | §4.22 |
| `generated_tests` running inside the pipeline | §4.24 |
| The unrepaired-defect re-scan | §4.25 |
| Manual-check routing (a working build with a broken suite) | §4.26 |
| The final re-audit reporting final state | §4.27 |
| `test_blame` routing repair in anger | §4.30 |
| `EXECUTING_CHECKS` gating a real verdict | §4.31 |
| `static_smoke` on a freshly generated page | §4.32 |

### The order to work in

| # | Work | Quota | Why |
|---|---|---|---|
| 1 | **Row 2** | ~90-170K | The static-frontend and route-contract checks have never run on a fresh build. Row 2 is the shape they were written for |
| 2 | **Row 3** | ~90-140K | Its real score is knowable for the first time (§0.6), and `schema_attr` names three defects in the shipped one |
| 3 | **Row 1** | ~60K | The only row that has ever met the 0-5xx half of the criterion |
| 4 | **Phase B1** | none | `PHASE23_PLAN.md`; startable any time quota is short |

Full procedure, per-row assertions and the refill arithmetic:
**`PHASE23_QUOTA_RUNBOOK.md`**.

### What changed on 2026-08-30 (evening) — the zero-quota session

Seven changes, no tokens spent on any of them. The theme is the one this phase
keeps returning to: **a signal that existed and could not be read.**

| # | Change | What it removes |
|---|---|---|
| 1 | `tools/verify_corpus.py` + `verification_baseline.json` | Every verifier, run against all 40 saved builds on a throwaway clone, diffed against a committed baseline. A checker is a hypothesis until it has been run against a real build, and nothing made that cheap |
| 2 | `tools/schema_attr_check.py` | A field read that no model declares. Found row 3's `sku` and `contact`, a **third** in the same build (`mv.direction`, which no runtime probe can reach), and three in `_live_verify_row2_final` — the build the probe scores 6/6 green |
| 3 | Blame rule 4 reaches request-time failures | An `AttributeError` naming a class defined elsewhere was repaired in the file that only *reads* it, which can rename or silence and can never add a missing field |
| 4 | `accept_rescan` in `tools/repair_guard.py` | A rewrite whose defects survived stayed on disk, with the failure in a counter that was logged and discarded |
| 5 | `VerificationOutcome.mark_fatal` | `unusable` was decided by substring-matching finding text; rewording a finding silently stopped it firing |
| 6 | The web probe records an outcome | The most important check in the pipeline was the only one whose result lived nowhere but the server log |
| 7 | Two quota floors in `run_live_matrix.py` | A row starting on a fast model that cannot finish it |

`test_phase23.py` **491 → 541**. All other suites unchanged and green.

**What is NOT proven by any of it:** nothing here has run inside a live build.
Items 2-6 change what a build reports about itself, and only a row does that.

### What changed on 2026-08-30, and why

The pipeline reported success it had not earned. Three defects compounded:

1. **Silence read as success.** `_smoke_test_runtime` returned `[]` for a clean
   run, a missing entry point, an app with **zero routes**, and a tester crash
   that meant verification never ran at all. `report.unresolved` could not tell
   them apart.
2. **Only one shape was verified.** Entry discovery searched three directories
   for the literal string `"FastAPI("`. A CLI was never executed, a static page
   never parsed, a library never imported.
3. **The product was bent to fit that verifier.** `prompts/architect.txt` forced
   a FastAPI backend into every project "NO EXCEPTIONS", justified in its own
   text as *"required for the testing and debugging pipeline to function."*

Row 4 is what they cost together: it shipped `done_with_context` with a valid
ZIP, containing a FastAPI app at `bulk_file_renamer/main.py` that was never
probed (the search looked in `backend/`, `src/` and the root) and a CLI that
nothing executed. **The log line `Runtime smoke test skipped (no FastAPI entry
point)` was recorded in this file as proof the non-web path worked. It was a
miss, not a skip.**

### The new verification surface

| Tool | What it does | Cost |
|---|---|---|
| `tools/verification.py` | Four answers instead of an empty list: VERIFIED / NOT_APPLICABLE / **NOT_RUN** / FAILED. NOT_RUN is never `ok` | — |
| `tools/build_shape.py` | One detector every verifier keys off. Finds a web app anywhere in the tree, Flask as well as FastAPI, a `create_app()` factory as well as a module-level binding | 0 |
| `tools/cli_smoke.py` | **Runs the tool**: `--help` must exit 0 and print something, each subcommand must describe itself, a tool with required arguments must print usage rather than raise. Runs in a temp sandbox, never the project | 0 |
| `tools/web_asset_check.py` | Parses the page: every local asset resolves, no bare specifier in a module, no `import` in a classic script, and every `fetch()` path matches a declared route | 0 |
| `tools/package_smoke.py` | Imports the library as a user would, so `__init__.py` re-exports and `__all__` promises are actually executed | 0 |
| `tools/feature_coverage.py` | Compares `intent["features"]` against route paths, function names, CLI flags. It reached only the README before | 0 |
| `tools/repair_guard.py` | One acceptance rule, shared. Two other agents overwrote files with no guard at all | 0 |

### The `unusable` verdict

A floor beneath `done_with_context`, not a replacement for `failed`. `failed`
means the pipeline crashed; `unusable` means it finished, the code is
downloadable, and the artifact does not run — no routes, `--help` dies, nothing
generated. Still in `DOWNLOADABLE_STATUSES`, still ships `SESSION_CONTEXT.md`.

`Pipeline._functional_verdict` is deliberately narrow and matches the findings
the verifiers already produce, so there is one vocabulary. A missing feature or
a failing test is still `done_with_context` — that is something a user can
finish.

**Plain `done` was reached for the first time** — row 4, 2026-08-30, §0.8. The
gate was deliberately left alone: it still ANDs nine conditions, including 100%
of generated tests passing and no `TODO` substring in any function body. It
turns out to be satisfiable after all, once the checks stop inventing findings
and remediation can actually repair what it reports. Whether nine ANDed
conditions is the *right* gate is a separate question, still open.

### Prompt contradictions that were producing the errors

Neither is visible from inside either file.

- `architect.txt` mandates *"plain HTML/CSS/JavaScript for ALL frontend code"*;
  `frontend_generator.txt` mandated React + Tailwind + axios. Row 2 shipped the
  hybrid — a React component in `app.js` loaded by a plain
  `<script type="module">`, whose bare `import React from "react"` no browser
  can resolve. The page rendered nothing and no gate looked at it.
- `backend_developer.txt` forbids ORMs; `debugger.txt`'s ✅ example was
  `db.query(Supplier).all()`. With an architect free to plan `alembic/`, that is
  the mechanism behind the persistence drift that opened row 3 at 0/16 routes
  and cost two remediation passes.

Both resolved, plus: the forced backend removed, `debugger.txt`'s "Maximum 60
lines" (which contradicted the deliberately uncapped rewrite budget and invites
truncation) replaced with "return the file complete", and a rule forbidding the
silencing of an AttributeError. **`test_phase23.py` §44 asserts the prompts
agree**, because a contradiction between two files is what no single-file review
catches.

### Repair reach

Three of `_diagnose`'s four "repairable" findings contributed **no**
`failed_paths`: frontend/TypeScript failures, "no executable tests generated",
and "generated tests fail". Remediation announced a repair, found nothing to
repair, logged "made no progress", and degraded the build — the commonest route
to `done_with_context`. The first two are now advisory (nothing here can fix
them); the third supplies the file under test, which it had all along. §45
asserts the invariant: anything called repairable must name a file.

### The open issues

**`PHASE23_HANDOFF.md` §0.-0.5 is the full list**, verified against the code
rather than remembered. The four that matter most:

1. **Rows 2 and 3 have not been rebuilt.** Everything in Phase 5 is a
   prompt-and-generation change, which §0.3's clone technique cannot exercise.
2. **`MIN_TOKENS_TO_START` still gates on the best model**
   (`run_live_matrix.py:183`) while the *fast* model is the bottleneck. It bit
   on 2026-08-30 — 20b hit its quota mid-tester and only the dual-model fallback
   saved the row. Documented, not fixed.
3. **A plain-JS frontend still gets no execution.** `frontend_debugger:122` and
   the tester's Vitest path `:478` both require `frontend/package.json`, which
   that shape does not have. `web_asset_check` parses it; nothing runs it.
4. **The debugger still cannot repair drift that belongs in another file.**
   §0.7's fix handles a renamed field; a *missing* one needs an edit to
   `schemas.py`, and runtime repair only ever edits the file that raised.

### What to distrust next

1. **A checker is a hypothesis until it has been run against a real build.**
   Four of the new checks reported a defect that did not exist, and every one
   was caught by disbelieving the result: the probe importing a package module
   bare, `detect_shapes` returning absolute paths, feature coverage not
   splitting `StockMovement`, and the flag regex reading `-d` instead of
   `--dry-run`. Each would have sent a repair at working code.
2. **A test can match its own documentation.** Three assertions passed or failed
   on prose in the file they were checking. Assert the directive, not the
   string.
3. **Scores will look worse.** Row 3 going 16/16 → 12/16 was the fix working.

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
| 4.23 | Three agents overwrote generated files with no guard at all; one shared rule now | ✅ᵒ | `tools/repair_guard.py`; a test repair may not go green by deleting the test |
| 4.24 | "Not checked" is no longer "checked and clean" | ✅ᵒ | `tools/verification.py`; NOT_RUN is never `ok` and contributes an explicit finding |
| 4.25 | One shape detector; a web app anywhere in the tree is found | ✅ | **found row 4's unprobed app**, which serves exactly one route: `GET /health` |
| 4.26 | The CLI is actually executed | ✅ | ran row 4's `cli.py` for the first time in the project's history — it passes |
| 4.27 | The page is parsed and its calls checked against real routes | ✅ | **caught row 2's `import React from "react"`**, which no gate had ever looked at |
| 4.28 | A library is imported the way a user imports it | ✅ᵒ | `__init__.py` re-exports and `__all__` promises are executed |
| 4.29 | The build is compared to `intent["features"]` | ✅ | row 3 6/6 and row 4 4/4, and it still catches a genuinely absent feature |
| 4.30 | An app that boots and serves nothing is `unusable`, not `done_with_context` | ✅ᵒ | the literal empty build; it used to return `[]` and log nothing |
| 4.31 | Verification runs even when a step crashed, and its result reaches the API | ✅ᵒ | a tester crash silently skipped every check; `smoke_summary` never left the log |
| 4.32 | The prompts no longer contradict each other | ✅ᵒ | React-vs-plain-JS and ORM-vs-sqlite3, both of which were shipping broken builds |
| 4.33 | "Repairable" now means there is a file to aim at | ✅ᵒ | 3 of 4 findings drove a pass that could do nothing, then degraded the build |

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
| Row 2, then rows 3 and 1 against the new checks | ~170K / ~140K / ~60K | the static-frontend and route-contract checks have never run on a fresh build; **check 20b by hand**, see §0 |
| ~~A1 assertion 2 — a build reaching plain `done`~~ | **met** | row 4 on 2026-08-30, with positive evidence rather than silence — §0.8 |
| ~~The lifespan that creates no tables~~ | **addressed** | the architect is now forbidden to plan an `alembic/` layout and every prompt agrees on raw sqlite3, so the shape that needed a migration nobody runs is not planned. Unproven until a row 3 rebuild |
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

## 0.8 The live run — row 4, 2026-08-30, and the first plain `done`

One row, chosen because it is the shape this work changes most and because the
headline assertion is answered at step 3 for ~2K tokens.

```
status  done          109,206 tokens   932s   zip ok (14,283 bytes)
shape   cli           (previous run: web_api+cli)
```

**A1 assertion 2 is met for the first time.** `SESSION_PROGRESS.md` had recorded
plain `done` as *"still never observed, on any row, ever"*, and Phase C's memory
gate (`status == done` + `review_score >= 7` + clean smoke) was unsatisfiable
because of it.

**It is earned, not silent** — which is the first thing to check, given that
"silence reads as clean" is the defect this whole session was about. The stored
record carries **positive evidence**, not four blanks:

| check | verdict | why |
|---|---|---|
| `cli_smoke` | **verified** | ran 2 entry points; `--help` exits 0 |
| `feature_coverage` | **verified** | 4/4 requested features have supporting code |
| `web_assets` | not applicable | ships no HTML page |
| `package_smoke` | not applicable | this project is run, not imported |

Zero `NOT_RUN`. Two checks executed the artifact and found it sound.

### What the architect produced

```
bulk_file_renamer/{cli,renamer,undo_log,logger,main}.py   requirements.txt   tests/
```

**No `backend/`, no routes, no CORS, zero FastAPI.** The previous run of the
same prompt produced `routes.py`, `services.py`, `models.py` and a FastAPI
`main.py`, of which the app served exactly one route — `GET /health` — beside
the CLI that had been asked for. `feature_coverage` reports "0 route(s)", which
is now the correct number.

### The repair-reach fix, on a real build

The only repairable finding was *"Generated tests fail for 3 file(s)"*, and it
logged `🐛 Debugging 3 Python files` — the debugger aimed at the files under
test. Before `0ffe495` that exact finding contributed no `failed_paths`, so
remediation would have announced a repair, found nothing to repair, logged "made
no progress", and degraded the build. Remediation fixed the tests and the build
reached `done`.

### Two things this run taught that offline work could not

1. **The dual-model fallback earned its keep.** 20b hit its daily quota during
   the tester and the run continued on 120b. Starting at 73,286 on the fast
   model was marginal and the row survived only because the models are distinct
   — the reason `groq-models-decommissioned` says never to set both to the same
   model.
2. **Reading the persisted record found two reporting defects the status line
   hid** (fixed in `8c956e6`): `verification_outcomes` appended instead of
   replacing, so every check appeared twice and no reader could tell which run
   they were seeing; and `smoke_summary` stored *"smoke test did not run (no
   FastAPI entry point found)"* for a CLI — accurate about the probe, and
   reading as a failure when the answer is "does not apply".

### Quota after

| Model | Left |
|---|---|
| `openai/gpt-oss-120b` | ~119,400 |
| `openai/gpt-oss-20b` | **~25,800** |

The fast model needs ~5.5h to reach the 70,000 gate. **Row 2 is the next row**
and it is the one the static-frontend and route-contract checks were written
for; do not start it on 20b below ~90K.

### Still unproven live

Row 2 (the frontend contradiction fix, `web_asset_check` on a fresh build) and
row 3 (the persistence pinning, and its real score under §0.6's probe). Both are
prompt-and-generation changes, which §0.3's clone technique explicitly cannot
exercise — only a rebuild can.

---

---

---

Read this file first. Then:

| File | Role |
|---|---|
| `SESSION_PROGRESS.md` (this) | Current state, what to do next, how to verify |
| `PHASE23_QUOTA_RUNBOOK.md` | **What to do when the budget is back**: the refill arithmetic, which row to start, what to assert when it finishes, and the traps |
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
