"""
api_platform/routes/downloads.py — Phase 20 (Issue 9 fix)
===========================================================
FIX — Issue 9: No explicit forbidden-file filter in the ZIP creation loop.

Root cause in previous versions:
  The rglob("*") sweep in download_project_zip() included every file in the
  output directory, including setup.py / manage.py / wsgi.py etc., if they
  somehow survived the pipeline's _purge_forbidden_files() step.  Scenarios
  where forbidden files could still appear at download time:
    a) Build was queued before Phase 20 pipeline was deployed (old output dir)
    b) _purge_forbidden_files() had a path-normalisation bug on Windows (Gap A,
       fixed in pipeline.py v2.2.1) that allowed some files through
    c) The architect stripped them from the JSON but the LLM generated them
       anyway during BackendDeveloper (two separate LLM calls)

  Defense-in-depth fix: add an explicit check inside the rglob loop so the
  ZIP NEVER contains a forbidden file, regardless of what the pipeline did.

All other functionality (SETUP.md injection, metadata.json, streaming
response) is identical to the previous version.
"""

import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api_platform.database import get_project, get_project_files, get_build_progress
from api_platform.runner import DOWNLOADABLE_STATUSES

# Import the canonical forbidden-file set from architect so the two lists
# are always in sync — no separate definition to maintain.
try:
    from agents.architect import FORBIDDEN_FILES
except ImportError:
    # Fallback in case agents package is not on the Python path at import time
    FORBIDDEN_FILES: frozenset[str] = frozenset({
        "setup.py", "manage.py", "wsgi.py", "asgi.py",
        "Makefile", "celery.py", "migrate.py", "seed.py",
        "gunicorn.conf.py",
    })

router  = APIRouter(prefix="/projects", tags=["downloads"])
VERSION = "AI App Builder v2.2.0"


# ── ZIP endpoint ──────────────────────────────────────────────────────────────

@router.get("/{build_id}/download")
async def download_project_zip(build_id: str):
    """Download a completed project as a ZIP file."""

    project = get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {build_id} not found")

    # Phase 21: done_with_context builds are downloadable too. They contain
    # usable code plus a SESSION_CONTEXT.md explaining what is unfinished —
    # refusing them would strand the user's work, which is exactly the failure
    # mode Phase 21 exists to remove.
    if project["status"] not in DOWNLOADABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Project is {project['status']}, so there are no packaged files "
                "to download yet. Builds can be downloaded once they reach "
                f"one of: {', '.join(DOWNLOADABLE_STATUSES)}."
            ),
        )

    output_path = project.get("output_path")
    if not output_path:
        raise HTTPException(status_code=404, detail="No output directory found for this project")

    output_dir = Path(output_path)
    if not output_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project output directory not found at {output_path}",
        )

    app_name    = project.get("app_name") or build_id
    root_folder = f"{app_name}/"

    # ── Gather metadata ───────────────────────────────────────────────────────
    files_db = get_project_files(build_id)
    progress = get_build_progress(build_id)

    metadata = {
        "build_id":         build_id,
        "app_name":         project.get("app_name"),
        "app_type":         project.get("app_type"),
        "complexity":       project.get("complexity"),
        "prompt":           project.get("prompt"),
        "status":           project.get("status"),
        # Phase 21: why the build ended this way, and how far it got
        "completion_reason": project.get("completion_reason"),
        "progress_percent":  project.get("progress_percent"),
        "review_score":     project.get("review_score"),
        "debug_score":      project.get("debug_score"),
        "test_score":       project.get("test_score"),
        "created_at":       project.get("created_at"),
        "completed_at":     project.get("completed_at"),
        "duration_seconds": project.get("duration_seconds"),
        "file_count":       None,
        "files":            [f["file_path"] for f in files_db],
        "build_steps": [
            {
                "step":      p["step"],
                "name":      p["step_name"],
                "status":    p["status"],
                "timestamp": p["timestamp"],
            }
            for p in progress
        ],
        "generated_by":  VERSION,
        "downloaded_at": datetime.utcnow().isoformat(),
    }

    # ── Read or generate SETUP.md ─────────────────────────────────────────────
    setup_content = _read_or_generate_setup(output_dir, project)

    # ── Build ZIP in memory ───────────────────────────────────────────────────
    zip_buffer = io.BytesIO()
    file_count = 0
    skipped_forbidden = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

        added_arcs: set[str] = set()

        for file_path in sorted(output_dir.rglob("*")):
            if not file_path.is_file():
                continue

            # Skip Python cache dirs
            if any(p in ("__pycache__", ".pytest_cache") for p in file_path.parts):
                continue

            # ── Issue 9 FIX: defense-in-depth forbidden-file filter ───────────
            # The pipeline's _purge_forbidden_files() is the primary defence.
            # This secondary check catches any that survived (old builds, Windows
            # path-sep bugs, or a second LLM generation pass that snuck one in).
            if file_path.name in FORBIDDEN_FILES:
                skipped_forbidden += 1
                rel = str(file_path.relative_to(output_dir)).replace("\\", "/")
                import logging
                logging.getLogger(__name__).warning(
                    f"🚫 ZIP: skipping forbidden file '{rel}' "
                    f"(should have been purged by pipeline — old build?)"
                )
                continue
            # ── End Issue 9 fix ───────────────────────────────────────────────

            arcname = root_folder + str(file_path.relative_to(output_dir))
            zf.write(file_path, arcname)
            added_arcs.add(arcname)
            file_count += 1

        # Add SETUP.md at ZIP root (always fresh)
        setup_arcname = root_folder + "SETUP.md"
        if setup_arcname not in added_arcs:
            zf.writestr(setup_arcname, setup_content)
            file_count += 1

        # ── Phase 21: guarantee a handoff document for degraded builds ────────
        # The rglob sweep above already picks up SESSION_CONTEXT.md when the
        # pipeline wrote it. This fallback covers the case where the pipeline
        # crashed before it could — the user still gets an explanation instead
        # of a silently incomplete ZIP.
        context_arcname = root_folder + "SESSION_CONTEXT.md"
        if project["status"] == "done_with_context" and context_arcname not in added_arcs:
            zf.writestr(context_arcname, _minimal_context_fallback(project))
            file_count += 1

        # Finalize metadata (include skipped count for transparency)
        metadata["file_count"]         = file_count
        metadata["forbidden_skipped"]  = skipped_forbidden
        zf.writestr(root_folder + "metadata.json", json.dumps(metadata, indent=2))

    # ── Stream response ───────────────────────────────────────────────────────
    zip_buffer.seek(0)
    zip_size  = zip_buffer.getbuffer().nbytes
    safe_name = re.sub(r"[^\w\-]", "_", app_name)
    filename  = f"{safe_name}_{build_id[:8]}.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(zip_size),
            "X-Build-ID":          build_id,
            "X-File-Count":        str(file_count),
            "X-Forbidden-Skipped": str(skipped_forbidden),
        },
    )


