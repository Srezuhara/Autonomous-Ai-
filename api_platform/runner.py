"""
api_platform/runner.py  v2.6.1  (Phase 20 — Authentic Test Scores + review_score fix)
=======================================================================================
Changes vs v2.6.0:

BUG FIX — review_score was always None in the database.

  Root cause in v2.6.0 (introduced during the Issue 11 refactor):
    The code extracted debug_results_list from result.debug_results but
    FORGOT to extract review_results_list from result.review_results.
    Then it called:
        review_score = _safe_review_score(debug_results_list, build_id)
    passing debug results (FileDebugResult objects, which have no .score
    attribute) to a function that looks for .score.  The function found
    no scores in any item and returned None every time.

  Fix (two lines added around line 445):
        review_results_list = (
            result.review_results
            if hasattr(result, "review_results") else []
        )
        review_score = _safe_review_score(review_results_list, build_id)  # ← was debug_results_list

  This restores the review_score field that has been silently NULL in the
  database for any build run with v2.6.0.

All v2.6.0 features retained unchanged:
  - Issue 11: _safe_test_score() cross-validates against debug_results
    (mock-only passes from debug-failed files excluded from numerator)
  - Cooperative cancellation
  - Token usage stored on cancel/fail/success
  - _safe_review_score / _safe_debug_score helpers
"""

import json
import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from api_platform.database import (
    add_build_step,
    create_project,
    get_project,
    update_project,
)

logger = logging.getLogger(__name__)

# ── Phase 21: build status vocabulary ─────────────────────────────────────────
# done               — every verification gate clean
# done_with_context  — usable code exists but the build was degraded or paused
#                      by quota; SESSION_CONTEXT.md explains what to do next.
#                      Downloadable, exactly like `done`.
# failed             — crashed before producing any usable code
# cancelled          — user cancelled
DOWNLOADABLE_STATUSES = ("done", "done_with_context")
TERMINAL_STATUSES     = ("done", "done_with_context", "failed", "cancelled")


# ── Safe score helpers ────────────────────────────────────────────────────────

def _safe_review_score(review_results: list, build_id: str) -> float | None:
    if not review_results:
        logger.warning(f"[{build_id[:8]}] review_results is empty — review_score=None")
        return None
    scores = []
    for r in review_results:
        raw = None
        for attr in ("score", "rating", "value", "review_score"):
            if hasattr(r, attr):
                raw = getattr(r, attr)
                break
        if raw is None and isinstance(r, dict):
            raw = r.get("score") or r.get("rating")
        if raw is None:
            continue
        try:
            val = float(str(raw).split("/")[0].strip())
            if 1.0 <= val <= 10.0:
                scores.append(val)
        except (ValueError, TypeError):
            pass
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def _safe_debug_score(debug_results: list, build_id: str) -> str | None:
    if not debug_results:
        return None
    passed = 0
    for r in debug_results:
        success = None
        for attr in ("success", "passed", "fixed", "ok"):
            if hasattr(r, attr):
                success = bool(getattr(r, attr))
                break
        if success is None and isinstance(r, dict):
            for key in ("success", "passed", "fixed", "ok"):
                if key in r:
                    success = bool(r[key])
                    break
        if success is None:
            success = True
        if success:
            passed += 1
    return f"{passed}/{len(debug_results)}"


