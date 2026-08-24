"""
agents/pipeline.py  v2.2.1  (Phase 20 — Build Isolation + Authentic Scores)
=============================================================================
Changes vs v2.2.0:

BUG FIX — Gap A: path comparison bug in _purge_forbidden_files()
  In v2.2.0 the purged-path filter used:
      purged_set = {str(Path(root) / d) for d in deleted}
  On Windows, Path() uses backslashes; the backend_files list uses forward
  slashes.  The set membership check silently fails → purged files remain
  in result.backend_files → Debugger and Tester try to import deleted files
  → build fails with FileNotFoundError after the backend step.

  Fix: normalise both sides to forward-slash strings before comparison.
      purged_set = {f"{root}/{d}".replace("\\", "/") for d in deleted}
      result.backend_files = [
          f for f in result.backend_files
          if f.replace("\\", "/") not in purged_set
      ]

All v2.2.0 features retained unchanged:
  Phase 20.1 — Build isolation (unique root dir per build via build_id)
  Phase 20.2 — Authentic test scores (debug_results flows to tester)
  Phase 20.3 — Forbidden file active deletion after backend generation
  Phase 19.3 — TypeScript validation (FrontendDebugger)
  Phase 19.1 — requirements.txt auto-validation (BackendDeveloper)
  Phase 17   — per-step token tracking
  Cooperative cancellation (cancel_check before each step)
"""
import logging
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List

from agents.intent_analyzer import IntentAnalyzer
from agents.planner import Planner
from agents.architect import Architect, FORBIDDEN_FILES
from agents.backend_developer import BackendDeveloper
from agents.frontend_generator import FrontendGenerator
from agents.frontend_debugger import FrontendDebugger, TsDebugResult
from agents.debugger import Debugger, FileDebugResult
from agents.reviewer import Reviewer, ReviewResult
from agents.tester import Tester, TestResult
from agents.documenter import Documenter, DocResult

try:
    from llm_client import GroqDailyQuotaError
except Exception:  # pragma: no cover — llm_client is always importable in practice
    class GroqDailyQuotaError(RuntimeError):  # type: ignore[no-redef]
        """Fallback stub so the pipeline imports even if llm_client is missing."""

logger = logging.getLogger(__name__)

STEP_TIMEOUT_SECONDS: int = int(os.getenv("STEP_TIMEOUT_SECONDS", "900"))
STEP_MAX_RETRIES:     int = 1

# Phase 21: how many LLM-backed repair passes _refine_and_remediate may run.
REMEDIATION_MAX_PASSES: int = int(os.getenv("REMEDIATION_MAX_PASSES", "2"))


class PipelineCancelledError(Exception):
    """Raised when cancel_check() returns True between steps."""


class PipelineVerificationError(Exception):
    """
    Phase 21: no longer raised by the pipeline.

    The deployability gate that used to raise this now runs
    _refine_and_remediate() instead, which repairs what it can and reports what
    it cannot rather than discarding the build. Kept for import compatibility
    with anything that still catches it.
    """


@dataclass
class RemediationReport:
    """Outcome of the self-healing refinement passes. Never an exception."""
    ran:            bool = False
    passes:         int  = 0
    llm_used:       bool = False
    repaired_files: list = field(default_factory=list)
    unresolved:     list = field(default_factory=list)   # human-readable issues
    degraded:       bool = False   # True ⇒ build finishes as done_with_context

    def summary(self) -> str:
        if not self.ran:
            return "no remediation needed"
        mode = "LLM+structural" if self.llm_used else "structural only"
        return (
            f"{self.passes} pass(es), {mode}, "
            f"{len(self.repaired_files)} file(s) repaired, "
            f"{len(self.unresolved)} issue(s) unresolved"
        )


@dataclass
class BuildResult:
    user_prompt:              str
    build_id:                 str   = field(default_factory=lambda: str(uuid4())[:8])
    intent:                   dict  = field(default_factory=dict)
    steps:                    list  = field(default_factory=list)
    architecture:             dict  = field(default_factory=dict)
    backend_files:            list  = field(default_factory=list)
    frontend_files:           list  = field(default_factory=list)
    frontend_debug_results:   list  = field(default_factory=list)
    debug_results:            list  = field(default_factory=list)
    review_results:           list  = field(default_factory=list)
    test_results:             list  = field(default_factory=list)
    doc_result:               Optional[DocResult] = None
    success:                  bool  = False
    error:                    str   = ""
    cancelled:                bool  = False
    started_at:               datetime = field(default_factory=datetime.now)
    completed_at:             Optional[datetime] = None
    current_step:             int   = 0

    # ── Phase 21: resilient completion metadata ───────────────────────────────
    quota_paused:             bool  = False   # build stopped on LLM daily quota
    degraded:                 bool  = False   # completed, but with known issues
    completion_reason:        str   = ""      # human-readable, shown in the UI
    progress_percent:         float = 0.0
    session_context_path:     str   = ""
    remediation:              Optional[RemediationReport] = None
    quota_details:            dict  = field(default_factory=dict)
    completed_steps:          list  = field(default_factory=list)
    pending_steps:            list  = field(default_factory=list)

    # ── Phase 22: runtime verification ────────────────────────────────────────
    smoke_summary:            str   = ""   # "N/M routes responded without a 5xx"

    @property
    def all_files(self):
        return self.backend_files + self.frontend_files

    @property
    def duration_seconds(self) -> float:
        if not self.completed_at:
            return (datetime.now() - self.started_at).total_seconds()
        return (self.completed_at - self.started_at).total_seconds()

    def complete(self, success: bool):
        self.success      = success
        self.completed_at = datetime.now()

    def summary(self) -> str:
        debug_passed = sum(1 for r in self.debug_results if r.success)
        scores       = [r.score for r in self.review_results if r.score]
        avg_score    = sum(scores) / len(scores) if scores else 0
        total_tests  = sum(r.tests_generated for r in self.test_results)
        tests_passed = sum(r.passed for r in self.test_results)
        doc_status   = str(self.doc_result) if self.doc_result else "not run"
        ts_fixed     = sum(1 for r in self.frontend_debug_results if r.success and not r.skipped)

        if self.cancelled:
            verdict = "🚫 CANCELLED"
        elif self.quota_paused:
            verdict = "🔑 PAUSED — QUOTA EXHAUSTED (files packaged)"
        elif self.success and self.degraded:
            verdict = "⚠️  DONE WITH CONTEXT (degraded)"
        elif self.success:
            verdict = "✅ SUCCESS"
        else:
            verdict = "❌ FAILED"

        lines = [
            f"\n{'='*50}",
            f"  BUILD RESULT: {verdict}",
            f"{'='*50}",
            f"  Build ID:      {self.build_id}",
            f"  Root folder:   {self.architecture.get('root_folder', '?')}",
            f"  App:           {self.intent.get('app_name', '?')}",
            f"  Type:          {self.intent.get('app_type', '?')}",
            f"  Complexity:    {self.intent.get('complexity', '?')}",
            f"  Files:         {len(self.all_files)}",
            f"  TS fixed:      {ts_fixed}/{len(self.frontend_debug_results)} files",
            f"  Debug:         {debug_passed}/{len(self.debug_results)} passing",
            f"  Review:        {avg_score:.1f}/10 avg score",
            f"  Tests:         {tests_passed}/{total_tests} passing",
            f"  Docs:          {doc_status}",
            f"  Duration:      {self.duration_seconds:.1f}s",
        ]
        if self.remediation and self.remediation.ran:
            lines.append(f"  Remediation:   {self.remediation.summary()}")
        if self.session_context_path:
            lines.append(f"  Handoff doc:   {self.session_context_path}")
        if self.completion_reason:
            lines.append(f"  Reason:        {self.completion_reason}")
        lines.append(f"{'='*50}")

        if self.error:
            lines.append(f"\n  ❌ Error: {self.error}")
        lines.append(f"{'='*50}\n")
        return "\n".join(lines)