# ── Phase 21: last-resort handoff note ────────────────────────────────────────

def _minimal_context_fallback(project: dict) -> str:
    """
    Written into the ZIP only when a done_with_context build has no
    SESSION_CONTEXT.md on disk (pipeline crashed before writing one).
    """
    progress = project.get("progress_percent")
    progress_str = f"{progress:.0f}%" if isinstance(progress, (int, float)) else "unknown"
    return f"""# 🧩 Session Context — {project.get('app_name') or 'project'}

> This build did not finish cleanly, but the code generated so far is included
> in this ZIP.

| | |
|---|---|
| **Status** | `{project.get('status')}` |
| **Progress** | {progress_str} |
| **Reason** | {project.get('completion_reason') or 'not recorded'} |
| **Review score** | {project.get('review_score') or '—'} |
| **Debug score** | {project.get('debug_score') or '—'} |
| **Test score** | {project.get('test_score') or '—'} |

## What to do next

1. Read `SETUP.md` in this ZIP and follow the backend setup steps.
2. Run the backend — any file that fails to import is where the build stopped.
3. If the build was paused by an LLM quota limit, wait for the daily reset (or add
   fresh `GROQ_API_KEY` values and call `POST /admin/reset-keys`), then submit the
   same prompt again for a complete run.

*The detailed handoff document could not be generated for this build, so this
summary was assembled from the build record at download time.*
"""


# ── SETUP.md helpers ──────────────────────────────────────────────────────────

def _read_or_generate_setup(output_dir: Path, project: dict) -> str:
    setup_file = output_dir / "SETUP.md"
    if setup_file.exists():
        try:
            content = setup_file.read_text(encoding="utf-8")
            if len(content.strip()) > 200:
                return content
        except Exception:
            pass
    return _generate_fallback_setup(output_dir, project)


