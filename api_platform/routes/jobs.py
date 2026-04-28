"""
api_platform/routes/jobs.py  (Phase 14 - fixed)

Fix: status endpoint now shows live elapsed_seconds and estimated_remaining
     for running builds, so polling every few seconds shows visible progress.
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException
from api_platform.runner import job_runner
from api_platform.database import get_project, get_build_progress

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Average step durations in seconds (rough estimates for progress display)
STEP_NAMES = [
    "intent_analyzer",
    "planner",
    "architect",
    "backend_developer",
    "frontend_generator",
    "debugger",
    "reviewer",
    "tester",
    "documenter",
]


def _elapsed(created_at: str) -> float:
    """Seconds since build started."""
    try:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                start = datetime.strptime(created_at, fmt)
                return round((datetime.utcnow() - start).total_seconds(), 1)
            except ValueError:
                continue
    except Exception:
        pass
    return 0.0


@router.get("/{build_id}/status")
async def get_job_status(build_id: str):
    """
    Get real-time job status and progress.

    For running builds, returns:
    - elapsed_seconds: how long the build has been running
    - current_step / step_name: the most recently started agent
    - completed_steps: all steps recorded so far

    Poll every 5-10 seconds to watch progress live.
    Use WS /ws/jobs/{build_id} for push-based updates.

    Status values:
    - pending:   created, not yet queued
    - queued:    waiting for a free worker
    - running:   build in progress
    - done:      completed successfully
    - failed:    build failed
    - cancelled: cancelled by user
    """
    project = get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found")

    status = project["status"]

    # Get all recorded progress steps
    steps = get_build_progress(build_id)

    current_step = 0
    step_name    = "pending"
    step_status  = "pending"

    if steps:
        latest      = steps[-1]
        current_step = latest["step"]
        step_name    = latest["step_name"]
        step_status  = latest["status"]

    response = {
        "build_id":         build_id,
        "status":           status,
        "current_step":     current_step,
        "total_steps":      9,
        "step_name":        step_name,
        "step_status":      step_status,
        "progress": {
            "step":      current_step,
            "step_name": step_name,
            "percent":   round((current_step / 9) * 100) if current_step > 0 else 0,
            "completed_steps": [
                {
                    "step":   s["step"],
                    "name":   s["step_name"],
                    "status": s["status"],
                    "at":     s["timestamp"],
                }
                for s in steps
            ],
            "remaining_steps": [
                name for i, name in enumerate(STEP_NAMES, start=1)
                if i > current_step
            ],
        },
        "started_at":        project.get("created_at"),
        "completed_at":      project.get("completed_at"),
        "duration_seconds":  project.get("duration_seconds"),
        # Result fields (populated when done)
        "app_name":     project.get("app_name"),
        "app_type":     project.get("app_type"),
        "complexity":   project.get("complexity"),
        "review_score": project.get("review_score"),
        "debug_score":  project.get("debug_score"),
        "test_score":   project.get("test_score"),
        "output_path":  project.get("output_path"),
    }

    # Add live timing info for running builds
    if status == "running":
        elapsed = _elapsed(project["created_at"])
        response["elapsed_seconds"] = elapsed
        # Estimate remaining based on average build time (~90s per step seen so far)
        if current_step > 0:
            secs_per_step = elapsed / current_step
            remaining_steps = 9 - current_step
            response["estimated_remaining_seconds"] = round(secs_per_step * remaining_steps)
        response["poll_hint"] = "Poll this endpoint every 5-10s to see progress, or use WS /ws/jobs/{build_id}"

    # Add queue position for queued builds
    if status == "queued":
        active = job_runner.get_active_jobs()
        queued_ids = [j["build_id"] for j in active.get("queued", [])]
        if build_id in queued_ids:
            response["queue_position"] = queued_ids.index(build_id) + 1
            response["poll_hint"] = "Build is queued. Poll to see when it starts running."

    return response


@router.get("/queue")
async def get_queue_status():
    """Get current job queue statistics — worker utilization, running count, queue depth."""
    return job_runner.get_queue_status()


@router.delete("/{build_id}")
async def cancel_job(build_id: str):
    """
    Cancel a running or queued job.
    Returns 409 if the job is already in a terminal state.
    """
    project = get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found")

    if project["status"] in ("done", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel job with status '{project['status']}'"
        )

    result = job_runner.cancel_build(build_id)

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel: {result.get('reason', 'unknown')}"
        )

    return {
        "message": f"Build {build_id} cancelled",
        "build_id": build_id,
        "reason":   result.get("reason"),
    }


@router.get("/active")
async def get_active_jobs():
    """List all currently running and queued jobs with details."""
    return job_runner.get_active_jobs()
