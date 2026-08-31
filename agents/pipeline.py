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
import difflib
import logging
import os
import re
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
    # Real findings that do NOT mean the build is broken: the artifact was
    # executed and works, but something about it could not be verified
    # automatically and is worth a human's attention. A failing generated test
    # suite is the case this exists for — the app serves 7/7 routes, and its
    # shipped tests do not run. Reporting that as a build defect would call a
    # working build degraded; dropping it would hide a real problem. It is
    # handed to the user as manual testing instead.
    manual_checks:  list = field(default_factory=list)
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

    # What every shape verifier actually did, as VerificationOutcome dicts.
    # `smoke_summary` was set here and read only by main.py's CLI table — it
    # never reached the database or any API route, which is why the matrix
    # driver has to grep server.log and has never been able to evaluate the
    # second half of its own pass criterion ("0 5xx from the smoke test").
    verification_outcomes:    list  = field(default_factory=list)
    build_shape:              str   = ""   # "web_api+cli", from tools/build_shape

    # The artifact does not run at all — see Pipeline._functional_verdict.
    # Distinct from `degraded`, which means "usable, but read the notes".
    unusable:                 bool  = False
    unusable_reasons:         list  = field(default_factory=list)

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

        Returns (issues, failed_backend_paths, advisory):
          issues              — problems a repair pass can actually act on
          failed_backend_paths — the files to aim those repairs at
          advisory            — problems that are real but that no repair pass
                                in this pipeline can fix

        The third element exists because the split was wrong. Three of the four
        problems this used to return as "repairable" contributed no paths, so
        remediation announced a repair, found nothing to repair, logged "made no
        progress", and degraded the build. Saying a thing is repairable and then
        not repairing it is worse than calling it advisory: it costs a pass and
        it misleads the reader.

        These are exactly the checks the old _assert_deployable() gate used —
        the difference is that finding a problem now starts a repair pass
        instead of throwing the whole build away.
        """
        issues:      list[str] = []
        failed_paths: list[str] = []
        advisory:    list[str] = []

        # Findings that are about the suite the build SHIPS rather than about
        # the application it built. They are produced here, and they are still
        # returned as ordinary issues, so the tester keeps driving repair — a
        # failing test is often the only sign that the code under test is
        # wrong, and that is worth the tokens.
        #
        # What changes is the ENDING. If, after the whole build has been
        # verified, the suite still does not run, that is not a defect in a
        # working application; it is something the user should check by hand.
        # The final re-audit routes these accordingly.
        self._test_suite_issues = []

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

        # What self-verification tried to repair and could not. It named the
        # file, held the defect list, and threw both away into a counter — so
        # the build shipped defects that a pass had already identified, and
        # remediation never heard about them. This IS repairable: the file is
        # right there.
        # Re-check against disk before reporting. These were recorded during
        # generation and the debugger runs after; row 2 shipped a checklist
        # telling the user to fix `bookmark.description` that the debugger had
        # already fixed, while `schema_attr` verified the same build clean.
        # `_diagnose` runs again in the final re-audit, so this is also what
        # keeps the shipped SESSION_CONTEXT.md honest.
        bd = getattr(self, "backend_developer", None)
        if bd is not None and getattr(bd, "unrepaired_defects", None):
            try:
                bd.rescan_unrepaired_defects(
                    result.architecture or {},
                    (result.architecture or {}).get("root_folder", ""),
                    list(result.backend_files or []),
                )
            except Exception as e:
                logger.warning(f"  ⚠️  unrepaired-defect re-scan skipped: {e}")

        unrepaired = dict(
            getattr(bd, "unrepaired_defects", {}) or {}
        )
        if unrepaired:
            failed_paths.extend(p for p in unrepaired if p not in failed_paths)
            preview = "; ".join(
                f"{path} ({defects[0][:80]})" if defects else path
                for path, defects in list(unrepaired.items())[:3]
            )
            issues.append(
                f"self-verification could not repair {len(unrepaired)} "
                f"file(s): {preview}"
            )

        # Frontend/TypeScript failures are NOT repairable here and never were.
        # They were announced as repairable, contributed nothing to
        # `failed_paths`, and so drove a remediation pass that found nothing to
        # do and then degraded the build — the commonest route to
        # done_with_context. The Python debugger cannot fix a .tsx file, and
        # agents/frontend_debugger.py has already spent its own attempts on it.
        # Reporting it honestly as advisory costs a user nothing and saves a
        # wasted pass.
        frontend_failures = [
            r for r in result.frontend_debug_results
            if not getattr(r, "success", True) and not getattr(r, "skipped", False)
        ]
        if frontend_failures:
            preview = ", ".join(getattr(r, "file_path", "?") for r in frontend_failures[:5])
            advisory.append(
                f"Frontend/TypeScript validation failed for "
                f"{len(frontend_failures)} file(s), and no later pass can repair "
                f"them: {preview}"
            )

        executable_tests = [
            r for r in result.test_results
            if not getattr(r, "skipped", False) and getattr(r, "tests_generated", 0) > 0
        ]
        failed_tests = [
            r for r in executable_tests
            if getattr(r, "passed", 0) < getattr(r, "tests_generated", 0)
        ]
        # Also advisory: no repair pass generates tests, so announcing this as
        # repairable guaranteed a pass that could do nothing about it.
        if not executable_tests and result.backend_files:
            _no_tests = (
                "No executable backend tests were generated, so the code is "
                "unverified by tests."
            )
            advisory.append(_no_tests)
            self._test_suite_issues.append(_no_tests)

        # This one IS repairable, and was the only one of the three that had a
        # file to aim at — it just never supplied it. A failing test usually
        # means the code under test is wrong, and `TestResult.file_path` names
        # that file, so hand it to the debugger instead of reporting the
        # failure and stopping.
        if failed_tests:
            preview = ", ".join(
                f"{getattr(r, 'file_path', '?')} "
                f"({getattr(r, 'passed', 0)}/{getattr(r, 'tests_generated', 0)})"
                for r in failed_tests[:5]
            )
            _test_issue = (
                f"Generated tests fail for {len(failed_tests)} file(s): {preview}"
            )
            issues.append(_test_issue)
            self._test_suite_issues.append(_test_issue)
            for r in failed_tests:
                fp = getattr(r, "file_path", "")
                if not fp or fp in failed_paths:
                    continue
                # `file_path` is the SOURCE file the test covers, and handing it
                # to the debugger is only useful if the source is what broke.
                # When every failure was raised inside the test itself — a
                # fixture calling .close() on the None that init_db() returned —
                # there is nothing in the source to repair, and the pass would
                # rewrite a file that was never wrong.
                #
                # Anything ambiguous (an assertion, or output that could not be
                # parsed) leaves this False and the file is repaired as before.
                if getattr(r, "all_test_defects", False):
                    logger.info(
                        f"  🧭 {fp}: not repairing — {getattr(r, 'blame_summary', '')} "
                        f"(the defect is in the test, which the tester repairs)"
                    )
                    continue
                failed_paths.append(fp)

        return issues, failed_paths, advisory

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

    # Files a LATER step owns. This audit runs during remediation (step 8) and
    # the documenter does not write until step 9, so flagging these is auditing
    # the future: the claim is guaranteed true here and guaranteed false by the
    # time SESSION_CONTEXT.md states it. Row 3 was degraded to
    # done_with_context over a README the documenter then filled in with 46
    # lines, and told the user to "Implement README.md". A documenter that
    # genuinely fails is already propagated as a build failure, so nothing is
    # hidden by waiting for it.
    _WRITTEN_BY_A_LATER_STEP = {"README.md", "SETUP.md"}

    def _audit_placeholders(self, project_dir: Path) -> list[str]:
        """Architect scaffold files that no generator ever filled in."""
        stubs = []
        for p in self._iter_project_files(project_dir, (".py", ".sql", ".txt", ".md", ".json")):
            rel = str(p.relative_to(project_dir)).replace("\\", "/")
            if rel in self._WRITTEN_BY_A_LATER_STEP:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if self._PLACEHOLDER_MARKER in text:
                stubs.append(rel)
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
        # Say WHY the import gate missed it, without asserting a mechanism that
        # may be wrong. Row 3's five were inside a module-level try/except that
        # swallowed the ImportError, and this message told the reader they were
        # inside function bodies — sending anyone who followed it to the wrong
        # place in the file.
        return [
            f"{len(phantom)} import(s) reference modules that do not exist locally "
            f"and are not installed: {preview}. The import check only reports what "
            f"raises at module level, so an import inside a function body — or one "
            f"wrapped in a try/except that swallows ImportError — passes it and "
            f"then fails, or silently does nothing, at request time."
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

    # Phrases that mean "this artifact does not function", as opposed to "this
    # artifact has a problem". The difference is the whole point of the
    # `unusable` verdict: one flaky generated test and an app that serves
    # nothing were both `done_with_context`, which made the status useless as a
    # signal. Matched against the findings the verifiers already produce, so
    # there is one vocabulary rather than a parallel set of predicates.
    _UNUSABLE_MARKERS = (
        "the application does not start",
        "declares no routes",
        "could not be started for verification",
        "fails on `--help`",
        "prints nothing for `--help`",
        "the page has no content",
    )

    def _functional_verdict(self, result: "BuildResult") -> tuple[bool, list[str]]:
        """
        (is_usable, reasons). False means the thing does not run at all.

        Deliberately narrow. This is not "is the build good" — degraded already
        covers that, and a build with a failing test or a missing feature is
        still something a user can open and finish. This is "did we ship
        something that cannot work", which until now was reported with exactly
        the same status as a cosmetic problem.
        """
        reasons: list[str] = []
        report = getattr(result, "remediation", None)
        unresolved = list(getattr(report, "unresolved", []) or [])

        # First, what the verifiers *said in a field*. A check that establishes
        # the artifact does not run marks its outcome fatal, so the verdict does
        # not depend on the wording of a sentence.
        structured: list[str] = []
        for outcome in (getattr(result, "verification_outcomes", None) or []):
            try:
                evidence = outcome.get("evidence") or {}
                if not evidence.get("fatal"):
                    continue
                structured.extend(
                    outcome.get("findings")
                    or evidence.get("fatal_reasons")
                    or [f"{outcome.get('check', 'a check')} found the artifact "
                        f"does not run"]
                )
            except Exception:
                continue
        reasons.extend(structured)

        # Then the wording, as a fallback — some findings reach `unresolved`
        # from paths that produce no outcome. When the strings fire and nothing
        # structured did, say so: that gap is how this decision silently stops
        # working, and it should be visible rather than inferred.
        matched_text: list[str] = []
        for finding in unresolved:
            low = finding.lower()
            for marker in self._UNUSABLE_MARKERS:
                if marker in low:
                    matched_text.append(finding)
                    break
        if matched_text and not structured:
            logger.info(
                "  🧾 `unusable` decided on finding text alone — no verifier "
                "marked its outcome fatal. If that is a check's omission rather "
                "than a path with no outcome, the flag is the thing to fix."
            )
        for finding in matched_text:
            if finding not in reasons:
                reasons.append(finding)

        # Nothing was generated at all. `_diagnose`'s test check is guarded by
        # `and result.backend_files`, so an empty backend produced no issue
        # whatsoever — the emptiest build possible scored clean.
        if not result.backend_files and not result.frontend_files:
            reasons.append("no source files were generated")

        return (not reasons), reasons

    def _verify_other_shapes(self, result: "BuildResult") -> list[str]:
        """
        Run the verifiers for every shape that is not a web API.

        Each returns a VerificationOutcome rather than a bare list, so a check
        that could not run says so instead of looking identical to one that
        passed. `collect_findings` turns a NOT_RUN into an explicit
        "this build is unverified" line.

        Outcomes are recorded on the build so the terminal status, the API and
        SESSION_CONTEXT.md can all state what was actually checked. Never raises.
        """
        root = result.architecture.get("root_folder", "")
        if not root:
            return []

        # A project directory that does not exist is a build-level problem, and
        # `_functional_verdict` reports it once. Asking each shape verifier
        # about it would file the same fact twice under two different check
        # names, which is how a clean build acquires phantom findings — the
        # other static audits skip a missing directory for the same reason.
        try:
            import config
            if not (Path(config.OUTPUT_DIR) / root).is_dir():
                return []
        except Exception:
            return []

        try:
            from tools.cli_smoke import smoke_test_cli
            from tools.web_asset_check import check_web_assets
            from tools.feature_coverage import check_feature_coverage
            from tools.package_smoke import smoke_test_package
            from tools.schema_attr_check import check_schema_attributes
            from tools.module_ref_check import check_module_refs
            from tools.generated_tests import run_generated_tests
            from tools.static_smoke import smoke_test_static
            from tools.verification import collect_findings
        except Exception as e:
            logger.warning(f"  ⚠️  Shape verifiers unavailable: {e}")
            return []

        intent = getattr(result, "intent", None) or {}

        # Record what this project actually is, so the status and the API can
        # say which shapes were verified rather than leaving the reader to infer
        # it from which checks happened to be silent.
        try:
            shapes = self._detect_shapes(root)
            if shapes is not None:
                result.build_shape = shapes.describe()
        except Exception:
            pass

        outcomes = []
        for name, fn in (
            ("cli_smoke", smoke_test_cli),
            ("web_assets", check_web_assets),
            # web_assets READS the page; this one SERVES it and fetches what it
            # asks for. Without it a project that is only a static page has no
            # check that executes anything, so since §4.31 it could never show
            # evidence of working at all.
            ("static_smoke", smoke_test_static),
            # Only fires for a project that is neither run nor served — the
            # product IS the importable API. Worth having now that the architect
            # no longer bolts a FastAPI app onto every request.
            ("package_smoke", smoke_test_package),
            # "It works" and "it is what you asked for" are different questions,
            # and only the first was ever asked. intent["features"] reached
            # exactly one place before this: the README.
            ("feature_coverage", lambda r: check_feature_coverage(r, intent)),
            # A field read that no model declares. Deterministic, and it sees
            # the write paths the runtime probe cannot reach — the ones whose
            # request body it could not synthesise, and the nullable column a
            # silenced repair writes NULL into without ever raising.
            ("schema_attr", check_schema_attributes),
            # One level up from `schema_attr`: that one checks the *fields* of a
            # class both files agree exists, this one checks that the name
            # exists at all. Row 3 died on `models.SupplierCreate`, which
            # `models.py` never defined — and `schema_attr` reported
            # `not_applicable`, because the models whose fields it would have
            # checked were the very thing that was missing.
            ("module_ref", check_module_refs),
            # The suite the build ships. Row 2 shipped one in which every test
            # errored at fixture setup and was still recorded `verified: yes`,
            # because no other check executes the tests — a suite that cannot
            # collect looked exactly like one that passed.
            ("generated_tests", run_generated_tests),
        ):
            try:
                outcomes.append(fn(root))
            except Exception as e:
                # A verifier that crashes must not be read as a pass.
                from tools.verification import VerificationOutcome
                logger.warning(f"  ⚠️  {name} raised: {e}")
                outcomes.append(VerificationOutcome.not_run(
                    name, detail=f"the check itself raised {type(e).__name__}: {e}"
                ))

        for outcome in outcomes:
            logger.info(f"  🧾 {outcome.summary()}")
            for finding in outcome.findings:
                logger.warning(f"     🚨 {finding}")

        # The web probe ran before this and reported its findings itself, so it
        # is recorded but NOT re-collected — the same defect must not be filed
        # twice under two check names. Recording it here rather than appending
        # from there preserves the replace-not-append rule: this list describes
        # the last run, and a reader can tell which run they are looking at.
        recorded = list(outcomes)
        smoke_outcome = getattr(self, "_smoke_outcome", None)
        if smoke_outcome is not None:
            recorded.insert(0, smoke_outcome)

        # Findings that describe the artifact not working stay advisory and
        # degrade the build. Findings from `generated_tests` are different in
        # kind: the suite is something the build *ships*, not something the
        # build *is*, and when another check has executed the artifact and found
        # it sound, a broken suite does not make the product broken.
        #
        # So when there is positive evidence the thing runs, those findings are
        # routed to the user as manual testing rather than counted against the
        # build. With no such evidence they stay advisory, because then they are
        # corroborating what the other checks already suspect.
        works = any(o.is_evidence_of_working for o in recorded)
        # Read by the final re-audit, which decides whether a test-suite finding
        # is a defect in this build or something to hand over for manual
        # testing. Recorded rather than recomputed so both decisions are made
        # from the same evidence.
        self._artifact_verified_working = works
        manual: list[str] = []
        counted = []
        #: check name -> the outcome as it reads AFTER routing. Only a check
        #: whose findings were *partly* routed appears here; see below for why
        #: a wholly-routed one must not.
        rewritten: dict = {}
        for outcome in outcomes:
            if works and outcome.check in self._MANUAL_WHEN_WORKING:
                manual.extend(outcome.findings)
                continue
            # A check can also route *some* of its findings, when only part of
            # what it reports is about the shipped suite rather than the
            # product. `module_ref` is the case: an undefined name in
            # `backend/routes.py` stops the application, and the identical
            # defect in `tests/test_routes.py` stops only that test. Whole-check
            # routing cannot express the difference, and getting it wrong either
            # way is a real cost — hiding the first, or degrading a working
            # build for the second.
            partial = outcome.evidence.get("manual_findings") or []
            if works and partial:
                routed = [f for f in outcome.findings if f in set(partial)]
                if routed:
                    manual.extend(routed)
                    kept = [f for f in outcome.findings if f not in set(partial)]
                    from tools.verification import Status, VerificationOutcome
                    if not kept:
                        # Nothing left that counts against the build: the check
                        # passes, and its findings live on as manual testing.
                        outcome = VerificationOutcome.verified(
                            outcome.check, detail=outcome.detail,
                            shape=outcome.shape,
                            evidence=dict(outcome.evidence),
                        )
                    else:
                        outcome = VerificationOutcome(
                            check=outcome.check, status=Status.FAILED,
                            shape=outcome.shape, detail=outcome.detail,
                            findings=kept, evidence=dict(outcome.evidence),
                        )
                    rewritten[outcome.check] = outcome
            counted.append(outcome)

        self._manual_checks = manual
        if manual:
            logger.info(
                f"  🧑‍🔬 {len(manual)} finding(s) do not affect a build that "
                "has been shown to work — handing them to the user as manual "
                "testing rather than marking the build degraded"
            )

        try:
            # Replace, do not append. This runs twice — once before remediation
            # and once in the final re-audit — and appending listed every check
            # twice, leaving a reader unable to tell which run they were looking
            # at or whether a repair had changed anything. The last run is the
            # one that describes the shipped artifact.
            #
            # Written AFTER routing, and this ordering is load-bearing. It used
            # to be written before, so a check whose findings were all handed to
            # manual testing was still recorded `failed` — and the record is
            # what `GET /jobs/{id}/status` serves and what
            # `run_live_matrix.verification_verdict` judges a matrix row on.
            # A build that works and ships one test file with a bad import
            # therefore failed its row, which is §4.26's decision undone by the
            # driver rather than by the pipeline.
            #
            # Only a *partly* routed check is rewritten. A wholly routed one
            # (`generated_tests`) stays `failed` on purpose: the driver excludes
            # it by name and prints "for manual testing: generated_tests", which
            # is the shape a passing row takes when its suite is broken. Calling
            # it `verified` here would delete that signal.
            result.verification_outcomes = [
                rewritten.get(o.check, o).to_dict() for o in recorded
            ]
        except Exception:
            pass

        return collect_findings(counted)

    #: Checks whose failure is not a verdict on the artifact itself, provided
    #: something else executed the artifact and found it sound.
    _MANUAL_WHEN_WORKING = ("generated_tests",)

    def _hand_over_test_suite_findings(
        self, issues: list, advisory: list
    ) -> tuple:
        """
        Move test-suite findings to manual testing once the build is verified.

        Called only at the end, after the tester has run and repair has had
        every pass it was going to get. Until then these are ordinary issues
        and they drive repair, because a failing test is often the only sign
        that the code under test is wrong.

        What this decides is the ending. If the suite still does not run and
        something has executed the application and found it sound, the two
        facts are independent: the product works, and the tests shipped beside
        it do not. That goes to the user as manual testing. With no evidence
        the artifact works it stays outstanding, because then it corroborates
        what the other checks already suspect.
        """
        findings = list(getattr(self, "_test_suite_issues", []) or [])
        if not findings or not getattr(self, "_artifact_verified_working", False):
            return issues, advisory

        issues   = [i for i in issues if i not in findings]
        advisory = [a for a in advisory if a not in findings]

        already = list(getattr(self, "_manual_checks", []) or [])
        handed_over = [f for f in findings if f not in already]
        self._manual_checks = already + handed_over

        logger.info(
            f"  🧑‍🔬 The application was verified; {len(handed_over)} "
            "test-suite finding(s) go to the user for manual testing rather "
            "than counting against the build"
        )
        return issues, advisory

    def _detect_shapes(self, root: str):
        """Every shape this project contains, or None if it cannot be read."""
        try:
            import config
            from tools.build_shape import detect_shapes
            project_dir = Path(config.OUTPUT_DIR) / root
            if not project_dir.is_dir():
                return None
            return detect_shapes(project_dir, rel_to=config.OUTPUT_DIR)
        except Exception as e:
            logger.warning(f"  ⚠️  Shape detection failed: {e}")
            return None

    def _route_definition_file(self, root: str) -> str:
        """
        The generated file a "no routes at all" repair should be aimed at.

        Prefer the file that already defines a router, since that is where the
        handlers belong; fall back to the entry point, which is where a missing
        `include_router` lives. Returns an OUTPUT_DIR-relative path, the way the
        rest of the pipeline spells them, or "" when neither can be found.
        """
        try:
            import config
            project_dir = Path(config.OUTPUT_DIR) / root
            if not project_dir.exists():
                return ""
        except Exception:
            return ""

        entry = ""
        for path in sorted(project_dir.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = str(path.relative_to(Path(config.OUTPUT_DIR))).replace("\\", "/")
            if "APIRouter(" in text:
                return rel
            if "FastAPI(" in text and not entry:
                entry = rel
        return entry

    # ── Phase 22: runtime smoke test (no LLM, no quota cost) ──────────────────

    def _smoke_test_runtime(self, result: BuildResult) -> list[str]:
        """
        Boot the generated app and call every route it declares.

        This is the first check in the pipeline that asks the user's question —
        "does the app respond?" — rather than "does the file import?". The
        todo_app build passed debug 3/3 with an endpoint that raised on every
        request, because the offending import sat inside a handler body and
        nothing ever sent a request.

        Findings used to be advisory only — "issues the repair passes cannot
        fix". That was true of the summary string and false of the failure
        behind it: a handler raising on every request is exactly what an LLM
        repair pass can fix, given the traceback. `self._smoke_runtime_errors`
        is set here so remediation can aim one.

        Never raises.
        """
        from tools.verification import VerificationOutcome

        self._smoke_runtime_errors = {}
        # The web probe is the most important check in the pipeline and the only
        # one that never said what it did. It returned a bare list, so its
        # result lived in the server log and nowhere else — which is why
        # run_live_matrix.py has to tell an operator to grep for it, and why the
        # matrix has never been able to evaluate the second half of its own pass
        # criterion. `_verify_other_shapes` records this alongside the rest.
        self._smoke_outcome = None
        root = result.architecture.get("root_folder", "")
        if not root:
            return []

        try:
            from tools.runtime_smoke import smoke_test_app
            smoke = smoke_test_app(root)
        except Exception as e:
            logger.warning(f"  ⚠️  Runtime smoke test failed to run: {e}")
            self._smoke_outcome = VerificationOutcome.not_run(
                "runtime_smoke",
                detail=f"the probe itself raised {type(e).__name__}: {e}",
            )
            return []

        # Record it on the build so the documenter and API can report it.
        try:
            result.smoke_summary = smoke.summary()
        except Exception:
            pass

        if not smoke.ran or not smoke.entry:
            # "No web entry point" is two different answers wearing one log line.
            #
            # For a CLI tool or a library it is correct and complete: there is no
            # web app, so the web probe has nothing to say. For a project that
            # DOES contain a web app the probe could not find, it means the build
            # went unverified — and that is what shipped on row 4, where the app
            # sat in `bulk_file_renamer/` while the search looked in `backend/`,
            # `src/` and the root. Both returned `[]`, which the pipeline reads
            # as "clean".
            #
            # Ask the shape detector which one this is and say so.
            shapes = self._detect_shapes(root)
            if shapes is not None and shapes.is_web:
                entry = shapes.primary_web_entry
                where = entry.path if entry else "unknown"
                logger.warning(
                    f"  🚨 A web app was found at {where} but the probe could not "
                    f"boot it — this build is UNVERIFIED"
                )
                finding = (
                    f"a web application exists at {where} but could not be "
                    f"started for verification, so none of its endpoints have "
                    f"been checked"
                )
                self._smoke_outcome = VerificationOutcome.not_run(
                    "runtime_smoke", shape=shapes.describe(),
                    detail=f"a web app was found at {where} and the probe "
                           f"could not boot it",
                    findings=[finding],
                ).mark_fatal("the web app could not be started at all")
                return [finding]
            what = shapes.describe() if shapes is not None else "unknown"
            logger.info(
                f"  ℹ️  No web entry point, and none expected for this build "
                f"({what}) — the web probe does not apply"
            )
            # Say that plainly in the stored summary too. SmokeResult's own text
            # is "smoke test did not run (no FastAPI entry point found)", which
            # is accurate about the probe and misleading about the build: for a
            # CLI it reads as a failure when the answer is "does not apply".
            try:
                result.smoke_summary = (
                    f"not applicable — this build is {what}, with no web app to probe"
                )
            except Exception:
                pass
            self._smoke_outcome = VerificationOutcome.not_applicable(
                "runtime_smoke", shape=what,
                detail="this build ships no web application to probe",
            )
            return []

        if not smoke.app_loaded:
            logger.warning(f"  🚨 App failed to boot: {smoke.error[:200]}")
            # A build whose app never loads is the worst outcome there is, and
            # it used to be the one nothing tried to fix: the finding went into
            # the advisory list while a single broken route — strictly less
            # damage — was repaired. When the traceback names a generated file,
            # aim a repair at it exactly as a 5xx does.
            blame = smoke.blame_file
            if blame:
                blame, note = self._redirect_blame_to_definition(
                    root, blame, smoke.error
                )
                if note:
                    logger.info(f"  \U0001f9ed {note}")
                path = f"{root}/{blame}" if not blame.startswith(root) else blame
                self._smoke_runtime_errors[path] = (
                    f"the app does not start — importing it raises: "
                    f"{self._trim_keeping_frames(smoke.error)}"
                )
            finding = (
                f"the application does not start: {smoke.error[:200]}. "
                f"Every endpoint is unreachable."
            )
            self._smoke_outcome = VerificationOutcome.failed(
                "runtime_smoke", [finding], shape="web_api",
                detail=f"the app at {smoke.entry} raises while being imported",
                evidence={"entry": smoke.entry},
            ).mark_fatal("the application does not start")
            return [finding]

        if not smoke.probes:
            # An app that boots and declares NO routes used to return `[]` here
            # — no issue, no advisory, not even the summary line below — and was
            # therefore indistinguishable from a clean run. This is the literal
            # empty build: §4.20 shipped exactly it, a routes.py of five
            # try/except ImportError blocks that left the router with nothing on
            # it, and every gate went green.
            #
            # A web app with no endpoints has not been verified; it has been
            # found empty. Say so, and aim a repair at the file that should have
            # defined them.
            logger.warning("  🚨 App boots but declares NO routes — nothing to serve")
            routes_file = self._route_definition_file(root)
            if routes_file:
                self._smoke_runtime_errors[routes_file] = (
                    "the application starts but exposes no HTTP routes at all. "
                    "Either no route handler is defined, or the router is never "
                    "included on the app with app.include_router(...)."
                )
            finding = (
                "the application starts but declares no routes, so it serves "
                "nothing. Every requested endpoint is missing."
            )
            self._smoke_outcome = VerificationOutcome.failed(
                "runtime_smoke", [finding], shape="web_api",
                detail=f"the app at {smoke.entry} boots and declares 0 routes",
                evidence={"entry": smoke.entry, "routes_total": 0},
            ).mark_fatal("the application declares no routes")
            return [finding]

        logger.info(f"  🔥 Runtime smoke test: {smoke.summary()}")
        for probe in smoke.probes:
            mark = "✅" if probe.ok else "🚨"
            logger.info(f"     {mark} {probe.method:6} {probe.path} → {probe.status}")

        failures = smoke.failures
        evidence = {
            "entry": smoke.entry,
            "routes_ok": smoke.passed,
            "routes_total": smoke.total,
        }
        if not failures:
            # Positive evidence, and the first time it has been recorded
            # anywhere but the log: this app was booted and every route it
            # declares answered without a server error.
            self._smoke_outcome = VerificationOutcome.verified(
                "runtime_smoke", shape="web_api",
                detail=smoke.summary(), evidence=evidence,
            )
            return []

        # Aim a repair: the outermost project frame is the handler that was
        # called, which is where the mistake lives even when the exception
        # surfaces deeper in. Files are keyed the way the rest of the pipeline
        # spells them — relative to OUTPUT_DIR, root folder included.
        for probe in failures:
            blame = probe.blame_file
            if not blame:
                continue
            blame, note = self._redirect_missing_field_to_definition(
                root, blame, probe.error
            )
            if note:
                logger.info(f"  \U0001f9ed {note}")
            path = f"{root}/{blame}" if not blame.startswith(root) else blame
            existing = self._smoke_runtime_errors.get(path, "")
            entry = (
                f"{probe.method} {probe.path} → {probe.status or 'no response'}: "
                f"{self._trim_keeping_frames(probe.error)}"
            )
            self._smoke_runtime_errors[path] = (
                f"{existing}\n{entry}" if existing else entry
            )

        detail = ", ".join(
            f"{p.method} {p.path} → {p.status or 'no response'}" for p in failures[:5]
        )
        finding = (
            f"{len(failures)} of {smoke.total} endpoint(s) return a server error when "
            f"called: {detail}. These fail at request time, which the import check "
            f"cannot see."
        )
        outcome = VerificationOutcome.failed(
            "runtime_smoke", [finding], shape="web_api",
            detail=smoke.summary(), evidence=evidence,
        )
        # Some routes answering is a build with broken endpoints; none answering
        # is a build that does not work. Only the second is `unusable`.
        if smoke.passed == 0:
            outcome.mark_fatal("every endpoint returns a server error")
        self._smoke_outcome = outcome
        return [finding]

    def _redirect_blame_to_definition(
        self, root: str, blame: str, error: str
    ) -> tuple:
        """
        A boot failure about an imported name belongs to the file that defines it.

        The three blame rules that existed all point at a frame. This one cannot:
        matrix row 2's `routes.py` does

            from services import BookmarkOut          # a PLAIN class
            @router.get(..., response_model=List[BookmarkOut])

        and FastAPI raises while importing routes.py, so every frame names
        routes.py. But routes.py is right — `BookmarkOut` simply is not a Pydantic
        model, and the fix is in services.py. Aiming the repair at routes.py and
        telling it "the bug is in THIS file, do not make the other module
        tolerate it" instructs the model away from the only fix that works, which
        is exactly what was observed: both models produced something the guards
        rejected.

        So: if the blamed file merely IMPORTS a name the error complains about,
        and that name comes from another generated module, repair that module.

        Returns `(path, note)` — the original blame unchanged when no such name
        is found, so a genuine in-file bug keeps the frame-based rule.
        """
        try:
            import config
            from tools.code_patcher import imported_symbols

            project_dir = Path(config.OUTPUT_DIR) / root
            blamed = project_dir / blame
            if not blamed.is_file():
                return blame, ""
            symbols = imported_symbols(blamed.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return blame, ""

        for symbol, module in symbols.items():
            if symbol not in error:
                continue
            # `services` -> backend/services.py, next to the file that imports it,
            # or anywhere in the project. Only generated modules qualify: a
            # complaint naming `List` must not send a repair into typing.
            leaf = module.split(".")[-1] + ".py"
            for candidate in (blamed.parent / leaf, project_dir / leaf):
                if not candidate.is_file() or candidate == blamed:
                    continue
                rel = str(candidate.relative_to(project_dir)).replace(chr(92), "/")
                return rel, (
                    f"{blame} only imports `{symbol}` from `{module}`; "
                    f"repairing {rel}, which defines it"
                )
        return blame, ""

    # An AttributeError names the class and the attribute, and nothing else.
    _ATTR_ERROR = re.compile(
        r"['\"]?(\w+)['\"]? object has no attribute ['\"](\w+)['\"]"
    )

    # How alike two field names have to be before one is read as a misspelling
    # of the other. Judgment, not measurement — but calibrated against the three
    # live cases it has to separate, and asserted in the suite so a change to it
    # has to face them: contact/contact_email is 0.70, sku against ProductBase's
    # closest field is 0.29, direction against StockMovementBase's is 0.53.
    _RENAME_SIMILARITY = 0.6

    def _redirect_missing_field_to_definition(
        self, root: str, blame: str, error: str
    ) -> tuple:
        """
        The fourth blame rule, applied to a request-time failure.

        `_redirect_blame_to_definition` handles this for a boot failure. A 500
        never reached it, so an `AttributeError` naming a class defined in
        `schemas.py` sent the repair to `routes.py` — which can rename the read
        or silence it, and can never add the field that is missing. That is what
        the live measurement caught the debugger doing: `prod.sku` became
        `data.get("sku")`, a silent None into a NOT NULL column, and it scored
        HIGHER than the correct repair.

        The two cases need opposite targets, and the model itself separates
        them:

          * `sup.contact` where the model declares `contact_email` — a
            misspelling. Repair it where it is read; §0.7 proved the model does
            this correctly once it can see the definition.
          * `prod.sku` where the model declares nothing like it — the field is
            genuinely absent, and no edit to `routes.py` can invent it. Repair
            the file that defines the class.

        Returns `(path, note)`, the blame unchanged when nothing applies — so a
        failure that is not this shape keeps the frame-based rule.
        """
        try:
            match = self._ATTR_ERROR.search(error or "")
            if not match:
                return blame, ""
            class_name, attr = match.group(1), match.group(2)

            from tools.schema_attr_check import find_model_definition
            defining_file, fields = find_model_definition(root, class_name)
            if not defining_file:
                return blame, ""

            rel = defining_file
            if rel.startswith(f"{root}/"):
                rel = rel[len(root) + 1:]
            if rel == blame:
                return blame, ""              # already aimed at the definition

            if attr in fields:
                return blame, ""              # the field exists; not this rule

            close = difflib.get_close_matches(
                attr, list(fields), n=1, cutoff=self._RENAME_SIMILARITY
            )
            if close:
                return blame, ""              # a misspelling, repairable in place

            return rel, (
                f"`{class_name}` declares no `{attr}` and nothing like it "
                f"({', '.join(fields) or 'no fields'}); repairing {rel}, which "
                f"defines it, rather than {blame}, which only reads it"
            )
        except Exception:
            return blame, ""

    _RUNTIME_ERROR_CHARS = 400

    @classmethod
    def _trim_keeping_frames(cls, error: str) -> str:
        """
        Trim a probe error without losing the `(at file:line in func)` suffix.

        `error[:400]` cut from the head, which is where the exception message is
        — and left the frame chain, which is at the tail, to be dropped first.
        That chain is what `_generate_targeted_runtime_fix` parses to decide
        which block to repair, so cutting it silently downgrades every long
        error to a whole-file rewrite. Keep both ends and drop the middle.
        """
        text = (error or "").strip()
        if len(text) <= cls._RUNTIME_ERROR_CHARS:
            return text

        match = re.search(r"\s*\(at [^)]+\)\s*$", text)
        if not match:
            return text[:cls._RUNTIME_ERROR_CHARS]

        frames = match.group(0).strip()
        head_room = cls._RUNTIME_ERROR_CHARS - len(frames) - 3
        if head_room < 80:
            # A frame chain that long IS the useful part; keep it and a stub of
            # the message rather than dropping the anchor to fit the message.
            return text[:80] + " … " + frames
        return text[:head_room] + " … " + frames

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

        issues, failed_paths, diag_advisory = self._diagnose(result)

        # Static audit runs even when verification is clean: the todo_app build
        # scored debug 3/3 while shipping a function-body import of a module
        # that was never generated, placeholder files, and dangling frontend
        # imports. None of that is visible to the import/test gates.
        advisory = list(diag_advisory) + self._audit_generated_output(result)

        # Phase 22: actually run the app. Static analysis cannot tell a handler
        # that works from one that raises the moment a request arrives.
        smoke_advisory = self._smoke_test_runtime(result)
        advisory = advisory + smoke_advisory

        # …and run every OTHER shape this project contains. The web probe was
        # the only executing check in the pipeline, so a CLI tool was verified
        # by "the files import" — which by definition never runs what is under
        # `if __name__ == "__main__"` — and a static page by one regex.
        shape_advisory = self._verify_other_shapes(result)
        advisory = advisory + shape_advisory

        # Phase 23: a 5xx whose traceback names a generated file is repairable,
        # and used to be filed under "cannot be fixed" purely because the smoke
        # test ran after the diagnosis that decides what gets repaired. A build
        # shipped with three of five routes returning 500 while remediation
        # reported "no files were repaired this pass".
        runtime_errors = dict(getattr(self, "_smoke_runtime_errors", {}) or {})
        for path in runtime_errors:
            if path not in failed_paths:
                failed_paths.append(path)
        if runtime_errors:
            issues = list(issues) + [
                f"{len(runtime_errors)} file(s) raise at request time: "
                f"{', '.join(sorted(runtime_errors)[:4])}"
            ]

        if not issues and not advisory:
            logger.info("✅ Verification clean — no remediation needed")
            report.manual_checks = list(getattr(self, "_manual_checks", []) or [])
            if report.manual_checks:
                logger.info(
                    f"  🧑‍🔬 {len(report.manual_checks)} item(s) recorded for "
                    "manual testing; the build itself verified clean"
                )
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
            # Nothing here can be repaired, so this is the end of the road for
            # this build — which makes it the point where a test-suite finding
            # stops being an outstanding issue and becomes a manual check.
            _, advisory = self._hand_over_test_suite_findings([], advisory)
            report.unresolved    = advisory
            report.manual_checks = list(getattr(self, "_manual_checks", []) or [])
            report.degraded      = bool(advisory)
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
                    fresh = self.debugger.run(failed_paths, runtime_errors=runtime_errors)
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

            issues, failed_paths, diag_advisory = self._diagnose(result)

            # Re-run the app. It costs no tokens and it is the only thing that
            # can say whether a request-time repair actually worked — the
            # import check passed before the repair too.
            if runtime_errors:
                smoke_advisory = self._smoke_test_runtime(result)
                runtime_errors = dict(getattr(self, "_smoke_runtime_errors", {}) or {})
                if runtime_errors:
                    for path in runtime_errors:
                        if path not in failed_paths:
                            failed_paths.append(path)
                    issues = list(issues) + [
                        f"{len(runtime_errors)} file(s) still raise at request time: "
                        f"{', '.join(sorted(runtime_errors)[:4])}"
                    ]
                else:
                    logger.info("  ✅ Every endpoint now responds without a server error")

            if not issues:
                logger.info(f"  ✅ Remediation resolved all issues on pass {attempt}")
                break

            if not self._quota_available():
                logger.warning("  🔑 Quota exhausted mid-remediation — stopping repair passes")
                break

        # Re-run the whole diagnosis, not just the static audit. `issues` and
        # `diag_advisory` came from the pass BEFORE remediation, so reusing them
        # shipped a checklist describing a state that no longer existed — row 2
        # told its reader to fix `bookmark.description` after the debugger had
        # already fixed it. Everything the shipped document says must describe
        # what is on disk now. It is a static re-scan and costs no tokens.
        issues, failed_paths, diag_advisory = self._diagnose(result)

        # `smoke_advisory` is whatever the last run of the app said, so a repair
        # that worked is not reported as an outstanding failure.
        advisory = (
            list(diag_advisory)
            + self._audit_generated_output(result)
            + list(smoke_advisory)
            + self._verify_other_shapes(result)
        )

        # The request-time failures are already stated by `smoke_advisory`, in
        # the form that names the endpoints. Keeping the synthetic issue
        # string too would print the same fact twice in SESSION_CONTEXT.md.
        issues = [i for i in issues if "raise at request time" not in i]

        # The tester has run, and repair has had every pass it was going to get.
        # If the suite still does not run and the application itself has been
        # executed and found sound, the two facts are independent: the product
        # works, and the tests that ship beside it do not. Handing that to the
        # user as manual testing is honest; calling the build degraded for it is
        # not. With no evidence the artifact works, it stays an outstanding
        # issue, because then it corroborates what the other checks suspect.
        issues, advisory = self._hand_over_test_suite_findings(issues, advisory)

        report.unresolved    = list(issues) + list(advisory)
        report.manual_checks = list(getattr(self, "_manual_checks", []) or [])
        report.degraded      = bool(report.unresolved)

        if report.manual_checks and not report.unresolved:
            logger.info(
                "  ✅ Nothing is outstanding against this build; "
                f"{len(report.manual_checks)} item(s) are recorded for manual "
                "testing and do not degrade it"
            )

        # Separate "has problems" from "does not run". Both were
        # done_with_context, so the status could not distinguish a flaky test
        # from an application that serves nothing.
        result.remediation = report
        usable, why_not = self._functional_verdict(result)
        result.unusable  = not usable
        result.unusable_reasons = why_not
        if not usable:
            logger.error(
                "  ⛔ This build does not function: "
                + "; ".join(w[:120] for w in why_not[:3])
            )

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

            # ── Verification must happen, even when a step did not ────────────
            #
            # `_refine_and_remediate` is called from inside the per-step `try`,
            # right after the tester returns. So when the tester raised — or
            # timed out twice at 900s — the loop broke and NOTHING ran: no
            # static audit, no SQL check, no runtime smoke test, no shape
            # verifiers. The build was then packaged and shipped, and its report
            # was indistinguishable from a build that had passed every one of
            # them. That is the same "silence reads as clean" defect the
            # VerificationOutcome states exist to remove, one level up.
            #
            # A quota stop is the exception: `_refine_and_remediate` has its own
            # quota gate and would produce a degraded report without spending
            # tokens, but running it here would also re-enter the debugger for a
            # build we already know is paused. The handoff document covers that
            # case and says plainly that verification did not run.
            if result.remediation is None and quota_stop is None and (
                result.backend_files or result.frontend_files
            ):
                logger.warning(
                    "  🧾 Verification never ran (the pipeline stopped before the "
                    "tester) — running it now so this build is not reported as "
                    "clean by default"
                )
                try:
                    result.remediation = self._refine_and_remediate(result)
                    if result.remediation.degraded:
                        result.degraded = True
                except Exception as e:
                    logger.warning(f"  ⚠️  Late verification failed: {e}")

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
