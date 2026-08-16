"""
Phase 21 Test Suite — Resilient Refinement & Quota Context Handoff
==================================================================
Offline tests. No server and no LLM calls required — every LLM boundary is
stubbed, and the quota tracker is driven directly.

Run: python test_phase21.py
"""
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Force UTF-8 stdout so the emoji in log lines don't blow up on cp1252 consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config
import llm_client
from agents.pipeline import Pipeline, BuildResult, RemediationReport

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        PASS.append(name)
        print(f"  [PASS]  {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL]  {name}  {detail}")


# ── Test doubles ──────────────────────────────────────────────────────────────

@dataclass
class FakeDebug:
    file_path: str
    success:   bool


@dataclass
class FakeReview:
    file_path: str
    score:     float = 0.0


@dataclass
class FakeTest:
    file_path:       str
    passed:          int  = 0
    tests_generated: int  = 0
    skipped:         bool = False
    skip_reason:     str  = ""
    errors:          list = field(default_factory=list)


def kill_all_quota():
    llm_client._mark_model_daily_limited(llm_client._HEAVY_MODEL, "test: daily quota")
    llm_client._mark_model_daily_limited(llm_client._FAST_MODEL,  "test: daily quota")


def restore_quota():
    llm_client._reset_exhausted()


def cleanup(root: str):
    d = Path(config.OUTPUT_DIR) / root
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


# ── 1. Quota detection helpers (Component 1) ──────────────────────────────────

print("\n[1] llm_client quota detection")
restore_quota()
check("is_quota_exhausted() False with healthy keys", llm_client.is_quota_exhausted() is False)

llm_client._mark_model_daily_limited(llm_client._HEAVY_MODEL, "test")
check("heavy model reported exhausted",
      llm_client.is_quota_exhausted(llm_client._HEAVY_MODEL) is True)
check("fast model still usable",
      llm_client.is_quota_exhausted(llm_client._FAST_MODEL) is False)
check("global check False while ONE model survives",
      llm_client.is_quota_exhausted() is False,
      "a dead 70b must not stop builds the 8b can finish")

llm_client._mark_model_daily_limited(llm_client._FAST_MODEL, "test")
check("global check True once BOTH models are dead",
      llm_client.is_quota_exhausted() is True)

err = llm_client._make_quota_error(llm_client._FAST_MODEL, "tokens per day")
check("GroqDailyQuotaError subclasses RuntimeError", isinstance(err, RuntimeError),
      "existing `except RuntimeError` callers must keep working")
details = err.details()
check("quota error carries model",      details.get("model") == llm_client._FAST_MODEL)
check("quota error carries key counts", isinstance(details.get("keys_total"), int))
check("quota error carries reset hint", bool(details.get("reset_hint")))

snap = llm_client.get_quota_snapshot()
check("quota snapshot has all_exhausted flag", snap.get("all_exhausted") is True)
check("quota snapshot is JSON-serializable",
      __import__("json").dumps(snap) is not None)

restore_quota()
check("reset clears exhaustion", llm_client.is_quota_exhausted() is False)


# ── 2. generate_text preserves the quota type (Component 1, the key fix) ──────

print("\n[2] generate_text() preserves GroqDailyQuotaError")

_original_call_groq = llm_client._call_groq
try:
    kill_all_quota()

    def _boom(prompt, system, max_tokens, model):
        raise llm_client._make_quota_error(model, "simulated daily limit")

    llm_client._call_groq = _boom
    raised = None
    try:
        llm_client.generate_text("hello", agent_name="Reviewer")
    except Exception as e:
        raised = e

    check("generate_text raises GroqDailyQuotaError, not bare RuntimeError",
          isinstance(raised, llm_client.GroqDailyQuotaError),
          f"got {type(raised).__name__}: {raised}")
    check("re-raised error still carries diagnostics",
          bool(getattr(raised, "reset_hint", "")))
finally:
    llm_client._call_groq = _original_call_groq
    restore_quota()


# ── 3. _refine_and_remediate never raises (Component 2) ───────────────────────

print("\n[3] _refine_and_remediate() repairs instead of aborting")

pipe   = Pipeline(build_id="test2100")
result = BuildResult(user_prompt="test", build_id="test2100")
result.architecture  = {"root_folder": "phase21_remediate", "files": []}
result.backend_files = ["phase21_remediate/backend/routes.py"]
result.debug_results = [FakeDebug("phase21_remediate/backend/routes.py", False)]
result.test_results  = [FakeTest("phase21_remediate/backend/routes.py", 1, 3)]

