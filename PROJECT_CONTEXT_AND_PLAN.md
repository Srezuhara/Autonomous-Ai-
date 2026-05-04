# AI App Builder — Full Project Context & Implementation Plan
## Conversation Summary as of May 2, 2026

---

## 1. PROJECT OVERVIEW

A full-stack **autonomous AI app builder** that takes a natural language prompt and runs a
9-agent pipeline to generate, debug, review, test, and document a complete application.

### Stack
| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI + SQLite (api_platform/) |
| AI Agents | Python classes in agents/ |
| LLM Provider | Groq (multi-key rotation) + Ollama fallback |
| Frontend | React 19 + TypeScript + Tailwind CSS + Vite |
| Real-time | WebSocket (/ws/jobs/{build_id}) + REST polling fallback |
| Output | Generated projects written to generated_projects/ |

### Root Directory
```
C:\programes\comppython\Aiautonomous\
├── agents/                  # 9 AI agents
│   ├── pipeline.py          # Orchestrates all 9 steps
│   ├── intent_analyzer.py
│   ├── planner.py
│   ├── architect.py
│   ├── backend_developer.py
│   ├── frontend_generator.py
│   ├── debugger.py
│   ├── reviewer.py
│   ├── tester.py            # ← ACTIVELY BEING FIXED
│   ├── documenter.py
│   └── base_agent.py
├── api_platform/            # FastAPI platform backend
│   ├── main.py
│   ├── runner.py            # JobRunner (ThreadPoolExecutor)
│   ├── database.py          # SQLite CRUD
│   ├── models.py
│   └── routes/
│       ├── projects.py
│       ├── jobs.py
│       ├── analytics.py     # ← FIXED (stats endpoints)
│       ├── downloads.py
│       └── websockets.py
├── prompts/                 # LLM system prompts (txt files)
│   ├── tester.txt           # ← ACTIVELY BEING FIXED
│   ├── architect.txt
│   ├── backend_developer.txt
│   └── ...
├── tools/
│   ├── file_writer.py
│   ├── code_executor.py
│   └── dependency_installer.py
├── frontend/src/
│   ├── api/client.ts        # ← FIXED
│   ├── pages/
│   │   ├── Dashboard.tsx    # ← FIXED
│   │   ├── Statistics.tsx   # ← FIXED
│   │   ├── BuildProgress.tsx # ← FIXED
│   │   ├── ProjectDetail.tsx # ← FIXED
│   │   └── NewBuild.tsx
│   └── hooks/
│       └── useBuildProgress.ts  # ← FIXED
├── llm_client.py            # ← FIXED (key rotation)
├── start_server.py          # ← NEW (safe uvicorn launcher)
└── generated_projects/      # Output directory
```

---

## 2. THE 9-STEP PIPELINE

```
Step 1: IntentAnalyzer   → extracts app_name, app_type, features, tech_stack
Step 2: Planner          → creates ordered build steps
Step 3: Architect        → designs folder/file structure, scaffolds empty files
Step 4: BackendDeveloper → generates Python/FastAPI code
Step 5: FrontendGenerator→ generates HTML/CSS/JS (or React) code
Step 6: Debugger         → runs import checks, auto-fixes errors, installs packages
Step 7: Reviewer         → scores code quality 1-10 per file
Step 8: Tester           → generates & runs pytest tests
Step 9: Documenter       → writes README.md
```

---

## 3. ALL BUGS FOUND & FIXED IN THIS CONVERSATION

### 3.1 LLM Key Rotation — `llm_client.py`
**Bug:** 401 (invalid) keys were retried every call eating the rotation budget.
`tried` set was key-string-based causing premature exhaustion. Any transient
error triggered Ollama fallback even with `LLM_PROVIDER=groq`.

**Fix:** 401 keys permanently removed (`_invalid` set). `tried` is now
index-based. Per-key retry with `Retry-After` header support. `LLM_PROVIDER=groq`
never falls through to Ollama — fails fast with clear message instead.

**File:** `llm_client.py` (root)

---

