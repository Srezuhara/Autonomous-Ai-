# Phase 23 Handoff

*Written 2026-08-26, at the end of the session that executed `PHASE23_PLAN.md`
Phase A and the quota-capacity follow-on. Read this first in a new session.*

Full evidence and reasoning: **`PHASE23_LIVE_VALIDATION.md`**.
Original plan: **`PHASE23_PLAN.md`** (Phases B and C are untouched).

---

## 1. State of the tree

**Nothing is committed.** All work is in the working tree on `main`.

| File | Change |
|---|---|
| `llm_client.py` | quota simulation switch; truncation retry; quota error type; per-model daily ledger; model-split default; token caps; fast→heavy fallback |
| `agents/debugger.py` | repair-shrinkage guard; bounded repair prompt |
| `agents/architect.py` | entry point exempt from the deployability cap; priority table reordered |
| `tools/code_executor.py` | package-relative import check |
| `main.py` | CLI reports token usage |
| `api_platform/main.py` | `/health` exposes per-model daily usage |
| `frontend/playwright.config.ts`, `frontend/package.json` | gated `live` E2E project |
| `frontend/e2e/live.spec.ts` | **new** — live E2E suite |
| `test_phase23.py` | **new** — 78 offline assertions |
| `PHASE23_LIVE_VALIDATION.md` | **new** — the evidence document |

### Suite status

| Suite | Result |
|---|---|
| `test_phase23.py` | ✅ 78 / 78 (new) |
| `test_phase21.py` | ✅ 77 / 77 |
| `test_phase22.py` | ✅ 85 / 85 |
| `test_phase17.py` | ✅ 53 / 53 — count is data-dependent, see §4 |
| `test_groq_rate_limit_handling.py` | ✅ 4 / 4 |
| frontend `typecheck` / `lint` / `test` / `build` | ✅ 191 unit tests, clean build |
| frontend E2E default | ✅ 80 tests listed in 4 files (`live` excluded) |

---

## 2. What was fixed (six fixes, each red-first)

| # | Fix | Symptom it removes |
|---|---|---|
| 1 | Package-relative import check (`code_executor.py`) | Debugger rewriting correct package code to satisfy a check that could not validate `from .models import X` |
| 2 | CLI token reporting (`main.py`) | CLI builds measured their token cost and discarded it at exit |
| 3 | Truncation retry (`llm_client.py`) | `finish_reason="length"` was never read; half-written files returned as complete code |
| 4 | Repair-shrinkage guard (`debugger.py`) | A "repair" deleting the file it repaired — an empty module imports perfectly |
| 5 | Quota error type (`llm_client.py`) | Quota already exhausted at build start → `failed`, NULL reason, no handoff doc, HTTP 400 download |
| 6 | Entry point exempt from cap (`architect.py`) | The deployability cap deleting `main.py`, shipping apps with no `app = FastAPI()` |

Fixes 3, 4 and 6 are the ones that were silently destroying builds. Fix 6 is
deterministic: *any* architecture including a `schemas.py` lost its entry point.

### Capacity work (the follow-on)

| Change | Effect |
|---|---|
| Per-model daily token ledger, rolling 24h, in `/health` + `get_quota_snapshot()` | The 200K/day limit is reported by Groq **only** inside the 429 that enforces it; now it can be seen beforehand |
| Codegen agents moved to `gpt-oss-120b` | Unlocks the second, separate 200K/day budget **and** uses the stronger model |
| Codegen caps 950 → 2000 | 950 is the budget that truncated live; caps are not spend |
| Debugger prompt bounded | 44% of calls, previously with no cap of any kind |
| Fast→heavy quota fallback | A build survives one model running out — verified live |

---

## 3. What must be done on fresh quota (the real outstanding work)

**Budget reality:** ~85–98K tokens per build against **200K per model per day**.
Two models ⇒ roughly 4 builds/day, and the matrix needs 4 builds. Plan for one
day, ideally starting with a full budget on both models.

### 3.1 — Verify Fix 6 produces a *booting* app  ← highest priority

Fix 6 is proven by unit test but has **never been confirmed end to end**. The
quality gate is explicit:

```
🔥 Runtime smoke test: N/N routes responded without a server error
```

not `ℹ️ skipped (no FastAPI entry point)` and not `🚨 App failed to boot`.

```bash
venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1
# then POST a simple FastAPI + SQLite CRUD prompt to /projects/
```

Confirm the generated project contains `backend/main.py` with `app = FastAPI()`.

