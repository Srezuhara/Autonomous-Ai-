# Phase 23 A — Live validation

*Run 2026-08-26 on restored Groq free-tier quota. This is the evidence document
`PHASE23_PLAN.md` Phase A asks for: what actually happened when real builds ran
on the current `openai/gpt-oss-*` models, not what was expected to happen.*

---

## A0 — Pre-flight

| Check | Result |
|---|---|
| `gpt-oss-120b` / `gpt-oss-20b` alive on all 8 keys | ✅ both present on every key, plus `gpt-oss-safeguard-20b` |
| `GET /health` → `llm.status` | ✅ `healthy` |
| `groq_keys_available` | ✅ 8 / 8, 0 exhausted, no daily limit flagged |
| `test_phase21.py` | ✅ 77 / 77 |
| `test_phase22.py` | ✅ 85 / 85 |
| `test_groq_rate_limit_handling.py` | ✅ 4 / 4 |
| frontend `typecheck` | ✅ |
| frontend `lint` | ✅ clean |
| frontend `test` | ✅ 191 / 191 across 11 files |
| frontend `build` | ✅ built in 23.2s |

No pre-existing failure, so anything the live runs surface is attributable to
the live path.

### A0 finding 1 — the plan's own liveness recipe returns a false negative

`PHASE23_PLAN.md` A0.1 proposes:

```bash
curl -s -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models
```

Against this machine every key returns **HTTP 403, Cloudflare `error code: 1010`**
— a client-fingerprint block, not an authentication or a quota result.
Reproduced identically on all 8 keys through `urllib`; the same 8 keys succeed
immediately through the `groq` SDK, which uses `httpx`.

This matters more than a broken snippet. A blanket 403 on every key is exactly
the ambiguous signal A0.1 exists to *eliminate* — it looks precisely like "the
keys are dead" and would have sent this phase into key rotation or a support
ticket before spending a single token. The liveness check has to go through the
same HTTP client the product uses:

```python
from groq import Groq
sorted(m.id for m in Groq(api_key=key).models.list().data if 'gpt-oss' in m.id)
```

### A0 finding 2 — the TPD ceiling is real but invisible until you hit it

The plan paces everything against a **200K tokens-per-day** limit. Groq's
response headers do not mention it. A live probe of both models returns only:

| Header | Value |
|---|---|
| `x-ratelimit-limit-tokens` | **8000** (per minute) |
| `x-ratelimit-limit-requests` | **1000** |
| `x-ratelimit-remaining-tokens` | 7927 |
| `x-ratelimit-reset-tokens` | 547ms |

There is no `*-tokens-day` header at all, at any point, including when the daily
budget is nearly gone.

On the strength of that this document initially concluded there was no daily
ceiling. **That was wrong**, and the A2 matrix proved it by walking into the
wall — the limit exists and appears only in the body of the 429 that enforces it:

```
rate limit reached for model `openai/gpt-oss-20b` … on tokens per day (tpd):
limit 200000, used 199306, requested 3187. please try again in 17m56.976s.
```

So the plan's figure was right and its risk note was well-founded. The practical
consequence is worse than if the limit were merely low: **it cannot be monitored.**
Nothing in the headers, `/health`, or `get_quota_snapshot()` can tell you that
190K of 200K is gone, so there is no way to pace against it prospectively — the
first indication is the failure itself. Any budgeting has to be done by summing
`total_tokens` from the `projects` table locally.

Both limits bind, at different timescales: 8K TPM governs how *fast* a build can
run (A1 spent most of its 774s in `waiting 26–55s for token-per-minute budget`),
and 200K TPD governs how *many* builds exist in a day. At the measured ~98K per
build, that is **two builds per day**.

---

## A1 — Closing Phase 22's open thread

```
LOG_LEVEL=INFO venv/Scripts/python.exe main.py \
  "Build a todo app with a REST API and a SQLite database"
```

Result: **`DONE (WITH CONTEXT)`** — `todo_app_4fe8055a`, 6 files, 774.5s.

| Metric | Value |
|---|---|
| Debug | 5/5 files passing |
| Review | 5.0 / 10 |
| Tests | 6/9 |
| Runtime smoke | **5/5 routes responded without a server error** |
| Reason | 2 unresolved verification issues after automatic repair |

### The three Step-1 assertions

