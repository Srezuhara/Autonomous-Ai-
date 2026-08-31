# Phase 23 — the plan for the next two sessions

*Written 2026-08-31 at the end of the eighth session, and approved. This is the
executable plan: Part A is everything that can be done with no quota, Part B is
what to spend the refill on. `SESSION_PROGRESS.md` §0 is the state it was
written against; `PHASE23_QUOTA_RUNBOOK.md` is the standing procedure, and §B1
here deliberately overrides its §3 row order.*

> ## ✅ Part A is COMPLETE (2026-08-31, ninth session, zero tokens)
>
> All five no-quota items are closed and committed; `test_phase23.py` is
> **820/820** and the corpus baseline is clean and re-recorded. What each one
> turned out to be is recorded in `SESSION_PROGRESS.md` §0.0.
>
> | item | outcome |
> |---|---|
> | **A1** record written before routing | fixed (§4.39) — reproduced first; it would have failed row 3 on a correct build |
> | **A2** `feature_coverage` vocabulary | fixed (§4.40); **the tightening still does not ship** — synonyms are now the sole blocker |
> | **A3** `repair_guard` thresholds | floor measured and kept; ratio instrumented rather than guessed at (§4.41) |
> | **A4** the `done` gate | audited, and it found a real defect (§4.42): 14 of 42 placeholder findings were on complete files |
> | **A5** `web_asset_check` recall | closed (§4.43) — the skip was hiding exactly one real defect |
>
> **Start at Part B.** Re-run the quota arithmetic in Part 0 first; the ~22 h
> figure was measured on 2026-08-31 and the ledger is optimistic between 429s.
> Part 0's three "verify before trusting" facts are now: 820/820, baseline
> clean, HEAD `826507b` or later.


## Context

Phase 23 exists to make the pipeline's verdict about its own builds trustworthy.
Before it, "verified" meant "inspected"; a build could ship `done_with_context`
with a valid ZIP and an artifact nothing had ever executed. Seven sessions have
closed most of that: `VerificationOutcome` separates "not applicable" from "not
run", `EXECUTING_CHECKS` gates what counts as evidence, and every build shape now
has a verifier that actually runs the thing.

The eighth session (2026-08-31) closed row 3's blocker — `routes.py` written
against schemas `models.py` never defined — with a new `module_ref` checker, a
`schema_attr` that stops shrugging, and a prompt that states the contract. It
also measured two "obvious" fixes and dropped both.

**Two things now block finishing the phase:**

1. **A defect introduced by that same session's change.** Planning the live-run
   path revealed it: `result.verification_outcomes` is written *before* manual
   routing rewrites the outcome, so the API reports `module_ref: failed` even
   when every one of its findings was routed to manual testing. The matrix
   driver reads the API. A build that works perfectly but ships one test file
   with a bad import would **fail its row** — reintroducing, through the driver,
   exactly the mistake §4.26 was decided to prevent.
2. **Nothing since the sixth session has run inside a live build.** Every change
   is validated against the 41 saved builds only. Row 3 is the standing proof
   that this is not enough: both of its blockers were invisible to all 41, and
   one fresh build found both.

Quota is **~22 hours out** (measured below), so there is a full session of
no-quota work before a live row is possible. The intended outcome: when the
refill lands, row 3 runs against a pipeline with nothing known-broken in it, and
Phase 23 closes on that row's result.

---

## Part 0 — State, as of 2026-08-31

Verify these before trusting anything below; all three are free.

| Fact | How to check |
|---|---|
| `test_phase23.py` is **765/765** | `venv/Scripts/python.exe test_phase23.py` |
| Corpus baseline is **clean** | `venv/Scripts/python.exe tools/verify_corpus.py --baseline verification_baseline.json` |
| HEAD is `b768904` | `git log --oneline -3` |

**Quota, measured 2026-08-31.** Both models are *over* their daily budget in the
24-hour window:

| Model | Used in window | Floor needs | Time to floor |
|---|---|---|---|
| `openai/gpt-oss-20b` (fast) | ~296,366 | ≤110,000 (90K floor) | **~22 h** |
| `openai/gpt-oss-120b` (heavy) | ~287,293 | ≤130,000 (70K floor) | **~22 h** |

