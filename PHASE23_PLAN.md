# Phase 23+ Plan — live validation → production hardening → vector memory

*Written 2026-08-25. Covers the three phases queued after Phase 22: the live test
run that Groq quota exhaustion blocked, Stage 4 production hardening, and Stage 5.1
vector memory on ChromaDB.*

## Context

The frontend work is finished and verified (`SESSION_PROGRESS.md` §2.6–2.8) but the
backend has an open thread. `PHASE22_HANDOFF.md` §6 Step 1 says it plainly: the
Groq daily token quota (200K TPD) ran out during Phase 22 validation, so the final
end-to-end run **never completed**. Phase 22's runtime smoke test, route-aware
tester guidance and generator self-verification are all committed and covered by
85 offline assertions — but only *one* live build ever ran to completion on the
new gpt-oss models, and the handoff itself warns that "one good build is not
evidence the generators improved."

So the first thing quota returning buys is proof, not features. After that come
the two things the roadmap has been deferring: Stage 4 production hardening
(`PROJECT_CONTEXT_AND_PLAN_5.md` §5) and Stage 5.1 vector memory, whose dependency
`chromadb>=0.5.0` has sat in `requirements.txt` since Phase 19 without a single
`import chromadb` anywhere in the source.

**Cost constraint: everything here must be free.** It is. Verified rather than
assumed:

| Component | Cost | Evidence |
|---|---|---|
| ChromaDB + embeddings | **$0**, fully local | Ran it: `chromadb 1.5.8`, `DefaultEmbeddingFunction` → ONNX `all-MiniLM-L6-v2`, 384-dim, no API key, no torch. One-time 79 MB model download, now cached at `~/.cache/chroma/onnx_models/` |
| PostgreSQL, Alembic, SQLAlchemy | $0, open source | `psycopg2`, `sqlalchemy`, `alembic` are **already installed** in the venv |
| slowapi, prometheus-client, python-jose, passlib | $0, open source | `passlib[bcrypt]` and `python-jose` are already declared in `requirements.txt` |
| Docker Desktop | $0 for personal use | Compose also runs on plain Docker Engine |
| Sentry | **opt-in only** — disabled unless `SENTRY_DSN` is set | Default config transmits nothing anywhere |

The only budgeted resource is Groq free-tier quota, and Phase A is designed around
spending it deliberately.

**Ordering note.** Hardening lands before vector memory on purpose: auth
introduces `owner_id`, and if memory is built afterwards every remembered build
carries its owner from the first write instead of needing a backfill.

**Before anything:** the landing restructure is still uncommitted
(`SESSION_PROGRESS.md` §3.1 item 1 — `Landing.tsx`, `landing.css`, `NewBuild.tsx`,
`charts/index.tsx`, new `charts/frame.tsx`, `components/landing/`). Review and
commit it, so a live-validation phase starts from a clean tree and any regression
found is attributable.

---

# Phase A — Live validation on fresh quota

No feature work. The deliverable is evidence, plus fixes for whatever the evidence
exposes. Output document: **`PHASE23_LIVE_VALIDATION.md`**.

### A0. Pre-flight — zero tokens

1. **Check the models are still alive before touching keys.** This is the trap
   `PHASE22_HANDOFF.md` §5 names: decommissioned models return HTTP 404 on every
   key and the retry loop reports it as `All 8 usable Groq keys tried for [] without
   success` — indistinguishable from quota exhaustion.
   ```bash
   curl -s -H "Authorization: Bearer $GROQ_API_KEY" \
     https://api.groq.com/openai/v1/models | grep -o 'gpt-oss[^"]*'
   ```
   Expect `openai/gpt-oss-120b` and `openai/gpt-oss-20b`.
2. `GET /health` → `llm.status` must be `healthy`, `groq_keys_available` = 8.
   If keys are still marked exhausted from before, `POST /admin/reset-keys`.
3. Run every offline suite green first — a live failure must not be a pre-existing one:
   `test_phase21.py` (77), `test_phase22.py` (85), `test_groq_rate_limit_handling.py`,
   and the frontend `typecheck / lint / test / build`.

### A1. Close Phase 22's open thread

One CLI build, exactly as the handoff specifies:

```bash
LOG_LEVEL=INFO venv/Scripts/python.exe main.py "Build a todo app with a REST API and a SQLite database"
```

