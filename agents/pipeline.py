"""
agents/pipeline.py  v2.0.0  (Phase 17 — reliability & observability)
======================================================================
Changes vs v1.x:
  - STEP_TIMEOUT_SECONDS = 240  (configurable hard timeout per step)
  - STEP_MAX_RETRIES = 1        (each step retried once before failing the build)
  - _run_step_with_timeout()    — ThreadPoolExecutor-based timeout (works on Windows)
  - Structured "data" dict emitted on both success AND failure:
      success: {"elapsed_seconds": N, + step-specific metrics}
      failure: {"error": "...", "error_type": "...", "traceback": "...",
                "elapsed_seconds": N, "timed_out": bool}
  - Token tracking: set_current_build_id() called at pipeline start
  - _build_step_data() centralises per-step success payload building
"""
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from uuid import uuid4
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any

from agents.intent_analyzer import IntentAnalyzer
from agents.planner import Planner
from agents.architect import Architect
from agents.backend_developer import BackendDeveloper
from agents.frontend_generator import FrontendGenerator
from agents.debugger import Debugger, FileDebugResult
from agents.reviewer import Reviewer, ReviewResult
from agents.tester import Tester, TestResult
from agents.documenter import Documenter, DocResult

logger = logging.getLogger(__name__)

# ── Phase 17: configurable per-step limits ─────────────────────────────────────
STEP_TIMEOUT_SECONDS: int = 240   # seconds before a hung step is cancelled
STEP_MAX_RETRIES:     int = 1     # extra attempts after the first failure (0 = no retry)


@dataclass
class BuildResult:
    user_prompt:    str
    build_id:       str   = field(default_factory=lambda: str(uuid4())[:8])
    intent:         dict  = field(default_factory=dict)
    steps:          list  = field(default_factory=list)
    architecture:   dict  = field(default_factory=dict)
    backend_files:  list  = field(default_factory=list)
    frontend_files: list  = field(default_factory=list)
    debug_results:  list  = field(default_factory=list)
    review_results: list  = field(default_factory=list)
    test_results:   list  = field(default_factory=list)
    doc_result:     Optional[DocResult] = None
    success:        bool  = False
    error:          str   = ""
    started_at:     datetime = field(default_factory=datetime.now)
    completed_at:   Optional[datetime] = None
    current_step:   int   = 0

    @property
    def all_files(self):
        return self.backend_files + self.frontend_files

    @property
    def duration_seconds(self) -> float:
        if not self.completed_at:
            return (datetime.now() - self.started_at).total_seconds()
        return (self.completed_at - self.started_at).total_seconds()

    def complete(self, success: bool):
        self.success = success
        self.completed_at = datetime.now()

    def summary(self) -> str:
        debug_passed = sum(1 for r in self.debug_results if r.success)
        scores       = [r.score for r in self.review_results if r.score]
        avg_score    = sum(scores) / len(scores) if scores else 0
        total_tests  = sum(r.tests_generated for r in self.test_results)
        tests_passed = sum(r.passed for r in self.test_results)
        doc_status   = str(self.doc_result) if self.doc_result else "not run"

        lines = [
            f"\n{'='*50}",
            f"  BUILD RESULT: {'✅ SUCCESS' if self.success else '❌ FAILED'}",
            f"{'='*50}",
            f"  Build ID:   {self.build_id}",
            f"  App:        {self.intent.get('app_name', '?')}",
            f"  Type:       {self.intent.get('app_type', '?')}",
            f"  Complexity: {self.intent.get('complexity', '?')}",
            f"  Files:      {len(self.all_files)}",
            f"  Debug:      {debug_passed}/{len(self.debug_results)} passing",
            f"  Review:     {avg_score:.1f}/10 avg score",
            f"  Tests:      {tests_passed}/{total_tests} passing",
            f"  Docs:       {doc_status}",
            f"  Duration:   {self.duration_seconds:.1f}s",
            f"{'='*50}",
        ]
        if self.all_files:
            lines.append("  Generated files:")
            for f in self.all_files:
                lines.append(f"    📄 {f}")
        if self.debug_results:
            lines.append("\n  Debug results:")
            for r in self.debug_results:
                lines.append(f"    {r}")
        if self.review_results:
            lines.append("\n  Review results:")
            for r in self.review_results:
                lines.append(f"    {r}")
        if self.test_results:
            lines.append("\n  Test results:")
            for r in self.test_results:
                lines.append(f"    {r}")
        if self.error:
            lines.append(f"\n  ❌ Error: {self.error}")
        lines.append(f"{'='*50}\n")
        return "\n".join(lines)


