# AI App Builder — Complete Project Context & Implementation Roadmap

**Document date:** May 2026  
**Status:** Active development — Phase 14 complete, Phase 15–20 planned  
**Stack:** Python 3.10+ backend · React 19 + TypeScript frontend · SQLite · Groq API + Ollama fallback

---

## PART 1 — WHAT HAS BEEN BUILT (COMPLETE)

### 1.1 System Overview

A fully autonomous full-stack application generator. A user types one sentence describing what they want to build. A 9-agent AI pipeline then designs, codes, debugs, reviews, tests, and documents the entire project — frontend and backend — and delivers it as a downloadable ZIP with a complete setup guide.

```
User prompt
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  9-AGENT PIPELINE                                    │
│                                                      │
│  1. IntentAnalyzer  → structured JSON requirements  │
│  2. Planner         → ordered build steps (5-7)     │
│  3. Architect       → folder/file structure JSON    │
│  4. BackendDeveloper → FastAPI Python files         │
│  5. FrontendGenerator → HTML/CSS/JS files           │
│  6. Debugger        → autonomous import-fix loop    │
│  7. Reviewer        → code quality scores 1-10     │
│  8. Tester          → pytest generation + execution │
│  9. Documenter      → README.md + SETUP.md         │
└──────────────────────────────────────────────────────┘
    │
    ▼
Generated project ZIP (downloadable)
```

### 1.2 Project Folder Structure

```
Aiautonomous/                          ← project root
│
├── agents/                            ← 9 AI agents
│   ├── __init__.py
│   ├── base_agent.py                  ← shared LLM call + JSON parse + retry
│   ├── intent_analyzer.py
│   ├── planner.py
│   ├── architect.py
│   ├── backend_developer.py
│   ├── frontend_generator.py
│   ├── debugger.py
│   ├── reviewer.py
│   ├── tester.py
│   ├── documenter.py
│   └── pipeline.py                    ← orchestrates all 9 steps
│
├── api_platform/                      ← FastAPI REST platform
│   ├── __init__.py
│   ├── main.py                        ← app startup, CORS, routers
│   ├── database.py                    ← SQLite: projects, files, build_progress
│   ├── models.py                      ← Pydantic schemas
│   ├── runner.py                      ← ThreadPoolExecutor job queue (3 workers)
│   └── routes/
│       ├── __init__.py
│       ├── projects.py                ← CRUD for projects
│       ├── jobs.py                    ← build status, cancel, queue
│       ├── downloads.py               ← ZIP streaming + SETUP.md injection
│       ├── analytics.py               ← /stats, /stats/daily, rebuild, cleanup
│       └── websockets.py              ← WS /ws/jobs/{id} real-time progress
│
├── tools/                             ← agent tools
│   ├── __init__.py
│   ├── file_writer.py                 ← create/read/list files in OUTPUT_DIR
│   ├── code_executor.py               ← run_python() import-check, run_command()
│   └── dependency_installer.py        ← pip_install(), extract_missing_package()
│
├── prompts/                           ← LLM system prompts (.txt files)
│   ├── architect.txt
│   ├── backend_developer.txt
│   ├── debugger.txt
│   ├── documenter.txt
│   ├── frontend_generator.txt
│   ├── intent_analyzer.txt
│   ├── planner.txt
│   ├── reviewer.txt
│   └── tester.txt
│
├── frontend/                          ← React 19 + TypeScript dashboard
│   └── src/
│       ├── api/client.ts              ← all API calls, typed interfaces
│       ├── hooks/
│       │   ├── useHealth.ts           ← { health, refetch }
│       │   ├── useQueries.ts          ← useBuilds, useStats, useDailyStats
│       │   └── useBuildProgress.ts    ← WebSocket progress hook
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Sidebar.tsx
│       │   │   └── FloatingStatus.tsx ← LLM health + reset keys button
│       │   └── shared/
│       │       ├── BuildCard.tsx
│       │       ├── StatusBadge.tsx
│       │       └── StepTracker.tsx    ← live 9-step progress tracker
│       └── pages/
│           ├── Landing.tsx            ← 3D Spline + shader hero
│           ├── Dashboard.tsx          ← project list + metrics
│           ├── NewBuild.tsx           ← prompt input form
│           ├── BuildProgress.tsx      ← WebSocket live view
│           ├── ProjectDetail.tsx      ← scores + files + download
│           └── Statistics.tsx         ← recharts area/bar/pie
│
├── generated_projects/                ← OUTPUT_DIR (all generated apps live here)
├── llm_client.py                      ← Groq multi-key rotation + Ollama fallback
├── config.py                          ← env var loading + connection tests
├── main.py                            ← rich CLI entry point
└── requirements.txt
```

