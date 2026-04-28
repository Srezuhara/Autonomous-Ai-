"""
api_platform/routes/projects.py  (Phase 14 - fixed)
====================================================
Rewritten to match the Phase 13/14 JobRunner and database.
The new runner:
  - start_build(prompt) only — no build_id kwarg
  - no get_job(), list_jobs(), delete_job()
  - all project data lives in the database
"""

import logging
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from api_platform.models import BuildRequest, BuildStatus, ProjectSummary, ProjectDetail
from api_platform.runner import job_runner
from api_platform.database import get_project, list_projects, delete_project, get_project_files

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", status_code=202)
async def create_project(request: BuildRequest):
    """
    Start a new project build.

    Returns immediately with build_id and status "queued".
    The build runs in the background.
    Poll GET /jobs/{build_id}/status for progress updates.
    """
    try:
        build_id = job_runner.start_build(request.prompt)  # returns build_id str
        logger.info(f"📝 Created build {build_id[:8]}: {request.prompt[:50]}...")
        return {
            "build_id": build_id,
            "status": "queued",
            "prompt": request.prompt,
            "started_at": None,
            "progress": None,
            "status_url": f"/jobs/{build_id}/status",
        }
    except Exception as e:
        logger.error(f"❌ Failed to start build: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def list_all_projects(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=None),
):
    """List all projects, newest first. Optionally filter by status."""
    try:
        projects = list_projects(limit=limit, offset=offset)

        # Optional status filter
        if status:
            projects = [p for p in projects if p.get("status") == status]

        return {
            "total": len(projects),
            "limit": limit,
            "offset": offset,
            "projects": projects,
        }
    except Exception as e:
        logger.error(f"❌ Failed to list projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{build_id}")
async def get_project_detail(build_id: str):
    """Get full details for a single project including files and progress."""
    project = get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found")

    # Attach file list
    files = get_project_files(build_id)
    project["files"] = [f["file_path"] for f in files]
    project["file_count"] = len(files)

    return project


@router.delete("/{build_id}")
async def delete_project_endpoint(build_id: str):
    """
    Delete a project from the database and its generated files from disk.
    If the build is still running/queued it will be cancelled first.
    """
    project = get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Build {build_id} not found")

    # Cancel if still active
    if project["status"] in ("queued", "running"):
        job_runner.cancel_build(build_id)

    # Delete files from disk
    files_deleted = False
    output_path = project.get("output_path")
    if output_path:
        p = Path(output_path)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            files_deleted = True
            logger.info(f"🗑️  Deleted files: {p}")

    # Delete from DB (cascades to files + build_progress tables)
    delete_project(build_id)

    return {
        "message": f"Build {build_id} deleted successfully",
        "build_id": build_id,
        "files_deleted": files_deleted,
    }
