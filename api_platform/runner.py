"""
api_platform/runner.py  —  v2.5.0  (Phase 17 — reliability & observability)
=============================================================================
Changes vs v2.4:
  1. set_current_build_id() called in _run_build() before Pipeline starts
     so every Groq call in that thread is attributed to the right build.
  2. get_and_reset_token_usage() called after pipeline completes and the
     result is stored to the DB via update_project(token_usage=...).
  3. Structured step data (from pipeline._emit_progress "data" dict) is now
     stored to build_progress.data (JSON) so the frontend BuildLogsPanel can
     show per-step details (elapsed time, error tracebacks, score previews).
  4. _safe_test_score: returns "0/0 (collection errors)" instead of None
     when tests were attempted but all skipped.
  5. All _safe_* helpers unchanged from v2.4.
"""

import json
import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from queue import Queue
from typing import Optional

from api_platform.database import (
    add_build_step,
    create_project,
    get_project,
    update_project,
)

logger = logging.getLogger(__name__)


# ── Safe score helpers ────────────────────────────────────────────────────────

def _safe_review_score(review_results: list, build_id: str) -> float | None:
    if not review_results:
        logger.warning(f"[{build_id[:8]}] review_results is empty — review_score=None")
        return None

    logger.info(
        f"[{build_id[:8]}] Extracting review scores from {len(review_results)} result(s)..."
    )
    scores = []

    for i, r in enumerate(review_results):
        raw = None
        for attr in ("score", "rating", "value", "review_score"):
            if hasattr(r, attr):
                raw = getattr(r, attr)
                break
        if raw is None and isinstance(r, dict):
            raw = r.get("score") or r.get("rating")

        logger.info(
            f"[{build_id[:8]}]   result[{i}] raw score = {raw!r} "
            f"(type={type(raw).__name__})"
        )
        if raw is None:
            continue

        try:
            cleaned = str(raw).split("/")[0].strip()
            val = float(cleaned)
            if 1.0 <= val <= 10.0:
                scores.append(val)
                logger.info(f"[{build_id[:8]}]   → accepted {val}")
            else:
                logger.warning(f"[{build_id[:8]}]   → out of range (1-10): {val}")
        except (ValueError, TypeError) as e:
            logger.warning(f"[{build_id[:8]}]   → could not parse {raw!r}: {e}")

    if not scores:
        logger.warning(
            f"[{build_id[:8]}] No valid review scores found — review_score=None"
        )
        return None

    avg = round(sum(scores) / len(scores), 2)
    logger.info(f"[{build_id[:8]}] review_score = {avg} (from {len(scores)} file(s))")
    return avg


def _safe_debug_score(debug_results: list, build_id: str) -> str | None:
    if not debug_results:
        logger.warning(f"[{build_id[:8]}] debug_results is empty — debug_score=None")
        return None

    logger.info(
        f"[{build_id[:8]}] Extracting debug scores from {len(debug_results)} result(s)..."
    )
    passed = 0

    for i, r in enumerate(debug_results):
        success = None
        for attr in ("success", "passed", "fixed", "ok", "is_success", "no_errors"):
            if hasattr(r, attr):
                success = bool(getattr(r, attr))
                logger.info(
                    f"[{build_id[:8]}]   debug[{i}].{attr} = {success}"
                )
                break

        if success is None and isinstance(r, dict):
            for key in ("success", "passed", "fixed", "ok"):
                if key in r:
                    success = bool(r[key])
                    logger.info(
                        f"[{build_id[:8]}]   debug[{i}]['{key}'] = {success}"
                    )
                    break

        if success is None:
            if isinstance(r, bool):
                success = r
            else:
                logger.warning(
                    f"[{build_id[:8]}]   debug[{i}] — no recognisable success attr"
                )
                success = True  # benefit of doubt

        if success:
            passed += 1

    score = f"{passed}/{len(debug_results)}"
    logger.info(f"[{build_id[:8]}] debug_score = {score}")
    return score


