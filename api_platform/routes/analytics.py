"""
api_platform/routes/analytics.py  — Phase 19.5 (Rebuild Context Fix)

Changes vs Phase 17.1:
  - rebuild_project() now composes a COMBINED prompt when custom_prompt is given:
      original_prompt + "\n\n[REBUILD INSTRUCTIONS]\n" + custom_prompt
    This ensures the pipeline always knows WHAT app it is rebuilding AND what
    to improve, instead of treating the custom instructions as a standalone prompt.
  - Added `original_prompt` field to rebuild response for UI display.
  - All other behaviour identical to Phase 17.1.
"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api_platform import database as db

router = APIRouter(tags=["statistics"])


# ── App type classifier ────────────────────────────────────────────────────────

_TYPE_KEYWORDS: list[tuple[list[str], str]] = [
    (["todo", "task", "tasks"],                     "todo_app"),
    (["kanban", "board", "trello"],                 "kanban_board"),
    (["chat", "messaging", "message", "slack"],     "chat_app"),
    (["blog", "cms", "content management"],         "blog_platform"),
    (["weather", "forecast", "climate"],            "weather_app"),
    (["dashboard", "analytics", "metrics"],         "dashboard"),
    (["report", "pdf", "excel", "csv", "chart"],    "report_tool"),
    (["ecommerce", "e-commerce", "shop", "store",
      "cart", "product"],                           "ecommerce"),
    (["auth", "login", "signup", "authentication"], "auth_service"),
    (["api", "rest api", "crud"],                   "rest_api"),
    (["portfolio", "resume", "cv"],                 "portfolio"),
    (["social", "feed", "follow", "post"],          "social_app"),
    (["game", "quiz", "puzzle"],                    "game"),
    (["booking", "reservation", "appointment"],     "booking_app"),
    (["finance", "budget", "expense", "invoice"],   "finance_app"),
    (["inventory", "stock", "warehouse"],           "inventory_app"),
    (["scraper", "crawl", "spider"],                "web_scraper"),
    (["cli", "command line", "terminal", "script"], "cli_tool"),
]


def _refine_app_type(app_type: str | None, prompt: str | None) -> str:
    if not app_type:
        app_type = "unknown"
    generic = {"web_app", "api", "application", "app", "unknown", "web", "website"}
    if app_type.lower() not in generic:
        return app_type.lower()
    if prompt:
        pl = prompt.lower()
        for keywords, refined_type in _TYPE_KEYWORDS:
            if any(kw in pl for kw in keywords):
                return refined_type
    return app_type.lower()


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


# ── /stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_platform_stats():
    rows  = db.list_projects(limit=10_000)
    total = len(rows)

    empty_token_block = {
        "total_prompt_tokens":     0,
        "total_completion_tokens": 0,
        "total_tokens":            0,
        "avg_tokens_per_build":    None,
    }

    if total == 0:
        return {
            "total_builds":         0,
            "avg_duration_seconds": None,
            "duration_seconds":     {"average": None, "min": None, "max": None},
            "success_rate_percent": 0.0,
            "builds_today":         0,
            "builds_this_week":     0,
            "by_status":            {},
            "top_app_types":        [],
            "average_review_score": None,
            "token_usage":          empty_token_block,
            "message": "No builds yet. Start your first build with POST /projects/",
        }

    by_status: dict[str, int] = {}
    for r in rows:
        s = r.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1

    done      = by_status.get("done", 0)
    failed    = by_status.get("failed", 0)
    completed = done + failed
    success_rate = round((done / completed * 100), 1) if completed else 0.0

    durations = []
    for r in rows:
        if r.get("status") == "done" and r.get("duration_seconds") is not None:
            try:
                d = float(r["duration_seconds"])
                if d > 0:
                    durations.append(d)
            except (TypeError, ValueError):
                pass

    avg_duration = round(sum(durations) / len(durations), 1) if durations else None
    min_duration = round(min(durations), 1) if durations else None
    max_duration = round(max(durations), 1) if durations else None

    type_counts: dict[str, int] = {}
    for r in rows:
        if r.get("status") != "done":
            continue
        refined = _refine_app_type(r.get("app_type"), r.get("prompt"))
        if refined == "unknown":
            continue
        type_counts[refined] = type_counts.get(refined, 0) + 1

    top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:10]

    scores = []
    for r in rows:
        if r.get("status") == "done" and r.get("review_score") is not None:
            try:
                scores.append(float(r["review_score"]))
            except (TypeError, ValueError):
                pass
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    now         = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = today_start - timedelta(days=7)

    builds_today = 0
    builds_this_week = 0
    for r in rows:
        if not r.get("created_at"):
            continue
        try:
            dt = _parse_dt(r["created_at"])
            if dt >= today_start:
                builds_today += 1
            if dt >= week_start:
                builds_this_week += 1
        except Exception:
            pass

    # ── Token usage ───────────────────────────────────────────────────────────
    total_prompt_tokens     = 0
    total_completion_tokens = 0
    total_tokens_all        = 0
    builds_with_tokens      = 0

    for r in rows:
        pt = r.get("prompt_tokens") or 0
        ct = r.get("completion_tokens") or 0
        tt = r.get("total_tokens") or 0
        try:
            pt = int(pt); ct = int(ct); tt = int(tt)
        except (TypeError, ValueError):
            pt = ct = tt = 0

        total_prompt_tokens     += pt
        total_completion_tokens += ct
        total_tokens_all        += tt
        if tt > 0:
            builds_with_tokens += 1

    avg_tokens = (
        round(total_tokens_all / builds_with_tokens)
        if builds_with_tokens > 0 else None
    )

    return {
        "total_builds":          total,
        "avg_duration_seconds":  avg_duration,
        "duration_seconds": {
            "average": avg_duration,
            "min":     min_duration,
            "max":     max_duration,
        },
        "success_rate_percent":  success_rate,
        "builds_today":          builds_today,
        "builds_this_week":      builds_this_week,
        "by_status":             by_status,
        "top_app_types":         [{"type": t, "count": c} for t, c in top_types],
        "average_review_score":  avg_score,
        "token_usage": {
            "total_prompt_tokens":     total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens":            total_tokens_all,
            "avg_tokens_per_build":    avg_tokens,
        },
        "generated_at": now.isoformat(),
    }


# ── /stats/daily ───────────────────────────────────────────────────────────────

@router.get("/stats/daily")
async def get_daily_stats(days: int = Query(default=30, ge=1, le=90)):
    rows = db.list_projects(limit=10_000)
    now  = datetime.utcnow()

    daily: dict[str, dict] = {}
    for i in range(days):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        daily[day] = {
            "date":         day,
            "total":        0,
            "success":      0,
            "failed":       0,
            "cancelled":    0,
            "total_tokens": 0,
        }

    for r in rows:
        if not r.get("created_at"):
            continue
        try:
            day = _parse_dt(r["created_at"]).strftime("%Y-%m-%d")
        except Exception:
            continue

        if day not in daily:
            continue

        daily[day]["total"] += 1
        status = r.get("status", "unknown")
        if status == "done":
            daily[day]["success"] += 1
        elif status in ("failed", "cancelled"):
            daily[day][status] += 1

        try:
            daily[day]["total_tokens"] += int(r.get("total_tokens") or 0)
        except (TypeError, ValueError):
            pass

    return {
        "days": days,
        "data": sorted(daily.values(), key=lambda x: x["date"]),
    }


# ── /projects/{id}/rebuild ─────────────────────────────────────────────────────

class RebuildRequest(BaseModel):
    """
    Optional body for rebuild endpoint.

    - custom_prompt: additional instructions describing what to improve.
      When provided, the pipeline receives a COMBINED prompt:
        "<original_prompt>\n\n[REBUILD INSTRUCTIONS]\n<custom_prompt>"
      This ensures the pipeline understands WHAT app to build AND what
      to change — preventing the "builds a new app from scratch" bug
      where only the custom_prompt was used as the full build prompt.

    - If omitted or empty, the original project prompt is reused unchanged
      (same-prompt rebuild behaviour).
    """
    custom_prompt: str = ""


def _build_combined_prompt(original_prompt: str, custom_prompt: str) -> str:
    """
    Combine original project description with custom rebuild instructions.

    The output reads naturally to the IntentAnalyzer so it correctly
    identifies the app type, then picks up the improvements from the
    REBUILD INSTRUCTIONS block.

    Example output:
        Create a Python AI report generator that takes CSV/Excel data,
        analyzes it, generates charts, and produces a professional PDF
        report with insights using reportlab and matplotlib.

        [REBUILD INSTRUCTIONS]
        Improve test coverage and add integration tests.
        Improve error handling and add input validation.
        Make the UI more responsive and mobile-friendly.
    """
    custom = custom_prompt.strip()
    original = original_prompt.strip()

    if not custom:
        return original

    return (
        f"{original}\n\n"
        f"[REBUILD INSTRUCTIONS]\n"
        f"{custom}"
    )


@router.post("/projects/{build_id}/rebuild")
async def rebuild_project(build_id: str, body: RebuildRequest = None):
    """
    Start a new build from an existing project.

    - No body / empty custom_prompt → re-runs the original prompt unchanged.
    - custom_prompt provided → builds with original context + improvement instructions.
      The IntentAnalyzer will see the full original description so it generates
      the correct app type and structure, then applies the requested improvements.
    """
    from api_platform.runner import job_runner

    project = db.get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {build_id} not found")

    original_prompt = project.get("prompt")
    if not original_prompt:
        raise HTTPException(
            status_code=400,
            detail="Original project has no prompt stored",
        )

    custom = (body.custom_prompt or "").strip() if body else ""

    # ── KEY FIX: always include original_prompt as the base ──────────────────
    # Previously: prompt_to_use = custom if custom else original_prompt
    # Bug: when custom was set, original_prompt was dropped entirely, causing
    # the pipeline to build "Improve test coverage..." as a fresh project.
    prompt_to_use = _build_combined_prompt(original_prompt, custom)

    new_build_id = job_runner.start_build(prompt_to_use)
    return {
        "message":            "Rebuild started",
        "original_build_id":  build_id,
        "new_build_id":       new_build_id,
        "prompt":             prompt_to_use,
        "original_prompt":    original_prompt,
        "custom_prompt":      custom,
        "used_custom_prompt": bool(custom),
        "status_url":         f"/jobs/{new_build_id}/status",
    }


# ── /projects/cleanup ──────────────────────────────────────────────────────────

class CleanupRequest(BaseModel):
    older_than_days: int = 30
    statuses: list[str] = ["done", "failed", "cancelled"]
    dry_run: bool = True


@router.delete("/projects/cleanup")
async def cleanup_old_projects(req: CleanupRequest):
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
            "dry_run":         True,
            "would_delete":    len(targets),
            "older_than_days": req.older_than_days,
            "statuses":        req.statuses,
            "cutoff":          cutoff.isoformat(),
            "projects": [
                {
                    "build_id":   t["build_id"],
                    "app_name":   t.get("app_name"),
                    "status":     t["status"],
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
            if out:
                p = Path(out)
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
            db.delete_project(bid)
            deleted.append(bid)
        except Exception as e:
            errors.append({"build_id": bid, "error": str(e)})

    return {
        "dry_run":       False,
        "deleted":       len(deleted),
        "errors":        len(errors),
        "deleted_ids":   deleted,
        "error_details": errors,
        "cutoff":        cutoff.isoformat(),
    }