| # | Assertion | Verdict |
|---|---|---|
| 1 | `🔥 Runtime smoke test` appears and reports N/N routes, 0× 5xx | ✅ **Confirmed.** `🔥 Runtime smoke test: 5/5 routes responded without a server error`, every probe logged `✅`, no `🚨`. |
| 2 | A clean build reaches `done` and writes **no** `SESSION_CONTEXT.md` | ⚠️ **Not demonstrated.** This build was not clean — it finished `done_with_context` and *did* write `SESSION_CONTEXT.md` (4411 chars), correctly, because two verification issues survived repair. The negative case needs a build that actually finishes clean; see A2. |
| 3 | A degraded build shows the amber panel and stays downloadable | ✅ **Confirmed**, though not against the CLI build (A1 finding 1). Verified against a `done_with_context` build the platform holds: `GET /projects/{id}/download` → HTTP 200, `application/zip`, 13,814 bytes, valid `PK\x03\x04` header. The amber panel itself is `bp-note--warn`, already covered by the offline suite and re-asserted live in A4. |

The smoke test — the single feature Phase 22 shipped without live proof — works.
That is the one thing A1 was for, and it is now evidence rather than assumption.

### A1 finding 1 — CLI builds are invisible to the platform

The plan says "Record `total_tokens` from the DB for this build." That is not
possible. `main.py` persists **nothing**: after the run, `projects` still held
exactly 50 rows and no row referenced `todo_app_4fe8055a`. The most recent DB row
is an unrelated build from a previous session.

Two consequences, and the second is the one that matters:

1. Assertion 3 cannot be evaluated against a CLI build at all — `GET /downloads/{id}`
   is keyed on a `build_id` the CLI never registers.
2. **Token usage was measured and then discarded.** The pipeline *does* call
   `llm_client.set_current_build_id()` (`pipeline.py:232`, `:1002`), so every call
   was counted into `_token_store` for the whole run — but only `runner.py:429`
   ever reads it back, so a CLI build throws the number away at exit. The unit of
   currency this phase is supposed to be paced by was collected and dropped on
   the floor.

Fixed — see A5 fix 2. A1's own token figure is unrecoverable; the A2 matrix
supplies the numbers instead, which is also why the matrix was run through the
API rather than the CLI.

### A1 finding 2 — the empty-file guard fires, and holds

`backend/services.py` was first written at **0 chars**. Phase 22's generator
self-verification caught it and the file ended the run at 2512 chars with real
content. Working as designed; recorded because it is the first live confirmation
of that guard.

---

## A2 — Live matrix

Pass criterion, fixed before any build ran (from the plan):

> ≥3 of 4 reach `done` or `done_with_context` with a downloadable ZIP, and every
> build that boots reports **0 5xx** from the smoke test.

Run sequentially through `POST /projects/` against a server restarted with the
A5 fixes applied, checking `/health` between builds. The API path is used rather
than the CLI so that status, scores and tokens are actually recorded (A1
finding 1).

### Sequencing note — why there is a "before" row and then a fresh matrix

The matrix was started on the shipped code. Its **first build exposed two
defects severe enough to invalidate the remaining three** (Fix 3, truncation;
Fix 4, the gutting repair) — every subsequent build would have been measuring a
bug already diagnosed, at roughly 15 minutes and ~98K tokens each.

So the driver was stopped after build 1 rather than spending ~45 minutes
confirming a known result. Build 1 was left to finish server-side on the
unmodified server, giving one honest "before" data point; the four fixes were
then applied and the **full four-build matrix re-run on fixed code**. The pass
criterion was not changed.

### Before — build 1 on shipped code

| Field | Value |
|---|---|
| Prompt shape | simple FastAPI + SQLite CRUD (bookmark manager) |
| Status | `done_with_context` |
| Debug | 5/5 |
| Review | 7.33 / 10 |
| Tests | 12/12 |
| **Runtime smoke** | **🚨 App failed to boot** — `cannot import name 'router' from 'routes'` |
| Downloadable | ✅ 12,920-byte valid ZIP |
| Tokens | **98,490** (56,541 in / 41,949 out) |
| Duration | 810.5s |

Read that row carefully: **every score is healthy and the application does not
start.** Debug passed because the gutted file imports; the reviewer scored the
remains 7.33; the tester reported 12/12 against an app with no routes. The only
signal that told the truth was the Phase 22 smoke test — which is a direct
vindication of the feature A1 existed to validate, arriving as a byproduct of
trying to validate something else.