class Pipeline:
    def __init__(self, build_id: str = None, progress_callback: Callable = None):
        """
        Args:
            build_id:          Unique build identifier (auto-generated if not provided)
            progress_callback: Called with a progress dict on every step change.
                               Dict shape:
                               {
                                 "build_id":  str,
                                 "step":      int,
                                 "step_name": str,
                                 "status":    "running" | "done" | "failed",
                                 "timestamp": str (ISO),
                                 "data":      dict   ← structured per-step payload
                               }
        """
        self.build_id          = build_id or str(uuid4())[:8]
        self.progress_callback = progress_callback

        self.intent_analyzer    = IntentAnalyzer()
        self.planner            = Planner()
        self.architect          = Architect()
        self.backend_developer  = BackendDeveloper()
        self.frontend_generator = FrontendGenerator()
        self.debugger           = Debugger()
        self.reviewer           = Reviewer()
        self.tester             = Tester()
        self.documenter         = Documenter()

    # ── Phase 17: step runner with timeout + retry ─────────────────────────────

    def _run_step_with_timeout(
        self,
        step_num:  int,
        step_name: str,
        fn:        Callable,
        timeout:   int = STEP_TIMEOUT_SECONDS,
        retries:   int = STEP_MAX_RETRIES,
    ) -> Any:
        """
        Run fn() in a worker thread with a hard wall-clock timeout.

        Uses ThreadPoolExecutor.submit() + Future.result(timeout=N) so it works
        cross-platform (no signal.alarm, which is Unix-only).

        On timeout or exception, retries up to `retries` additional times.
        Raises the last exception if all attempts fail.

        Note: the worker thread continues running after a timeout (Python threads
        cannot be forcibly killed). The future is cancelled so the result is ignored,
        but the thread will still complete in the background. This is the standard
        Python trade-off for cross-platform timeouts.
        """
        last_exc: Optional[Exception] = None
        total_attempts = retries + 1

        for attempt in range(1, total_attempts + 1):
            attempt_label = f"attempt {attempt}/{total_attempts}"
            logger.info(
                f"  ⏱️  [{step_name}] Starting ({attempt_label}, timeout={timeout}s)"
            )

            # Each attempt gets its own single-worker pool so threads don't accumulate
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"step_{step_name}") as executor:
                future = executor.submit(fn)
                try:
                    result = future.result(timeout=timeout)
                    if attempt > 1:
                        logger.info(
                            f"  ✅ [{step_name}] Succeeded on {attempt_label}"
                        )
                    return result

                except FuturesTimeoutError:
                    # future.cancel() is a best-effort hint; the thread may still run
                    future.cancel()
                    last_exc = TimeoutError(
                        f"Step '{step_name}' timed out after {timeout}s. "
                        f"The step was taking too long — check Ollama/Groq connectivity."
                    )
                    logger.warning(
                        f"  ⏰ [{step_name}] Timed out after {timeout}s ({attempt_label})"
                    )

                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        f"  ❌ [{step_name}] Failed ({attempt_label}): "
                        f"{type(exc).__name__}: {exc}"
                    )

            if attempt < total_attempts:
                logger.info(f"  🔁 [{step_name}] Retrying ({attempt + 1}/{total_attempts})…")

        # All attempts exhausted — propagate the last exception
        raise last_exc  # type: ignore[misc]

    # ── Progress emitter ────────────────────────────────────────────────────────

    def _emit_progress(
        self,
        step:      int,
        step_name: str,
        status:    str,
        data:      Dict = None,
    ):
        """Emit a progress event via the registered callback."""
        if self.progress_callback:
            self.progress_callback({
                "build_id":  self.build_id,
                "step":      step,
                "step_name": step_name,
                "status":    status,
                "timestamp": datetime.now().isoformat(),
                "data":      data or {},
            })

    # ── Per-step success data builders ─────────────────────────────────────────

    def _build_step_data(self, step_name: str, val: Any) -> dict:
        """
        Build a structured data dict for a step's success outcome.
        These are stored in build_progress.data (JSON) and shown in the
        BuildLogsPanel on the frontend.
        """
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

    # ── Main pipeline ───────────────────────────────────────────────────────────

    def run(self, user_prompt: str) -> BuildResult:
        # ── Phase 17: register build for token tracking ───────────────────────
        try:
            import llm_client
            llm_client.set_current_build_id(self.build_id)
        except Exception:
            pass  # token tracking is best-effort; never crash the pipeline

        result = BuildResult(user_prompt=user_prompt, build_id=self.build_id)

        # ── Step definitions ───────────────────────────────────────────────────
        # Each entry: (step_num, step_name, zero-arg lambda)
        # Lambdas close over `result` so they always use the latest partial results.
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

        # Attribute names on BuildResult, parallel to steps_def
        result_attrs = [
            "intent", "steps", "architecture",
            "backend_files", "frontend_files",
            "debug_results", "review_results", "test_results", "doc_result",
        ]

        try:
            for (step_num, step_name, fn), attr in zip(steps_def, result_attrs):
                result.current_step = step_num
                step_start          = datetime.now()

                # Emit "running" immediately so the UI shows the step as active
                self._emit_progress(step_num, step_name, "running")
                logger.info(f"🔄 [{step_num}/9] {step_name}…")

                try:
                    val = self._run_step_with_timeout(step_num, step_name, fn)
                    setattr(result, attr, val)

                    # Build structured payload and measure elapsed time
                    elapsed    = round((datetime.now() - step_start).total_seconds(), 1)
                    step_data  = self._build_step_data(step_name, val)
                    step_data["elapsed_seconds"] = elapsed

                    self._emit_progress(step_num, step_name, "done", step_data)
                    logger.info(f"✅ [{step_num}/9] {step_name} done in {elapsed}s")

                except Exception as exc:
                    elapsed = round((datetime.now() - step_start).total_seconds(), 1)
                    tb      = traceback.format_exc()

                    # Structured failure data stored to DB so BuildLogsPanel
                    # can display "what went wrong" in ProjectDetail
                    self._emit_progress(step_num, step_name, "failed", {
                        "error":           str(exc),
                        "error_type":      type(exc).__name__,
                        "traceback":       tb[-1000:],   # last 1000 chars of traceback
                        "elapsed_seconds": elapsed,
                        "timed_out":       isinstance(exc, TimeoutError),
                    })
                    logger.error(
                        f"💥 [{step_num}/9] {step_name} failed after {elapsed}s: {exc}"
                    )
                    raise   # propagate to outer try/except to mark build failed

            result.complete(success=True)

        except Exception as e:
            result.error = str(e)
            result.complete(success=False)
            logger.error(
                f"💥 Pipeline failed at step {result.current_step}: {e}",
                exc_info=True,
            )

        return result


# ── CLI smoke test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    def on_progress(progress):
        status = progress["status"]
        step   = progress["step"]
        name   = progress["step_name"]
        data   = progress.get("data", {})
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
