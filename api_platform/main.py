"""
api_platform/main.py  v2.2.0  (Phase 14 + multi-key rotation)
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

import config
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    # `127.0.0.1` is a different origin from `localhost` as far as the browser is
    # concerned, and Vite hands out whichever the user typed. Additive only —
    # the existing entries are untouched. In dev the Vite proxy makes requests
    # same-origin anyway, so this is now a belt-and-braces entry rather than the
    # thing the app depends on.
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
# Order matters. `analytics_router` carries the literal path
# `DELETE /projects/cleanup`, while `projects.router` carries the parameterised
# `DELETE /projects/{build_id}`. FastAPI matches in registration order, so with
# projects first the literal route was unreachable — "cleanup" was swallowed as
# a build_id and the endpoint 404'd on a build that does not exist.
#
# Nothing else collides: analytics' other paths are `/stats`, `/stats/daily` and
# `POST /projects/{build_id}/rebuild`, none of which shadow a projects route.
app.include_router(analytics_router)
app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(downloads_router)
app.include_router(ws_router)


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["info"])
async def root():
    from llm_client import get_key_status, get_rate_limit_status
    pool = job_runner.get_pool_status()
    ks   = get_key_status()
    rl   = get_rate_limit_status()
    return {
        "service": "AI App Builder Platform",
        "version": "2.2.0",
        "status":  "running",
        "timestamp": datetime.utcnow().isoformat(),
        "workers": pool,
        "llm": {
            "provider": getattr(config, "LLM_PROVIDER", "groq"),
            "groq_keys_available": ks["available_keys"],
            "groq_keys_exhausted": ks["exhausted_keys"],
            "groq_keys_total":     ks["total_keys"],
            "exhausted_70b":       ks["exhausted_70b"],
            "exhausted_8b":        ks["exhausted_8b"],
            "fully_exhausted":     ks["fully_exhausted"],
            "rate_limits":         rl,
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
    from llm_client import get_key_status, get_rate_limit_status
    pool = job_runner.get_pool_status()
    ks   = get_key_status()
    rl   = get_rate_limit_status()
    provider = getattr(config, "LLM_PROVIDER", "groq")

    # Determine overall LLM health
    if rl["any_daily_limited"]:
        llm_status = "quota_limited"
    elif rl["max_cooldown_seconds"] > 0:
        llm_status = "rate_limited"
    elif ks["available_keys"] == 0:
        llm_status = "missing_groq_keys" if provider == "groq" else "ollama_only"
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
            "provider":        provider,
            "groq_keys_total":     ks["total_keys"],
            "groq_keys_available": ks["available_keys"],
            "groq_keys_exhausted": ks["exhausted_keys"],
            "exhausted_70b":       ks["exhausted_70b"],
            "exhausted_8b":        ks["exhausted_8b"],
            "fully_exhausted":     ks["fully_exhausted"],
            "rate_limits":         rl,
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


# ── SPA mount ─────────────────────────────────────────────────────────────────
# Serves the built frontend from this same origin, so one command runs the whole
# product: no second port, no CORS, no proxy.
#
# Registered LAST, and only if `frontend/dist` exists. Every API route above is
# already bound by the time this runs, so nothing here can shadow one; with no
# build present the whole block is a no-op and the app behaves exactly as it did
# before.

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# Client-side routes that collide with a real API path. `GET /projects/{id}`
# returns JSON to the app and must keep doing so, but the *same* URL typed into
# the address bar is a page the SPA owns. The two are told apart by `Accept`:
# a browser navigation asks for text/html, `fetch` does not.
_SPA_ROUTE_PREFIXES = ("/dashboard", "/build", "/projects", "/stats")


def _wants_html(request) -> bool:
    return "text/html" in request.headers.get("accept", "")


if FRONTEND_DIST.is_dir():

    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="spa-assets",
    )

    @app.middleware("http")
    async def spa_navigation(request, call_next):
        """
        Hand browser *navigations* to the SPA before routing sees them.

        Without this, opening `/projects/{id}` directly — a deep link, a
        refresh, a bookmark — renders the API's JSON in the browser instead of
        the build report, because that path really is an API route. Only GETs
        that explicitly ask for HTML are diverted, so every programmatic call
        still reaches its endpoint untouched.
        """
        path = request.url.path
        if (
            request.method == "GET"
            and _wants_html(request)
            and any(path == p or path.startswith(p + "/") for p in _SPA_ROUTE_PREFIXES)
        ):
            index = FRONTEND_DIST / "index.html"
            if index.is_file():
                return FileResponse(index)
        return await call_next(request)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """
        History fallback for every other client-side route.

        A request for a file that genuinely exists in dist (favicon, manifest)
        is served as itself; anything else gets the shell and React Router
        takes it from there.
        """
        candidate = (FRONTEND_DIST / full_path).resolve()
        # Containment check: a crafted path must not escape the dist directory.
        if full_path and candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST):
            return FileResponse(candidate)

        index = FRONTEND_DIST / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Frontend build not found")
        return FileResponse(index)

    logger.info(f"🖥️  Serving SPA from {FRONTEND_DIST}")

else:
    logger.info(
        "🖥️  No frontend/dist — API only "
        "(run `npm run build` in frontend/ to serve the SPA too)"
    )