class Pipeline:
    def __init__(
        self,
        build_id:          str      = None,
        progress_callback: Callable = None,
        cancel_check:      Callable[[], bool] = None,
    ):
        self.build_id          = build_id or str(uuid4())[:8]
        self.progress_callback = progress_callback
        self._cancel_check     = cancel_check or (lambda: False)

        self.intent_analyzer    = IntentAnalyzer()
        self.planner            = Planner()
        self.architect          = Architect()
        self.backend_developer  = BackendDeveloper()
        self.frontend_generator = FrontendGenerator()
        self.frontend_debugger  = FrontendDebugger()
        self.debugger           = Debugger()
        self.reviewer           = Reviewer()
        self.tester             = Tester()
        self.documenter         = Documenter()

    # ── Token tracking: propagate build_id into sub-threads ───────────────────

    def _make_tracked_fn(self, fn: Callable) -> Callable:
        build_id = self.build_id

        def _tracked():
            try:
                import llm_client
                llm_client.set_current_build_id(build_id)
            except Exception:
                pass
            return fn()

        return _tracked

    # ── Step runner with timeout + retry ──────────────────────────────────────

    def _run_step_with_timeout(
        self,
        step_num:  int,
        step_name: str,
        fn:        Callable,
        timeout:   int = STEP_TIMEOUT_SECONDS,
        retries:   int = STEP_MAX_RETRIES,
    ) -> Any:
        last_exc: Optional[Exception] = None
        total_attempts = retries + 1

        for attempt in range(1, total_attempts + 1):
            logger.info(
                f"  ⏱️  [{step_name}] Starting "
                f"(attempt {attempt}/{total_attempts}, timeout={timeout}s)"
            )
            tracked_fn = self._make_tracked_fn(fn)

            with ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"step_{step_name}",
            ) as executor:
                future = executor.submit(tracked_fn)
                try:
                    result = future.result(timeout=timeout)
                    if attempt > 1:
                        logger.info(f"  ✅ [{step_name}] Succeeded on attempt {attempt}")
                    return result

                except FuturesTimeoutError:
                    future.cancel()
                    last_exc = TimeoutError(
                        f"Step '{step_name}' timed out after {timeout}s."
                    )
                    logger.warning(f"  ⏰ [{step_name}] Timed out (attempt {attempt})")

                # Phase 21: a dead daily quota cannot be retried into working.
                # Retrying just burns another full step timeout and produces a
                # misleading "attempt 2/2" in the logs — fail fast so run() can
                # intercept and write the handoff document while there is still
                # time on the clock.
                except GroqDailyQuotaError:
                    logger.error(
                        f"  🔑 [{step_name}] LLM daily quota exhausted — "
                        "not retrying, handing off to quota interception."
                    )
                    raise

                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        f"  ❌ [{step_name}] Failed (attempt {attempt}): "
                        f"{type(exc).__name__}: {exc}"
                    )

            if attempt < total_attempts:
                logger.info(f"  🔁 [{step_name}] Retrying…")

        raise last_exc  # type: ignore[misc]

    # ── Progress emitter ──────────────────────────────────────────────────────

    def _emit_progress(self, step: int, step_name: str, status: str, data: Dict = None):
        if self.progress_callback:
            self.progress_callback({
                "build_id":  self.build_id,
                "step":      step,
                "step_name": step_name,
                "status":    status,
                "timestamp": datetime.now().isoformat(),
                "data":      data or {},
            })

    # ── Phase 20.3: Delete forbidden files after backend generation ───────────

    def _purge_forbidden_files(self, root_folder: str) -> list[str]:
        """
        Actively delete any forbidden files (setup.py, manage.py, etc.) from the
        output directory, even if the LLM regenerated them despite prompt restrictions.
        Returns list of relative paths (forward-slash) for logging and set comparison.

        BUG FIX v2.2.1 (Gap A): returned paths now always use forward slashes so
        the set-membership check in run() works correctly on Windows too.
        """
        import config
        deleted = []
        project_dir = Path(config.OUTPUT_DIR) / root_folder
        if not project_dir.exists():
            return deleted

        for forbidden_name in FORBIDDEN_FILES:
            for match in project_dir.rglob(forbidden_name):
                try:
                    match.unlink()
                    # Always use forward slashes for cross-platform consistency
                    rel = str(match.relative_to(project_dir)).replace("\\", "/")
                    deleted.append(rel)
                    logger.warning(
                        f"🗑️  Deleted forbidden file: {rel} "
                        f"(LLM generated it despite prompt restrictions)"
                    )
                except Exception as e:
                    logger.warning(f"⚠️  Could not delete {match}: {e}")
        return deleted

    # ── Per-step success data builders ────────────────────────────────────────

    def _build_step_data(self, step_name: str, val: Any) -> dict:
        try:
            if step_name == "intent_analyzer" and isinstance(val, dict):
                return {
                    "intent":     val,
                    "app_name":   val.get("app_name"),
                    "app_type":   val.get("app_type"),
                    "complexity": val.get("complexity"),
                }
            if step_name == "planner" and isinstance(val, list):
                return {"steps_count": len(val)}
            if step_name == "architect" and isinstance(val, dict):
                return {
                    "files_count": len(val.get("files", [])),
                    "root_folder": val.get("root_folder"),
                }
            if step_name in ("backend_developer", "frontend_generator") and isinstance(val, list):
                return {"files_generated": len(val)}
            if step_name == "frontend_debugger" and isinstance(val, list):
                fixed   = sum(1 for r in val if r.success and not r.skipped)
                skipped = sum(1 for r in val if r.skipped)
                return {
                    "ts_files_checked": len(val),
                    "ts_files_fixed":   fixed,
                    "ts_files_skipped": skipped,
                }
            if step_name == "debugger" and isinstance(val, list):
                passed = sum(1 for r in val if r.success)
                return {"passed": passed, "total": len(val)}
            if step_name == "reviewer" and isinstance(val, list):
                scores = [r.score for r in val if r.score]
                avg    = round(sum(scores) / len(scores), 2) if scores else 0
                return {"avg_score": avg, "files_reviewed": len(val)}
            if step_name == "tester" and isinstance(val, list):
                passed        = sum(r.passed for r in val)
                total         = sum(r.tests_generated for r in val)
                skipped_count = sum(1 for r in val if r.skipped)
                return {
                    "passed":  passed,
                    "total":   total,
                    "skipped": skipped_count,
                }
            if step_name == "documenter" and val is not None:
                return {"readme_path": getattr(val, "readme_path", None)}
        except Exception:
            pass
        return {}

    # ── Main pipeline ─────────────────────────────────────────────────────────

    # ── Phase 21: diagnosis + self-healing refinement (replaces the hard gate) ─

    def _diagnose(self, result: BuildResult) -> tuple[list[str], list[str]]:
        """
        Inspect the build for deployability problems.

        Returns (issues, failed_backend_paths):
          issues              — human-readable problem descriptions
          failed_backend_paths — backend files whose import/debug check failed,
                                 i.e. the files worth re-repairing

        These are exactly the checks the old _assert_deployable() gate used —
        the difference is that finding a problem now starts a repair pass
        instead of throwing the whole build away.
        """
        issues:      list[str] = []
        failed_paths: list[str] = []

        failed_debug = [
            r for r in result.debug_results
            if not getattr(r, "success", False)
        ]
        if failed_debug:
            failed_paths = [
                getattr(r, "file_path", "") for r in failed_debug
                if getattr(r, "file_path", "")
            ]
            preview = ", ".join(getattr(r, "file_path", "?") for r in failed_debug[:5])
            issues.append(
                f"{len(failed_debug)}/{len(result.debug_results)} backend file(s) "
                f"fail import/debug verification: {preview}"
            )

        frontend_failures = [
            r for r in result.frontend_debug_results
            if not getattr(r, "success", True) and not getattr(r, "skipped", False)
        ]
        if frontend_failures:
            preview = ", ".join(getattr(r, "file_path", "?") for r in frontend_failures[:5])
            issues.append(
                f"Frontend/TypeScript validation failed for "
                f"{len(frontend_failures)} file(s): {preview}"
            )

        executable_tests = [
            r for r in result.test_results
            if not getattr(r, "skipped", False) and getattr(r, "tests_generated", 0) > 0
        ]
        failed_tests = [
            r for r in executable_tests
            if getattr(r, "passed", 0) < getattr(r, "tests_generated", 0)
        ]
        if not executable_tests and result.backend_files:
            issues.append(
                "No executable backend tests were generated — the code is unverified."
            )
        if failed_tests:
            preview = ", ".join(
                f"{getattr(r, 'file_path', '?')} "
                f"({getattr(r, 'passed', 0)}/{getattr(r, 'tests_generated', 0)})"
                for r in failed_tests[:5]
            )
            issues.append(
                f"Generated tests fail for {len(failed_tests)} file(s): {preview}"
            )

        return issues, failed_paths

    # ── Phase 21.1: deterministic output audit (no LLM, no quota cost) ────────
    #
    # The import/debug gate runs each file with `python <file>`, which only
    # executes MODULE-LEVEL code. Three whole classes of defect sail past it:
    #
    #   1. Imports inside function bodies — a route handler doing
    #      `from weather import get_weather` never executes at import time, so
    #      the file "passes" debug and then 500s on the first request.
    #   2. Architect placeholder files that no generator ever filled in; they
    #      keep their "will be generated by the code generation agents" stub.
    #   3. Frontend relative imports (./TodoList) pointing at files that were
    #      never generated. Plain-JS projects get NO tsc validation at all, so
    #      nothing else in the pipeline looks at them.
    #
    # These are reported as advisory issues: they mark the build degraded and
    # are listed in SESSION_CONTEXT.md, but they do NOT drive extra LLM repair
    # passes, because re-running the debugger cannot fix them.

    _PLACEHOLDER_MARKER = "will be generated by the code generation agents"
    _TODO_MARKERS       = ("TODO:", "TO DO:", "TODO ", "TO DO ")
    _JS_EXTS            = (".js", ".jsx", ".ts", ".tsx", ".mjs")

    def _audit_generated_output(self, result: BuildResult) -> list[str]:
        """Static audit of what was actually written to disk. Never raises."""
        issues: list[str] = []
        root = result.architecture.get("root_folder", "")
        if not root:
            return issues

        try:
            import config
            project_dir = Path(config.OUTPUT_DIR) / root
            if not project_dir.exists():
                return issues
        except Exception:
            return issues

        try:
            issues.extend(self._audit_placeholders(project_dir))
        except Exception as e:
            logger.warning(f"  ⚠️  Placeholder audit failed: {e}")
        try:
            issues.extend(self._audit_python_imports(project_dir))
        except Exception as e:
            logger.warning(f"  ⚠️  Python import audit failed: {e}")
        try:
            issues.extend(self._audit_js_imports(project_dir))
        except Exception as e:
            logger.warning(f"  ⚠️  Frontend import audit failed: {e}")
        try:
            issues.extend(self._audit_stub_functions(project_dir))
        except Exception as e:
            logger.warning(f"  ⚠️  Stub-function audit failed: {e}")

        return issues

    def _iter_project_files(self, project_dir: Path, suffixes: tuple):
        SKIP = {"__pycache__", "node_modules", ".git", "venv", ".venv",
                "dist", ".pytest_cache", "tests"}
        for p in project_dir.rglob("*"):
            if not p.is_file() or p.suffix not in suffixes:
                continue
            if any(part in SKIP for part in p.parts):
                continue
            yield p

    def _audit_placeholders(self, project_dir: Path) -> list[str]:
        """Architect scaffold files that no generator ever filled in."""
        stubs = []
        for p in self._iter_project_files(project_dir, (".py", ".sql", ".txt", ".md", ".json")):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if self._PLACEHOLDER_MARKER in text:
                stubs.append(str(p.relative_to(project_dir)).replace("\\", "/"))
        if not stubs:
            return []
        return [
            f"{len(stubs)} planned file(s) were never filled in and still contain "
            f"the scaffold placeholder: {', '.join(sorted(stubs)[:6])}"
        ]

    def _audit_python_imports(self, project_dir: Path) -> list[str]:
        """
        Imports of modules that are neither local files, stdlib, nor installed.
        Catches function-body imports the module-level import check cannot see.
        """
        import ast
        import importlib.util
        import sys as _sys

        py_files = list(self._iter_project_files(project_dir, (".py",)))
        if not py_files:
            return []

        # Every module name that resolves locally (file stems + package dirs)
        local: set[str] = set()
        for p in project_dir.rglob("*.py"):
            local.add(p.stem)
        for p in project_dir.rglob("*"):
            if p.is_dir():
                local.add(p.name)

        stdlib = getattr(_sys, "stdlib_module_names", frozenset())
        phantom: dict[str, str] = {}

        for p in py_files:
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            rel = str(p.relative_to(project_dir)).replace("\\", "/")

            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:      # relative import — different failure mode
                        continue
                    if node.module:
                        names = [node.module.split(".")[0]]

                for name in names:
                    if not name or name in local or name in stdlib:
                        continue
                    if name in phantom:
                        continue
                    try:
                        if importlib.util.find_spec(name) is not None:
                            continue        # genuinely installed
                    except Exception:
                        pass                # unresolvable → treat as phantom
                    phantom[name] = rel

        if not phantom:
            return []
        preview = ", ".join(f"`{m}` (in {f})" for m, f in sorted(phantom.items())[:5])
        return [
            f"{len(phantom)} import(s) reference modules that do not exist locally "
            f"and are not installed: {preview}. Imports inside function bodies do "
            f"not run during the import check, so these fail only at request time."
        ]

    def _audit_js_imports(self, project_dir: Path) -> list[str]:
        """Relative frontend imports pointing at files that were never generated."""
        import re as _re

        pattern = _re.compile(
            r"""(?:from\s+|require\(\s*)['"](\.{1,2}/[^'"]+)['"]"""
        )
        missing: list[str] = []

        for p in self._iter_project_files(project_dir, self._JS_EXTS):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel_file = str(p.relative_to(project_dir)).replace("\\", "/")

            for spec in pattern.findall(text):
                target = (p.parent / spec).resolve()
                if target.exists() and target.is_file():
                    continue
                found = False
                for ext in self._JS_EXTS:
                    if target.with_suffix(ext).exists():
                        found = True
                        break
                    if (target / f"index{ext}").exists():
                        found = True
                        break
                if not found:
                    missing.append(f"`{spec}` (in {rel_file})")

        if not missing:
            return []
        return [
            f"{len(missing)} frontend import(s) point at files that were never "
            f"generated: {', '.join(sorted(set(missing))[:5])}. The frontend will "
            f"not build until these exist."
        ]

    def _audit_stub_functions(self, project_dir: Path) -> list[str]:
        """Route/service functions whose body is still a TODO placeholder."""
        import ast

        stubs: list[str] = []
        for p in self._iter_project_files(project_dir, (".py",)):
            try:
                source = p.read_text(encoding="utf-8", errors="ignore")
                tree   = ast.parse(source)
            except Exception:
                continue
            rel = str(p.relative_to(project_dir)).replace("\\", "/")

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                try:
                    segment = ast.get_source_segment(source, node) or ""
                except Exception:
                    continue
                if any(m in segment for m in self._TODO_MARKERS):
                    stubs.append(f"{rel}:{node.name}()")

        if not stubs:
            return []
        return [
            f"{len(stubs)} function(s) are unimplemented TODO stubs: "
            f"{', '.join(sorted(stubs)[:6])}"
        ]

    # ── Phase 22: runtime smoke test (no LLM, no quota cost) ──────────────────

    def _smoke_test_runtime(self, result: BuildResult) -> list[str]:
        """
        Boot the generated app and call every route it declares.

        This is the first check in the pipeline that asks the user's question —
        "does the app respond?" — rather than "does the file import?". The
        todo_app build passed debug 3/3 with an endpoint that raised on every
        request, because the offending import sat inside a handler body and
        nothing ever sent a request.

        Findings are advisory: they mark the build degraded and are written into
        SESSION_CONTEXT.md. Never raises.
        """
        root = result.architecture.get("root_folder", "")
        if not root:
            return []

        try:
            from tools.runtime_smoke import smoke_test_app
            smoke = smoke_test_app(root)
        except Exception as e:
            logger.warning(f"  ⚠️  Runtime smoke test failed to run: {e}")
            return []

        # Record it on the build so the documenter and API can report it.
        try:
            result.smoke_summary = smoke.summary()
        except Exception:
            pass

        if not smoke.ran or not smoke.entry:
            logger.info("  ℹ️  Runtime smoke test skipped (no FastAPI entry point)")
            return []

        if not smoke.app_loaded:
            logger.warning(f"  🚨 App failed to boot: {smoke.error[:200]}")
            return [
                f"the application does not start: {smoke.error[:200]}. "
                f"Every endpoint is unreachable."
            ]

        if not smoke.probes:
            return []

        logger.info(f"  🔥 Runtime smoke test: {smoke.summary()}")
        for probe in smoke.probes:
            mark = "✅" if probe.ok else "🚨"
            logger.info(f"     {mark} {probe.method:6} {probe.path} → {probe.status}")

        failures = smoke.failures
        if not failures:
            return []

        detail = ", ".join(
            f"{p.method} {p.path} → {p.status or 'no response'}" for p in failures[:5]
        )
        return [
            f"{len(failures)} of {smoke.total} endpoint(s) return a server error when "
            f"called: {detail}. These fail at request time, which the import check "
            f"cannot see."
        ]

    def _quota_available(self) -> bool:
        """True when at least one Groq model still has usable daily quota."""
        try:
            import llm_client
            return not llm_client.is_quota_exhausted()
        except Exception:
            return True   # can't tell → assume yes, the call itself will decide

    def _retest_files(self, result: BuildResult, paths: list[str]) -> None:
        """
        Re-run the tester over `paths` only, merging the fresh TestResults into
        result.test_results by file_path.

        Scoping the re-test to repaired files is what keeps remediation
        affordable: the tester spends up to MAX_TEST_FIXES LLM calls per file,
        so re-testing untouched files reproduces known failures at full cost.
        Results for untouched files are preserved so the aggregate test score
        still reflects the entire project.
        """
        fresh = self.tester.run(
            paths,
            result.architecture,
            debug_results=result.debug_results,
        )

        by_path = {
            getattr(r, "file_path", ""): r
            for r in result.test_results
        }
        for r in fresh:
            key = getattr(r, "file_path", "")
            # The tester appends a synthetic "frontend/" entry for Vitest runs.
            # Keep whichever entry we already had unless this pass produced a
            # real result for the same key.
            if key:
                by_path[key] = r
        result.test_results = list(by_path.values())

    def _refine_and_remediate(self, result: BuildResult) -> RemediationReport:
        """
        Self-healing refinement pass. Replaces the old _assert_deployable() gate.

        NEVER raises (except GroqDailyQuotaError, which run() intercepts) — a
        build that produced code always proceeds to documentation and packaging.

        Strategy:
          1. Diagnose (repairable) + audit (advisory, static). Both clean →
             return immediately, the build stays `done`.
          2. Deterministic repair (free, no LLM): structural import surgery.
          3. Quota gate: if the daily quota is dead, stop here — spending the
             last tokens on repair would starve the handoff document.
          4. Up to REMEDIATION_MAX_PASSES LLM-backed passes: re-debug the failed
             files, then re-test ONLY those files so scores stay honest without
             paying to reproduce known failures.
          5. Report whatever is still broken.
        """
        report = RemediationReport()

        issues, failed_paths = self._diagnose(result)

        # Static audit runs even when verification is clean: the todo_app build
        # scored debug 3/3 while shipping a function-body import of a module
        # that was never generated, placeholder files, and dangling frontend
        # imports. None of that is visible to the import/test gates.
        advisory = self._audit_generated_output(result)

        # Phase 22: actually run the app. Static analysis cannot tell a handler
        # that works from one that raises the moment a request arrives.
        advisory = advisory + self._smoke_test_runtime(result)

        if not issues and not advisory:
            logger.info("✅ Verification clean — no remediation needed")
            return report

        report.ran = True
        if issues:
            logger.warning(
                f"🩺 Verification found {len(issues)} repairable issue(s) — starting "
                f"self-healing refinement instead of failing the build:"
            )
            for issue in issues:
                logger.warning(f"    • {issue}")
        if advisory:
            logger.warning(
                f"🔍 Static audit found {len(advisory)} issue(s) the repair passes "
                f"cannot fix (they will be documented, not retried):"
            )
            for issue in advisory:
                logger.warning(f"    • {issue}")

        self._emit_progress(8, "remediation", "running", {
            "issues":       issues,
            "advisory":     advisory,
            "failed_files": failed_paths,
        })

        # Advisory-only: nothing an LLM repair pass can act on. Mark the build
        # degraded so the handoff document is written, and spend zero tokens.
        if not issues:
            report.unresolved = advisory
            report.degraded   = True
            logger.warning(
                "  📋 No repairable verification failures — recording the static "
                "audit findings and skipping LLM repair entirely (0 tokens spent)"
            )
            self._emit_progress(8, "remediation", "done", {
                "passes":     0,
                "llm_used":   False,
                "degraded":   True,
                "unresolved": report.unresolved,
                "reason":     "advisory_only",
            })
            return report

        # ── Step 2: deterministic structural repair (always, costs nothing) ───
        if failed_paths:
            try:
                # Must be given the WHOLE file set, not just the failing ones:
                # the repair derives "which module names are local" from the
                # paths it receives. Passing only failed_paths made it blind to
                # sibling modules, so it silently repaired nothing.
                repairs = self.debugger._apply_structural_import_repairs(
                    result.backend_files or failed_paths
                )
                if repairs:
                    report.repaired_files.extend(failed_paths)
                    logger.info(
                        f"  🔧 Structural repair applied {len(repairs)} fix(es) "
                        f"across {len(failed_paths)} file(s)"
                    )
            except Exception as e:
                logger.warning(f"  ⚠️  Structural repair pass failed (non-fatal): {e}")

        # Forbidden files can reappear if a repair rewrote a file wholesale.
        root = result.architecture.get("root_folder", "project")
        try:
            purged = self._purge_forbidden_files(root)
            if purged:
                logger.warning(f"  🗑️  Purged {len(purged)} forbidden file(s) during remediation")
        except Exception as e:
            logger.warning(f"  ⚠️  Forbidden-file purge during remediation failed: {e}")

        # ── Step 3: quota gate ────────────────────────────────────────────────
        if not self._quota_available():
            report.unresolved = list(issues) + list(advisory)
            report.degraded   = True
            logger.warning(
                "  🔑 LLM quota exhausted — skipping LLM repair passes. "
                "Structural repairs applied; remaining issues documented."
            )
            self._emit_progress(8, "remediation", "done", {
                "passes":     report.passes,
                "llm_used":   False,
                "degraded":   True,
                "unresolved": report.unresolved,
                "reason":     "quota_exhausted",
            })
            return report

        # ── Step 4: LLM-backed repair passes ──────────────────────────────────
        #
        # COST NOTE (Phase 21.1): this loop used to re-run the tester over EVERY
        # backend file on every pass. Because the tester regenerates each test
        # file from scratch and allows MAX_TEST_FIXES LLM retries per file, a
        # 3-file backend cost up to ~27 extra LLM round-trips per pass — twice.
        # That is how a single build could drain a day of free-tier quota while
        # fixing nothing, since the failures were structural (bad mock patterns)
        # rather than something more retries could resolve.
        #
        # We now re-test ONLY the files this pass actually repaired, and merge
        # those results into the existing set so the overall score still covers
        # the whole project.
        for attempt in range(1, REMEDIATION_MAX_PASSES + 1):
            report.passes  = attempt
            report.llm_used = True
            logger.info(f"  🔁 Remediation pass {attempt}/{REMEDIATION_MAX_PASSES}")

            repaired_this_pass: list[str] = []

            try:
                if failed_paths:
                    fresh = self.debugger.run(failed_paths)
                    # Merge the fresh results over the stale ones so the DB
                    # scores reflect the repaired state, not the pre-repair one.
                    by_path = {
                        getattr(r, "file_path", ""): r
                        for r in result.debug_results
                    }
                    for r in fresh:
                        by_path[getattr(r, "file_path", "")] = r
                        if getattr(r, "success", False):
                            fp = getattr(r, "file_path", "")
                            if fp:
                                repaired_this_pass.append(fp)
                                if fp not in report.repaired_files:
                                    report.repaired_files.append(fp)
                    result.debug_results = list(by_path.values())

                # Only re-test what changed. If the debugger repaired nothing,
                # re-testing would produce identical failures at full token cost.
                if repaired_this_pass:
                    self._retest_files(result, repaired_this_pass)
                else:
                    logger.info(
                        "  ⏭️  No files were repaired this pass — skipping re-test "
                        "(re-running it would spend tokens to reproduce the same failures)"
                    )
            except GroqDailyQuotaError:
                # Quota died mid-repair. Let run() intercept it and write the
                # handoff document — the partial repairs above are kept.
                raise
            except Exception as e:
                logger.warning(f"  ⚠️  Remediation pass {attempt} failed (non-fatal): {e}")
                break

            # Nothing improved and nothing to re-test → further passes are a
            # guaranteed no-op. Stop rather than burning the remaining budget.
            if not repaired_this_pass:
                logger.warning(
                    "  🛑 Remediation made no progress this pass — stopping early "
                    "instead of repeating identical LLM work"
                )
                break

            issues, failed_paths = self._diagnose(result)
            if not issues:
                logger.info(f"  ✅ Remediation resolved all issues on pass {attempt}")
                break

            if not self._quota_available():
                logger.warning("  🔑 Quota exhausted mid-remediation — stopping repair passes")
                break

        # Re-run the static audit: repairs may have introduced or resolved
        # phantom imports, and the report must describe the FINAL state on disk.
        advisory = self._audit_generated_output(result)

        report.unresolved = list(issues) + list(advisory)
        report.degraded   = bool(report.unresolved)

        if report.unresolved:
            logger.warning(
                f"  ⚠️  {len(report.unresolved)} issue(s) remain after remediation — "
                "build will complete with a diagnostic context file "
                "(no code is discarded)"
            )
        self._emit_progress(8, "remediation", "done", {
            "passes":         report.passes,
            "llm_used":       report.llm_used,
            "degraded":       report.degraded,
            "repaired_files": report.repaired_files,
            "unresolved":     report.unresolved,
        })
        return report

    def run(self, user_prompt: str) -> BuildResult:
        try:
            import llm_client
            llm_client.set_current_build_id(self.build_id)
        except Exception:
            pass

        result = BuildResult(user_prompt=user_prompt, build_id=self.build_id)

        # ── Step definitions ──────────────────────────────────────────────────
        steps_def = [
            (1, "intent_analyzer",
             lambda: self.intent_analyzer.run(user_prompt)),

            (2, "planner",
             lambda: self.planner.run(result.intent)),

            (3, "architect",
             # Phase 20.1: pass build_id for isolated output directory
             lambda: self.architect.run(result.intent, result.steps, build_id=self.build_id)),

            (4, "backend_developer",
             lambda: self.backend_developer.run(result.intent, result.architecture)),

            (5, "frontend_generator",
             lambda: self.frontend_generator.run(result.intent, result.architecture)),

            # Phase 19.3: TypeScript validation step (internal substep at slot 5)
            (5, "frontend_debugger",
             lambda: self.frontend_debugger.run(
                 result.architecture.get("root_folder", "project"),
                 result.frontend_files,
             )),

            (6, "debugger",
             lambda: self.debugger.run(result.backend_files)),

            (7, "reviewer",
             lambda: self.reviewer.run(result.backend_files)),

            (8, "tester",
             # Phase 20.2: pass ALL debug_results (not just passed files)
             lambda: self.tester.run(
                 result.backend_files,
                 result.architecture,
                 debug_results=result.debug_results,
             )),

            (9, "documenter",
             lambda: self.documenter.run(
                 result.intent,
                 result.architecture,
                 result.backend_files,
                 review_results=result.review_results,
             )),
        ]

        result_attr_map = {
            (1, "intent_analyzer"):    "intent",
            (2, "planner"):            "steps",
            (3, "architect"):          "architecture",
            (4, "backend_developer"):  "backend_files",
            (5, "frontend_generator"): "frontend_files",
            (5, "frontend_debugger"):  "frontend_debug_results",
            (6, "debugger"):           "debug_results",
            (7, "reviewer"):           "review_results",
            (8, "tester"):             "test_results",
            (9, "documenter"):         "doc_result",
        }

        # Phase 21: human-readable step labels for the handoff document.
        step_labels = [f"{num}. {name}" for (num, name, _) in steps_def]
        completed_labels: list[str] = []

        # Set when the loop stops early but usable code exists. Both cases end
        # as a packaged build with a SESSION_CONTEXT.md rather than a bare failure.
        quota_stop: Optional[GroqDailyQuotaError] = None
        failure_stop: Optional[Exception]         = None

        try:
            for (step_num, step_name, fn) in steps_def:

                # ── Cooperative cancellation ──────────────────────────────────
                if self._cancel_check():
                    logger.info(
                        f"🚫 Build {self.build_id[:8]} cancelled before "
                        f"step {step_num} ({step_name})"
                    )
                    raise PipelineCancelledError(
                        f"Cancelled before step {step_num} ({step_name})"
                    )

                result.current_step = step_num
                step_start          = datetime.now()

                self._emit_progress(step_num, step_name, "running")
                logger.info(f"🔄 [{step_num}/9] {step_name}…")

                try:
                    val = self._run_step_with_timeout(step_num, step_name, fn)

                    attr = result_attr_map.get((step_num, step_name))
                    if attr:
                        setattr(result, attr, val)

                    # Phase 20.3: purge forbidden files after backend generation
                    if step_name == "backend_developer":
                        root = result.architecture.get("root_folder", "project")
                        deleted = self._purge_forbidden_files(root)
                        if deleted:
                            logger.warning(
                                f"🗑️  Purged {len(deleted)} forbidden file(s) "
                                f"after backend generation: {deleted}"
                            )
                            # BUG FIX v2.2.1 (Gap A): use forward-slash normalised
                            # strings for comparison so this works on Windows too.
                            # Old code:  str(Path(root) / d)  → uses OS separator
                            # New code:  f"{root}/{d}".replace("\\", "/")  → always /
                            if result.backend_files:
                                purged_set = {
                                    f"{root}/{d}".replace("\\", "/")
                                    for d in deleted
                                }
                                result.backend_files = [
                                    f for f in result.backend_files
                                    if f.replace("\\", "/") not in purged_set
                                ]

                    elapsed   = round((datetime.now() - step_start).total_seconds(), 1)
                    step_data = self._build_step_data(step_name, val)
                    step_data["elapsed_seconds"] = elapsed

                    self._emit_progress(step_num, step_name, "done", step_data)
                    logger.info(f"✅ [{step_num}/9] {step_name} done in {elapsed}s")

                    completed_labels.append(f"{step_num}. {step_name}")

                    # Phase 21: the old hard gate lived here and raised
                    # PipelineVerificationError, aborting the build before the
                    # documenter ever ran. It now repairs what it can and
                    # records what it cannot.
                    if step_name == "tester":
                        result.remediation = self._refine_and_remediate(result)
                        if result.remediation.degraded:
                            result.degraded = True
                        else:
                            logger.info(
                                "Deployable-build check passed: imports/debug/tests verified"
                            )

                except PipelineCancelledError:
                    raise

                # ── Phase 21: quota interception ──────────────────────────────
                except GroqDailyQuotaError as quota_exc:
                    elapsed = round((datetime.now() - step_start).total_seconds(), 1)
                    self._emit_progress(step_num, step_name, "failed", {
                        "error":           str(quota_exc),
                        "error_type":      "GroqDailyQuotaError",
                        "quota_exhausted": True,
                        "elapsed_seconds": elapsed,
                    })
                    logger.error(
                        f"🔑 [{step_num}/9] {step_name} stopped after {elapsed}s: "
                        f"LLM daily quota exhausted. Packaging work-in-progress "
                        f"with a handoff document instead of failing the build."
                    )
                    quota_stop = quota_exc
                    break

                except Exception as exc:
                    elapsed = round((datetime.now() - step_start).total_seconds(), 1)
                    tb      = traceback.format_exc()

                    self._emit_progress(step_num, step_name, "failed", {
                        "error":           str(exc),
                        "error_type":      type(exc).__name__,
                        "traceback":       tb[-1000:],
                        "elapsed_seconds": elapsed,
                        "timed_out":       isinstance(exc, TimeoutError),
                    })
                    logger.error(
                        f"💥 [{step_num}/9] {step_name} failed after {elapsed}s: {exc}"
                    )

                    # Phase 19.3: frontend_debugger failure is non-fatal
                    if step_name == "frontend_debugger":
                        logger.warning(
                            "⚠️  FrontendDebugger failed — continuing without TS fixes"
                        )
                        continue

                    # Phase 21: if real code already exists on disk, a later-step
                    # crash must not discard it. Package it with a diagnostic
                    # document instead. Only a failure before any code was
                    # generated is a genuine `failed` build.
                    if result.backend_files:
                        failure_stop = exc
                        break

                    raise

            # ── Finalisation ──────────────────────────────────────────────────
            result.completed_steps = completed_labels
            result.pending_steps   = [
                lbl for lbl in step_labels if lbl not in completed_labels
            ]
            result.progress_percent = round(
                100.0 * len(completed_labels) / max(1, len(step_labels)), 1
            )

            if quota_stop is not None:
                self._finalise_with_context(
                    result,
                    reason       = "quota_exhausted",
                    error_detail = str(quota_stop),
                    quota_error  = quota_stop,
                )
                result.quota_paused      = True
                result.degraded          = True
                result.completion_reason = (
                    f"LLM daily quota exhausted during step "
                    f"{result.current_step} ({result.progress_percent:.0f}% complete). "
                    f"Generated files packaged with SESSION_CONTEXT.md."
                )
                result.complete(success=True)

            elif failure_stop is not None:
                self._finalise_with_context(
                    result,
                    reason       = "step_failed",
                    error_detail = f"{type(failure_stop).__name__}: {failure_stop}",
                )
                result.degraded          = True
                result.error             = str(failure_stop)
                result.completion_reason = (
                    f"Step {result.current_step} failed "
                    f"({type(failure_stop).__name__}), but generated code was "
                    f"packaged with SESSION_CONTEXT.md."
                )
                result.complete(success=True)

            elif result.degraded:
                self._finalise_with_context(
                    result,
                    reason       = "remediation_incomplete",
                    error_detail = "",
                )
                unresolved = result.remediation.unresolved if result.remediation else []
                result.completion_reason = (
                    f"Build completed with {len(unresolved)} unresolved "
                    f"verification issue(s) after automatic repair. "
                    f"See SESSION_CONTEXT.md."
                )
                result.complete(success=True)

            else:
                result.completion_reason = ""
                result.complete(success=True)

        except PipelineCancelledError:
            result.cancelled = True
            result.complete(success=False)

        except Exception as e:
            result.error = str(e)
            result.complete(success=False)
            logger.error(
                f"💥 Pipeline failed at step {result.current_step}: {e}",
                exc_info=True,
            )

        return result

    # ── Phase 21: graceful finalisation ───────────────────────────────────────

    def _finalise_with_context(
        self,
        result:       BuildResult,
        reason:       str,
        error_detail: str = "",
        quota_error:  Optional[Exception] = None,
    ) -> None:
        """
        Package an interrupted or degraded build: purge forbidden files, write
        the normal docs if quota allows, and always write SESSION_CONTEXT.md.

        Never raises — this is the last thing standing between the user and
        losing their generated code.
        """
        root = result.architecture.get("root_folder", "project")

        try:
            purged = self._purge_forbidden_files(root)
            if purged:
                logger.warning(f"🗑️  Purged {len(purged)} forbidden file(s) before packaging")
        except Exception as e:
            logger.warning(f"⚠️  Final forbidden-file purge failed: {e}")

        # Quota snapshot + structured error details for the handoff document.
        quota_snapshot: dict = {}
        try:
            import llm_client
            quota_snapshot = llm_client.get_quota_snapshot()
        except Exception as e:
            logger.warning(f"⚠️  Could not capture quota snapshot: {e}")

        if quota_error is not None and hasattr(quota_error, "details"):
            try:
                result.quota_details = quota_error.details()
            except Exception:
                result.quota_details = {"message": str(quota_error)}

        # README/SETUP need the LLM — only attempt them when quota remains and
        # the documenter step did not already run.
        if result.doc_result is None and self._quota_available():
            try:
                logger.info("📝 Running documenter before packaging the partial build…")
                result.doc_result = self.documenter.run(
                    result.intent,
                    result.architecture,
                    result.backend_files,
                    review_results=result.review_results,
                )
                self._emit_progress(9, "documenter", "done", {"partial": True})
            except Exception as e:
                logger.warning(f"⚠️  Documenter failed during finalisation (non-fatal): {e}")

        # SESSION_CONTEXT.md — the template path makes no LLM calls, so this
        # works even when every key is dead. This is the whole point of Phase 21.
        try:
            self._emit_progress(9, "session_context", "running", {"reason": reason})
            path = self.documenter.generate_session_context(
                intent           = result.intent,
                architecture     = result.architecture,
                backend_files    = result.backend_files,
                frontend_files   = result.frontend_files,
                completed_steps  = result.completed_steps,
                pending_steps    = result.pending_steps,
                reason           = reason,
                quota_snapshot   = quota_snapshot,
                remediation      = result.remediation,
                progress_percent = result.progress_percent,
                debug_results    = result.debug_results,
                review_results   = result.review_results,
                test_results     = result.test_results,
                error_detail     = error_detail,
            )
            result.session_context_path = path
            self._emit_progress(9, "session_context", "done", {
                "path":             path,
                "reason":           reason,
                "progress_percent": result.progress_percent,
            })
            logger.info(f"📄 Handoff document written: {path}")
        except Exception as e:
            logger.error(f"❌ Could not write SESSION_CONTEXT.md: {e}", exc_info=True)
            self._emit_progress(9, "session_context", "failed", {"error": str(e)})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    def on_progress(progress):
        status  = progress["status"]
        step    = progress["step"]
        name    = progress["step_name"]
        data    = progress.get("data", {})
        elapsed = data.get("elapsed_seconds", "?")
        if status == "failed":
            print(f"  ❌ [{step}/9] {name}: FAILED — {data.get('error', '?')} ({elapsed}s)")
        elif status == "done":
            print(f"  ✅ [{step}/9] {name}: done ({elapsed}s)")
        else:
            print(f"  🔄 [{step}/9] {name}: {status}")

    pipeline = Pipeline(progress_callback=on_progress)
    result   = pipeline.run("Build a weather dashboard")
    print(result.summary())