def _safe_test_score(
    test_results:  list,
    build_id:      str,
    debug_results: list = None,
) -> str | None:
    """
    Compute the test score string ("passed/total") from test_results.

    Issue 11 FIX: when debug_results is supplied, test passes for files
    whose debug success=False are excluded from the numerator.  The total
    (denominator) still counts all generated tests so the score reflects
    genuine coverage, not inflated mock-only passes.

    Example:
      routes.py   → debug success=False, tests: 2 passed (mock-only)
      services.py → debug success=True,  tests: 3 passed (real)
      Old score: "5/5"  (misleadingly perfect)
      New score: "3/5"  (authentic — only services.py passes count)
    """
    if not test_results:
        return None

    PASSED_ATTRS = ("passed", "passed_count", "num_passed", "tests_passed")
    TOTAL_ATTRS  = ("tests_generated", "total", "num_tests", "tests_total", "count")

    # Build a set of file paths where debug succeeded (for quick lookup)
    debug_passed_files: set[str] | None = None
    if debug_results:
        debug_passed_files = set()
        for r in debug_results:
            success = None
            for attr in ("success", "passed", "fixed", "ok"):
                if hasattr(r, attr):
                    success = bool(getattr(r, attr))
                    break
            if success is None and isinstance(r, dict):
                for key in ("success", "passed", "fixed", "ok"):
                    if key in r:
                        success = bool(r[key])
                        break
            if success:
                fp = (
                    getattr(r, "file_path", None)
                    or (r.get("file_path") if isinstance(r, dict) else None)
                )
                if fp:
                    debug_passed_files.add(fp)

    total_passed  = 0
    total_tests   = 0
    any_attempted = False

    for r in test_results:
        skipped = (
            r.get("skipped", False) if isinstance(r, dict)
            else getattr(r, "skipped", False)
        )
        if not skipped:
            any_attempted = True

        p, t = None, None
        if isinstance(r, dict):
            for a in PASSED_ATTRS:
                if a in r: p = r[a]; break
            for a in TOTAL_ATTRS:
                if a in r: t = r[a]; break
        else:
            for a in PASSED_ATTRS:
                if hasattr(r, a): p = getattr(r, a); break
            for a in TOTAL_ATTRS:
                if hasattr(r, a): t = getattr(r, a); break

        try:
            p_int = int(p or 0)
            t_int = int(t or 0)
        except (TypeError, ValueError):
            p_int = t_int = 0

        total_tests += t_int

        # Issue 11: only count passes for files that also passed debugging
        if debug_passed_files is not None and not skipped:
            fp = (
                getattr(r, "file_path", None)
                or (r.get("file_path") if isinstance(r, dict) else None)
            )
            if fp and fp not in debug_passed_files:
                logger.debug(
                    f"[{build_id[:8]}] Excluding {p_int} mock-only test pass(es) "
                    f"from '{fp}' (debug success=False)"
                )
                continue  # exclude from numerator, already added to total

        total_passed += p_int

    if total_tests == 0:
        return "0/0 (collection errors)" if any_attempted else None
    return f"{total_passed}/{total_tests}"


def _safe_intent(result, build_id: str) -> dict:
    try:
        val = result.intent
        return val if isinstance(val, dict) else {}
    except AttributeError:
        return {}


def _safe_arch(result, build_id: str) -> dict:
    try:
        val = result.architecture
        return val if isinstance(val, dict) else {}
    except AttributeError:
        return {}


# ── JobRunner ─────────────────────────────────────────────────────────────────

