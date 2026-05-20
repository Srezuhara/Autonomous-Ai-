"""
agents/pipeline.py  v2.1.0  (Phase 19 — generated project quality)
===================================================================
Changes vs v2.0.2 (Phase 17 cooperative cancellation):

Phase 19.3 — Frontend Build Validation
  - New Step 5.5: FrontendDebugger runs after FrontendGenerator
  - Runs `tsc --noEmit` and auto-fixes TypeScript errors via LLM
  - Adds `frontend_debug_results` to BuildResult
  - Emits progress event for step 5 as "frontend_debugger"
  - Step count stays at 9 externally (5.5 is internal); progress callback
    uses step=5, step_name="frontend_debugger" so the UI shows it correctly

Phase 19.1 — requirements.txt validation
  - BackendDeveloper.run() now calls validate_and_fix_requirements() internally
  - No pipeline-level change needed — transparent to the pipeline

Phase 19.2 — Multi-file context
  - BackendDeveloper and FrontendGenerator now use role-ordered generation
    with full-header context; transparent to the pipeline

Phase 19.4 — CORS auto-detection
  - BackendDeveloper detects frontend port from architecture; transparent

All Phase 17 features retained: per-step timeout, retry, cancel_check,
structured data emission, token tracking in sub-threads.
"""
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from uuid import uuid4
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List

from agents.intent_analyzer import IntentAnalyzer
from agents.planner import Planner
from agents.architect import Architect
from agents.backend_developer import BackendDeveloper
from agents.frontend_generator import FrontendGenerator
from agents.frontend_debugger import FrontendDebugger, TsDebugResult  # Phase 19.3
from agents.debugger import Debugger, FileDebugResult
from agents.reviewer import Reviewer, ReviewResult
from agents.tester import Tester, TestResult
from agents.documenter import Documenter, DocResult

logger = logging.getLogger(__name__)

STEP_TIMEOUT_SECONDS: int = 240
STEP_MAX_RETRIES:     int = 1


class PipelineCancelledError(Exception):
    """Raised when cancel_check() returns True between steps."""