issues, failed = pipe._diagnose(result)
check("diagnosis finds the failing import", any("import/debug" in i for i in issues))
check("diagnosis finds the failing tests",  any("tests fail" in i for i in issues))
check("diagnosis returns the failed path",
      failed == ["phase21_remediate/backend/routes.py"])

# Quota dead ⇒ deterministic-only path, no LLM calls at all
kill_all_quota()
report = None
raised = None
try:
    report = pipe._refine_and_remediate(result)
except Exception as e:
    raised = e
restore_quota()

check("remediation raised nothing", raised is None, f"raised {raised!r}")
check("remediation reports it ran",       report is not None and report.ran is True)
check("remediation flags degraded",       report is not None and report.degraded is True)
check("remediation skipped LLM on dead quota",
      report is not None and report.llm_used is False,
      "must not spend the last tokens on repair instead of the handoff doc")
check("remediation recorded unresolved issues",
      report is not None and len(report.unresolved) > 0)

# A clean build must not trigger remediation at all
clean = BuildResult(user_prompt="test", build_id="test2101")
clean.architecture  = {"root_folder": "phase21_clean", "files": []}
clean.backend_files = ["phase21_clean/backend/main.py"]
clean.debug_results = [FakeDebug("phase21_clean/backend/main.py", True)]
clean.test_results  = [FakeTest("phase21_clean/backend/main.py", 4, 4)]
clean_report = pipe._refine_and_remediate(clean)
check("clean build skips remediation entirely", clean_report.ran is False)
check("clean build is not degraded",            clean_report.degraded is False)


# ── 4. SESSION_CONTEXT.md generation with zero LLM calls (Component 3) ────────

print("\n[4] SESSION_CONTEXT.md is generated without any LLM call")

ROOT = "phase21_context"
cleanup(ROOT)

from agents.documenter import Documenter
from tools.file_writer import create_file

create_file(f"{ROOT}/backend/main.py",   "from fastapi import FastAPI\napp = FastAPI()\n")
create_file(f"{ROOT}/backend/routes.py", "from fastapi import APIRouter\nrouter = APIRouter()\n")

kill_all_quota()   # prove the template path needs no quota
doc  = Documenter()
path = doc.generate_session_context(
    intent          = {"app_name": ROOT, "app_type": "api", "complexity": "medium"},
    architecture    = {
        "root_folder": ROOT,
        "files": [
            {"path": "backend/main.py",     "type": "python", "description": "entrypoint"},
            {"path": "backend/routes.py",   "type": "python", "description": "REST routes"},
            {"path": "backend/services.py", "type": "python", "description": "business logic"},
        ],
    },
    backend_files    = [f"{ROOT}/backend/main.py", f"{ROOT}/backend/routes.py"],
    frontend_files   = [],
    completed_steps  = ["1. intent_analyzer", "2. planner", "3. architect", "4. backend_developer"],
    pending_steps    = ["5. frontend_generator", "6. debugger", "7. reviewer",
                        "8. tester", "9. documenter"],
    reason           = "quota_exhausted",
    quota_snapshot   = llm_client.get_quota_snapshot(),
    remediation      = RemediationReport(ran=True, passes=1, llm_used=False,
                                         unresolved=["routes.py fails to import"]),
    progress_percent = 44.4,
    debug_results    = [FakeDebug(f"{ROOT}/backend/main.py", True),
                        FakeDebug(f"{ROOT}/backend/routes.py", False)],
    review_results   = [FakeReview(f"{ROOT}/backend/main.py", 7.5)],
    test_results     = [FakeTest(f"{ROOT}/backend/main.py", 3, 4)],
)
restore_quota()

ctx_file   = Path(config.OUTPUT_DIR) / ROOT / "SESSION_CONTEXT.md"
alias_file = Path(config.OUTPUT_DIR) / ROOT / "BUILD_CONTEXT.md"
check("generate_session_context returned a path", bool(path))
check("SESSION_CONTEXT.md exists on disk",        ctx_file.exists())
check("BUILD_CONTEXT.md alias exists",            alias_file.exists())

body = ctx_file.read_text(encoding="utf-8") if ctx_file.exists() else ""
check("reports a non-zero progress percentage",  "44% complete" in body)
check("lists completed steps as checked",        "- [x] 4. backend_developer" in body)
check("lists pending steps as unchecked",        "- [ ] 8. tester" in body)
check("explains the quota reason",               "quota" in body.lower())
check("includes the key-status table",           "API key status" in body)
check("flags the file that fails to import",     "import failed" in body)
check("names the file that was never generated", "backend/services.py" in body)
check("includes run instructions",               "uvicorn main:app" in body)
check("includes a resume path",                  "same prompt" in body)