Three assertions, all named in `PHASE22_HANDOFF.md` §6:
- `🔥 Runtime smoke test` appears and reports **N/N routes**, 0× 5xx.
- A clean build reaches `done` and writes **no** `SESSION_CONTEXT.md`.
- A degraded build shows the amber panel and **stays downloadable**.

Record `total_tokens` from the DB for this build. It is the unit of currency for
pacing everything below against the 200K TPD ceiling.

### A2. Live matrix — 4 builds

The point is to defeat the single-data-point problem, so the pass criterion is
fixed **now**, before any build runs:

> ≥3 of 4 reach `done` or `done_with_context` with a downloadable ZIP, and every
> build that boots reports **0 5xx** from the smoke test.

| # | Prompt shape | Exercises |
|---|---|---|
| 1 | simple FastAPI + SQLite CRUD | the baseline path, smoke test |
| 2 | medium FastAPI + a JS frontend | `frontend_generator`, `frontend_debugger`, dangling-import guard |
| 3 | complex / multi-entity | `_normalise_backend_architecture` cap, the architect-variance risk `PHASE22_HANDOFF.md` §6 Step 3 flags |
| 4 | non-FastAPI (CLI or Streamlit) | the documented blind spot — smoke test must **skip cleanly**, not crash |

Run them **sequentially**, checking `/health` between each. Log per build:
status, review/debug/test scores, smoke N/N, tokens, duration, and whether the
architect over-engineered (the alembic-for-a-todo-app failure mode).

### A3. Deliberate quota-exhaustion run

Burning a real key costs a whole day of quota and is not repeatable. Add a
test-only switch to `llm_client.py` instead:

- `GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS` (default `0` = off). When set, `_call_groq`
  raises `_make_quota_error(model, "simulated")` after N successful calls.
- Placed next to the existing env knobs (`GROQ_RATE_LIMIT_MAX_RETRIES` etc.), it
  reuses `_make_quota_error()` so the simulated error is byte-identical in type and
  payload to a real one — which is the whole point.

Then verify the Phase 21 handoff path end to end on the *current* models:
`SESSION_CONTEXT.md` is written with real quota diagnostics from
`get_quota_snapshot()`, status is `done_with_context`, and
`GET /downloads/{id}` still serves the ZIP.

### A4. Full-stack E2E against a live backend

Playwright deliberately does not own the backend (`SESSION_PROGRESS.md` §4). Keep
that: add a **separate** project rather than changing the default run.

- `frontend/playwright.config.ts` — new project `live`, excluded from the default
  `npm run test:e2e`, run via `npm run test:e2e:live`.
- `frontend/e2e/live.spec.ts` — starts a real build through the UI and asserts:
  WebSocket step transitions land in `StepTracker` (not the 5s poll fallback);
  cancel mid-build yields `cancelled` and **not** "Build complete — your files are
  ready"; the ZIP downloads and is a valid archive; with the A3 switch on, the quota
  banner renders and download stays enabled.
- Reuse `e2e/helpers.ts` and the existing fixtures rather than inventing new ones.

### A5. Fix and re-run

Anything found gets a deterministic offline regression test in `test_phase22.py`
(or a new `test_phase23.py`) **first**, verified to fail before the fix — the
standard this project already holds itself to (`SESSION_PROGRESS.md` §2.8's guard
was checked to go red when the bug is reintroduced).

**Verification:** `PHASE23_LIVE_VALIDATION.md` contains the 4-row matrix with real
numbers, the three Step-1 assertions marked, and the quota-handoff artefacts. All
offline suites still green.

---

# Phase B — Stage 4 production hardening

Five sub-phases, sequenced so each lands on the one before it.

### B1. Persistence layer first — SQLAlchemy + Alembic (4.3)

Auth needs a schema change, so migrations must exist before auth, not after.

- New `api_platform/db/` — SQLAlchemy models mirroring `projects` / `files` /
  `build_progress` exactly as `database.py:34-75` defines them.
- **Keep `api_platform/database.py`'s function signatures as the seam.**
  `get_project`, `list_projects`, `update_project`, `add_build_step` etc. are called
  from `runner.py`, all five route modules and the tests; reimplementing their bodies
  over SQLAlchemy means **zero call-site changes**.
- `DATABASE_URL` env var, defaulting to
  `sqlite:///generated_projects/platform.db` — Postgres becomes opt-in, and
  today's local workflow is unchanged.
- Alembic init + an initial revision **stamped** against the existing DB (the 50
  live builds in `platform.db` must survive), then one revision per later change.
  This replaces the hand-rolled `ALTER TABLE ... except OperationalError` block at
  `database.py:81-98`.