### 1.3 LLM Architecture

```
generate_text(prompt)
    │
    ├─→ _call_groq()          [PRIMARY]
    │       │
    │       ├── tries keys 0→1→2→...→N (round-robin, stable index)
    │       ├── 429 + Retry-After ≤10s  → wait + retry same key
    │       ├── 429 + no/long header    → mark exhausted, next key
    │       ├── 401 Unauthorized        → mark permanently invalid, next key
    │       └── all keys exhausted/invalid → raise RuntimeError
    │
    └─→ _call_ollama()        [FALLBACK]
            │
            ├── timeout: connect=10s, read=300s
            ├── max_tokens: 1500
            ├── retry once on ReadTimeout (model loading)
            └── ConnectError → clear message to user
```

**Key pool:** Up to 20 keys via `GROQ_API_KEY`, `GROQ_API_KEY_2` ... `GROQ_API_KEY_20`

### 1.4 Database Schema (SQLite — `platform.db`)

```sql
projects        (build_id PK, prompt, app_name, app_type, complexity,
                 status, debug_score, review_score, test_score,
                 output_path, created_at, completed_at, duration_seconds)

files           (id, build_id FK, file_path, file_type)

build_progress  (id, build_id FK, step, step_name, status, timestamp, data)
```

### 1.5 API Surface (18 endpoints)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/projects/` | Start new build (returns immediately, 202) |
| GET | `/projects/` | List all projects (pagination + status filter) |
| GET | `/projects/{id}` | Project detail + file list |
| DELETE | `/projects/{id}` | Delete project + files |
| GET | `/projects/{id}/download` | Stream ZIP |
| POST | `/projects/{id}/rebuild` | Clone build with same prompt |
| GET | `/jobs/{id}/status` | Build progress poll |
| DELETE | `/jobs/{id}` | Cancel job |
| GET | `/jobs/queue` | Worker pool stats |
| GET | `/jobs/active` | Running + queued jobs |
| WS | `/ws/jobs/{id}` | Real-time push progress |
| GET | `/stats` | Platform-wide analytics |
| GET | `/stats/daily` | Per-day build counts (7/14/30d) |
| POST | `/projects/{id}/rebuild` | Re-run same prompt |
| DELETE | `/projects/cleanup` | Batch delete old builds |
| POST | `/admin/reset-keys` | Reset exhausted Groq keys |
| GET | `/health` | Full system health |
| GET | `/` | Root info |

### 1.6 Frontend Pages

| Page | Route | Purpose |
|------|-------|---------|
| Landing | `/` | Marketing page (3D Spline + shader + pipeline explainer) |
| Dashboard | `/dashboard` | Build history, metrics, status filters |
| New Build | `/build` | Prompt input with example cards |
| Build Progress | `/build/:id` | Live WebSocket step tracker |
| Project Detail | `/projects/:id` | Scores, file tree, download ZIP |
| Statistics | `/stats` | Area/bar/pie charts (recharts) |

---

## PART 2 — BUGS FIXED ACROSS SESSIONS

### 2.1 Critical Bug Fixes (Delivered)

| Bug | Root Cause | Fix File |
|-----|-----------|----------|
| 6/7 Groq keys used, last key skipped | `_get_next_groq_key()` advanced index before selecting; shrinking modulo skipped last key | `llm_client.py` |
| 401 key looped forever, never marked invalid | Only 429 triggered exhaustion; 401 kept cycling | `llm_client.py` |
| Per-minute 429 marked key as daily-exhausted | No `Retry-After` header check | `llm_client.py` |
| Ollama timed out despite being live | `timeout=180` total; 7B model needs 300s read | `llm_client.py` |
| Ollama crash brought down whole build | `ReadTimeout` not caught, propagated to pipeline | `llm_client.py` |
| `setup.py` always fails debug loop | `distutils` setup.py requires CLI args; import-exec always exits 1 | `debugger.py` (blocklist needed) |
| Test score showed `None` when tests skipped | `_safe_test_score` returned `None` for 0/0 | `runner.py` |
| Rebuild navigated to `/build/undefined` | `res.build_id` used but API returns `new_build_id` | `client.ts` |
| Score bar always 0% for debug/test | `parseScorePct` didn't handle `"3/5"` fraction format | `ProjectDetail.tsx` |
| Step names showed hardcoded fallback always | `StepTracker` never read server `step_name` field | `StepTracker.tsx` |
| 7th key still not used after first fix | 401 key was "available" (not exhausted), consumed the last slot | `llm_client.py` v3.2 |