cleanup(ROOT)


# ── 5. Quota interception end-to-end (Component 2) ────────────────────────────

print("\n[5] Pipeline packages a quota-killed build instead of failing it")

ROOT2 = "phase21_quota_stop"
cleanup(ROOT2)

pipe2 = Pipeline(build_id="test2102")

ARCH = {
    "root_folder": ROOT2,
    "files": [
        {"path": "backend/main.py",   "type": "python",     "description": "entrypoint"},
        {"path": "frontend/App.jsx",  "type": "jsx",        "description": "UI shell"},
    ],
}


def _fake_backend(intent, architecture):
    create_file(f"{ROOT2}/backend/main.py",
                "from fastapi import FastAPI\napp = FastAPI()\n")
    return [f"{ROOT2}/backend/main.py"]


def _quota_death(*args, **kwargs):
    raise llm_client._make_quota_error(llm_client._FAST_MODEL, "simulated daily limit")


pipe2.intent_analyzer.run   = lambda prompt: {
    "app_name": ROOT2, "app_type": "api", "complexity": "medium",
}
pipe2.planner.run           = lambda intent: ["step one", "step two"]
pipe2.architect.run         = lambda intent, steps, build_id=None: ARCH
pipe2.backend_developer.run = _fake_backend
# Quota dies at step 5, right after real code hit the disk
pipe2.frontend_generator.run = _quota_death

kill_all_quota()
res = pipe2.run("build a test api")
restore_quota()

check("build is NOT marked failed",        res.success is True,
      f"success={res.success} error={res.error!r}")
check("build is flagged quota_paused",     res.quota_paused is True)
check("build is flagged degraded",         res.degraded is True)
check("generated files are retained",      res.backend_files == [f"{ROOT2}/backend/main.py"])
check("progress percentage is computed",   0 < res.progress_percent < 100,
      f"got {res.progress_percent}")
check("completed steps recorded",          "4. backend_developer" in res.completed_steps)
check("pending steps recorded",            "9. documenter" in res.pending_steps)
check("completion_reason is human-readable", "quota" in res.completion_reason.lower())
check("session context path is set",       bool(res.session_context_path))

ctx2 = Path(config.OUTPUT_DIR) / ROOT2 / "SESSION_CONTEXT.md"
check("SESSION_CONTEXT.md written for the paused build", ctx2.exists())
if ctx2.exists():
    text2 = ctx2.read_text(encoding="utf-8")
    check("paused context names the app",        ROOT2 in text2)
    check("paused context lists the built file", "backend/main.py" in text2)

check("quota diagnostics captured on result",
      res.quota_details.get("model") == llm_client._FAST_MODEL,
      f"got {res.quota_details}")

cleanup(ROOT2)


# ── 6. A late-step crash still packages the code (Component 2) ────────────────

print("\n[6] Pipeline packages a late-step crash instead of discarding code")

ROOT3 = "phase21_late_crash"
cleanup(ROOT3)

pipe3 = Pipeline(build_id="test2103")
ARCH3 = {
    "root_folder": ROOT3,
    "files": [{"path": "backend/main.py", "type": "python", "description": "entrypoint"}],
}


def _fake_backend3(intent, architecture):
    create_file(f"{ROOT3}/backend/main.py", "print('hello')\n")
    return [f"{ROOT3}/backend/main.py"]


pipe3.intent_analyzer.run    = lambda prompt: {"app_name": ROOT3, "app_type": "api"}
pipe3.planner.run            = lambda intent: ["a"]
pipe3.architect.run          = lambda intent, steps, build_id=None: ARCH3
pipe3.backend_developer.run  = _fake_backend3
pipe3.frontend_generator.run = lambda intent, architecture: []
pipe3.frontend_debugger.run  = lambda root, files: []
pipe3.debugger.run           = lambda files: [FakeDebug(f"{ROOT3}/backend/main.py", True)]
pipe3.reviewer.run           = lambda files: [FakeReview(f"{ROOT3}/backend/main.py", 8.0)]


def _tester_explodes(*args, **kwargs):
    raise ValueError("simulated tester crash")


pipe3.tester.run = _tester_explodes

kill_all_quota()   # keeps the documenter from making real LLM calls
res3 = pipe3.run("build a test api")
restore_quota()