Recompute rather than trusting the table — the arithmetic is a rolling 24h sum
against `200000 - floor`:

```bash
venv/Scripts/python.exe -c "
import sys,time; sys.path.insert(0,'.')
import llm_client as lc; lc._ledger_load()
now=time.time(); W=lc._LEDGER_WINDOW_SECONDS
for m,floor in ((lc._FAST_MODEL,90000),(lc._HEAVY_MODEL,70000)):
    es=[(t,n) for t,mm,n,*r in lc._ledger if mm==m]
    cur=sum(n for t,n in es if t>now-W); target=200000-floor
    h=next((h for h in range(0,49) if sum(n for t,n in es if t>now+h*3600-W)<=target), None)
    print(f'{m:<24} used~{cur:>8,} need<={target:>7,} -> ~{h}h')
"
```

> **The ledger under-reports by ~51K** — it records only calls that returned
> 2xx. Treat every number here as optimistic and start a row with margin over
> the floor, not just above it. See `PHASE23_QUOTA_RUNBOOK.md` §0.-1.

---

# Part A — No-quota work, in priority order

## A1. The `module_ref` recording bug — do this first

**Why first:** it is the only item that can make a *correct* live row report as
a failure, and row 3 is the row we are saving quota for.

**The mechanism.** In `agents/pipeline.py::_verify_other_shapes`:

- line ~1019 assigns `result.verification_outcomes = [o.to_dict() for o in recorded]`
- lines ~1039-1073 then run the manual-routing loop, which rewrites a
  partially-routed outcome into `counted` — **not into `recorded`**

So the rewrite never reaches the record. `run_live_matrix.verification_verdict`
reads `row["verification"]` from `GET /jobs/{id}/status`, and its
`MANUAL_CHECKS = ("generated_tests",)` does not include `module_ref`, so a
`failed` there fails the row.

**Confirm the bug before fixing it.** `test_phase23.py`'s `_m26_run` harness
(≈line 5341) already returns the result object:

```python
adv, manual, res = _m26_run("works", <a verified executing outcome>)
# with a module_ref reporting only test-file findings:
#   manual            -> contains them            (correct today)
#   res.verification_outcomes -> module_ref "failed"  (the bug)
```

**The fix.** Reorder, and apply the rewrite to the record as well:

1. Compute `works` from `recorded` (unchanged — it must precede routing).
2. In the routing loop, collect partially-rewritten outcomes into a
   `{check_name: outcome}` map alongside `counted`.
3. After the loop, build the final record as
   `[rewritten.get(o.check, o) for o in recorded]` and assign
   `result.verification_outcomes` from *that*.

**Three invariants the fix must not break** — each gets a test:

- **`generated_tests` stays `failed` in the record.** It is whole-check routed
  (`continue`d out of `counted`), and the driver both excludes it by name and
  prints `"; for manual testing: generated_tests"`. Rewriting it to `verified`
  would delete that signal, which the runbook §4 documents as a passing shape.
  Only *partially* routed checks rewrite the record.
- **`_functional_verdict` still sees `evidence["fatal"]`** for a source-file
  defect (`agents/pipeline.py:854`). Test-only findings never set fatal, so the
  rewritten `verified` outcome carries no fatal flag — assert this, because it
  is the path by which `unusable` could silently stop firing.
- **`replace, do not append`** still holds — this runs twice, before remediation
  and in the final re-audit, and the record must describe the last run.

**Then close the loop end to end**: feed the rewritten record to
`run_live_matrix.verification_verdict()` in a test and assert the row *passes*.
That assertion is the one that would have caught this, and none of the three
existing "the three places agree" tests does — they compare the check-name
tuples, not the record.

**Verify:** `test_phase23.py` green; corpus baseline unchanged (this touches no
checker, so a diff here means something else moved).

---

## A2. `feature_coverage` — fix the vocabulary before the threshold

**The measured defect** (eighth session): the check reports 5/5 corpus projects
verified and **four of those passes are on the wrong word.** It is right by
accident. Evidence, from `corpus_intents.json` against the built artifacts:

| requested feature | matches on | actually implemented as | gap |
|---|---|---|---|
| "tag filtering" | `tag` | `filter_bookmarks` | `_normalise` never strips `-ing` |
| "reverse a rename" | `rename` | `undo_log`, `--undo-log` | synonym |
| "a frontend that lists bookmarks" | `bookmark` | `frontend/` directory | directory names not collected |
| "adds a bookmark through a form" | `bookmark` | inputs, no literal `<form>` | HTML tag names stripped as markup |

**Do NOT ship the "distinctive word" tightening.** It was measured: five
features flip covered→missing and **four of the five flips are wrong**, telling
working builds they are incomplete. The threshold cannot be tightened until the
vocabulary is right.

**Steps, in order:**

1. **`_normalise` (`tools/feature_coverage.py:80`) — strip `-ing`.** Guard it:
   only when the remainder is ≥5 characters, so `string`→`str` cannot happen.
   `filtering`→`filter` is the case that matters.
2. **`_artifact_vocabulary` (line ~129) — collect directory names.** Every
   directory under the project root that is not in the skip set. `frontend/`,
   `backend/`, `cli/` are real, user-visible structure.
3. **Collect HTML structural tag names**, not just visible text — `form`,
   `table`, `input`, `button`, `nav`, `select`. The current regex strips all
   markup, so a page *containing* a form cannot match a feature *asking* for
   one.
4. **Re-measure the four rows above.** Each should now match on the *right*
   word. Add an assertion per row to `test_phase23.py` naming the expected
   matching word, not just the verdict — otherwise the test passes on the same
   accident.
5. **Only then** re-run the distinctive-word experiment (the script is described
   in `SESSION_PROGRESS.md` §0.1). If it now flips only genuinely-absent
   features, ship it; if it still flips a working build, stop and say so.

> **Expect no verdict change on the corpus from steps 1-3.** All five projects
> already pass. That is precisely why these were dropped last session as
> unverifiable on their own — they are worth doing *now* only because step 5
> depends on them, and step 5 does change verdicts. If step 5 is abandoned,
> abandon steps 1-3 too rather than shipping an unverifiable change.

**Verify:** the four new word-level assertions; corpus diff explained in both
directions (a feature that starts matching and one that goes quiet are the same
class of mistake).

---

## A3. `repair_guard` — measure the thresholds instead of asserting them

`tools/repair_guard.py` rejects a generated fix on two numbers that were chosen
by judgment: `_SMALL_FILE_CHARS = 120` (line 62) and a `0.6` shrink ratio (lines
177, 283). The comment at line 171 records that an earlier `0.5`-above-400-chars
rule "left two holes a repair fell through", so the numbers have moved before on
anecdote.

**Make it a measurement.** The corpus is 41 builds of real generated files:

1. Write a throwaway script (scratchpad, not the repo) that walks every `.py`
   file in `generated_projects/` and reports the distribution of file sizes and,
   for every build that has a `.orig`/backup or a git-tracked earlier version,
   the before/after size ratio of real repairs.
2. Answer two questions with numbers: **what fraction of genuine files fall
   under 120 chars** (i.e. are exempted from the shrink check entirely), and
   **what does the ratio distribution of accepted repairs actually look like**.
3. Adjust only if the data says so, and record the measurement in the docstring
   next to the constant — the point is that the next person finds a number with
   evidence behind it, not a better guess.

**If the data is too thin to justify a change, say so and leave the numbers
alone.** That is a valid outcome and should be written down, so this item stops
being reopened.

---

## A4. Audit the `done` gate