### 3.2 Statistics NaN Duration — `analytics.py` + `Statistics.tsx` + `Dashboard.tsx`
**Bug:** `/stats` returned `duration_seconds: {average, min, max}` (nested).
Frontend read `stats.avg_duration_seconds` (top-level, didn't exist) → `NaN`.

**Fix:** `/stats` now returns BOTH `avg_duration_seconds` (top-level convenience
field) AND `duration_seconds: {average, min, max}` (detail). Frontend reads
top-level field with fallback.

**Files:** `api_platform/routes/analytics.py`, `frontend/src/pages/Statistics.tsx`,
`frontend/src/pages/Dashboard.tsx`

---

### 3.3 Statistics Graph Empty — `analytics.py` + `Statistics.tsx`
**Bug:** `/stats/daily` emitted key `done` for successful builds. Recharts
charts used `dataKey="success"`. Mismatch → flat zero line even after builds.

**Fix:** `/stats/daily` now emits `success` (renamed from `done`) to match
Recharts `dataKey`. Frontend `DailyStatsResponse` type updated to `{days, data[]}`.

**Files:** `api_platform/routes/analytics.py`, `frontend/src/pages/Statistics.tsx`

---

### 3.4 Mid-Build Server Restart — `start_server.py`
**Bug:** Running `uvicorn --reload` watched ALL directories including
`generated_projects/`. Agents write files continuously during builds →
WatchFiles detected changes → uvicorn restarted → active build killed.

**Fix:** New `start_server.py` launches uvicorn programmatically, restricting
`reload_dirs` to `["api_platform", "agents", "tools", "prompts"]` and
explicitly excluding `generated_projects/`.

**File:** `start_server.py` (new file at root)

---

### 3.5 Rebuild Navigates to /build/undefined — `client.ts` + `ProjectDetail.tsx`
**Bug:** The rebuild API returns `{ new_build_id, original_build_id, ... }`.
`client.ts` typed `rebuildProject` as returning `BuildResponse { build_id }`.
`ProjectDetail.tsx` read `res.build_id` → `undefined` → navigated to
`/build/undefined` → WebSocket connected to `/ws/jobs/undefined` → server
closed immediately → page showed "Build Failed" stuck at 0 of 9 steps.

**Fix:** Added `RebuildResponse` interface with `new_build_id`. `rebuildProject`
now returns `RebuildResponse`. `ProjectDetail.tsx` reads `res.new_build_id`.
Added loading spinner on Rebuild button.

**Files:** `frontend/src/api/client.ts`, `frontend/src/pages/ProjectDetail.tsx`

---

### 3.6 Stale Test Poisoning All Files — `tester.py`
**Bug:** `_run_pytest` ran `pytest tests/` (whole directory). When `test_main.py`
had a collection error (broken import), every subsequent file's pytest run also
failed because pytest collected the broken `test_main.py` first and aborted.
All 6 files showed "collection error" even though 5 of them were fine.

**Fix:** `_run_pytest_single` now runs `pytest tests/test_X.py` — each file
is tested in complete isolation. A broken test for one file cannot affect any other.

**File:** `agents/tester.py`

---

### 3.7 Tests Skipped for Non-FastAPI Projects — `tester.py` + `tester.txt`
**Bug:** `TESTABLE_FILES = {"main.py", "routes.py"}` — only 2 file names.
Any project that didn't have exactly those filenames (CLI tools, data scripts,
task managers with services.py/models.py) got 0 tests → `test_score = None`.
Also `tester.txt` forced FastAPI `TestClient` pattern for every file including
plain Python modules → broken test code.

**Fix:** `TESTABLE_FILES` expanded to 20+ names. Added auto-discovery of any
`.py` file containing `def`/`class`. Detects FastAPI vs plain Python by checking
for `FastAPI`/`APIRouter` in source code and generates appropriate test pattern.
`tester.txt` updated with both Pattern A (FastAPI) and Pattern B (plain Python).

**Files:** `agents/tester.py`, `prompts/tester.txt`

---

### 3.8 Wrong ProjectDetail Files Type — `client.ts` + `ProjectDetail.tsx`
**Bug:** `ProjectDetail.files` typed as `Array<{file_path, file_type}>` but
API returns `string[]`. Any component doing `f.file_path` got `undefined`.

**Fix:** `ProjectDetail.files` is now `string[]`. `ProjectDetail.tsx` renders
`f` directly. Added graceful fallback for old-shape objects.

