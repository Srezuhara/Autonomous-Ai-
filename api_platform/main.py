"""
api_platform/main.py  v2.2.0  (Phase 14 + multi-key rotation)
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

import config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api_platform.database import initialize_db
from api_platform.runner import job_runner
from api_platform.routes import projects, jobs
from api_platform.routes.downloads import router as downloads_router
from api_platform.routes.analytics import router as analytics_router
from api_platform.routes.websockets import router as ws_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────
    logger.info("🚀 Starting AI App Builder Platform v2.2.0")

    initialize_db()
    logger.info("✅ Database initialized")

    job_runner.start()
    logger.info(f"🔧 Worker pool: {job_runner.max_workers} workers ready")

    # Show which Groq keys are loaded
    from llm_client import get_key_status
    ks = get_key_status()
    logger.info(f"🔑 Groq keys loaded: {ks['total_keys']} total")

    logger.info("✅ Platform ready (Phase 14: ZIP + Stats + WebSocket + Multi-key)")

    yield

    # ── Shutdown ──────────────────────────────────────────
    logger.info("⏳ Shutting down worker pool…")
    job_runner.shutdown(wait=True)
    logger.info("✅ Platform shutdown complete")


app = FastAPI(
    title="AI App Builder Platform",
    description=(
        "Build full-stack applications from a single prompt.\n\n"
        "**Phase 14:** ZIP downloads · WebSocket · Stats · Rebuild · Cleanup\n\n"
        "**Multi-key:** Groq API keys rotate automatically on daily limit"
    ),
    version="2.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(downloads_router)
app.include_router(analytics_router)
app.include_router(ws_router)


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["info"])
async def root():
    from llm_client import get_key_status
    pool = job_runner.get_pool_status()
    ks   = get_key_status()
    return {
        "service": "AI App Builder Platform",
        "version": "2.2.0",
        "status":  "running",
        "timestamp": datetime.utcnow().isoformat(),
        "workers": pool,
        "llm": {
            "provider": getattr(config, "LLM_PROVIDER", "both"),
            "groq_keys_available": ks["available_keys"],
            "groq_keys_exhausted": ks["exhausted_keys"],
            "groq_keys_total":     ks["total_keys"],
        },
        "endpoints": {
            "docs":       "/docs",
            "health":     "/health",
            "projects":   "/projects/",
            "stats":      "/stats",
            "jobs_queue": "/jobs/queue",
            "websocket":  "ws://localhost:8000/ws/jobs/{build_id}",
        },
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["info"])
async def health():
    from llm_client import get_key_status
    pool = job_runner.get_pool_status()
    ks   = get_key_status()

    # Determine overall LLM health
    if ks["available_keys"] == 0:
        llm_status = "ollama_only"
    elif ks["exhausted_keys"] > 0:
        llm_status = "degraded"
    else:
        llm_status = "healthy"

    return {
        "status": "healthy",
        "version": "2.2.0",
        "timestamp": datetime.utcnow().isoformat(),
        "worker_pool": pool,
        "llm": {
            "status":          llm_status,
            "provider":        getattr(config, "LLM_PROVIDER", "both"),
            "groq_keys_total":     ks["total_keys"],
            "groq_keys_available": ks["available_keys"],
            "groq_keys_exhausted": ks["exhausted_keys"],
            "keys": ks["keys"],   # [{suffix: "...abc123", status: "available"}, ...]
        },
        "features": {
            "concurrent_builds":  True,
            "job_cancellation":   True,
            "zip_download":       True,
            "websocket_progress": True,
            "statistics":         True,
            "project_rebuild":    True,
            "auto_cleanup":       True,
            "multi_key_rotation": ks["total_keys"] > 1,
        },
    }


# ── Key management ────────────────────────────────────────────────────────────

@app.post("/admin/reset-keys", tags=["info"])
async def reset_keys():
    """
    Reset all exhausted Groq keys.
    Call this after midnight when daily limits have refreshed,
    or after adding a new API key to .env and restarting.
    """
    from llm_client import _reset_exhausted, get_key_status
    _reset_exhausted()
    ks = get_key_status()
    return {
        "message": "All Groq keys reset to available",
        "keys_available": ks["available_keys"],
        "keys": ks["keys"],
    }