check("late crash does not fail the build",   res3.success is True,
      f"success={res3.success} error={res3.error!r}")
check("late crash marks the build degraded",  res3.degraded is True)
check("late crash is NOT flagged quota",      res3.quota_paused is False)
check("original error is preserved",          "simulated tester crash" in res3.error)
ctx3 = Path(config.OUTPUT_DIR) / ROOT3 / "SESSION_CONTEXT.md"
check("SESSION_CONTEXT.md written for the crash", ctx3.exists())

cleanup(ROOT3)


# ── 7. Status vocabulary is consistent across the platform (Component 4) ──────

print("\n[7] Status vocabulary")

from api_platform.runner import DOWNLOADABLE_STATUSES, TERMINAL_STATUSES
from api_platform.routes.analytics import SUCCESS_STATUSES

check("done_with_context is downloadable", "done_with_context" in DOWNLOADABLE_STATUSES)
check("done_with_context is terminal",     "done_with_context" in TERMINAL_STATUSES)
check("done_with_context counts as success in analytics",
      "done_with_context" in SUCCESS_STATUSES)
check("failed is never downloadable",      "failed" not in DOWNLOADABLE_STATUSES)

from api_platform.database import initialize_db, list_projects
initialize_db()
rows = list_projects(limit=1)
if rows:
    check("projects carry completion_reason column", "completion_reason" in rows[0])
    check("projects carry progress_percent column",  "progress_percent"  in rows[0])
else:
    check("DB column check skipped (empty DB)", True)


# ── 8. Quota errors are never swallowed as per-file failures (21.1) ──────────

print("\n[8] Agents do not swallow GroqDailyQuotaError")

from agents.reviewer import Reviewer
from agents.frontend_debugger import FrontendDebugger
from agents.documenter import Documenter as _Doc


def _raises_quota(*args, **kwargs):
    raise llm_client._make_quota_error(llm_client._FAST_MODEL, "simulated")


ROOT4 = "phase21_swallow"
cleanup(ROOT4)
create_file(f"{ROOT4}/backend/main.py", "x = 1\n")

rv = Reviewer()
rv.think_json = _raises_quota
raised = None
try:
    rv._review_file(f"{ROOT4}/backend/main.py")
except Exception as e:
    raised = e
check("reviewer propagates quota instead of returning an error result",
      isinstance(raised, llm_client.GroqDailyQuotaError),
      f"got {type(raised).__name__}")

fd = FrontendDebugger()
fd.think = _raises_quota
raised = None
try:
    fd._ask_llm_to_fix("App.tsx", "const x = 1", ["TS1005"])
except Exception as e:
    raised = e
check("frontend_debugger propagates quota instead of returning None",
      isinstance(raised, llm_client.GroqDailyQuotaError),
      f"got {type(raised).__name__}")

dc = _Doc()
dc.think = _raises_quota
raised = None
try:
    dc.run({"app_name": ROOT4}, {"root_folder": ROOT4}, [f"{ROOT4}/backend/main.py"])
except Exception as e:
    raised = e
check("documenter propagates quota instead of shipping an empty README",
      isinstance(raised, llm_client.GroqDailyQuotaError),
      f"got {type(raised).__name__}")

# A NON-quota error must still be handled gracefully (no behaviour regression)
rv2 = Reviewer()
rv2.think_json = lambda *a, **k: (_ for _ in ()).throw(ValueError("bad json"))
res_rv = rv2._review_file(f"{ROOT4}/backend/main.py")
check("reviewer still absorbs ordinary per-file errors",
      getattr(res_rv, "error", "") != "")

cleanup(ROOT4)


# ── 9. Static output audit catches what the import/test gates miss (21.1) ─────

print("\n[9] Deterministic output audit (0 LLM calls)")

ROOT5 = "phase21_audit"
cleanup(ROOT5)

# Reproduce every defect class seen in the real todo_app build
create_file(f"{ROOT5}/backend/schema.sql",
            "# Database schema\n# This file will be generated by the code generation agents.\n")
create_file(f"{ROOT5}/backend/routes.py", '''
from fastapi import APIRouter
router = APIRouter()

@router.get("/weather/")
async def get_weather():
    from weather import get_weather_data   # phantom, inside function body
    return get_weather_data()

@router.get("/todo/")
async def get_todos():
    # TODO: implement database query
    return []
''')
create_file(f"{ROOT5}/frontend/src/App.js",
            "import TodoList from './TodoList';\nexport default function App() { return null }\n")

