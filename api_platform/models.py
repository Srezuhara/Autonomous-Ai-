"""
api_platform/models.py  (Phase 14 - fixed)
==========================================
Cleaned up Pydantic models to match what the new runner/database actually returns.
Key fix: BuildRequest no longer has force_rebuild (was causing bad Swagger default body).
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any


class BuildRequest(BaseModel):
    """Request to start a new project build."""
    prompt: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="What app to build",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "prompt": "Build a todo app with FastAPI backend and React frontend"
            }
        }
    }


class BuildStatus(BaseModel):
    """Immediate response when a build is created."""
    build_id: str
    status: str
    prompt: str
    started_at: Optional[datetime] = None
    progress: Optional[Dict[str, Any]] = None
    status_url: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "build_id": "a1b2c3d4-...",
                "status": "queued",
                "prompt": "Build a todo app",
                "started_at": None,
                "progress": None,
                "status_url": "/jobs/a1b2c3d4-.../status",
            }
        }
    }


class ProjectSummary(BaseModel):
    """Lightweight project list item."""
    build_id: str
    app_name: Optional[str] = None
    app_type: Optional[str] = None
    status: str
    debug_score: Optional[str] = None
    review_score: Optional[float] = None
    test_score: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class ProjectDetail(BaseModel):
    """Full project details including files."""
    build_id: str
    prompt: str
    app_name: Optional[str] = None
    app_type: Optional[str] = None
    complexity: Optional[str] = None
    status: str
    debug_score: Optional[str] = None
    review_score: Optional[float] = None
    test_score: Optional[str] = None
    output_path: Optional[str] = None
    files: List[str] = []
    file_count: int = 0
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class CleanupRequest(BaseModel):
    """Request body for the cleanup endpoint."""
    older_than_days: int = Field(default=30, ge=1)
    statuses: List[str] = ["done", "failed", "cancelled"]
    dry_run: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "older_than_days": 30,
                "statuses": ["done", "failed", "cancelled"],
                "dry_run": True,
            }
        }
    }


class HealthCheck(BaseModel):
    """Health check response."""
    status: str
    version: str
    timestamp: str
    worker_pool: Dict[str, Any]
    features: Dict[str, bool]
