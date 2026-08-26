# Phase 23 Handoff

*Updated 2026-08-26 at the end of the second session, which committed the first
session's work, closed the four offline defects it had listed, and spent the
remaining quota on live validation. Read this first in a new session.*

Full evidence and reasoning: **`PHASE23_LIVE_VALIDATION.md`**.
Original plan: **`PHASE23_PLAN.md`** (Phases B and C are still untouched).

---

## 0. What changed in the second session

Everything is **committed** on `main`, as seven commits named `groq api fixes…`.

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

## 1. State of the tree

Committed on `main`. Working tree clean apart from `frontend-screenshots/`,
which is deliberately untracked.

### Suite status

| Suite | Result |
|---|---|
| `test_phase23.py` | ✅ 142 / 142 (78 → 142; sections 17-20 are new) |
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

### 4.1 — Generated routes wrap a generator dependency (the row 1 500s) ← next

Reproduced offline, no quota needed:

```
File "…/backend/routes.py", line 53, in list_tasks_endpoint
    return get_tasks(db)
File "…/backend/crud.py", line 68, in get_tasks
    cur = conn.execute(
AttributeError: 'generator' object has no attribute 'execute'
```

`crud.get_db()` is a generator function. `routes.py` wrote its own `get_db()`
that calls it as if it returned a connection, then yields the *generator*, so
every DB-touching route gets a generator where it expects a connection. The two
routes that "passed" only returned 422 — request validation rejected them before
they reached the database.

What this says about the pipeline, and why it matters more than the bug:

- the import check passes (the module imports fine);
- the generated unit tests pass (9/12 — they call `crud` directly, never through
  the dependency);
- the reviewer scored it 6.0;
- **only the runtime smoke test caught it**, and remediation then made no
  progress on it ("no files were repaired this pass").

So the smoke test is earning its keep and the repair path is not. Deciding
whether the Debugger should be given the smoke-test failures as input is
probably the highest-value pipeline change available.

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
7. **The live E2E suite spends real quota**, so it is opt-in:
   `cd frontend && npm run test:e2e:live` with the backend already running. Test
   4 additionally needs `LIVE_QUOTA_SIM=1` on the runner and the backend started
   with `GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS=6` — and **restart the backend
   without that variable afterwards**, or every later build hands itself a
   simulated quota wall.