### 2.2 Structural Improvements (Delivered)

| Improvement | File |
|-------------|------|
| Tester discovers any `.py` with `def`/`class`, not just 2 hardcoded filenames | `tester.py` |
| Each test file runs in isolation (no stale-test poisoning) | `tester.py` |
| Smart 2-level conftest path scanner for nested projects | `tester.py` |
| Pre-installs `requirements.txt` before pytest | `tester.py` |
| Extracts actual function names → accurate mock paths | `tester.py` |
| FastAPI vs plain-Python test pattern detection | `tester.py` |
| Tester prompt has both Pattern A and Pattern B | `tester.txt` |
| Architect prompt mandates backend even for frontend-only prompts | `architect.txt` |
| `SETUP.md` generated per project with real env vars, packages, endpoints | `documenter.py` |
| ZIP always includes real `SETUP.md`, falls back to rich template | `downloads.py` |
| FloatingStatus shows Reset Keys button when keys exhausted | `FloatingStatus.tsx` |
| `useHealth` exposes `refetch` for post-reset update | `useHealth.ts` |
| `VITE_API_URL` env var support in frontend | `client.ts` |

---

## PART 3 — KNOWN REMAINING ISSUES

### 3.1 `setup.py` False-Negative in Debugger
The debugger import-checks `setup.py` files using `spec.loader.exec_module()`. `setup.py` (distutils/setuptools) requires CLI arguments and always exits 1 when import-executed. The debugger wastes 6 LLM calls trying to fix an unfixable false failure.

**Fix needed:** Add `"setup.py"` to `IGNORE_ERRORS` or a filename blocklist in `debugger.py`.

### 3.2 Cascading Import Error in Tester (test_main.py)
When `main.py` imports from a sibling module (e.g. `from streamlit_ui import run_streamlit_ui`) and that function doesn't exist, `test_main.py` fails collection — but the tester's LLM fix loop only rewrites the test file, not `main.py`. The fix is for the tester to also attempt patching the broken import in `main.py` at collection-error time, or mock the entire sibling import.

### 3.3 Ollama max_tokens=600 Still Causes Truncation
Even at 1500 tokens, complex reviewer/tester prompts on Ollama return truncated JSON. This causes `think_json()` parse failures that consume LLM fix attempts unnecessarily.

### 3.4 One Invalid Groq Key Wastes One Slot Per Call
A 401 key is now marked invalid but the detection happens inside the call loop. If the invalid key is encountered first, one HTTP round trip is wasted. A startup validation check would eliminate this.

---

## PART 4 — NEXT IMPLEMENTATION STEPS

### Phase 15 — Robustness (Priority: HIGH — do next)

#### 15.1 Debugger `setup.py` Blocklist
```python
# In debugger.py, expand TESTABLE_FILES blocklist:
SKIP_DEBUG_FILES = {
    "setup.py",       # distutils always fails import-exec
    "conftest.py",    # pytest internal
    "manage.py",      # Django CLI
    "wsgi.py",        # WSGI server entry
    "asgi.py",        # ASGI server entry
}
```
Add check at top of `_debug_file()`: if `Path(file_path).name in SKIP_DEBUG_FILES` → mark success immediately.

#### 15.2 Groq Key Startup Validation
On server startup, fire one cheap test call per key (`max_tokens=1`). Keys returning 401 are immediately moved to `_permanently_invalid` set and never tried again. Log which keys are valid at boot.

```python
# In llm_client.py
_permanently_invalid: set[int] = set()

def _validate_keys_on_startup():
    for i, key in enumerate(_groq_keys):
        try:
            # 1-token probe
            ...
            if resp.status_code == 401:
                _permanently_invalid.add(i)
                logger.warning(f"🔑 Key ...{key[-8:]} is INVALID (401) — removed from pool")
        except Exception:
            pass
```

#### 15.3 Tester Collection-Error Recovery — Sibling Import Patching
When pytest exits code 2 and the error mentions `cannot import name 'X' from 'Y'`, the tester should:
1. Read the actual source of `Y` (sibling module)
2. Add a mock for `X` at the top of the test file using `unittest.mock.MagicMock`
3. Bypass the broken import entirely rather than trying to fix the generated app code