pipe5 = Pipeline(build_id="test2104")
res5  = BuildResult(user_prompt="x", build_id="test2104")
res5.architecture = {"root_folder": ROOT5, "files": []}

kill_all_quota()          # prove the audit needs no quota whatsoever
audit = pipe5._audit_generated_output(res5)
restore_quota()

blob = " | ".join(audit)
check("audit runs with zero quota available", isinstance(audit, list))
check("detects unfilled scaffold placeholders", "schema.sql" in blob)
check("detects function-body phantom import",  "`weather`" in blob,
      "this is the defect that passed debug 3/3 in the real build")
check("detects dangling frontend import",      "./TodoList" in blob)
check("detects TODO-stub handlers",            "get_todos()" in blob)
check("does NOT flag installed packages",      "fastapi" not in blob)

# No false positives on a healthy project
ROOT6 = "phase21_healthy"
cleanup(ROOT6)
create_file(f"{ROOT6}/backend/main.py",
            "from fastapi import FastAPI\nfrom db import Database\napp = FastAPI()\n")
create_file(f"{ROOT6}/backend/db.py", "class Database:\n    pass\n")
res6 = BuildResult(user_prompt="x", build_id="test2105")
res6.architecture = {"root_folder": ROOT6, "files": []}
clean_audit = pipe5._audit_generated_output(res6)
check("clean project produces no audit findings", clean_audit == [],
      f"false positives: {clean_audit}")

cleanup(ROOT5)
cleanup(ROOT6)


# ── 10. Remediation cost controls (21.1) ─────────────────────────────────────

print("\n[10] Remediation does not re-test untouched files")

pipe7 = Pipeline(build_id="test2106")
res7  = BuildResult(user_prompt="x", build_id="test2106")
res7.architecture  = {"root_folder": "phase21_cost", "files": []}
res7.backend_files = [
    "phase21_cost/backend/a.py",
    "phase21_cost/backend/b.py",
    "phase21_cost/backend/c.py",
]
res7.debug_results = [FakeDebug(p, False) for p in res7.backend_files]
res7.test_results  = [FakeTest(p, 0, 3) for p in res7.backend_files]

tester_calls: list[list[str]] = []


def _spy_tester(paths, architecture, debug_results=None):
    tester_calls.append(list(paths))
    return [FakeTest(p, 3, 3) for p in paths]


# Debugger repairs only ONE of the three files
def _spy_debugger(paths):
    return [FakeDebug(p, p.endswith("a.py")) for p in paths]


pipe7.tester.run   = _spy_tester
pipe7.debugger.run = _spy_debugger
report7 = pipe7._refine_and_remediate(res7)

check("tester was called at least once", len(tester_calls) >= 1,
      f"calls={tester_calls}")
if tester_calls:
    check("re-test was scoped to the repaired file only",
          tester_calls[0] == ["phase21_cost/backend/a.py"],
          f"got {tester_calls[0]} — re-testing all 3 files is what drained quota")
check("results for untouched files are preserved",
      len(res7.test_results) == 3,
      f"got {len(res7.test_results)} — aggregate score must still cover the project")
check("remediation stops once no further progress is possible",
      report7.passes <= 2, f"passes={report7.passes}")

# When the debugger repairs nothing, the tester must not be called at all
tester_calls.clear()
res8 = BuildResult(user_prompt="x", build_id="test2107")
res8.architecture  = {"root_folder": "phase21_cost2", "files": []}
res8.backend_files = ["phase21_cost2/backend/a.py"]
res8.debug_results = [FakeDebug("phase21_cost2/backend/a.py", False)]
res8.test_results  = [FakeTest("phase21_cost2/backend/a.py", 0, 2)]

pipe8 = Pipeline(build_id="test2108")
pipe8.tester.run   = _spy_tester
pipe8.debugger.run = lambda paths: [FakeDebug(p, False) for p in paths]
report8 = pipe8._refine_and_remediate(res8)
check("no repairs ⇒ tester never re-invoked (0 tokens)", tester_calls == [],
      f"got {tester_calls}")
check("no-progress remediation still reports degraded", report8.degraded is True)


# ── Summary ───────────────────────────────────────────────────────────────────

total = len(PASS) + len(FAIL)
print(f"\n{'='*58}")
print(f"  Phase 21 Test Results: {len(PASS)}/{total} passed")
print(f"{'='*58}")
if FAIL:
    print("\nFailed tests:")
    for f in FAIL:
        print(f"  [FAIL]  {f}")
else:
    print("\n  All tests passed. Phase 21 is fully implemented.")

sys.exit(0 if not FAIL else 1)