This is also the honest answer to the plan's **Risk 1**. Build quality here was
not dominated by architect variance; it was dominated by two mechanical defects
in the repair path, both fixable, both now fixed. Precedent retrieval would not
have helped this build at all.

### The 98K figure, and the pacing it implies

98,490 tokens for one simple CRUD app is the measured unit of currency. Set
against the plan's assumed 200K/day ceiling that would allow **two builds a
day** — but as A0 finding 2 establishes, no such daily ceiling is reported. The
real cost is time: ~13.5 minutes wall, most of it spent waiting on the 8K TPM
budget.

### After — the matrix could not be completed: the day's quota ran out

| # | Shape | Status | Tokens | Duration | Downloadable |
|---|---|---|---|---|---|
| 1 | simple FastAPI + SQLite CRUD | `done_with_context` (quota, 30%) | 6,631 | 38.8s | ✅ ZIP |
| 2 | medium FastAPI + JS frontend | `failed` | 0 | 0.04s | ✗ 400 |
| 3 | complex / multi-entity | `failed` | 0 | 0.04s | ✗ 400 |
| 4 | non-FastAPI (CLI) | `failed` | 0 | 0.04s | ✗ 400 |

Build 1 reached step 4 and hit the 200K TPD wall (`used 199306, requested 3187`).
Builds 2–4 then died in 0.04s each without issuing a single call.

**The matrix does not meet its pass criterion, and it is not evidence about
generation quality.** It is evidence about quota: three of the four builds never
ran. The criterion (≥3 of 4 downloadable, 0 5xx from anything that boots) must be
re-evaluated on a fresh day. Nothing here should be read as a verdict on the
generators.

The budget arithmetic explains it exactly, and is worth keeping:

| Spend | Tokens |
|---|---|
| A1 CLI build (recovered by subtraction) | ~94,200 |
| Matrix-1 build 1 (bookmark manager) | 98,490 |
| Matrix-2 build 1 (before the wall) | 6,631 |
| **Total** | **~199,300 of 200,000** |