**Files:** `frontend/src/api/client.ts`, `frontend/src/pages/ProjectDetail.tsx`

---

### 3.9 Build Failed Shown for WS Connection Issues — `useBuildProgress.ts` + `BuildProgress.tsx`
**Bug:** `hasFailed = wsStatus === 'error'`. Any WebSocket drop (including the
`/ws/jobs/undefined` from bug 3.5) showed "Build Failed" permanently.

**Fix:** `hasFailed = isFinished && actualStatus === 'failed'`. WebSocket error
is now an implementation detail — REST polling fallback takes over silently.
"WS Error" pill renamed to "Polling…". `buildDone` flag set by both WS
`complete` message and REST polling fallback.

**Files:** `frontend/src/hooks/useBuildProgress.ts`,
`frontend/src/pages/BuildProgress.tsx`

---

### 3.10 Wrong DailyStats API Return Type — `client.ts`
**Bug:** `getDailyStats` typed as returning `DailyStats[]` (bare array).
API actually returns `{ days: number, data: DailyStats[] }` (wrapped object).
Frontend tried to iterate the wrapper object → undefined for all values.

**Fix:** Added `DailyStatsResponse` interface. `getDailyStats` returns
`DailyStatsResponse`. `Statistics.tsx` unwraps `.data` array correctly.

**File:** `frontend/src/api/client.ts`

---

## 4. CURRENT STATE (as of May 2, 2026)

### Working ✅
- New Build flow (prompt → pipeline → live progress → result)
- WebSocket real-time progress with REST polling fallback
- Rebuild button navigates correctly to new build's progress page
- Groq key rotation (401 permanent removal, 429 wait/rotate)
- Statistics graph shows builds correctly (success/failed lines)
- Avg Duration metric no longer shows NaN
- Debug scores (6/6) and Review scores (7.0) showing correctly
- ZIP download working
- Server no longer restarts mid-build

### Still Broken / Incomplete ❌
- **Test scores still showing `—`** for web apps (task_manager etc.)
  - Root cause: architect generates `backend/main.py` + `backend/routes.py`
    but tester finds 0 files matching `TESTABLE_FILES` if build is fast (45s)
    which suggests architect may be skipping backend for "web_app" prompts
  - Secondary root cause: even when files exist, pytest import paths for
    projects with non-standard folder layouts still fail collection

- **Frontend-only projects get no test scores**
  - JavaScript/TypeScript/HTML files are completely untested
  - No JavaScript test runner (Jest/Vitest) is invoked at any point

- **conftest.py path resolution breaks for nested project structures**
  - e.g. `ai_report_generator/ai_report_generator/` double-nesting causes
    `import ai_report_generator.ai_report_generator.module` instead of
    `import module`

---

## 5. NEXT IMPLEMENTATION PLAN

### Priority 1 — Fix Test Scores for ALL Project Types (HIGH)

#### 5.1 JavaScript/TypeScript Test Runner Integration

**Problem:** Frontend projects (React apps, plain HTML/JS) have zero test
coverage. The tester only runs pytest which only works on Python files.
A "web_app" prompt generates `frontend/src/App.js` + backend Python files.
The JS files are never tested.

**Plan:**

**Step A — Detect project type in Tester.run():**
```python
has_js_files = any(
    fp.endswith(('.js', '.jsx', '.ts', '.tsx'))
    for fp in file_paths
)
has_py_files = len(py_files) > 0
```

**Step B — Install Jest/Vitest if JS files exist:**
```python
def _setup_js_testing(self, root: str, architecture: dict) -> bool:
    """Install Vitest and write vitest.config.js if project has JS files."""
    project_dir = Path(config.OUTPUT_DIR) / root
    frontend_dir = project_dir / "frontend"
    if not frontend_dir.exists():
        # Try flat structure
        frontend_dir = project_dir
    # Check for package.json
    pkg_json = frontend_dir / "package.json"
    if not pkg_json.exists():
        return False
    # Install vitest
    result = run_command("npm install --save-dev vitest @vitest/ui jsdom", 
                         cwd=str(frontend_dir), timeout=120)
    return result.success
```