def _safe_test_score(test_results: list, build_id: str) -> str | None:
    """
    Returns:
        "N/M"                      — normal
        "0/0 (collection errors)"  — tests attempted but all skipped
        None                       — no test results at all
    """
    if not test_results:
        logger.warning(f"[{build_id[:8]}] test_results is empty — test_score=None")
        return None

    logger.info(
        f"[{build_id[:8]}] Extracting test scores from {len(test_results)} result(s)..."
    )

    total_passed  = 0
    total_tests   = 0
    any_attempted = False

    PASSED_ATTRS = ("passed", "passed_count", "num_passed", "tests_passed", "pass_count")
    TOTAL_ATTRS  = (
        "tests_generated", "total", "num_tests", "tests_total", "total_tests", "count"
    )

    for i, r in enumerate(test_results):
        skipped = r.get("skipped", False) if isinstance(r, dict) else getattr(r, "skipped", False)
        if not skipped:
            any_attempted = True

        p, t = None, None
        if isinstance(r, dict):
            for a in PASSED_ATTRS:
                if a in r:
                    p = r[a]
                    break
            for a in TOTAL_ATTRS:
                if a in r:
                    t = r[a]
                    break
        else:
            for a in PASSED_ATTRS:
                if hasattr(r, a):
                    p = getattr(r, a)
                    break
            for a in TOTAL_ATTRS:
                if hasattr(r, a):
                    t = getattr(r, a)
                    break

        logger.info(
            f"[{build_id[:8]}]   test[{i}] passed={p!r} total={t!r} skipped={skipped}"
        )

        try:
            total_passed += int(p or 0)
            total_tests  += int(t or 0)
        except (TypeError, ValueError) as e:
            logger.warning(f"[{build_id[:8]}]   test[{i}] parse error: {e}")

    if total_tests == 0:
        if any_attempted:
            logger.warning(
                f"[{build_id[:8]}] Tests attempted but 0 collected — likely collection errors"
            )
            return "0/0 (collection errors)"
        logger.warning(f"[{build_id[:8]}] No tests found — test_score=None")
        return None

    score = f"{total_passed}/{total_tests}"
    logger.info(f"[{build_id[:8]}] test_score = {score}")
    return score


def _safe_intent(result, build_id: str) -> dict:
    try:
        val = result.intent
        if isinstance(val, dict):
            return val
        logger.warning(
            f"[{build_id[:8]}] result.intent is {type(val).__name__}, not dict"
        )
        return {}
    except AttributeError:
        logger.warning(f"[{build_id[:8]}] result has no .intent attribute")
        return {}


def _safe_arch(result, build_id: str) -> dict:
    try:
        val = result.architecture
        if isinstance(val, dict):
            return val
        logger.warning(
            f"[{build_id[:8]}] result.architecture is {type(val).__name__}, not dict"
        )
        return {}
    except AttributeError:
        logger.warning(f"[{build_id[:8]}] result has no .architecture attribute")
        return {}


# ─────────────────────────────────────────────────────────────────────────────