@dataclass
class BuildResult:
    user_prompt:          str
    build_id:             str   = field(default_factory=lambda: str(uuid4())[:8])
    intent:               dict  = field(default_factory=dict)
    steps:                list  = field(default_factory=list)
    architecture:         dict  = field(default_factory=dict)
    backend_files:        list  = field(default_factory=list)
    frontend_files:       list  = field(default_factory=list)
    frontend_debug_results: list = field(default_factory=list)   # Phase 19.3
    debug_results:        list  = field(default_factory=list)
    review_results:       list  = field(default_factory=list)
    test_results:         list  = field(default_factory=list)
    doc_result:           Optional[DocResult] = None
    success:              bool  = False
    error:                str   = ""
    cancelled:            bool  = False
    started_at:           datetime = field(default_factory=datetime.now)
    completed_at:         Optional[datetime] = None
    current_step:         int   = 0

    @property
    def all_files(self):
        return self.backend_files + self.frontend_files

    @property
    def duration_seconds(self) -> float:
        if not self.completed_at:
            return (datetime.now() - self.started_at).total_seconds()
        return (self.completed_at - self.started_at).total_seconds()

    def complete(self, success: bool):
        self.success     = success
        self.completed_at = datetime.now()

    def summary(self) -> str:
        debug_passed = sum(1 for r in self.debug_results if r.success)
        scores       = [r.score for r in self.review_results if r.score]
        avg_score    = sum(scores) / len(scores) if scores else 0
        total_tests  = sum(r.tests_generated for r in self.test_results)
        tests_passed = sum(r.passed for r in self.test_results)
        doc_status   = str(self.doc_result) if self.doc_result else "not run"

        # Phase 19.3 summary
        ts_fixed = sum(1 for r in self.frontend_debug_results if r.success and not r.skipped)

        lines = [
            f"\n{'='*50}",
            f"  BUILD RESULT: {'✅ SUCCESS' if self.success else '❌ FAILED'}",
            f"{'='*50}",
            f"  Build ID:      {self.build_id}",
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
            f"{'='*50}",
        ]
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

        self.intent_analyzer     = IntentAnalyzer()
        self.planner             = Planner()
        self.architect           = Architect()
        self.backend_developer   = BackendDeveloper()
        self.frontend_generator  = FrontendGenerator()
        self.frontend_debugger   = FrontendDebugger()   # Phase 19.3
        self.debugger            = Debugger()
        self.reviewer            = Reviewer()
        self.tester              = Tester()
        self.documenter          = Documenter()

    # ── Token tracking: propagate build_id into sub-threads ───────────────────

    def _make_tracked_fn(self, fn: Callable) -> Callable:
        """Wrap fn so the sub-thread calls set_current_build_id before running."""
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
                return {"files_count": len(val.get("files", []))}
            if step_name in ("backend_developer", "frontend_generator") and isinstance(val, list):
                return {"files_generated": len(val)}
            if step_name == "frontend_debugger" and isinstance(val, list):
                # Phase 19.3: structured TS debug summary
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
                passed = sum(r.passed for r in val)
                total  = sum(r.tests_generated for r in val)
                return {"passed": passed, "total": total}
            if step_name == "documenter" and val is not None:
                return {"readme_path": getattr(val, "readme_path", None)}
        except Exception:
            pass
        return {}

    # ── Main pipeline ─────────────────────────────────────────────────────────

    def run(self, user_prompt: str) -> BuildResult:
        try:
            import llm_client
            llm_client.set_current_build_id(self.build_id)
        except Exception:
            pass

        result = BuildResult(user_prompt=user_prompt, build_id=self.build_id)

        # ── Step definitions ──────────────────────────────────────────────────
        # Note: FrontendDebugger (Phase 19.3) is step 5 extended — it runs
        # immediately after FrontendGenerator using the same step number slot
        # so the DB step count stays at 9 and the UI progress bar is unaffected.
        # We label it "frontend_debugger" in the step_name for the UI.
        steps_def = [
            (1, "intent_analyzer",
             lambda: self.intent_analyzer.run(user_prompt)),
            (2, "planner",
             lambda: self.planner.run(result.intent)),
            (3, "architect",
             lambda: self.architect.run(result.intent, result.steps)),
            (4, "backend_developer",
             lambda: self.backend_developer.run(result.intent, result.architecture)),
            (5, "frontend_generator",
             lambda: self.frontend_generator.run(result.intent, result.architecture)),
            # Phase 19.3: TypeScript validation step (step_num=5, substep)
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

        # Maps each (step_num, step_name) → which result attribute to populate
        result_attr_map = {
            (1, "intent_analyzer"):   "intent",
            (2, "planner"):           "steps",
            (3, "architect"):         "architecture",
            (4, "backend_developer"): "backend_files",
            (5, "frontend_generator"):"frontend_files",
            (5, "frontend_debugger"): "frontend_debug_results",  # Phase 19.3
            (6, "debugger"):          "debug_results",
            (7, "reviewer"):          "review_results",
            (8, "tester"):            "test_results",
            (9, "documenter"):        "doc_result",
        }

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

                    elapsed    = round((datetime.now() - step_start).total_seconds(), 1)
                    step_data  = self._build_step_data(step_name, val)
                    step_data["elapsed_seconds"] = elapsed

                    self._emit_progress(step_num, step_name, "done", step_data)
                    logger.info(f"✅ [{step_num}/9] {step_name} done in {elapsed}s")

                except PipelineCancelledError:
                    raise

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

                    # Phase 19.3: if frontend_debugger fails, log but do NOT
                    # abort the pipeline — it's a quality enhancement, not critical.
                    if step_name == "frontend_debugger":
                        logger.warning(
                            "⚠️  FrontendDebugger failed — continuing pipeline without TS fixes"
                        )
                        continue

                    raise

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
    result   = pipeline.run(
        "Build a weather dashboard that shows temperature, humidity and a 5-day forecast"
    )
    print(result.summary())