**Step C — Generate JS test file via LLM:**
```python
def _generate_js_tests(self, file_path: str, code: str) -> str:
    stem = Path(file_path).stem
    prompt = f"""Write Vitest unit tests for this JavaScript/TypeScript file.

FILE: {file_path}
CODE: {code[:2000]}

Pattern:
  import {{ describe, it, expect, vi }} from 'vitest'
  import {{ someFunction }} from './{stem}'

  describe('{stem}', () => {{
    it('works with valid input', () => {{
      const result = someFunction('test')
      expect(result).toBeDefined()
    }})
    it('handles empty input', () => {{
      expect(() => someFunction('')).not.toThrow()
    }})
  }})

Return ONLY the test code. No markdown."""
    return self.think(prompt)
```

**Step D — Run Vitest and parse output:**
```python
def _run_vitest(self, test_file: str, frontend_dir: str) -> tuple[str, int]:
    result = run_command(
        f"npx vitest run {test_file} --reporter=verbose",
        cwd=frontend_dir,
        timeout=60
    )
    output = (result.stdout or "") + (result.stderr or "")
    return output, result.returncode

def _parse_vitest_output(self, output: str) -> tuple[int, int]:
    # "Tests: 2 passed, 1 failed"
    passed = self._count_keyword(output, "passed")
    failed = self._count_keyword(output, "failed")
    return passed, failed
```

**Step E — Combine Python + JS scores in TestResult:**
```python
# Return combined score: "3/3 py, 2/2 js" or just "5/5"
total_passed = py_passed + js_passed
total_tests  = py_total  + js_total
```

---

#### 5.2 Fix conftest.py for Deeply Nested Projects

**Problem:** Projects like `ai_report_generator` generate files at
`ai_report_generator/ai_report_generator/*.py`. The conftest adds
`ai_report_generator/` to sys.path but test imports use
`import ai_report_generator.ai_report_generator.module` (dotted) instead
of `import module` (simple).

**Fix — Smarter conftest that adds the DEEPEST directory containing .py files:**
```python
CONFTEST_TEMPLATE = '''\
import sys, os

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.normpath(os.path.join(_tests_dir, ".."))

def _add_if_has_py(path):
    if os.path.isdir(path) and path not in sys.path:
        try:
            if any(f.endswith(".py") for f in os.listdir(path)):
                sys.path.insert(0, path)
        except PermissionError:
            pass

# Add root
_add_if_has_py(_project_root)

# Add all subdirectories (1 level)
_skip = {"tests", "__pycache__", "node_modules", "frontend", "dist", ".git"}
for _name in os.listdir(_project_root):
    _sub = os.path.join(_project_root, _name)
    if os.path.isdir(_sub) and _name not in _skip and not _name.startswith("."):
        _add_if_has_py(_sub)
        # Also add 2nd-level subdirectories (handles double-nested packages)
        for _name2 in os.listdir(_sub):
            _sub2 = os.path.join(_sub, _name2)
            if os.path.isdir(_sub2) and _name2 not in _skip:
                _add_if_has_py(_sub2)
'''
```

**Fix — LLM prompt explicitly bans dotted imports:**
Add to `_generate_tests` prompt:
```
CRITICAL IMPORT RULE:
Use ONLY the file's simple stem name.
  CORRECT:   import data_analysis
  CORRECT:   from data_analysis import analyze
  WRONG:     import ai_report_generator.ai_report_generator.data_analysis
  WRONG:     from backend.data_analysis import analyze
The conftest.py has already added the source directory to sys.path.
```

---

#### 5.3 Fix Architect to Always Generate Backend Files

**Problem:** A prompt like "A React task manager app" causes the architect
to potentially skip the FastAPI backend entirely (since React doesn't "need"
one for a todo app). Build completes in 45s with only JS files → 0 Python
files → tester finds nothing → `test_score = None`.

**Fix — Strengthen architect.txt:**
```
MANDATORY RULE — ALWAYS INCLUDE BACKEND:
Every project MUST include at minimum:
  backend/main.py   (FastAPI app)
  backend/routes.py (API endpoints)

Even if the user prompt is "frontend-only", create a minimal FastAPI backend
with at least 2 CRUD endpoints relevant to the app's domain.
This is required for the testing pipeline to function correctly.

A task manager MUST have:
  GET  /tasks        → list all tasks
  POST /tasks        → create a task
  PUT  /tasks/{id}   → update a task
  DELETE /tasks/{id} → delete a task
```