#### 15.4 Architect Blocklist for Non-Debuggable Files
Pass a hint to the architect prompt: `setup.py`, `manage.py`, `wsgi.py` should never be created as standalone backend files that go through the debug pipeline.

---

### Phase 16 — Quality Improvements (Priority: MEDIUM)

#### 16.1 Smarter Reviewer Prompt
Current reviewer gives every file 7/10 with identical feedback. Fix: add file-specific context (the actual function names, line count, imports) and require the reviewer to cite specific line numbers in issues.

#### 16.2 Multi-file Test Context
When testing `chart_generation.py`, pass the content of its direct imports (`data_analysis.py`) as context so the LLM writes tests that match the actual function signatures rather than guessing.

#### 16.3 Dependency Pre-check Before Debug
Before running the debug loop, scan `requirements.txt` and install all packages. Currently done in the Tester but NOT in the Debugger — which causes false import failures during debugging for packages like `reportlab`, `matplotlib`, `streamlit`.

```python
# Add to debugger.py run():
self._pre_install_project_deps(py_files)
```

#### 16.4 Frontend Test Scaffolding (Vitest)
When the architecture includes `.tsx`/`.jsx` files, generate a basic `vitest.config.ts` and one smoke test per React component. Currently the tester skips all frontend files.

---

### Phase 17 — Platform Features (Priority: MEDIUM)

#### 17.1 Build Templates / Presets
Add a `GET /templates` endpoint returning curated prompt templates with known-good complexity settings. Frontend shows a template picker on the New Build page.

```
Templates:
  - REST API + CRUD (FastAPI + SQLite)
  - Data Dashboard (FastAPI + Recharts)
  - AI Chatbot (FastAPI + WebSocket)
  - CSV/Excel Processor (pandas + reportlab)
  - Web Scraper (httpx + BeautifulSoup)
```

#### 17.2 Build Comparison View
`GET /projects/compare?ids=a,b,c` — returns scores side-by-side. Frontend renders a comparison table so the user can see which prompt wording produced the best results.

#### 17.3 Incremental Rebuild (Patch Mode)
Instead of regenerating all 9 steps, accept a `patch_prompt` like "add authentication to the existing project". The pipeline skips steps 1-3 (already done), only re-runs steps 4-9 with the diff context.

#### 17.4 Project Versioning
Store multiple build versions per project (`versions` table). The frontend shows a version history timeline. Users can roll back to any previous version's ZIP.

#### 17.5 Real-time Log Streaming
Currently WebSocket only sends step-level events. Extend it to stream individual log lines from each agent so the user can see "Thinking..." → "Generated routes.py (1200 chars)" in real time.

---

### Phase 18 — Production Deployment (Priority: HIGH when ready to ship)

#### 18.1 Database Migration: SQLite → PostgreSQL
SQLite has write serialization — only one build can write to DB at a time. With 3 concurrent workers this causes occasional lock timeouts. Switch to PostgreSQL with asyncpg.

```python
# config.py addition
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///platform.db")
# Use SQLAlchemy async engine when DATABASE_URL starts with postgresql://
```

#### 18.2 Celery + Redis Job Queue
The current `ThreadPoolExecutor` with 3 workers is single-process. Replace with Celery + Redis to support:
- Multiple server processes (horizontal scaling)
- Job persistence across server restarts
- Priority queues (premium users jump the queue)
- Dead letter queue for failed builds

```python
# requirements.txt additions
celery[redis]>=5.4.0
redis>=5.0.0
flower>=2.0.0  # Celery monitoring UI
```

#### 18.3 Authentication + User Accounts
Add JWT-based auth so builds are scoped to users:
```
POST /auth/register
POST /auth/login  
POST /auth/refresh
GET  /users/me
GET  /users/me/projects
```

Packages: `python-jose`, `passlib[bcrypt]`, `python-multipart`

#### 18.4 Rate Limiting
Per-user build limits to prevent abuse:
- Free tier: 3 builds/day
- Pro tier: unlimited
Use `slowapi` (FastAPI rate limiter backed by Redis).

#### 18.5 File Storage: Local → S3-Compatible
Generated projects currently live on the server's local filesystem. For multi-server deployment, move to S3/R2/MinIO:
```python
# config.py
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")  # or "s3"
S3_BUCKET       = os.getenv("S3_BUCKET", "")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")  # for R2/MinIO
```

