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
import sys
import os
import argparse
import logging
import uvicorn

# Force UTF-8 stdout encoding to avoid UnicodeEncodeErrors on some terminals.
#
# `line_buffering=True` is cheap and makes a redirected stdout readable while a
# build runs instead of in 8KB gulps. It is NOT, however, the reason those five
# 1,567-byte session logs in this repo contain only the startup banner — that was
# measured on 2026-09-03 and the answer was different, see `--log-file` below.
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Start the AI App Builder API server")
    parser.add_argument("--host",      default="0.0.0.0",  help="Bind host")
    parser.add_argument("--port",      default=8000, type=int, help="Bind port")
    parser.add_argument("--no-reload", action="store_true",  help="Disable auto-reload")
    parser.add_argument("--workers",   default=1, type=int,  help="Number of worker processes")
    parser.add_argument("--log-file",  default=os.getenv("SERVER_LOG_FILE", ""),
                        help="Also write every log line to this file. Use it for "
                             "any run whose log you intend to read afterwards.")
    args = parser.parse_args()

    # Why this exists, measured on 2026-09-03.
    #
    # Five logs in this repo are exactly 1,567 bytes — the startup banner and
    # nothing else — and two live rows were assessed without their build log
    # because of it. The cause was assumed to be block buffering and it is not:
    # after `line_buffering=True` was added, a row's log was STILL 1,551 bytes
    # while the build ran, and still 1,551 after the process exited. A buffer
    # would have flushed. The output never reached the file.
    #
    # It is the launch, not the process. Started detached from a shell that then
    # exits (`nohup ... &` from a tool call, which is how an agent starts it),
    # the inherited stdout stops being written to once that shell is gone, so
    # everything after startup is lost. Sessions that ran the server in a
    # terminal that stayed open have 272KB logs of exactly the same output.
    #
    # A file the server opens itself does not care how it was launched.
    if args.log_file:
        handler = logging.FileHandler(args.log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        print(f"|  Log file: {args.log_file}")

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

    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Only watch actual source code directories
    reload_dirs = [
        os.path.join(base_dir, "api_platform"),
        os.path.join(base_dir, "agents"),
        os.path.join(base_dir, "tools"),
        os.path.join(base_dir, "prompts"),
    ]

    print(f"""
+------------------------------------------------------+
|         AI App Builder Platform — Starting           |
+------------------------------------------------------+
|  Host:    {args.host:<43}|
|  Port:    {args.port:<43}|
|  Reload:  {str(reload):<43}|
|  Workers: {args.workers:<43}|
+------------------------------------------------------+
|  IMPORTANT: generated_projects/ is EXCLUDED from     |
|  the file watcher so builds won't be interrupted.    |
+------------------------------------------------------+
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