---

### Priority 2 — Improve Test Pass Rates (MEDIUM)

#### 5.4 Pre-Test Dependency Installation

**Problem:** Generated projects need packages like `pandas`, `reportlab`,
`matplotlib` etc. that may not be installed. Pytest fails with `ImportError`
and the tester burns all 3 fix attempts on the same install error.

**Fix — Install from requirements.txt before running tests:**
```python
def _pre_install_deps(self, root: str) -> None:
    """Install project requirements before running tests."""
    req_file = Path(config.OUTPUT_DIR) / root / "requirements.txt"
    if req_file.exists():
        logger.info("📦 Installing project dependencies before testing...")
        from tools.dependency_installer import pip_install_requirements
        result = pip_install_requirements(str(req_file))
        if result.success:
            logger.info("✅ Dependencies installed")
        else:
            logger.warning(f"⚠️  Some deps failed: {result.stderr[:200]}")
```

Add to `Tester.run()` before the file loop:
```python
self._pre_install_deps(root)
```

---

#### 5.5 Smarter Mock Generation

**Problem:** LLM generates mocks for wrong function names (e.g. `routes.get_tasks`
when the actual function is `routes.fetch_tasks`). Tests fail with
`AttributeError: <module 'routes'> does not have attribute 'get_tasks'`.

**Fix — Pass actual function names to LLM:**
```python
def _extract_function_names(self, code: str) -> list[str]:
    """Extract def names from source code for accurate mock paths."""
    return re.findall(r'^(?:async )?def (\w+)', code, re.MULTILINE)

# In _generate_tests:
func_names = self._extract_function_names(code)
func_hint = f"\nACTUAL FUNCTION NAMES IN THIS FILE: {func_names}"
# Append to prompt
```

---

#### 5.6 Test Result Aggregation Fix in runner.py

**Problem:** `_safe_test_score` returns `None` when `total_tests == 0`.
This happens legitimately when all tests are skipped (collection errors).
But the frontend shows `—` (dash) which looks like "tests weren't run" rather
than "tests couldn't be generated".

**Fix — Return "0/0" instead of None when tests were attempted but all skipped:**
```python
def _safe_test_score(test_results, build_id):
    if not test_results:
        return None
    
    total_passed = 0
    total_tests  = 0
    any_attempted = False
    
    for r in test_results:
        if not r.skipped:
            any_attempted = True
        total_passed += getattr(r, 'passed', 0) or 0
        total_tests  += getattr(r, 'tests_generated', 0) or 0
    
    if total_tests == 0 and any_attempted:
        return "0/0 (collection errors)"  # distinguish from "not run"
    if total_tests == 0:
        return None
    return f"{total_passed}/{total_tests}"
```

---

### Priority 3 — Quality of Life Improvements (LOW)

#### 5.7 Test Score Display in ProjectDetail

**Problem:** Test score gauge uses `(raw / 10) * 100` for the progress bar
width. But test scores are fractions like "3/5" not numbers out of 10.
The bar always shows 0% for test scores.

**Fix — Smart score parser in ScoreGauge:**
```typescript
function parseScore(value: string | number | undefined): number {
  if (value == null) return 0;
  const str = String(value);
  // Fraction format: "3/5" → 60%
  if (str.includes('/')) {
    const [num, den] = str.split('/').map(Number);
    if (den > 0) return (num / den) * 100;
  }
  // Numeric out of 10: "7.5" → 75%
  const n = parseFloat(str);
  if (!isNaN(n)) return Math.min(100, (n / 10) * 100);
  return 0;
}
```

**File:** `frontend/src/pages/ProjectDetail.tsx` (update `ScoreGauge`)

---

#### 5.8 Build Progress — Show Step Names from Server

**Problem:** `StepTracker` uses a hardcoded `STEP_NAMES` map keyed by step
number. If the server sends a different `step_name` (e.g. "backend_developer"
vs "Backend Dev"), the display shows the hardcoded name, not the live one.

**Fix:** Use `step.step_name` from the WebSocket message as primary display,
fall back to hardcoded map only if empty.

---