#### 18.6 Docker + Docker Compose
```yaml
# docker-compose.yml
services:
  api:
    build: .
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://...
      - GROQ_API_KEY=${GROQ_API_KEY}
    depends_on: [db, redis]

  worker:
    build: .
    command: celery -A tasks worker --concurrency=4
    depends_on: [db, redis]

  db:
    image: postgres:16-alpine

  redis:
    image: redis:7-alpine

  frontend:
    build: ./frontend
    ports: ["80:80"]
```

#### 18.7 Environment Configuration for Production
```env
# .env.production
LLM_PROVIDER=groq
GROQ_API_KEY=...
GROQ_API_KEY_2=...
GROQ_MODEL=llama-3.3-70b-versatile

DATABASE_URL=postgresql://user:pass@db:5432/aibuilder
REDIS_URL=redis://redis:6379/0

STORAGE_BACKEND=s3
S3_BUCKET=ai-builder-projects
S3_ENDPOINT_URL=https://your-r2-endpoint.com

OUTPUT_DIR=/mnt/projects
LOG_LEVEL=WARNING

# Frontend
VITE_API_URL=https://api.yourdomain.com
```

---

### Phase 19 — Advanced AI Features (Priority: LOW / Future)

#### 19.1 Agent Memory with ChromaDB
Store successful build patterns in a vector database. When a new prompt is similar to a past successful build, the architect/backend agents retrieve that build's structure as context — dramatically improving first-try success rates.

```python
# agents/memory.py
import chromadb

class BuildMemory:
    def store_success(self, build_result: BuildResult): ...
    def retrieve_similar(self, intent: dict, n=3) -> list[dict]: ...
```

#### 19.2 Self-Improving Prompts
After each build, score which prompts led to the most passing tests and highest review scores. Use those as few-shot examples in subsequent calls — the agents improve over time without retraining.

#### 19.3 Multi-Model Support
Currently locked to Groq (Llama) + Ollama. Add:
- Anthropic Claude API (excellent for code)
- OpenAI GPT-4o
- Google Gemini
- Local models via LM Studio

```python
# config.py
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
# Supported: groq | ollama | anthropic | openai | gemini | lmstudio
```

#### 19.4 Code Execution Sandbox (E2E Testing)
Instead of import-check only, actually start the generated FastAPI server in a Docker container, hit all endpoints with real requests, and report actual HTTP response codes. This would make the debug score meaningful.

#### 19.5 Streaming Code Generation
Instead of waiting for the full file to be generated, stream tokens from the LLM directly to the WebSocket so the user sees code appearing in real time on the Build Progress page.

---

### Phase 20 — Monetisation & SaaS (Priority: Future)

#### 20.1 Stripe Integration
```
POST /billing/create-checkout-session
POST /billing/webhook
GET  /billing/portal
```
Subscription tiers:
- **Free:** 3 builds/day, no ZIP download, community support
- **Pro ($19/mo):** Unlimited builds, ZIP download, priority queue, email support
- **Team ($49/mo):** 5 seats, shared project library, API access

#### 20.2 Public Project Gallery
Allow users to make builds public. A gallery page shows the best-rated generated apps with their prompts — acts as social proof and SEO content.

#### 20.3 API Access (Developer Tier)
Expose the pipeline as a pure REST API so developers can integrate it into their own tools:
```bash
curl -X POST https://api.aibuilder.dev/v1/build \
  -H "Authorization: Bearer sk_..." \
  -d '{"prompt": "Build a todo API"}'
```

---

## PART 5 — IMMEDIATE NEXT ACTION CHECKLIST

These are the specific code changes to make right now, in priority order:

### ✅ Done (this session and previous)
- [x] LLM key rotation off-by-one fix
- [x] 401 key permanent-invalid marking
- [x] Per-minute vs daily 429 distinction
- [x] Ollama 300s timeout + retry
- [x] Tester file discovery expansion
- [x] Per-file isolated pytest runs
- [x] Smart 2-level conftest
- [x] Pre-install deps before testing
- [x] Function name extraction for mocks
- [x] FastAPI vs plain Python pattern detection
- [x] Architect mandatory backend rule
- [x] SETUP.md generation in documenter
- [x] ZIP SETUP.md injection in downloads
- [x] FloatingStatus reset-keys button
- [x] ProjectDetail smart score parser
- [x] StepTracker live name preference
- [x] runner.py "0/0 (collection errors)" score