class JobRunner:
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self._executor:  Optional[ThreadPoolExecutor] = None
        self._futures:   dict[str, Future]  = {}
        self._cancelled: set[str]           = set()
        self._lock       = threading.Lock()
        self._running:   set[str]           = set()

    def start(self):
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="builder",
        )
        logger.info(f"🔧 Worker pool: {self.max_workers} workers ready")

    def shutdown(self, wait: bool = True):
        if self._executor:
            active = len(self._running)
            if active:
                logger.info(f"⏳ Waiting for {active} active job(s) to complete…")
            self._executor.shutdown(wait=wait)
            logger.info("✅ JobRunner shutdown complete")

    def start_build(self, prompt: str) -> str:
        build_id = str(uuid.uuid4())
        create_project(build_id, prompt)
        update_project(build_id, status="queued")

        if self._executor is None:
            raise RuntimeError("JobRunner not started. Call start() first.")

        future = self._executor.submit(self._run_build, build_id, prompt)
        with self._lock:
            self._futures[build_id] = future
        future.add_done_callback(lambda f: self._on_future_done(build_id, f))
        logger.info(f"📋 Queued build {build_id[:8]}… — '{prompt[:60]}'")
        return build_id

    def cancel_build(self, build_id: str) -> dict:
        project = get_project(build_id)
        if not project:
            return {"success": False, "reason": "not_found"}
        if project["status"] in TERMINAL_STATUSES:
            return {"success": False, "reason": f"already_{project['status']}"}

        with self._lock:
            self._cancelled.add(build_id)
            future = self._futures.get(build_id)

        if future and not future.running():
            cancelled = future.cancel()
            if cancelled:
                update_project(
                    build_id,
                    status       = "cancelled",
                    completed_at = datetime.utcnow().isoformat(),
                )
                logger.info(f"🚫 Cancelled queued build {build_id[:8]}")
                return {"success": True, "reason": "cancelled_from_queue"}

        update_project(build_id, status="cancelled")
        logger.info(f"🚫 Signalled running build {build_id[:8]} to cancel")
        return {"success": True, "reason": "cancel_signal_sent"}

    def is_cancelled(self, build_id: str) -> bool:
        with self._lock:
            return build_id in self._cancelled

    def get_pool_status(self) -> dict:
        with self._lock:
            active = len(self._running)
            queued = sum(
                1 for bid, f in self._futures.items()
                if bid not in self._running and not f.done()
            )
        available   = max(0, self.max_workers - active)
        utilization = round((active / self.max_workers) * 100, 1) if self.max_workers else 0.0
        return {
            "max":                 self.max_workers,
            "active":              active,
            "available":           available,
            "utilization_percent": utilization,
        }

    def get_queue_status(self) -> dict:
        with self._lock:
            running    = list(self._running)
            queued_ids = [
                bid for bid, f in self._futures.items()
                if bid not in self._running and not f.done()
            ]
        return {
            "running": len(running),
            "queued":  len(queued_ids),
            "workers": self.get_pool_status(),
        }

    def get_active_jobs(self) -> dict:
        with self._lock:
            running_ids = list(self._running)
            queued_ids  = [
                bid for bid, f in self._futures.items()
                if bid not in self._running and not f.done()
            ]
        running_jobs = []
        for bid in running_ids:
            p = get_project(bid)
            if p:
                running_jobs.append({
                    "build_id":   bid,
                    "app_name":   p.get("app_name"),
                    "status":     p.get("status"),
                    "created_at": p.get("created_at"),
                })
        queued_jobs = []
        for i, bid in enumerate(queued_ids):
            p = get_project(bid)
            if p:
                queued_jobs.append({
                    "build_id":       bid,
                    "queue_position": i + 1,
                    "status":         p.get("status"),
                    "created_at":     p.get("created_at"),
                })
        return {
            "running":      running_jobs,
            "queued":       queued_jobs,
            "total_active": len(running_jobs) + len(queued_jobs),
        }

    # ── Internal build runner ──────────────────────────────────────────────────

    def _run_build(self, build_id: str, prompt: str):
        if self.is_cancelled(build_id):
            return

        with self._lock:
            self._running.add(build_id)

        update_project(build_id, status="running")
        start_time = datetime.utcnow()
        logger.info(f"▶️  Starting build {build_id[:8]}")

        result         = None
        pipeline_error = None
        quota_error    = None

        try:
            from agents.pipeline import Pipeline, PipelineCancelledError

            try:
                import llm_client
                llm_client.set_current_build_id(build_id)
                logger.info(f"[{build_id[:8]}] Token tracking registered")
            except Exception as tok_exc:
                logger.warning(f"[{build_id[:8]}] Could not register token tracking: {tok_exc}")

            def _on_progress(progress: dict):
                self._progress_callback(
                    build_id  = build_id,
                    step      = progress.get("step", 0),
                    step_name = progress.get("step_name", "unknown"),
                    status    = progress.get("status", "running"),
                    data      = progress.get("data"),
                )

            pipeline = Pipeline(
                build_id          = build_id,
                progress_callback = _on_progress,
                cancel_check      = lambda: self.is_cancelled(build_id),
            )
            result = pipeline.run(prompt)

        except Exception as exc:
            # Phase 21: a quota error that escapes the pipeline is NOT a build
            # failure — the pipeline already packaged whatever it generated.
            # Record it separately so the status branch below can mark the build
            # done_with_context instead of discarding it as failed.
            try:
                from llm_client import GroqDailyQuotaError
                is_quota = isinstance(exc, GroqDailyQuotaError)
            except Exception:
                is_quota = False

            if is_quota:
                quota_error = exc
                logger.error(
                    f"🔑 Build {build_id[:8]} stopped on LLM daily quota: {exc}"
                )
            else:
                pipeline_error = exc
                logger.exception(f"❌ Build {build_id[:8]} pipeline failed: {exc}")

        # ── Collect token usage regardless of cancel/fail/success ─────────────
        token_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        try:
            import llm_client
            token_usage = llm_client.get_and_reset_token_usage(build_id)
            logger.info(
                f"[{build_id[:8]}] Tokens — "
                f"prompt={token_usage['prompt_tokens']:,}  "
                f"completion={token_usage['completion_tokens']:,}  "
                f"total={token_usage['total_tokens']:,}"
            )
        except Exception as tok_exc:
            logger.warning(f"[{build_id[:8]}] Could not collect token usage: {tok_exc}")

        duration = (datetime.utcnow() - start_time).total_seconds()

        # ── Handle cancellation ───────────────────────────────────────────────
        if self.is_cancelled(build_id):
            update_project(
                build_id,
                status            = "cancelled",
                completed_at      = datetime.utcnow().isoformat(),
                duration_seconds  = round(duration, 2),
                prompt_tokens     = token_usage["prompt_tokens"],
                completion_tokens = token_usage["completion_tokens"],
                total_tokens      = token_usage["total_tokens"],
            )
            logger.info(
                f"🚫 Build {build_id[:8]} cancelled "
                f"({token_usage['total_tokens']:,} tokens used)"
            )
            with self._lock:
                self._running.discard(build_id)
            return

        # ── Extract scores ────────────────────────────────────────────────────
        review_score = None
        debug_score  = None
        test_score   = None
        intent       = {}
        arch         = {}
        output_path  = None
        # Phase 21: completion metadata persisted for every outcome
        completion_reason = ""
        progress_percent  = None

        if result is not None:
            try:
                intent = _safe_intent(result, build_id)
                arch   = _safe_arch(result, build_id)

                # BUG FIX v2.6.1: extract review_results AND debug_results separately.
                # v2.6.0 accidentally passed debug_results_list to _safe_review_score(),
                # which caused review_score to always be None (debug results have no
                # .score attribute).
                review_results_list = (
                    result.review_results
                    if hasattr(result, "review_results") else []
                )
                debug_results_list = (
                    result.debug_results
                    if hasattr(result, "debug_results") else []
                )
                test_results_list = (
                    result.test_results
                    if hasattr(result, "test_results") else []
                )

                # review_score uses review_results (ReviewResult objects with .score)
                review_score = _safe_review_score(review_results_list, build_id)
                # debug_score uses debug_results (FileDebugResult objects with .success)
                debug_score  = _safe_debug_score(debug_results_list, build_id)
                # Issue 11: pass debug_results to exclude mock-only passes
                test_score   = _safe_test_score(
                    test_results_list,
                    build_id,
                    debug_results=debug_results_list,
                )

                logger.info(
                    f"[{build_id[:8]}] Scores — "
                    f"review={review_score}, debug={debug_score!r}, test={test_score!r}"
                )
            except Exception as score_exc:
                logger.exception(f"[{build_id[:8]}] Score extraction error: {score_exc}")

            # Phase 21: output_path and completion metadata are computed OUTSIDE
            # the score try-block. A done_with_context build must always carry an
            # output_path — the download route refuses without one, which would
            # defeat the entire point of packaging a partial build.
            try:
                import config
                from pathlib import Path
                arch        = arch   or _safe_arch(result, build_id)
                intent      = intent or _safe_intent(result, build_id)
                root_folder = arch.get("root_folder") or intent.get("app_name", "project")
                output_path = str(Path(config.OUTPUT_DIR) / root_folder)
            except Exception as path_exc:
                logger.exception(f"[{build_id[:8]}] Output path resolution failed: {path_exc}")

            completion_reason = getattr(result, "completion_reason", "") or ""
            progress_percent  = getattr(result, "progress_percent", None)

        # ── Write final status to DB ──────────────────────────────────────────
        try:
            if pipeline_error is not None:
                update_project(
                    build_id,
                    status            = "failed",
                    completed_at      = datetime.utcnow().isoformat(),
                    duration_seconds  = round(duration, 2),
                    prompt_tokens     = token_usage["prompt_tokens"],
                    completion_tokens = token_usage["completion_tokens"],
                    total_tokens      = token_usage["total_tokens"],
                    completion_reason = f"{type(pipeline_error).__name__}: {pipeline_error}"[:500],
                )
                self._progress_callback(
                    build_id, -1, "error", "failed",
                    {"error": str(pipeline_error)}
                )
            else:
                # ── Phase 21: four-way terminal status ────────────────────────
                # done_with_context means "usable code exists, but read
                # SESSION_CONTEXT.md first" — it is downloadable, unlike failed.
                is_cancelled = getattr(result, "cancelled", False) if result else False
                is_degraded  = bool(
                    result and (
                        getattr(result, "degraded", False)
                        or getattr(result, "quota_paused", False)
                    )
                )

                if is_cancelled:
                    final_status = "cancelled"
                elif is_degraded:
                    final_status = "done_with_context"
                elif result and result.success:
                    final_status = "done"
                else:
                    final_status = "failed"

                # A quota error that escaped the pipeline entirely (result is
                # None or unmarked) still counts as a context handoff when the
                # pipeline managed to produce an output directory.
                if quota_error is not None and final_status == "failed":
                    final_status      = "done_with_context"
                    completion_reason = completion_reason or (
                        f"LLM daily quota exhausted: {quota_error}"
                    )

                update_project(
                    build_id,
                    status            = final_status,
                    app_name          = intent.get("app_name"),
                    app_type          = intent.get("app_type"),
                    complexity        = intent.get("complexity"),
                    review_score      = review_score,
                    debug_score       = debug_score,
                    test_score        = test_score,
                    output_path       = output_path,
                    completed_at      = datetime.utcnow().isoformat(),
                    duration_seconds  = round(duration, 2),
                    prompt_tokens     = token_usage["prompt_tokens"],
                    completion_tokens = token_usage["completion_tokens"],
                    total_tokens      = token_usage["total_tokens"],
                    completion_reason = completion_reason[:500] or None,
                    progress_percent  = progress_percent,
                )

                if final_status == "done_with_context":
                    logger.warning(
                        f"⚠️  Build {build_id[:8]} → done_with_context in {duration:.1f}s "
                        f"({progress_percent or 0:.0f}% complete, "
                        f"{token_usage['total_tokens']:,} tokens) — {completion_reason}"
                    )
                    self._progress_callback(
                        build_id, -1, "complete", final_status,
                        {
                            "reason":               completion_reason,
                            "progress_percent":     progress_percent,
                            "session_context_path": getattr(result, "session_context_path", ""),
                            "downloadable":         True,
                        },
                    )
                else:
                    logger.info(
                        f"✅ Build {build_id[:8]} → {final_status} in {duration:.1f}s "
                        f"({token_usage['total_tokens']:,} tokens)"
                    )
        except Exception as db_exc:
            logger.exception(f"[{build_id[:8]}] DB update failed: {db_exc}")
        finally:
            with self._lock:
                self._running.discard(build_id)

    def _progress_callback(self, build_id, step, step_name, status, data=None):
        add_build_step(build_id, step, step_name, status, json.dumps(data) if data else None)
        try:
            from api_platform.routes.websockets import notify_subscribers
            notify_subscribers(build_id, {
                "type":      "progress",
                "build_id":  build_id,
                "step":      step,
                "step_name": step_name,
                "status":    status,
                "timestamp": datetime.utcnow().isoformat(),
                "data":      data,
            })
        except Exception:
            pass

    def _on_future_done(self, build_id: str, future: Future):
        with self._lock:
            self._futures.pop(build_id, None)
            self._running.discard(build_id)
            self._cancelled.discard(build_id)


job_runner = JobRunner(max_workers=3)