def _generate_fallback_setup(output_dir: Path, project: dict) -> str:
    app_name     = project.get("app_name") or "project"
    app_type     = project.get("app_type") or "web app"
    prompt_text  = project.get("prompt") or ""
    review       = project.get("review_score")
    debug        = project.get("debug_score") or "—"
    test         = project.get("test_score") or "—"
    duration     = project.get("duration_seconds")
    duration_str = f"{int(duration)}s" if duration else "—"

    py_packages  = _read_requirements(output_dir)
    env_vars     = _scan_env_vars(output_dir)
    endpoints    = _scan_endpoints(output_dir)
    has_frontend = _detect_frontend(output_dir)
    has_tests    = _detect_tests(output_dir)
    tree         = _file_tree(output_dir, app_name)

    env_block = ""
    if env_vars:
        env_lines = "\n".join(f"{v}=your_{v.lower()}_here" for v in sorted(env_vars))
        env_block = f"\nCreate a `.env` file in the `backend/` folder:\n\n```env\n{env_lines}\n```\n"
    else:
        env_block = "\nNo environment variables detected — you can skip this step.\n"

    endpoint_table = ""
    if endpoints:
        endpoint_table = "\n| Method | Endpoint | Notes |\n|--------|----------|-------|\n"
        for method, path in endpoints:
            endpoint_table += f"| `{method}` | `{path}` | — |\n"
    else:
        endpoint_table = "\n_See README.md for the full API reference._\n"

    frontend_section = ""
    if has_frontend:
        frontend_section = """
---

## 3. Frontend Setup

> **Prerequisites:** Node.js 18 or higher — https://nodejs.org

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.
"""

    test_section = ""
    if has_tests:
        test_section = """
---

## Running the Test Suite

```bash
pytest tests/ -v
```
"""

    if py_packages:
        pkg_list     = "\n".join(f"  {p}" for p in py_packages[:15])
        install_note = f"This project requires:\n```\n{pkg_list}\n```\nInstall with:\n"
    else:
        install_note = "Install all dependencies with:\n"

    packages_cmd = "```bash\npip install -r requirements.txt\n```"

    return f"""# Setup Guide — {app_name}

> Generated by **{VERSION}**
> Build time: {duration_str} · Review: {review}/10 · Debug: {debug} · Tests: {test}

---

## What You Built

> {prompt_text}

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.10+ |
| pip | 23+ |
{"| Node.js | 18+ |" if has_frontend else ""}

---

## 1. Extract the ZIP

```bash
unzip {app_name}_*.zip
cd {app_name}
```

```
{tree}
```

---

## 2. Backend Setup

**Windows (PowerShell):**
```powershell
python -m venv venv
.\\venv\\Scripts\\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

{install_note}{packages_cmd}

### Environment variables
{env_block}

### Start the backend

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Visit **http://localhost:8000/docs** to verify.
{frontend_section}
---

## API Reference
{endpoint_table}
{test_section}
---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | `pip install -r requirements.txt` inside venv |
| Port 8000 in use | `lsof -i :8000` then kill, or use `--port 8001` |
| CORS errors | Add your frontend URL to `allow_origins` in `backend/main.py` |
| `.env` not found | Create `backend/.env` with the variables in section 2 |

---

*{VERSION} · {app_name}*
"""


# ── File inspection utilities ──────────────────────────────────────────────────

def _read_requirements(output_dir: Path) -> list[str]:
    for candidate in ["requirements.txt", "backend/requirements.txt"]:
        f = output_dir / candidate
        if f.exists():
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
                return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
            except Exception:
                pass
    return []


def _scan_env_vars(output_dir: Path) -> set[str]:
    patterns = [
        re.compile(r'os\.getenv\(["\']([A-Z_][A-Z0-9_]{2,})["\']'),
        re.compile(r'os\.environ\[["\']([A-Z_][A-Z0-9_]{2,})["\']'),
        re.compile(r'os\.environ\.get\(["\']([A-Z_][A-Z0-9_]{2,})["\']'),
    ]
    found: set[str] = set()
    SKIP = {"__pycache__", "node_modules", ".git", "venv", ".venv", "tests"}
    for py_file in output_dir.rglob("*.py"):
        if any(s in py_file.parts for s in SKIP):
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="ignore")
            for pat in patterns:
                found.update(pat.findall(src))
        except Exception:
            pass
    return found


def _scan_endpoints(output_dir: Path) -> list[tuple[str, str]]:
    pattern          = re.compile(
        r'@(?:router|app)\.(get|post|put|patch|delete)\(["\']([^"\']+)["\']'
    )
    routes_candidates = list(output_dir.rglob("routes.py"))
    if not routes_candidates:
        return []
    try:
        src   = routes_candidates[0].read_text(encoding="utf-8", errors="ignore")
        found = pattern.findall(src)
        return [(m.upper(), p) for m, p in found]
    except Exception:
        return []


def _detect_frontend(output_dir: Path) -> bool:
    for name in ["frontend", "src", "public"]:
        d = output_dir / name
        if d.is_dir():
            if any(d.rglob("*.html")) or any(d.rglob("*.js")) or any(d.rglob("*.tsx")):
                return True
    return False


def _detect_tests(output_dir: Path) -> bool:
    tests_dir = output_dir / "tests"
    return tests_dir.is_dir() and any(tests_dir.glob("test_*.py"))


def _file_tree(output_dir: Path, app_name: str, max_lines: int = 20) -> str:
    SKIP  = {"__pycache__", "node_modules", ".git", "venv", ".venv",
             ".pytest_cache", "dist", "__init__.py"}
    lines = [f"{app_name}/"]
    try:
        for path in sorted(output_dir.rglob("*")):
            rel   = path.relative_to(output_dir)
            parts = rel.parts
            if any(p in SKIP or p.startswith(".") for p in parts):
                continue
            depth  = len(parts) - 1
            indent = "  " * depth
            prefix = "├── " if path.is_dir() else "│   "
            lines.append(f"{indent}{prefix}{parts[-1]}{'/' if path.is_dir() else ''}")
            if len(lines) >= max_lines:
                lines.append("  └── ...")
                break
    except Exception:
        pass
    return "\n".join(lines)
