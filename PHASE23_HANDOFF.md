# Phase 23 Handoff

*Updated 2026-08-28 at the end of the third session, which ran matrix rows 1-3
live, confirmed the request-time repair path fires on a real build, and fixed
the three mechanical defects those rows exposed. Read §0.0 first.*

Full evidence and reasoning: **`PHASE23_LIVE_VALIDATION.md`**.
Original plan: **`PHASE23_PLAN.md`** (Phases B and C are still untouched).

---

## 0.0 What changed in the third session (2026-08-28)

**The matrix is three rows deep and the runtime-repair path has now run live.**
Rows 1, 2 and 3 all built; row 4 was refused by the driver because neither model
had 70,000 tokens left, which is the refusal working as designed. Both daily
budgets are spent — `gpt-oss-120b` 103%, `gpt-oss-20b` 96% — so **no further
live build is possible until the 00:00 UTC reset.**

| Row | Shape | Status | Tokens | Boots? | Smoke |
|---|---|---|---|---|---|
| 1 | simple FastAPI + SQLite CRUD | `done_with_context` | 94,576 | yes | ✅ **5/5 routes** (was 2/5) |
| 2 | medium FastAPI + JS frontend | `done_with_context` | 171,914 | **no** | 🚨 app never loads |
| 3 | complex / multi-entity | `done_with_context` | 131,848 | yes | 🚨 **7/19 routes** |
| 4 | non-FastAPI (CLI) | ⬜ refused — quota | — | — | — |

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

## 0.0.1 Three fixes, all offline-verified, none yet run live

Quota ran out before any of them could be exercised on a build. They are the
first thing to check after the reset — the same position §4.1 was in last
session, and §4.1 duly proved out.

| # | Fix | What it removes | Tests |
|---|---|---|---|
| 1 | `requirements.txt` no longer reads as a stub once filled (§4.3) | A complete file degrading a build to `done_with_context` | §22, 11 assertions |
| 2 | A boot failure is repairable, not advisory (§4.4) | Row 2: the app never loads and **nothing tries to fix it** | §23, 11 assertions |
| 3 | Rewrite budgets sized to the code (§4.5) | A flat cap smaller than the file it must reproduce | §24, 7 assertions |
| 4 | **Repair one block, not the whole file (§4.6)** | Row 3: a 10.7KB repair that could not fit the minute it was sent in | §25-26, 37 assertions |
| 5 | `reasoning_effort` on both models; retries that grow (§4.7) | 13 completions that returned **zero characters** and were billed anyway | §27, 9 assertions |

`test_phase23.py` is **259 / 259** (was 182). Every other suite is unchanged and
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
| 2 | Re-run rows 2 and 3 to verify the §4.3-§4.7 fixes on a live build | yes — after 00:00 UTC |
| 3 | Row 4, the one shape never yet built: `run_live_matrix.py --rows 4` | yes |
| 4 | A1 assertion 2 — a clean build reaching `done` with no `SESSION_CONTEXT.md`. §4.3 removes the reason all three rows missed it | falls out of 2-3 |

**Both daily budgets are spent** (120b 103%, 20b 96%). Nothing in 2-4 can start
before the reset; item 1 needs no quota at all and is fresh-session sized.

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
7. **`run_live_matrix.py` overwrites `PHASE23_MATRIX_RESULTS.md`**, it does not
   merge. Running `--rows 1` and then `--rows 2,3,4` leaves a report describing
   rows 2 and 3 only, and its "N of N rows pass" line counts status and ZIP —
   **not** the smoke test, which is not in the API. The full picture is §0.0.
8. **The server holds the code it started with.** Every fix in §4.3-4.5 was made
   while a build was running, so the process that produced rows 2 and 3 never
   had them. Restart before reading anything into a re-run.
9. **The live E2E suite spends real quota**, so it is opt-in:
   `cd frontend && npm run test:e2e:live` with the backend already running. Test
   4 additionally needs `LIVE_QUOTA_SIM=1` on the runner and the backend started
   with `GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS=6` — and **restart the backend
   without that variable afterwards**, or every later build hands itself a
   simulated quota wall.
