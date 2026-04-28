"""
api_platform/routes/analytics.py  (Phase 14 - fixed v2)

Fixes:
  - App type stats: derive a granular sub-type from the prompt when
    app_type is the generic "web_app", giving more useful breakdowns
  - Unknown entries excluded from stats
  - Missing Path import added to cleanup
"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api_platform import database as db

router = APIRouter(tags=["statistics"])


# ── App type classifier ────────────────────────────────────────────────────────

# Keyword → specific type mapping (checked in order, first match wins)
_TYPE_KEYWORDS: list[tuple[list[str], str]] = [
    (["todo", "task", "tasks"],                    "todo_app"),
    (["kanban", "board", "trello"],                "kanban_board"),
    (["chat", "messaging", "message", "slack"],    "chat_app"),
    (["blog", "cms", "content management"],        "blog_platform"),
    (["weather", "forecast", "climate"],           "weather_app"),
    (["dashboard", "analytics", "metrics"],        "dashboard"),
    (["ecommerce", "e-commerce", "shop", "store",
      "cart", "product"],                          "ecommerce"),
    (["auth", "login", "signup", "user management",
      "authentication"],                           "auth_service"),
    (["api", "rest api", "crud"],                  "rest_api"),
    (["portfolio", "resume", "cv"],                "portfolio"),
    (["social", "feed", "follow", "post"],         "social_app"),
    (["game", "quiz", "puzzle"],                   "game"),
    (["booking", "reservation", "appointment"],    "booking_app"),
    (["finance", "budget", "expense", "invoice"],  "finance_app"),
    (["inventory", "stock", "warehouse"],          "inventory_app"),
]


def _refine_app_type(app_type: str | None, prompt: str | None) -> str:
    """
    If app_type is a generic bucket like 'web_app' or 'api',
    try to derive a more specific type from the prompt text.
    Falls back to app_type or 'unknown'.
    """
    if not app_type:
        app_type = "unknown"

    # Already specific enough — keep it
    generic = {"web_app", "api", "application", "app", "unknown", "web", "website"}
    if app_type.lower() not in generic:
        return app_type.lower()

    # Try to classify from prompt
    if prompt:
        pl = prompt.lower()
        for keywords, refined_type in _TYPE_KEYWORDS:
            if any(kw in pl for kw in keywords):
                return refined_type

    return app_type.lower()


# ── Stats ──────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_platform_stats():
    """
    Overall platform statistics:
    success rate, average build duration, counts by status, top app types.

    App types are refined from the build prompt when the LLM returns a
    generic type like 'web_app', giving more useful breakdowns.
    """
    rows = db.list_projects(limit=10_000)

    total = len(rows)
    if total == 0:
        return {
            "total_builds": 0,
            "message": "No builds yet. Start your first build with POST /projects/",
        }

    # Counts by status
    by_status: dict[str, int] = {}
    for r in rows:
        s = r["status"]
        by_status[s] = by_status.get(s, 0) + 1

    done      = by_status.get("done", 0)
    failed    = by_status.get("failed", 0)
    completed = done + failed
    success_rate = round((done / completed * 100), 1) if completed else 0.0

    # Duration stats (done builds only)
    durations = [
        r["duration_seconds"] for r in rows
        if r.get("duration_seconds") and r["status"] == "done"
    ]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None
    min_duration = round(min(durations), 1) if durations else None
    max_duration = round(max(durations), 1) if durations else None

    # App types — refined from prompt, done builds only, exclude unknown
    type_counts: dict[str, int] = {}
    for r in rows:
        if r["status"] != "done":
            continue
        refined = _refine_app_type(r.get("app_type"), r.get("prompt"))
        if refined == "unknown":
            continue
        type_counts[refined] = type_counts.get(refined, 0) + 1

    top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:10]

    # Review scores (done builds only)
    scores = [r["review_score"] for r in rows if r.get("review_score") and r["status"] == "done"]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    # Today & this week
    now         = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = today_start - timedelta(days=7)

    builds_today = sum(
        1 for r in rows
        if r.get("created_at") and _parse_dt(r["created_at"]) >= today_start
    )
    builds_this_week = sum(
        1 for r in rows
        if r.get("created_at") and _parse_dt(r["created_at"]) >= week_start
    )

    return {
        "total_builds": total,
        "by_status": by_status,
        "success_rate_percent": success_rate,
        "builds_today": builds_today,
        "builds_this_week": builds_this_week,
        "duration_seconds": {
            "average": avg_duration,
            "min": min_duration,
            "max": max_duration,
        },
        "average_review_score": avg_score,
        "top_app_types": [{"type": t, "count": c} for t, c in top_types],
        "generated_at": now.isoformat(),
    }


@router.get("/stats/daily")
async def get_daily_stats(days: int = Query(default=30, ge=1, le=90)):
    """Builds per day for the last N days (default 30)."""
    rows = db.list_projects(limit=10_000)
    now  = datetime.utcnow()

    daily: dict[str, dict] = {}
    for i in range(days):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        daily[day] = {"date": day, "total": 0, "done": 0, "failed": 0, "cancelled": 0}

    for r in rows:
        if not r.get("created_at"):
            continue
        try:
            day = _parse_dt(r["created_at"]).strftime("%Y-%m-%d")
        except Exception:
            continue
        if day in daily:
            daily[day]["total"] += 1
            status = r.get("status", "unknown")
            if status in daily[day]:
                daily[day][status] += 1

    return {"days": days, "data": sorted(daily.values(), key=lambda x: x["date"])}


# ── Rebuild ────────────────────────────────────────────────────────────────────

@router.post("/projects/{build_id}/rebuild")
async def rebuild_project(build_id: str):
    """Start a new build using the exact same prompt. Original is untouched."""
    from api_platform.runner import job_runner

    project = db.get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {build_id} not found")

    prompt = project.get("prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Original project has no prompt stored")

    new_build_id = job_runner.start_build(prompt)
    return {
        "message": "Rebuild started",
        "original_build_id": build_id,
        "new_build_id": new_build_id,
        "prompt": prompt,
        "status_url": f"/jobs/{new_build_id}/status",
    }


# ── Cleanup ────────────────────────────────────────────────────────────────────

class CleanupRequest(BaseModel):
    older_than_days: int = 30
    statuses: list[str] = ["done", "failed", "cancelled"]
    dry_run: bool = True


@router.delete("/projects/cleanup")
async def cleanup_old_projects(req: CleanupRequest):
    """Delete old builds. Set dry_run=false to actually delete."""
    cutoff = datetime.utcnow() - timedelta(days=req.older_than_days)
    rows   = db.list_projects(limit=10_000)

    targets = []
    for r in rows:
        if r.get("status") not in req.statuses:
            continue
        if not r.get("created_at"):
            continue
        try:
            if _parse_dt(r["created_at"]) < cutoff:
                targets.append(r)
        except Exception:
            continue

    if req.dry_run:
        return {
            "dry_run": True,
            "would_delete": len(targets),
            "older_than_days": req.older_than_days,
            "statuses": req.statuses,
            "cutoff": cutoff.isoformat(),
            "projects": [
                {
                    "build_id": t["build_id"],
                    "app_name": t.get("app_name"),
                    "status": t["status"],
                    "created_at": t["created_at"],
                }
                for t in targets
            ],
            "hint": "Set dry_run=false to actually delete.",
        }

    deleted, errors = [], []
    for r in targets:
        bid = r["build_id"]
        try:
            out = r.get("output_path")
            if out and Path(out).exists():
                shutil.rmtree(out, ignore_errors=True)
            db.delete_project(bid)
            deleted.append(bid)
        except Exception as e:
            errors.append({"build_id": bid, "error": str(e)})

    return {
        "dry_run": False,
        "deleted": len(deleted),
        "errors": len(errors),
        "deleted_ids": deleted,
        "error_details": errors,
        "cutoff": cutoff.isoformat(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_dt(value: str) -> datetime:
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {value!r}")
