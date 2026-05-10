"""
api_platform/routes/jobs.py  (Phase 14 - fixed + logs endpoint added)
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException
from api_platform.runner import job_runner
from api_platform.database import get_project, get_build_progress

router = APIRouter(prefix="/jobs", tags=["jobs"])

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
    Poll every 5-10 seconds to watch progress live.
    Use WS /ws/jobs/{build_id} for push-based updates.
    """
    project = get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found")

    status = project["status"]
    steps  = get_build_progress(build_id)

    current_step = 0
    step_name    = "pending"
    step_status  = "pending"

    if steps:
        latest       = steps[-1]
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
                    # Phase 17: structured step payload (elapsed_seconds, error, traceback)
                    "data":   s.get("data"),  # raw JSON string; frontend JSON.parses it
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
        "app_name":     project.get("app_name"),
        "app_type":     project.get("app_type"),
        "complexity":   project.get("complexity"),
        "review_score": project.get("review_score"),
        "debug_score":  project.get("debug_score"),
        "test_score":   project.get("test_score"),
        "output_path":  project.get("output_path"),
    }

    if status == "running":
        elapsed = _elapsed(project["created_at"])
        response["elapsed_seconds"] = elapsed
        if current_step > 0:
            secs_per_step = elapsed / current_step
            remaining_steps = 9 - current_step
            response["estimated_remaining_seconds"] = round(secs_per_step * remaining_steps)
        response["poll_hint"] = "Poll this endpoint every 5-10s to see progress, or use WS /ws/jobs/{build_id}"

    if status == "queued":
        active = job_runner.get_active_jobs()
        queued_ids = [j["build_id"] for j in active.get("queued", [])]
        if build_id in queued_ids:
            response["queue_position"] = queued_ids.index(build_id) + 1
            response["poll_hint"] = "Build is queued. Poll to see when it starts running."

    return response


@router.get("/{build_id}/logs")
async def get_build_logs(build_id: str):
    """
    Get detailed per-step build logs for a completed or running build.
    Returns all recorded pipeline steps with timestamps and data payloads.
    """
    project = get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found")

    steps = get_build_progress(build_id)

    return [
        {
            "step":      s["step"],
            "step_name": s["step_name"],
            "status":    s["status"],
            "timestamp": s["timestamp"],
            "data":      s.get("data"),   # raw JSON string from DB
        }
        for s in steps
    ]


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