### 🔲 Next — Phase 15 (do this week)

1. **`debugger.py`** — Add `SKIP_DEBUG_FILES` set. `setup.py`, `manage.py`, `wsgi.py`, `asgi.py` should be auto-passed without import-check.

2. **`debugger.py`** — Add `_pre_install_project_deps()` — same as tester does, install `requirements.txt` before the debug loop starts. This eliminates false `ModuleNotFoundError` during debug.

3. **`llm_client.py`** — Add `_validate_keys_on_startup()` called once at import time. Probes each key with `max_tokens=1`. Marks 401 keys permanently invalid before any build starts.

4. **`tester.py`** — Improve collection-error recovery: when error is `cannot import name 'X' from 'Y'`, generate a mock for X instead of trying to fix the import. Add `# noqa` stubs.

5. **`backend_developer.txt`** — Add rule: never create `setup.py`. Use `pyproject.toml` or just `requirements.txt`.

6. **`architect.txt`** — Add to blocklist: no `setup.py`, `manage.py` in the generated file list.

### 🔲 Then — Phase 16 (next week)

7. **`reviewer.py`** — Pass actual function names and line count in prompt. Require line-number citations in issues list.

8. **`debugger.py`** — Two-pass: first pass fixes import errors, second pass specifically handles `setup.py`-style distutils files by converting to a plain Python module.

9. **`tester.py`** — Pass sibling module content as context when generating tests for files that import from siblings.

### 🔲 Then — Phase 17 (two weeks)

10. **`api_platform/routes/templates.py`** — `GET /templates` with 5 curated build templates.

11. **`frontend/src/pages/NewBuild.tsx`** — Template picker grid above the prompt textarea.

12. **`api_platform/database.py`** — Add `versions` table for build history per project.

---

## PART 6 — TECHNOLOGY DECISIONS LOG

| Decision | Chosen | Reason | Alternatives considered |
|----------|--------|--------|------------------------|
| Primary LLM | Groq (Llama 3.3 70B) | Free tier, fast inference, 7 keys available | OpenAI (cost), Anthropic (cost), local-only (slow) |
| Fallback LLM | Ollama (Qwen 2.5 7B q4) | Free, local, no rate limits | None (Groq-only) |
| Backend framework | FastAPI | Async, auto-docs, Pydantic | Django REST, Flask |
| Job queue | ThreadPoolExecutor | Simple, no infra dependency | Celery (overkill for now) |
| Database | SQLite | Zero infra, sufficient for single-server | PostgreSQL (Phase 18) |
| Frontend | React 19 + TypeScript | Type safety, ecosystem | Next.js (SSR not needed), Vue |
| Styling | Tailwind CSS 4 + CSS modules | Utility-first, design system via tokens | Styled Components, MUI |
| Charts | Recharts | React-native, good defaults | Chart.js, D3 |
| 3D/Animations | Spline + Three.js + Framer Motion | Visual differentiation | None |
| Real-time | WebSocket (native FastAPI) | Simple, no extra deps | SSE, polling |
| Test runner | pytest | Standard, rich output | unittest |
| Code generation | Import-check via `importlib` | Safe, no subprocess server start | Full execution (too dangerous) |

---

## PART 7 — DEPLOYMENT READINESS CHECKLIST

### Current State
- ✅ Runs locally (Windows tested, Linux compatible)
- ✅ Multi-key Groq rotation with Ollama fallback
- ✅ 3 concurrent builds
- ✅ WebSocket real-time progress
- ✅ ZIP download with SETUP.md
- ✅ Build history with analytics
- ✅ React dashboard with all pages functional
- ⚠️  SQLite (single writer — ok for <10 concurrent users)
- ⚠️  Local file storage (not cloud-ready)
- ❌ No auth/user accounts
- ❌ No rate limiting
- ❌ No Docker
- ❌ No CI/CD
- ❌ Not HTTPS

### Minimum for Public Beta
1. Add auth (Phase 18.3) — 2 days
2. Docker Compose (Phase 18.6) — 1 day
3. Rate limiting (Phase 18.4) — 4 hours
4. PostgreSQL swap (Phase 18.1) — 1 day
5. Domain + SSL (Cloudflare) — 2 hours

**Estimated time to public beta:** ~1 week of focused work

---

*Last updated: May 2026 | AI App Builder v2.2.0 | Phase 14 complete*
