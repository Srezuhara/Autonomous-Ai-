# Quota runbook — what to spend the next refill on

*Written 2026-08-30, at the end of the sixth session. This is a procedure, not a
narrative: it exists so the session that opens when the budget is back does not
have to re-derive any of this.*

Read `SESSION_PROGRESS.md` §0 for state and `PHASE23_HANDOFF.md` §0.-0.5 for the
open defects. **This file is only about the live runs**: when they can start,
which one to start, and what to assert when it finishes.

---

## 0.-1 Read this before trusting any number below (2026-08-31)

**The ledger under-reports. It has now been made self-correcting, but only
forward.** `_add_tokens` is reached only after `raise_for_status()`, so the
ledger records a call only when it returned 2xx with a usage body. Every 400,
every 429-rejected attempt and every attempt retried after a per-minute wait
spends real budget and leaves no trace.

Measured on row 2, this session: the ledger said **145,967** used on
`gpt-oss-20b` at the moment Groq's own 429 said **`used 197323`**. A ~51,000
token shortfall — a quarter of the daily limit, entirely in the optimistic
direction. The row cleared the 90,000 fast floor showing "151,303 left" and ran
the model dry mid-tester anyway. **The floors added on 2026-08-30 were
denominated in a unit that could not do the job they were added for.**

Fixed: `_mark_model_daily_limited` now parses `limit N, used M` out of the 429
and calls `reconcile_ledger_from_groq`, which anchors the bucket to Groq's own
figure. It reconciles **upward only** — an over-count costs a wait, an
under-count costs a dead build. The 429 is the single exact reading of Groq's
counter this code ever receives; it used to be spent on a log line.

Two consequences for the next session:

- **The estimate is still optimistic between 429s.** Reconciliation happens when
  a model hits the wall, not before. Treat `--dry-run` as a lower bound on spend
  and an upper bound on budget, and prefer starting a row with margin over the
  floor rather than just above it.
- Even a full rebuild from the database's own build rows
  (`seed_ledger_from_history`) came out **21,923 tokens short** of Groq's figure,
  so the gap is not a bookkeeping slip in one path — non-2xx spend is invisible
  everywhere.

---

## 0. The one thing to get right

**Check the FAST model, not the best one.** `gpt-oss-20b` carries the tester,
the reviewer and every remediation pass, and it is what runs out. The driver now
enforces two floors — `MIN_FAST_TOKENS_TO_START = 90,000` and
`MIN_HEAVY_TOKENS_TO_START = 70,000` (`run_live_matrix.py`) — but read the
numbers yourself anyway. On 2026-08-30 a row started with 20b at 73,286, ran it
dry during the tester, and finished only because the dual-model fallback moved
it to 120b. That is the safety net working, not the plan working.

---

## 1. Start here, every time

```bash
# 1. The server holds the code it started with (--no-reload is deliberate:
#    reload watches generated_projects/ and kills builds mid-flight).
venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1

# 2. What is actually available. Costs nothing.
venv/Scripts/python.exe run_live_matrix.py --dry-run
```

`--dry-run` now prints a refusal per model against its own floor. If it says
"would start: yes", both budgets are genuinely there.

---

## 2. The refill arithmetic

**Groq's daily budget is a leaky bucket, not a calendar day.** It refills
continuously at `200000 / 86400 ≈ 2.315 tokens/second ≈ 8,333 per hour, per
model`, confirmed against Groq's own 429s to the second. **There is no reset to
wait for** — never plan around one, and never tell a user to come back tomorrow.

Measured at 2026-08-30 20:10, after row 4:

| Model | Left | To its floor |
|---|---|---|
| `openai/gpt-oss-20b` (fast) | 33,429 | **6.8 h** to 90,000 |
| `openai/gpt-oss-120b` (heavy) | 127,607 | already above 70,000 |

Row costs as measured, so a wait can be planned rather than guessed:

| Row | Shape | Total | Fast-model share |
|---|---|---|---|
| 1 | simple FastAPI + SQLite CRUD | 60-95K | moderate |
| 2 | FastAPI + plain-JS frontend | ~172K | high — the largest row there is |
| 3 | complex / multi-entity | 87.5K on the fixed code (was 131-186K) | **97.5K on 20b** in the 2026-08-30 run |
| 4 | CLI | 109K | 49.7K fast / 59.5K heavy |

**One row per ~16-21 hours is the honest ceiling.** From empty, the fast model
alone needs 10.8h to reach its floor.

---

## 3. The order, and what each row is for

> **Superseded on the row order (2026-08-31).**
> [`PHASE23_NEXT_SESSION_PLAN.md`](PHASE23_NEXT_SESSION_PLAN.md) §B1 runs **row
> 3 first**, not row 2. The table below was written before rows 2 and 3 were
> fixed. Row 3 is now the single build whose every known blocker is supposedly
> closed — the `__future__` shim (§4.33), the sibling imports (§4.34) and the
> missing Pydantic schemas (§4.35-4.38) — and it is cheaper than row 2. Nothing
> else in this file is superseded; §2, §4, §5 and §6 all still apply.


Every item here is something **only a rebuild can prove**. Anything that can be
verified against a saved project should be — see §6.

| # | Row | Command | What it proves that nothing cheaper can |
|---|---|---|---|
| 1 | **Row 2** | `run_live_matrix.py --rows 2` | The React-vs-plain-JS prompt contradiction fix, and `web_asset_check` on a *fresh* frontend. Row 2 is the shape that check was written for and it has never run on one. It is also the most expensive row, so it wants the fullest budget |
| 2 | **Row 3** | `--rows 3` | The persistence pinning (no `alembic/`, raw sqlite3 in every prompt), and its real score under the fixed write-probe **and** the new `schema_attr` check |
| 3 | **Row 1** | `--rows 1` | The only row that has ever met the 0-5xx half. A cheap regression check on the whole chain |
| 4 | Phase B1 | — | No quota. `PHASE23_PLAN.md`; start it any time the budget is short |

