"""
start_server.py — Safe uvicorn launcher for AI App Builder
===========================================================

Problem: running `uvicorn api_platform.main:app --reload` watches ALL
directories including `generated_projects/`.  During a build the agents
write dozens of files per second, which triggers WatchFiles to reload the
server, killing any active build mid-way.

Solution: launch uvicorn programmatically and exclude `generated_projects/`
(and a few other noisy folders) from the watch list.

Usage:
    python start_server.py                   # default: 0.0.0.0:8000, reload ON
    python start_server.py --no-reload       # production: no auto-reload
    python start_server.py --port 8001       # custom port
    python start_server.py --host 127.0.0.1  # localhost only

Why not just use --reload-exclude?
    uvicorn's --reload-exclude CLI flag only appeared in recent versions and
    the glob matching is tricky.  This script is more reliable across versions.
"""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Start the AI App Builder API server")
    parser.add_argument("--host",      default="0.0.0.0",  help="Bind host")
    parser.add_argument("--port",      default=8000, type=int, help="Bind port")
    parser.add_argument("--no-reload", action="store_true",  help="Disable auto-reload")
    parser.add_argument("--workers",   default=1, type=int,  help="Number of worker processes")
    args = parser.parse_args()

    reload = not args.no_reload

    # Directories that should NEVER trigger a reload.
    # generated_projects/ is the main culprit — agents write files there continuously.
    reload_excludes = [
        "generated_projects",
        "generated_projects/*",
        "__pycache__",
        "*.pyc",
        ".git",
        "node_modules",
        "frontend/dist",
        "frontend/node_modules",
        "*.db",          # SQLite WAL journal thrashes constantly
        "*.db-wal",
        "*.db-shm",
        "logs",
        "*.log",
    ]

    # Only watch actual source code directories
    reload_dirs = [
        "api_platform",
        "agents",
        "tools",
        "prompts",
    ]

    print(f"""
╔══════════════════════════════════════════════════════╗
║         AI App Builder Platform — Starting           ║
╠══════════════════════════════════════════════════════╣
║  Host:    {args.host:<43}║
║  Port:    {args.port:<43}║
║  Reload:  {str(reload):<43}║
║  Workers: {args.workers:<43}║
╠══════════════════════════════════════════════════════╣
║  IMPORTANT: generated_projects/ is EXCLUDED from     ║
║  the file watcher so builds won't be interrupted.    ║
╚══════════════════════════════════════════════════════╝
""")

    uvicorn_kwargs = dict(
        app="api_platform.main:app",
        host=args.host,
        port=args.port,
        reload=reload,
        log_level="info",
    )

    if reload:
        uvicorn_kwargs["reload_dirs"]     = reload_dirs
        uvicorn_kwargs["reload_excludes"] = reload_excludes

    if args.workers > 1 and not reload:
        uvicorn_kwargs["workers"] = args.workers

    uvicorn.run(**uvicorn_kwargs)


if __name__ == "__main__":
    main()