Two full builds is the daily budget. The plan's Risk 3 — "pace the matrix against
the measured per-build token cost and stop at the ceiling" — was correct, and this
phase could not honour it because the measurement it depends on (A1's token cost)
was being discarded by the CLI at the time (A1 finding 1, now fixed by Fix 2).

**However, the failures were not wasted.** Builds 2–4 exposed Fix 5, which is a
genuine defect in the Phase 21 feature this whole phase exists to validate.

---

### What the matrix still owes

On a fresh day, re-run `a2_matrix.py` (four sequential builds, ~13 min and ~98K
tokens each — the budget allows **two per day**, so the matrix needs two days).
Rows 2 and 4 are the two that have never run even once and carry the most
unknown: row 2 is the only exercise of `frontend_generator` / `frontend_debugger`
and the dangling-import guard, and row 4 is the documented smoke-test blind spot
where a non-FastAPI app must skip cleanly rather than crash.

---

## A3 — Deliberate quota-exhaustion run

The switch is implemented: **`GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS`** in
`llm_client.py`, default `0` (off), sitting with the other `GROQ_*` env knobs.

The design constraint is that the simulation must be *worthless* if it is
distinguishable from the real thing, so it reuses `_make_quota_error()` — the
same helper every genuine raise site calls — and also calls
`_mark_model_daily_limited()`, so `get_quota_snapshot()` is populated exactly as
it would be on a real wall. Without that second call the handoff document would
be produced with empty diagnostics, which is the one thing it exists to carry.

`test_phase23.py` §3–4 assert the sameness directly: same exception type, same
`GroqRateLimitError` base (so existing handlers catch it), same message, same
`model` / `keys_total` / `reset_hint`, `reason == "simulated"` so no one mistakes
an artefact for an outage, and a populated quota snapshot afterwards.

### The end-to-end verification happened for real, twice

A3's *purpose* is to prove the Phase 21 handoff path still works on the current
models. It was proven against a genuine 200K TPD wall rather than a simulated
one — better evidence than the switch was designed to produce:

| Case | Build | Outcome |
|---|---|---|
| Quota runs out **mid-build** (step 4 of 9) | `de756d20` | `done_with_context`, real quota diagnostics in `SESSION_CONTEXT.md`, **8,963-byte valid ZIP** |
| Quota **already gone** at step 1 | `6c50833c` | `done_with_context`, quota reason recorded, **5,651-byte valid ZIP** — *after Fix 5; the same condition produced a hard `failed` before it* |

The handoff document carries live diagnostics from `get_quota_snapshot()` as
specified — 8 keys total, `gpt-oss-20b` exhausted, `gpt-oss-120b` available,
plus the reset hint.

The simulation switch itself is implemented and covered by 36 offline
assertions, but it never fired end-to-end: the real quota wall pre-empted it
every time. It remains valuable precisely for the situation this phase could not
create on demand — exercising the path on a day when quota is *plentiful*.

**One cosmetic wrinkle, not fixed:** the handoff table reads
`Keys still usable | 8` and `Keys exhausted (any model) | 8` on the same
document. Both are technically true (usable for `120b`, exhausted for `20b`) but
together they read as a contradiction. Worth a wording pass.

---

## A4 — Full-stack E2E against a live backend

Landed as `frontend/e2e/live.spec.ts` plus a new Playwright project, run with
`npm run test:e2e:live`. Four tests: WebSocket step transitions reach
`StepTracker` rather than the 5s poll fallback; cancel mid-build yields
`cancelled` and never claims completion; the ZIP downloads and starts with the
`PK\x03\x04` local-file-header magic; and, under the A3 switch, the handoff
banner renders while the download stays enabled.

### A4 finding — `testIgnore` alone does not exclude a project

The plan asks for a `live` project "excluded from the default `npm run test:e2e`".
Adding `testIgnore: /live\.spec\.ts/` to the `chromium` project is not sufficient:
a bare `playwright test` runs **every declared project**, so `live` would have
executed anyway and started real builds — the exact opposite of the intent, and
it would have done so silently. Verified: the default listing went from 80 to 84
tests.

The project is therefore only *declared* when it is explicitly selected:

```ts
const LIVE_REQUESTED = process.argv.some(
  (arg, i) => arg === '--project=live' || (arg === '--project' && process.argv[i + 1] === 'live')
);
```

Default run is back to **80 tests in 4 files**; `--project=live` lists **4 tests
in 1 file**.

---

## A5 — Findings and fixes

### Fix 1 — the import check could not validate a package (quota burn)

**Found by:** the A1 live run, then reduced to a deterministic repro.

`run_python` (`tools/code_executor.py`) validated every generated file with:

```python
spec = importlib.util.spec_from_file_location('routes', '.../backend/routes.py')
spec.loader.exec_module(mod)
```

That gives the module no package context, so a perfectly valid
`from .models import TodoOut` raises `ImportError: attempted relative import with
no known parent package`. **The file was correct; the check was wrong.**

The Debugger believed the check. In the A1 run it burned LLM calls rewriting
working package code until it produced something the broken check would accept —
spending the budget this phase is paced against in order to make the output
*worse* (path-shim preambles instead of ordinary package imports). It self-healed
on attempt 2, so this was never a build failure, which is precisely why it had
survived: it only ever showed up as cost.

**Fix:** if a file sits inside a package — an unbroken chain of `__init__.py`
above it — import it by its real dotted name with the package root on `sys.path`.
Relative imports then resolve exactly as they do at runtime. Files outside a
package take the original path, unchanged.

**Regression test:** `test_phase23.py` §7, written first and **verified red**
(`25/26`) before the fix, green (`26/26`) after. It pins the three ways an
over-broad fix would be worse than the bug: a genuinely missing module must still
fail, a non-package module must be unaffected, and a syntax error inside a
package must still be caught. All three were already green while the bug was
present, so they are load-bearing.

### Fix 2 — the CLI discarded its own token measurement

**Found by:** A1 finding 1.

`main.py`'s summary panel now reports `Tokens: N (in / out)` from
`llm_client.get_and_reset_token_usage()`. The data was already being collected
for the whole run and thrown away at exit. `print_summary` is CLI-only (verified:
its sole caller is `main.py:320`), so this cannot race the API runner's own read.

### Fix 3 — truncated completions were accepted as if they were code

**Found by:** the first build of the A2 matrix. This is the most consequential
finding in the phase.

`bookmark_manager_c95501b4/backend/routes.py` came back cut off mid-statement:

```python
    if not cursor.fetchone():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
```
```
SyntaxError: '(' was never closed
```

The model had hit its output budget and said so — `finish_reason="length"`.
**Nothing in the codebase ever read `finish_reason`.** `_call_groq` returned
`data["choices"][0]["message"]["content"]` unconditionally, so a half-written
file was handed to the caller as a complete answer.

The cost compounds. The Debugger spent all three repair attempts on that file
and failed every one (`attempts: 3, fixes: 0`) — because each repair was
truncated the same way — then ran a root-cause pass and failed again. One
truncated call turns into five wasted ones, and the build ends degraded.

The project already knew this was the worst case. `llm_client.py:271-277` says
so in as many words: *"Truncated code is worse than useless — it is a syntax
error that the debugger then burns retries on."* The measurement was done, the
conclusion was written down, and the check that would act on it was never
written. `reasoning_effort=low` and the 1600-token floor reduced the frequency
enough that it stopped being obvious.

**Fix:** when `finish_reason == "length"`, retry with a larger output budget
(default ×2, up to 2 retries, both env-tunable) instead of returning the
fragment. A truncated call has already been paid for, so the retry salvages work
that was otherwise guaranteed to be discarded — and it removes the 3–5 failed
repair calls that followed. If it still truncates, the longest response is
returned with a loud `ERROR`, because an explicit warning beats a silent syntax
error.

**Also fixed in passing:** `max_tokens = _fit_output_budget_to_model_limit(…, max_tokens)`
assigned back into the same variable, so on any retry the budget was re-shrunk
from the already-shrunken value and ratcheted downward within a single call. The
caller's request is now held separately in `requested_max_tokens`.

**Regression test:** `test_phase23.py` §8, **verified red** (`26/29`) before the
fix, green (`29/29`) after. It stubs the HTTP boundary, so it costs nothing and
is deterministic. The red run reproduced production exactly: one call, budget
1600, truncated text returned verbatim to the caller.

### Fix 4 — a "repair" could delete the file it was repairing

**Found by:** the same build. This is the most damaging behaviour seen in the
phase, and it is downstream of Fix 3.

After `routes.py` arrived truncated, the Debugger repaired the syntax error by
**deleting the entire body of the file**. 2980 chars of route handlers became
413 chars of imports, with no `router = APIRouter()` left anywhere:

```python
from fastapi import APIRouter, Depends, HTTPException, status
import sqlite3
from typing import List

from schemas import BookmarkCreate
```

That is the complete file, post-"repair". It compiles perfectly, so the import
check passed and the repair was recorded as a success — while the application it
was repairing had ceased to exist. The smoke test caught the wreckage
(`🚨 App failed to boot: cannot import name 'router' from 'routes'`), but the
build still finished `done_with_context` with **review 7.33, tests 12/12** and a
downloadable ZIP.

The mechanism is worth stating precisely, because it generalises: the Debugger's
success criterion is *"the file imports cleanly"*, and **an empty module imports
perfectly**. Deleting code is the cheapest available way to satisfy the check.
`_accept_generated_fix` was asymmetric — it rejected fixes that were too *large*
(a multi-file paste, >1.6× or +1800 chars) and had no lower bound whatsoever.

**Fix:** a repair is now rejected if it drops a top-level symbol that existed
before (`router` vanishing is exactly the case that broke this build), or if it
shrinks a non-trivial file by more than half. Symbol extraction is by regex, not
`ast` — the file under repair is usually a syntax error, which is precisely when
an `ast`-based check cannot run.

**Regression test:** `test_phase23.py` §9, **verified red** (`31/33`) before the
fix, green (`33/33`) after, using the exact before/after content from the live
run. Two of its four assertions — a genuine repair is still accepted, and an
oversized multi-file paste is still rejected — were already green while the bug
was present, so they pin the guard against over-correction.

### Fix 5 — the quota handoff only worked if quota ran out *mid-build*

**Found by:** the A2 matrix hitting a real 200K TPD wall. This is a defect in the
Phase 21 feature this entire phase exists to validate, and it fires at that
feature's single most likely trigger point.

A build that runs *into* the quota mid-flight is handled exactly as designed:
`GroqDailyQuotaError` is raised, Phase 21 intercepts it, work-in-progress is
packaged, `SESSION_CONTEXT.md` is written with real diagnostics, and the build
ends `done_with_context` with a downloadable ZIP.

A build submitted when the quota was **already** gone got none of it. With every
key already marked exhausted, `_get_next_groq_key` returns `None` and the code
raised a bare `RuntimeError`. Different type, so the interception never saw it:

| | quota runs out mid-build | quota already exhausted |
|---|---|---|
| Exception | `GroqDailyQuotaError` | `RuntimeError` |
| Status | `done_with_context` | `failed` |
| `completion_reason` | full diagnostics | **NULL** |
| `SESSION_CONTEXT.md` | ✅ written | ✗ none |
| `output_path` | real project folder | `generated_projects\project` |
| Download | ✅ ZIP | ✗ HTTP 400 |

Live, builds 2, 3 and 4 all died this way in 0.04s. The user is shown "Build
failed" and, because `completion_reason` is NULL, the frontend falls back to
"Check the step log above for the failing agent" — for a build that has no steps
and whose real cause is perfectly well known.

The tell was in the old message itself: *"Daily quota **or** key authentication
failures are blocking this model."* It knew it was conflating two causes; the
exception type followed the message rather than the cause.

**Fix:** when no key remains *and the model is flagged daily-limited*, raise
`_make_quota_error(model, reason)` so the same wall produces the same error
whatever the timing. Genuine auth failure keeps a `RuntimeError`, now with a
message that says only what it means.

**Verified live, not just in test.** After the fix, a build submitted into a real
exhausted quota (`6c50833c`) finished `done_with_context` with a recorded reason
and a 5,651-byte valid ZIP — the same condition that produced `failed` + NULL +
HTTP 400 an hour earlier.

**Regression test:** `test_phase23.py` §10, **verified red** (`33/36`) before the
fix, green (`36/36`) after.

### Finding 6 — the download endpoint in the plan does not exist, and the miss is invisible

`PHASE23_PLAN.md` refers to `GET /downloads/{id}` in both A3 and C4. There is no
such route. `downloads.py` mounts its router at `prefix="/projects"` and the real
path is **`GET /projects/{build_id}/download`**.

What makes this worth writing down is not the wrong path — it is that the wrong
path *appears to work*. The SPA history fallback (`main.py`, `@app.get("/{full_path:path}")`)
answers **any** unmatched GET with `index.html` and HTTP **200**, regardless of
what the client asked for:

```
GET /downloads/fb3e4b24-…  →  200  text/html  1540 bytes   ← the SPA shell
GET /projects/fb3e4b24-…/download  →  200  application/zip  13814 bytes
```

A 200 with an HTML body is what a mistyped API path returns to a non-browser
client, so an integration bug reads as success until something inspects the
content type. It briefly fooled the verification for this very phase.

**Not fixed here, deliberately.** The narrow fix — have the catch-all `raise
HTTPException(404)` when the request did not ask for `text/html`, leaving genuine
browser navigations alone — is small and safe, but it changes request routing for
the entire product, and four live builds were running through that server at the
time. It is also entangled with B4, which relies on this mount to serve the whole
product from one port. Recommend doing it as its own change with its own test.

### Not fixed — recorded instead

- **The tester generated a 41-char `test_main.py`** and then reported
  `Tests: 0/0 passing (attempt 3)` — three attempts spent producing an empty test
  file that is scored as a failure. Worth a look, but it is a generation-quality
  issue rather than a defect with a deterministic repro, and the A2 matrix is the
  right evidence base for judging it. Feeds directly into the plan's Risk 1.

---

## Suite status after the A5 fixes

| Suite | Result |
|---|---|
| `test_phase17.py` | ✅ 53 / 53 — see note |
| `test_phase21.py` | ✅ 77 / 77 |
| `test_phase22.py` | ✅ 85 / 85 |
| `test_phase23.py` | ✅ **36 / 36** (new) |
| `test_groq_rate_limit_handling.py` | ✅ 4 / 4 |

> **`test_phase17` note.** Its total moved from 54 to 53 across this phase, which
> is not a regression: the suite picks the first `done`/`failed` project the API
> returns and asserts on whatever that build happens to contain. The newest such
> project is now one of the instant-failure builds from A2, which has no
> completed step carrying `elapsed_seconds`, so one conditional assertion does
> not fire. Worth flagging on its own terms — **a suite whose assertion count is
> a function of database contents is a weak regression signal**, because
> "53/53 passed" and "54/54 passed" look equally green while covering different
> things. Pinning it to a fixture build would fix that.

---

## Summary — what Phase A actually established

**Proven:**

- The Phase 22 runtime smoke test works, and is the only check that told the
  truth about a broken build (A1, and the `bookmark_manager` post-mortem).
- The Phase 21 quota handoff works against a real wall, in both the mid-build and
  the already-exhausted case — the latter only after Fix 5.
- A degraded build stays downloadable.
- 200K TPD is real, invisible, and allows ~2 builds/day at the measured cost.

**Not proven, and honestly outstanding:**

- The A2 matrix. Three of four builds never ran. Rows 2 (JS frontend) and 4
  (non-FastAPI smoke skip) remain entirely untested and need two more days of
  quota.
- Assertion 2 from A1 — that a *clean* build writes no `SESSION_CONTEXT.md` —
  has still never been observed, because no build in this phase finished clean.

**Five fixes, each with a red-first regression test:**

| Fix | What it stops |
|---|---|
| 1 · package-relative import check | Debugger rewriting correct code to satisfy a broken check |
| 2 · CLI token reporting | the pacing measurement being collected and discarded |
| 3 · truncation retry | half-written files returned as complete code |
| 4 · repair-shrinkage guard | a "fix" deleting the file it repairs |
| 5 · quota error type | a hard failure with no diagnostics when quota is already gone |

---

## Follow-on — raising daily build capacity

Phase A established the binding constraint: ~98K tokens per build against a 200K
per-model daily limit, i.e. **two builds a day**. The work below came out of
asking whether that could be raised without giving up quality. It could, because
the spend was lopsided rather than simply large.

### The finding: half the daily budget was never being used

The 429 names a model — *"rate limit reached for model `openai/gpt-oss-20b` … on
tokens per day (tpd): limit 200000"* — and during that exhaustion the handoff
document recorded `gpt-oss-120b: available`. **The two budgets are separate.**
Yet `_DEFAULT_HEAVY_AGENTS = "architect"` sent **40 of a build's 41 calls** to the
fast model. One 200K bucket was drained daily; the other sat nearly untouched.

The cause was a stale assumption. The routing docstring reasoned about a small
"free-tier 70b quota" beside a larger "8b quota" — true of the decommissioned
llama pair, false for the gpt-oss models that replaced them, where both carry the
same 200K. The comment protecting a scarcity that no longer existed is what
concentrated all the load on one model.

### Also worth knowing: 8 keys do not multiply the daily quota

The 429 attributes the limit to `organization org_01kjhb2kvxft0s58tg3tz9mg0p`.
All 8 keys rotate inside one organisation and therefore share one 200K pool per
model. Key rotation protects against per-key faults; it does nothing for TPD.

### What changed

| # | Change | Why it does not cost quality |
|---|---|---|
| 1 | **Per-model daily token ledger**, rolling 24h, persisted, surfaced in `/health` and `get_quota_snapshot()` | Pure instrumentation. Groq reports the daily limit *only* inside the 429 that enforces it, so nothing could previously see that 190K of 200K was gone. |
| 2 | **Code-producing agents moved to `gpt-oss-120b`** | It is the stronger model, and it is now writing the code. It also accepts `reasoning_effort=low`, which `20b` rejects — the measurement already in `llm_client.py` has 120b producing 3541 chars in **849 tokens** where 20b needs a **1600-token floor**. |
| 3 | **Codegen token caps raised** 950 → 2000 | Caps are not spend. 950 is the budget that truncated live, and since Fix 3 each truncation costs a whole extra call to recover. |
| 4 | **Debugger prompt bounded** — traceback trimmed to its tail, project map omitted for non-import errors and capped at 40 entries | The Debugger is 44% of calls and had *no* cap of any kind. None of this removes information the model needs. |
| 5 | **Fast→heavy quota fallback** | The mirror of an existing heavy→fast branch. Under the new routing the fast model runs out first, and without this a build died with half the day's tokens still unspent. |

**Deliberately not done:** trimming the source file on repair retries. It was in
the original plan on the reasoning that "the model already has the structure from
attempt 1" — which is wrong, because every `_generate_fix` call is a fresh
stateless request. Sending less source on a retry would hand the model *less* than
the attempt that already failed, and Fix 4's guard would then reject the weaker
result, costing more calls than it saved.

Also rejected: batching several files into one generation call (larger outputs are
exactly what triggers `finish_reason=length`), and lowering caps to save tokens
(caps are not spend; lowering them causes the truncation that costs retries).

### A cap that was never real

While right-sizing the budgets: under `GROQ_FREE_TIER_CONSERVE`, every *fast*-model
agent's cap was inert. `gpt-oss-20b` cannot be told to reason less, so
`_apply_reasoning_budget` raised anything below `_REASONING_MIN_TOKENS` (1600)
back up to it — the debugger's "850" was never 850. Those entries are now written
at the floor so the table states what actually happens.

### Verified live

A build run after the change put both models to work — `IntentAnalyzer` and
`Planner` on `20b`, `Architect` and `BackendDeveloper` on `120b` — with the ledger
reporting remaining budget per model for the first time.

Mid-build, `gpt-oss-20b` hit its genuine daily wall
(`used 199912, requested 1990`) and **the build did not die**:

```
Fast model [openai/gpt-oss-20b] is quota-exhausted for [Debugger];
retrying on heavy model [openai/gpt-oss-120b], which has its own daily budget.
```

The Debugger, then the Reviewer, all continued on the heavy model's separate
budget. This is the exact condition that killed matrix builds 2, 3 and 4 in
0.04s each — now absorbed.

### The ledger's honest limitation, found the hard way

The ledger counts only what **this process** has spent. It is an estimate of
Groq's counter, not a reading of it, so it under-reports after a cold start or if
anything else uses the same organisation's keys.

That limitation was made much worse by a bug in its own test suite: the tests
wrote to and reset the **real** ledger file. After a test run the ledger reported
`gpt-oss-20b` at **3.6%** while Groq's own counter said **99.9%** — the instrument
built to give warning of a quota wall would have walked straight into one. Fixed:
the suite now points `_LEDGER_PATH` at a scratch file and restores it afterwards,
with `test_phase23.py` §15 asserting the isolation holds.

### Fix 6 — the deployability cap was deleting the application's entry point

The verification build finished `done_with_context` with review 7.0 and tests
8/9 — and **could not be started at all**. There was no `app = FastAPI()` anywhere
in it, so the runtime smoke test reported *"skipped (no FastAPI entry point)"*.

The cause was in the architect, not in anything this phase changed:

```
Reduced backend Python architecture from 7 to 4 files for deployability.
Removed: ['backend/database.py', 'backend/exceptions.py', 'backend/main.py']
```

`_normalise_backend_architecture` trims an over-engineered backend down to a cap
using `sorted(backend_py, key=_backend_priority)[:cap]`. `BACKEND_FILE_PRIORITY`
ranked files by the order the layers are written — `models 0, schemas 1,
services 2, routes 3, main 4` — while the cap keeps the *lowest* numbers. For a
simple or medium app the cap is exactly **4**, so the survivors were
models/schemas/services/routes and **`main.py` was deleted**.

This is deterministic, not architect variance: *any* time the architect includes
a `schemas.py`, the app loses its entry point. Trimming for deployability that
removes the ability to deploy is not a trade-off.

**Fix**, in two parts:

1. The entry point (`main.py`/`app.py`) is reserved before the cap is applied;
   the cap then governs everything else.
2. `BACKEND_FILE_PRIORITY` now ranks by how *essential* a file is rather than by
   layer order — `main 0, routes 1, models 2, services 3, schemas 4`. This is
   what `_normalise_backend_architecture`'s own docstring always described as the
   target ("a deployable four-file FastAPI backend: models -> services -> routes
   -> main"); the table simply never encoded it.

A medium app capped at 4 now yields `main.py, models.py, routes.py, services.py`
— the documented shape — instead of four files that cannot run.

**Regression test:** `test_phase23.py` §16, **verified red** (`76/78`) before the
fix, green (`78/78`) after, using the exact 7-file architecture from the live
build. It also pins the behaviours an over-broad fix would break: the cap is
still enforced, an already-small architecture is untouched, and the existing
`app.py`-when-`main.py`-exists de-duplication still works.

**Still outstanding:** the ledger starts cold. Seeding it on boot from
`projects.total_tokens` for builds inside the window would make it accurate across
restarts — worth doing before anyone relies on it as a guard rather than a gauge.

---

**On the plan's Risk 1.** Phase A was supposed to tell us whether build quality is
dominated by architect variance — in which case vector memory (Phase C) is the
wrong lever. The evidence available says it is *not* architect variance: the one
build that completed on shipped code was destroyed by two mechanical defects in
the repair path (Fixes 3 and 4), and precedent retrieval would not have helped it
at all. That is a real signal, but it rests on **one build**, which is precisely
the single-data-point problem A2 existed to defeat. The matrix should be
completed before committing to Stage 5.1.