`degraded = bool(report.unresolved)` (`agents/pipeline.py:1873`) is the whole
gate: `done` versus `done_with_context`. `report.unresolved` is fed by
`_diagnose`'s categories, and `PHASE23_HANDOFF.md` §10 flags that one of them is
100%-of-generated-tests-passing — which now sits in tension with §4.26 ("a broken
test suite is not a broken build") and with the fact that **34 of 41 saved builds
ship a failing suite**.

**This is an audit, not a change.** Deliverable is a table in
`PHASE23_HANDOFF.md`: for each condition that can put a string into
`unresolved`, how often it fires across the corpus, and whether it is describing
the product or the scaffolding around it. Only then decide whether any condition
should move to advisory.

Row 4 (`bulk_file_renamer_912f9b22`) reached a plain `done`, so the gate is
reachable; the open question is whether it is the *right* gate, and nobody has
asked it.

---

## A5. `web_asset_check` recall gap — lowest priority, and possibly close it as intended

The check skips URLs it cannot resolve confidently. That is deliberate
precision-over-recall and is documented as such. Before writing any code,
**measure how many references are actually skipped** across the corpus and
whether any of them hide a real broken asset. If the number is small and none
hide a defect, close this item as working-as-intended rather than leaving it on
the list.

`static_smoke` already serves the page and fetches its assets, so the practical
gap is narrower than when this was written.

---

## A6. Pre-flight, so the quota window is not spent on setup

Do these while waiting; each is free and each has cost real time before:

1. **Restart the server after the A1-A2 edits.** It runs `--no-reload` and holds
   the code it started with — every fix in §4.3-4.5 was made while a build was
   running and the process that produced rows 2 and 3 never had them.
2. **Confirm one server only.** The ledger is per-checkout and two servers
   sharing it under-count.
3. **Confirm the real database is `generated_projects/platform.db`.** The
   `platform.db` in the repo root is a corrupt April file that will not open.
4. **Re-record the corpus baseline** after A1-A2 land, so the post-row diff shows
   only the new build.

---

# Part B — Quota work, when the refill lands

> ## ▶ START HERE (a new session reading this: this is the entry point)
>
> Part A is done. **There is no useful no-quota work left in Phase 23** — what
> remains can only be settled by a live build. Three commands, in order:
>
> ```bash
> venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1
> venv/Scripts/python.exe run_live_matrix.py --dry-run   # both models: "would start: yes"
> venv/Scripts/python.exe run_live_matrix.py --rows 3    # ~30-45 min
> ```
>
> **Measured 2026-08-31 (ninth session): ~21 h to both floors.** Fast model had
> used ~296,900 of a 110,000 ceiling; heavy ~287,300 of 130,000. Recompute with
> the snippet in Part 0 rather than trusting that — and read `--dry-run`
> yourself even when it passes, because the ledger under-reports by ~51K.
>
> Three things that have each cost real time:
>
> 1. **Do not tail `server.log`** while a build runs — it is block-buffered.
>    Poll `/jobs/{id}/status` (command in §B1).
> 2. **Restart the server** after any edit to the agents, tools or
>    `llm_client.py`. It runs `--no-reload` and holds the code it started with.
> 3. **A red result is a hypothesis about the pipeline first.** That has been
>    right every time in this phase. Do not spend a second row diagnosing it —
>    use the 2-7K debugger loop in §B4.
>
> If the budget is short and you want work anyway: **Phase B2 (JWT auth) needs
> no quota** — `PHASE23_PLAN.md` §B2 — but it belongs to the next phase and
> will not close this one.


## B0. Pre-flight (5 minutes, no tokens)

```bash
venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1
venv/Scripts/python.exe run_live_matrix.py --dry-run
```

`--dry-run` prints a refusal per model against its own floor. Proceed only on
"would start: yes" **for both**, and prefer margin over the floor rather than
just clearing it — the ledger is optimistic between 429s.

## B1. Run row 3 first

```bash
venv/Scripts/python.exe run_live_matrix.py --rows 3
```

**Why row 3 and not row 2** (this overrides `PHASE23_QUOTA_RUNBOOK.md` §3, which
was written before rows 2 and 3 were fixed): row 3 is the single build whose
*every* known blocker is now supposedly closed — the `__future__`/`sys.path`
shim ordering (§4.33), the mixed sibling imports (§4.34), and the missing
Pydantic schemas (§4.35-4.38). Nothing cheaper can test any of them, because
they are all generation-and-prompt defects. It is also cheaper than row 2
(~87-98K on the fast model versus ~172K), so a single refill can cover it with
margin.

Budget: ~30-45 minutes wall clock. A single step can take 30 minutes
(`STEP_TIMEOUT_SECONDS=900`, one retry).

**Do not read `server.log` for progress** — its output is block-buffered and
unreadable while a build runs. Poll the API instead:

```bash
curl -s localhost:8000/jobs/<build_id>/status | \
  venv/Scripts/python.exe -c "import json,sys; d=json.load(sys.stdin); \
  print(d['build_shape'], '|', d['smoke_summary']); \
  [print(' ', o['status'], o['check'], '-', o['detail']) for o in d['verification']]"
```

## B2. What to assert when it finishes

The driver writes both halves of the criterion into `PHASE23_MATRIX_RESULTS.md`.
Beyond its verdict, assert these by hand — each targets something this phase
changed and has never run live:

| Assertion | Why it is the point |
|---|---|
| `module_ref` is **`verified`**, not `failed` | Its four `*Create` findings were the row's cause of death. If it still fires, the prompt fix (§4.38) did not take. |
| `schema_attr` reports nothing, and is not `not_applicable` | A `not_applicable` here means zero Pydantic models again — the §4.37 finding should fire instead of shrugging. |
| A write endpoint returns **201, not 422** | The API accepting its own test's payload is the shape `generated_tests` kept failing on. |
| **Zero `not_run` outcomes** | A NOT_RUN is a hole in the evidence. The driver already fails the row for it; the thing to do is find out *why*, because it is usually a pipeline defect, not a build defect. |
| `grep -c "does not parse" server.log` is **0** | The phantom-defect count. Eight per build before the §4.13 fix, each spending an LLM call rewriting correct code. |
| A row reading `verified: yes — …; for manual testing: generated_tests` **is a pass** | §4.26. If A1 was done right, a test-only `module_ref` finding reads the same way. |

Then re-run the free corpus check, which now includes the new build, read its
result, believe it, and only then re-record:

```bash
venv/Scripts/python.exe tools/verify_corpus.py --baseline verification_baseline.json
venv/Scripts/python.exe tools/verify_corpus.py --json verification_baseline.json
```

## B3. If row 3 passes

Phase 23's core claim is then demonstrated end to end and the phase can close.
Spend any remaining budget in this order:

1. **Row 2** (~172K, the largest) — the only row that exercises
   `web_asset_check` on a *fresh* plain-JS frontend, which has still never
   happened. Assert `frontend/app.js` contains no bare `import React from
   "react"` or `import axios`.
2. **Row 1** (60-95K) — the cheap end-to-end regression; 5/5 routes, as on
   2026-08-28.

Each needs its own ~16-21 h refill. One row per refill is the honest ceiling.

## B4. If row 3 fails

**Treat a red result as a hypothesis about the pipeline first.** That has been
right every time in this phase — row 3's own death was `_inject_syspath`
breaking correctly-generated code.

Do not spend a second row on a diagnosis. Use the cheap loop instead
(`PHASE23_QUOTA_RUNBOOK.md` §6): clone the broken project the run just produced
and drive the real debugger at it — **2-7K tokens instead of 130-170K**. Two
rules for that loop: build the input the way the pipeline builds it (one line per
failure, or `_shared_cause()` reads the message as the exception type), and
remember it **cannot** exercise prompt or generation changes.

---

# Verification

**After Part A**, all three must hold together:

```bash
venv/Scripts/python.exe test_phase23.py                                    # expect 765+/765+
venv/Scripts/python.exe tools/verify_corpus.py --baseline verification_baseline.json
git log --oneline -3
```

- Every corpus diff explained **in both directions**. A check that starts
  reporting on a build known to work and a check that goes quiet on one known to
  be broken are the same mistake.
- A1 additionally requires the end-to-end assertion: a rewritten record fed to
  `run_live_matrix.verification_verdict()` returns a pass.
- A2 additionally requires word-level assertions, not verdict-level ones.

**After Part B**, the phase is closable when row 3 reaches a terminal state with
a verification record of positive evidence rather than blanks: zero `not_run`,
at least one check that executed the artifact, and the six assertions in B2.

# Housekeeping

- Commit this plan to the repo as **`PHASE23_NEXT_SESSION_PLAN.md`** at the root
  and link it from `SESSION_PROGRESS.md` §0, so a new session finds it from the
  documented entry point.
- Update the memory note `pipeline-open-defects` as items close — it is what a
  new session reads first.
- `PHASE23_QUOTA_RUNBOOK.md` §3 still recommends row 2 first. Either amend it or
  note that this plan supersedes it, so the two do not disagree.