#### 5.9 Add /admin/reset-keys Button to UI

**Problem:** When all 7 Groq keys hit daily limits, there's no UI button to
reset them after midnight. Users have to restart the server.

**Fix — Add reset button to the FloatingStatus component:**
```typescript
// FloatingStatus.tsx
const handleResetKeys = async () => {
  await api.resetKeys();
  // refetch health
};

// Show only when exhausted keys > 0
{health?.llm?.groq_keys_exhausted > 0 && (
  <button onClick={handleResetKeys} className="btn btn-ghost">
    Reset Keys ({health.llm.groq_keys_exhausted} exhausted)
  </button>
)}
```

---

## 6. FILE CHANGE SUMMARY (All Files Modified in This Session)

| File | Location | Status |
|------|----------|--------|
| `llm_client.py` | root | ✅ Fixed & delivered |
| `analytics.py` | `api_platform/routes/` | ✅ Fixed & delivered |
| `Statistics.tsx` | `frontend/src/pages/` | ✅ Fixed & delivered |
| `Dashboard.tsx` | `frontend/src/pages/` | ✅ Fixed & delivered |
| `start_server.py` | root (NEW) | ✅ Fixed & delivered |
| `client.ts` | `frontend/src/api/` | ✅ Fixed & delivered |
| `ProjectDetail.tsx` | `frontend/src/pages/` | ✅ Fixed & delivered |
| `useBuildProgress.ts` | `frontend/src/hooks/` | ✅ Fixed & delivered |
| `BuildProgress.tsx` | `frontend/src/pages/` | ✅ Fixed & delivered |
| `tester.py` | `agents/` | ✅ Fixed & delivered |
| `tester.txt` | `prompts/` | ✅ Fixed & delivered |

### Still To Implement
| File | Location | Priority |
|------|----------|----------|
| `tester.py` | `agents/` | HIGH — add JS/Vitest support |
| `tester.txt` | `prompts/` | HIGH — JS test pattern |
| `conftest_template` in `tester.py` | `agents/` | HIGH — 2-level path scan |
| `architect.txt` | `prompts/` | HIGH — always require backend |
| `ProjectDetail.tsx` | `frontend/src/pages/` | MEDIUM — fix score gauge bar |
| `runner.py` | `api_platform/` | MEDIUM — "0/0" vs None |
| `FloatingStatus.tsx` | `frontend/src/components/layout/` | LOW — reset keys button |

---

## 7. STARTUP COMMANDS (Current Working Setup)

```bash
# Terminal 1 — Backend (use start_server.py, NOT uvicorn directly)
cd C:\programes\comppython\Aiautonomous
venv\Scripts\activate
python start_server.py

# Terminal 2 — Frontend
cd C:\programes\comppython\Aiautonomous\frontend
npm run dev

# Verify backend health
curl http://localhost:8000/health

# Reset exhausted Groq keys (run after midnight)
curl -X POST http://localhost:8000/admin/reset-keys
```

---

## 8. KEY DESIGN DECISIONS & CONSTRAINTS

1. **Python-only backend** — The architect prompt enforces FastAPI for ALL backends.
   No Node/Express. Every generated project must have `backend/main.py` + `backend/routes.py`.

2. **Groq as primary LLM** — Set `LLM_PROVIDER=groq` in `.env`. Ollama is
   opt-in via `LLM_PROVIDER=both`. With 7 keys, rate limits are managed by
   waiting for `Retry-After` header (typically 2-6 seconds) before rotating.

3. **Tests run in isolation** — Each test file (`test_main.py`, `test_services.py`)
   is run with its own `pytest path/to/test_X.py` call. Never `pytest tests/`.

4. **conftest.py is dynamic** — Written fresh each build, scans the actual
   project structure to build sys.path. Never hardcodes `backend/`.

5. **WebSocket + REST fallback** — WS is preferred for live updates. If WS
   drops (connection error, build already done when page loads, rebuild-to-
   undefined bug), REST polling at 5s intervals silently takes over.
   "WS Error" is never shown to the user.

6. **Score fields** — `review_score` is float (7.14), `debug_score` is string
   ("6/6"), `test_score` is string ("3/5" or None). All handled by
   `_safe_*_score()` helpers in `runner.py`.