### 3.2 — Complete the A2 matrix

`PHASE23_PLAN.md` A2's pass criterion, fixed before any build ran and **not yet
met**:

> ≥3 of 4 reach `done` or `done_with_context` with a downloadable ZIP, and every
> build that boots reports **0 5xx** from the smoke test.

Driver script (rewrite from scratch or recreate — it lived in the session
scratchpad, not the repo): four sequential builds through `POST /projects/`,
polling `/jobs/{id}/status`, recording from the `projects` table, checking
`/health` between builds.

**Rows 2 and 4 have never run even once** and carry all the unknown:

| # | Shape | Exercises |
|---|---|---|
| 1 | simple FastAPI + SQLite CRUD | baseline, smoke test |
| 2 | medium FastAPI + **JS frontend** | `frontend_generator`, `frontend_debugger`, dangling-import guard — **never tested live** |
| 3 | complex / multi-entity | the architecture cap at `complex` (6 files), architect variance |
| 4 | **non-FastAPI** (CLI/Streamlit) | the documented blind spot — smoke test must skip *cleanly* |

**Note on the download URL.** It is `GET /projects/{build_id}/download`. There is
no `/downloads/{id}` — and because the SPA history fallback answers any unmatched
GET with `index.html` and HTTP 200, the wrong URL *looks* like it works. Check the
content type or the `PK\x03\x04` magic, never the status code.

### 3.3 — A1 assertion 2, still never observed

That a **clean** build reaches `done` and writes **no** `SESSION_CONTEXT.md`. No
build in this phase finished clean, so this has never been seen. It should become
observable now that Fixes 3, 4 and 6 are in.

### 3.4 — Measure the true post-fix baseline

The 98,490-token baseline predates every fix. Re-measure one build and compare:
tokens per model, calls per agent, wall time. Per-agent call counts:

```bash
grep -oE "🧠 \[[A-Za-z]+\]" server.log | sort | uniq -c | sort -rn
```

Baseline to beat: **98,490 tokens, 41 calls, 810s**, of which the Debugger was
18 calls. A post-fix build should show materially fewer Debugger calls, because
the truncation→gutting cascade that inflated them is gone.

### 3.5 — Run the live E2E suite

```bash
venv/Scripts/python.exe start_server.py       # backend must be running
cd frontend && npm run test:e2e:live
```

Four tests, never yet executed against a live backend: WebSocket step transitions
reach `StepTracker` (not the 5s poll fallback), cancel yields `cancelled` and
never claims completion, the ZIP is a valid archive, and — with
`GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS` set and `LIVE_QUOTA_SIM=1` — the handoff
banner renders with the download still enabled.

### 3.6 — Then re-read Risk 1 before starting Phase C

`PHASE23_PLAN.md` Risk 1: if quality is dominated by architect variance rather
than missing precedent, vector memory is the wrong lever.

The evidence so far says it was **not** variance — it was three mechanical
defects (Fixes 3, 4, 6), all now fixed, none of which precedent retrieval would
have helped. But that rests on **two builds**, which is exactly the
single-data-point problem A2 exists to defeat. Complete the matrix first.

---

## 4. Known issues not fixed

- **The ledger starts cold.** It counts only what the current process has spent,
  so after a restart it under-reports. Observed: it read `gpt-oss-20b` at 3.6%
  while Groq's counter said 99.9%. **Seed it on boot** from `projects.total_tokens`
  for builds inside the 24h window before relying on it as a guard rather than a
  gauge. *(This is offline work — no quota needed.)*
- **`test_phase17.py`'s assertion count is data-dependent.** It asserts on
  whichever `done`/`failed` project the API returns first, so the total moves
  (54 → 53) as the database changes. "53/53 passed" and "54/54 passed" look
  equally green while covering different things. Pin it to a fixture build.
- **The SPA catch-all returns 200 + HTML for any unmatched GET.** A mistyped API
  path reads as success to a non-browser client. The narrow fix is to 404 when
  the request did not ask for `text/html`, leaving browser navigations alone — but
  it touches product-wide routing and B4 depends on this mount, so it deserves its
  own change and test.
- **The handoff document's key table reads as a contradiction** —
  `Keys still usable | 8` beside `Keys exhausted (any model) | 8`. Both are true
  (usable for `120b`, exhausted for `20b`); the wording needs a pass.
- **8 keys do not multiply the daily quota.** All rotate inside
  `org_01kjhb2kvxft0s58tg3tz9mg0p` and share one 200K pool per model.

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