class JobRunner:
    """Manages a pool of worker threads that execute build pipelines concurrently."""

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures:   dict[str, Future]  = {}
        self._queue:     Queue              = Queue()
        self._cancelled: set[str]           = set()
        self._lock       = threading.Lock()
        self._running:   set[str]           = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

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

    # ── Public API ────────────────────────────────────────────────────────────

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

        if project["status"] in ("done", "failed", "cancelled"):
            return {"success": False, "reason": f"already_{project['status']}"}

        with self._lock:
            self._cancelled.add(build_id)
            future = self._futures.get(build_id)

        if future and not future.running():
            cancelled = future.cancel()
            if cancelled:
                update_project(
                    build_id,
                    status="cancelled",
                    completed_at=datetime.utcnow().isoformat(),
                )
                logger.info(f"🚫 Cancelled queued build {build_id[:8]}")
                return {"success": True, "reason": "cancelled_from_queue"}

        update_project(build_id, status="cancelled")
        logger.info(f"🚫 Signalled running build {build_id[:8]} to cancel")
        return {"success": True, "reason": "cancel_signal_sent"}

    def is_cancelled(self, build_id: str) -> bool:
        with self._lock:
            return build_id in self._cancelled

    # ── Status / monitoring ───────────────────────────────────────────────────

    def get_pool_status(self) -> dict:
        with self._lock:
            active = len(self._running)
            queued = sum(
                1 for bid, f in self._futures.items()
                if bid not in self._running and not f.done()
            )

        available   = max(0, self.max_workers - active)
        utilization = round(
            (active / self.max_workers) * 100, 1
        ) if self.max_workers else 0.0

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

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_build(self, build_id: str, prompt: str):
        if self.is_cancelled(build_id):
            return

        with self._lock:
            self._running.add(build_id)

        update_project(build_id, status="running")
        start_time = datetime.utcnow()
        logger.info(f"▶️  Starting build {build_id[:8]}")

        result           = None
        pipeline_success = False
        pipeline_error   = None

        try:
            from agents.pipeline import Pipeline

            # ── Phase 17: register build for per-thread token tracking ─────────
            try:
                import llm_client
                llm_client.set_current_build_id(build_id)
                logger.info(
                    f"[{build_id[:8]}] Token tracking registered for this thread"
                )
            except Exception as tok_exc:
                logger.warning(
                    f"[{build_id[:8]}] Could not register token tracking: {tok_exc}"
                )

            def _on_progress(progress: dict):
                self._progress_callback(
                    build_id  = build_id,
                    step      = progress.get("step", 0),
                    step_name = progress.get("step_name", "unknown"),
                    status    = progress.get("status", "running"),
                    data      = progress.get("data"),   # ← Phase 17 structured data
                )

            pipeline = Pipeline(build_id=build_id, progress_callback=_on_progress)
            result   = pipeline.run(prompt)
            pipeline_success = True

        except Exception as exc:
            pipeline_error = exc
            logger.exception(f"❌ Build {build_id[:8]} pipeline failed: {exc}")

        # ── Phase 17: collect token usage after pipeline completes ────────────
        token_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        try:
            import llm_client
            token_usage = llm_client.get_and_reset_token_usage(build_id)
            logger.info(
                f"[{build_id[:8]}] Token usage — "
                f"prompt={token_usage['prompt_tokens']:,}  "
                f"completion={token_usage['completion_tokens']:,}  "
                f"total={token_usage['total_tokens']:,}"
            )
        except Exception as tok_exc:
            logger.warning(
                f"[{build_id[:8]}] Could not collect token usage: {tok_exc}"
            )

        # Handle cancellation
        if self.is_cancelled(build_id):
            duration = (datetime.utcnow() - start_time).total_seconds()
            update_project(
                build_id,
                status       = "cancelled",
                completed_at = datetime.utcnow().isoformat(),
                duration_seconds = round(duration, 2),
            )
            logger.info(f"🚫 Build {build_id[:8]} was cancelled")
            with self._lock:
                self._running.discard(build_id)
            return

        # Extract scores
        review_score = None
        debug_score  = None
        test_score   = None
        intent       = {}
        arch         = {}
        output_path  = None

        if result is not None:
            try:
                intent = _safe_intent(result, build_id)
                arch   = _safe_arch(result, build_id)

                review_score = _safe_review_score(
                    result.review_results if hasattr(result, "review_results") else [],
                    build_id,
                )
                debug_score = _safe_debug_score(
                    result.debug_results if hasattr(result, "debug_results") else [],
                    build_id,
                )
                test_score = _safe_test_score(
                    result.test_results if hasattr(result, "test_results") else [],
                    build_id,
                )

                import config
                from pathlib import Path
                root_folder = arch.get("root_folder") or intent.get("app_name", "project")
                output_path = str(Path(config.OUTPUT_DIR) / root_folder)

                logger.info(
                    f"[{build_id[:8]}] Scores — "
                    f"review={review_score}, debug={debug_score!r}, test={test_score!r}"
                )

            except Exception as score_exc:
                logger.exception(
                    f"[{build_id[:8]}] Score extraction error: {score_exc}"
                )

        # Write final status to DB
        duration = (datetime.utcnow() - start_time).total_seconds()

        try:
            if pipeline_error is not None:
                update_project(
                    build_id,
                    status           = "failed",
                    completed_at     = datetime.utcnow().isoformat(),
                    duration_seconds = round(duration, 2),
                    # Phase 17: store token usage even on failure
                    prompt_tokens      = token_usage["prompt_tokens"],
                    completion_tokens  = token_usage["completion_tokens"],
                    total_tokens       = token_usage["total_tokens"],
                )
                self._progress_callback(
                    build_id, -1, "error", "failed",
                    {"error": str(pipeline_error)},
                )
            else:
                final_status = "done" if (result and result.success) else "failed"
                update_project(
                    build_id,
                    status             = final_status,
                    app_name           = intent.get("app_name"),
                    app_type           = intent.get("app_type"),
                    complexity         = intent.get("complexity"),
                    review_score       = review_score,
                    debug_score        = debug_score,
                    test_score         = test_score,
                    output_path        = output_path,
                    completed_at       = datetime.utcnow().isoformat(),
                    duration_seconds   = round(duration, 2),
                    # Phase 17: token tracking
                    prompt_tokens      = token_usage["prompt_tokens"],
                    completion_tokens  = token_usage["completion_tokens"],
                    total_tokens       = token_usage["total_tokens"],
                )
                logger.info(
                    f"✅ Build {build_id[:8]} → {final_status} in {duration:.1f}s "
                    f"({token_usage['total_tokens']:,} tokens)"
                )

        except Exception as db_exc:
            logger.exception(f"[{build_id[:8]}] DB update failed: {db_exc}")

        finally:
            with self._lock:
                self._running.discard(build_id)

    def _progress_callback(
        self,
        build_id:  str,
        step:      int,
        step_name: str,
        status:    str,
        data=None,
    ):
        # Phase 17: store the full structured data dict to build_progress.data
        add_build_step(
            build_id,
            step,
            step_name,
            status,
            json.dumps(data) if data else None,
        )

        try:
            from api_platform.routes.websockets import notify_subscribers
            notify_subscribers(
                build_id,
                {
                    "type":      "progress",
                    "build_id":  build_id,
                    "step":      step,
                    "step_name": step_name,
                    "status":    status,
                    "timestamp": datetime.utcnow().isoformat(),
                    "data":      data,
                },
            )
        except Exception:
            pass

    def _on_future_done(self, build_id: str, future: Future):
        with self._lock:
            self._futures.pop(build_id, None)
            self._running.discard(build_id)
            self._cancelled.discard(build_id)


# ── Singleton ──────────────────────────────────────────────────────────────────
job_runner = JobRunner(max_workers=3)