If only one row can be afforded, run **row 2**.

---

## 4. What to assert when a row finishes

Not "did it say done". The driver now reads both halves of the criterion from
the API and writes them into `PHASE23_MATRIX_RESULTS.md` — a row passes only
when every check either verified the artifact or correctly did not apply, **and
at least one check actually executed it**.

```bash
# The per-check record, from the database rather than the log:
curl -s localhost:8000/jobs/<build_id>/status | \
  venv/Scripts/python.exe -c "import json,sys; d=json.load(sys.stdin); \
  print(d['build_shape'], '|', d['smoke_summary']); \
  [print(' ', o['status'], o['check'], '-', o['detail']) for o in d['verification']]"

# The phantom-defect count. Must be 0 — 8 per build before the §4.13 fix, and
# each one spent an LLM call rewriting a file that was already correct.
grep -c "does not parse" server.log
```

Per row, beyond the driver's own verdict:

- **Row 2** — `web_assets` must be `verified`, and `frontend/app.js` must not
  contain a bare `import React from "react"` or `import axios`. Both shipped
  before and no gate looked at the page.
- **Row 3** — `schema_attr` must report nothing, and a write endpoint must
  actually execute (a 201, not a 422). The shipped row 3 has three undeclared
  field reads, one of which (`mv.direction`) no runtime probe can reach.
- **Row 1** — 5/5 routes, as it managed on 2026-08-28.
- **Any row** — zero `not_run` outcomes. A NOT_RUN is a hole in the evidence and
  the driver already fails the row for it; the thing to do is find out *why* the
  check could not run, because that is usually a pipeline defect, not a build
  defect.

**A seventh check exists as of 2026-08-31: `generated_tests`.** It runs the
suite the build ships, and it will usually FAIL — 34 of the 41 saved builds have
a suite that does not pass. **It does not decide the row.** It asks whether the
suite the build *ships* runs, not whether the thing built works, and those are
different questions: a build can serve every route it declares while its
generated tests do not collect. When another check has executed the artifact and
found it sound, the findings go to the user as manual testing and the row still
passes; with no such evidence they count against it. So a row reading
`verified: yes — ...; for manual testing: generated_tests` is a pass, and the
suite is still worth looking at.

Then re-run the free corpus check, which now includes the new build:

```bash
venv/Scripts/python.exe tools/verify_corpus.py --baseline verification_baseline.json
```

A new project shows as "new in the corpus (no baseline)". Once its result has
been read and believed, re-record: `--json verification_baseline.json`.

---

## 5. Traps that have each cost real time

1. **Use the venv.** System Python lacks `rich`; `python main.py` dies on import
   before the build starts.
2. **Restart the server** after editing `llm_client.py`, the agents or the
   tools. It runs `--no-reload`, so a running process holds the code it started
   with — every fix in §4.3-4.5 was made while a build was running and the
   process that produced rows 2 and 3 never had them.
3. **The real database is `generated_projects/platform.db`.** The `platform.db`
   in the repo root is a corrupt file from April and will not open.
4. **The download route is `GET /projects/{id}/download`.** Check for the `PK`
   magic bytes, not the status code.
5. **One server at a time.** The token ledger is per-checkout and cannot see
   other processes; two servers sharing the file will under-count.
6. **CLI builds (`main.py`) persist nothing** — no DB row, so no status and no
   verification record. Use `POST /projects/` when the run needs to be recorded.
7. **The live E2E suite spends real quota.** Test 4 needs `LIVE_QUOTA_SIM=1` and
   the backend started with `GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS=6` — and the
   backend **restarted without that variable afterwards**, or every later build
   hands itself a simulated quota wall.
8. **A step can take 30 minutes** (`STEP_TIMEOUT_SECONDS=900`, one retry), and a
   row up to 45.

---

## 6. When a row cannot be afforded

`SESSION_PROGRESS.md` §0.3: clone the broken project the matrix already
produced and drive the real debugger at it. **2-7K tokens instead of 130-170K**,
and it is how rows 2 and 3 were both repaired end to end in one session.

```python
shutil.copytree(OUT / "inventory_system_90ee973f", OUT / "_probe")
pl = Pipeline.__new__(Pipeline); br.architecture = {"root_folder": "_probe"}
pl._smoke_test_runtime(br)                       # -> pl._smoke_runtime_errors
Debugger()._repair_runtime_error(path, err, FileDebugResult(...))
```

Two rules for it:

- **Build the input the way the pipeline builds it** — one line per failure. A
  two-line error string makes `_shared_cause()` read the message as the
  exception type and route to the wrong prompt, which is how one measurement
  came out backwards.
- **It cannot exercise prompt or generation changes**, which is exactly what
  rows 2 and 3 are waiting on. Do not let a cheap verification stand in for one
  of those.

And the zero-token checks are always available, on every saved build:
`venv/Scripts/python.exe tools/verify_corpus.py`.

---

## 7. What a good result looks like

A row that reaches `done`, ships a ZIP with `PK` at the front, and carries a
verification record of **positive evidence rather than four blanks** — the way
row 4 did on 2026-08-30:

| check | verdict | why |
|---|---|---|
| `cli_smoke` | verified | ran 2 entry points; `--help` exits 0 |
| `feature_coverage` | verified | 4/4 requested features have supporting code |
| `web_assets` | not applicable | ships no HTML page |
| `package_smoke` | not applicable | this project is run, not imported |

Zero NOT_RUN, and at least one check that executed the artifact. Anything less
is a build nobody has verified, whatever its status says.