- Fix `datetime.utcnow()` (deprecated 3.12+) → `datetime.now(timezone.utc)` while
  in here — it appears throughout `database.py` and `runner.py`.
- Connection pooling: `QueuePool` sized against `job_runner.max_workers` (3).

### B2. JWT auth + multi-tenant isolation (4.1)

- New `users` table (Alembic revision): `id`, `email`, `password_hash`, `role`,
  `created_at`. `passlib[bcrypt]` for hashing, `python-jose` for tokens — both
  already declared in `requirements.txt`.
- New `api_platform/routes/auth.py`: `POST /auth/register`, `POST /auth/login`,
  `GET /auth/me`. `get_current_user` dependency in `api_platform/deps.py`.
- `owner_id` column on `projects`; existing 50 rows migrate to a seeded admin user.
  Every read/write in `projects.py`, `jobs.py`, `downloads.py` and `websockets.py`
  filters on it — including `job_runner.cancel_build` and the WS subscribe path,
  which currently accept any `build_id`.
- `/admin/reset-keys` becomes admin-role only.
- Frontend: a login page, token in memory with refresh in `localStorage`, a fetch
  wrapper that redirects to login on 401.

> **A design consequence to decide, not discover.** Landing reads `/health`,
> `/stats` and `useBuilds()` unauthenticated (`SESSION_PROGRESS.md` §2.7).
> Recommendation: `/health` and `/stats` stay public because they expose aggregates
> only (and §2.7's redaction decision already keeps key suffixes out of `/health`);
> the **recent-builds feed becomes authenticated**, and Landing's "empty means
> absent" rule (§2.7 decision 3) already renders that state correctly with no new
> code.

### B3. Rate limiting (4.2)

- `slowapi` middleware. `POST /projects/` at **5/hour per user** (this is what
  actually protects the Groq quota), `POST /auth/login` at 10/min per IP, a
  100/min global default.
- 429 responses carry `Retry-After`; `NewBuild.tsx` surfaces it in the existing
  `.nb-error-slot` (`SESSION_PROGRESS.md` §4 — animate the bare wrapper, it has no
  padding).

### B4. Containerisation (4.4)

- Multi-stage `Dockerfile`: node stage runs `npm run build`, python-slim stage
  copies `frontend/dist` into place — the guarded SPA mount at `main.py:228` then
  serves the whole product from one port with no CORS and no proxy.
- `docker-compose.yml`: `api`, `postgres`, named volumes for
  `generated_projects/` and the Chroma path Phase C introduces.
- `.dockerignore` must exclude `venv/`, `node_modules/`, `generated_projects/`,
  `*.db`, `frontend-screenshots/`.
- **The generated-code sandbox needs thought**: `tools/runtime_smoke.py` and
  `code_executor.py` spawn subprocesses that execute LLM-written code. Inside a
  container that is strictly safer than today, but the image needs the Python and
  Node toolchains those subprocesses expect.

### B5. Monitoring (4.5)

- `prometheus-client` → `GET /metrics`: build counter by terminal status, build
  duration histogram, Groq tokens counter, queue-depth gauge (from
  `job_runner.get_queue_status()`), Groq keys-available gauge.
- Structured JSON logging with `build_id` on every line.
- **Sentry gated behind `SENTRY_DSN`** — unset means not installed, not
  initialised, nothing transmitted. Free tier if it is ever wanted.

### B6. Tests — `test_phase23.py`, offline

Register/login round-trip; an expired token is rejected; **user A gets 404 on user
B's build** (the isolation assertion that matters); 429 after the 6th build in an
hour; `/metrics` exposes the named series; and the Alembic migration applies
cleanly to a **copy of the real `platform.db`** with all 50 builds intact.

**Verification:** `docker compose up` serves the working app at `:8000` with
Postgres; a build runs end to end inside the container; `test_phase23.py` green;
`test_phase17.py` (54) still green against the migrated DB; frontend E2E green
with auth added to the fixtures.

---

# Phase C — Vector memory across builds (ChromaDB)

Stage 5.1, the feature `chromadb` was added for in Phase 19 and never wired up.
Confirmed free and fully local (see the Context table).

### C1. `tools/vector_memory.py` — new, the whole storage layer

```python
remember_build(build_id, intent, architecture, scores, owner_id) -> bool
recall_similar(intent, k=3, max_distance=...) -> list[Precedent]
forget_build(build_id) -> None
memory_stats() -> dict
```

- `chromadb.PersistentClient(path=generated_projects/vector_memory)`, one
  collection `builds`, default ONNX embedder (verified: 384-dim, local, keyless).
- **Document text** = app_type + complexity + the feature list from `intent` + a
  flattened file tree from `architecture`. **Metadata** = `build_id`, `app_type`,
  `complexity`, `review_score`, `test_score`, `status`, `owner_id`, `created_at`.
- **Import-guarded.** If chroma is unavailable or the store is corrupt,
  `recall_similar` returns `[]` and `remember_build` returns `False`. Vector memory
  must never be able to fail a build.

### C2. The rule that decides whether this helps or hurts

> Only builds with status `done`, `review_score >= 7`, and a clean smoke result are
> remembered.

Recording every build teaches the architect its own failure modes — including the
alembic-for-a-todo-app run in `PHASE22_HANDOFF.md` §6 Step 3. Phase A's matrix is
what supplies the first honest set of good precedents, which is another reason it
comes first.

### C3. Retrieval → the Architect prompt

- `Architect.run(intent, steps, build_id, precedents=None)` — `agents/architect.py:129`.
  When precedents are present, a compact block is appended to the prompt built at
  `architect.py:139-149`: for each, its file tree and the scores it earned.
- **Hard character budget (~1200 chars, config-driven).** Prompt tokens count
  against Groq TPM, and `_fit_output_budget_to_model_limit` (`llm_client.py:460`)
  will silently *shrink the completion budget* to compensate — which is exactly how
  truncated code gets generated. Precedents must not eat the code budget.
- `agents/pipeline.py` step 3 calls `recall_similar()` and passes the result
  through; it emits the precedent count in that step's progress `data`, so
  `ProjectDetail` can show "3 precedents used" with no new API.

### C4. Write hook and lifecycle

- `api_platform/runner.py::_run_build`, immediately after the success-branch
  `update_project(...)` (`runner.py:575-592`), wrapped in try/except — same defensive
  posture as the surrounding DB block.
- **Deletion must propagate**, or memory outlives the database and starts citing
  builds that no longer exist: `forget_build()` from
  `projects.py::delete_project_endpoint` (`projects.py:102`) and from
  `DELETE /projects/cleanup` in `analytics.py`.
- One-off backfill script over the existing DB, applying the C2 filter — worth
  roughly a handful of precedents from the current 50 builds.

### C5. Dependency cleanup

- **Delete `langchain>=0.2.0` from `requirements.txt`.** Installed
  (`langchain 1.2.16`), imported nowhere in the source — verified across the repo.
- **Keep `chromadb`**, now genuinely used, and update the `# Vector memory (Phase 19)`
  comment to say what it actually powers.
- Reinstall clean and re-run `pip-audit`. Note honestly in `setup.md`: this does
  **not** reach zero CVEs the way deleting both would (`SESSION_PROGRESS.md` §3.1
  item 2) — chroma's own tree stays. Record what remains and confirm none of it is
  on the request path.

### C6. Surfacing + tests

- `GET /memory/stats` → collection size, app-type breakdown, last write.
- `test_phase24.py`, offline, real chroma against a temp path: round-trip;
  the C2 filter rejects a `failed` build and a low-scoring `done` build; `k` is
  respected; `forget_build` actually removes; the prompt block respects its char
  cap; and with chroma import-failed the pipeline still completes.

**Verification:** backfill, then run two builds with near-identical prompts —
the second's step-3 progress data must show precedents retrieved, and its architect
output should converge on the first's structure. Delete a remembered build via the
API and confirm `memory_stats()` drops by one. `test_phase24.py` green;
21/22/23 suites still green.

---

## Risks worth stating up front

1. **Phase A can invalidate Phase C's premise.** If the live matrix shows build
   quality is dominated by architect variance rather than by missing precedent,
   vector memory is the wrong lever and `PHASE22_HANDOFF.md` §6 Step 3
   (constraining the architect for simple/medium apps) is the better spend. Re-read
   the matrix before starting Phase C.
2. **B2 auth is the largest change in this plan** — DB schema, every route, and the
   whole frontend. It is also the one that most changes the local dev workflow.
   It is worth doing as its own commit with its own test run.
3. **Groq free-tier quota is the binding constraint on Phase A**, not time. Pace
   the matrix against the measured per-build token cost from A1 and stop at the
   ceiling rather than half-completing a fifth build.
