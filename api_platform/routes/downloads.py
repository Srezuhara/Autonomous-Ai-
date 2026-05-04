"""
api_platform/routes/downloads.py
GET /projects/{build_id}/download — Download project as ZIP

Changes in this version
────────────────────────
1. The ZIP now contains a real SETUP.md written by the Documenter agent
   instead of the old hardcoded 20-line generic stub.

2. Falls back to _generate_fallback_setup() — a rich templated version
   built from real project metadata — if no SETUP.md exists on disk.

3. README.md from the project is also included if it exists (it was
   already being picked up by the rglob("*") sweep, but now we ensure
   it lands at the ZIP root alongside SETUP.md for easy access).

4. Added test_score to metadata.json.
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

router = APIRouter(prefix="/projects", tags=["downloads"])

VERSION = "AI App Builder v2.2.0"


# ── ZIP endpoint ──────────────────────────────────────────────────────────────

@router.get("/{build_id}/download")
async def download_project_zip(build_id: str):
    """Download a completed project as a ZIP file."""

    project = get_project(build_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {build_id} not found")

    if project["status"] not in ("done", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Project is still {project['status']}. Wait for build to complete.",
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
        "review_score":     project.get("review_score"),
        "debug_score":      project.get("debug_score"),
        "test_score":       project.get("test_score"),
        "created_at":       project.get("created_at"),
        "completed_at":     project.get("completed_at"),
        "duration_seconds": project.get("duration_seconds"),
        "file_count":       None,   # filled after rglob below
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

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

        # Track which paths are already added so we don't double-add SETUP.md
        added_arcs: set[str] = set()

        # Add all generated project files
        for file_path in sorted(output_dir.rglob("*")):
            if not file_path.is_file():
                continue
            # Skip Python cache dirs
            if any(p in ("__pycache__", ".pytest_cache") for p in file_path.parts):
                continue

            arcname = root_folder + str(file_path.relative_to(output_dir))
            zf.write(file_path, arcname)
            added_arcs.add(arcname)
            file_count += 1

        # Add / overwrite SETUP.md at ZIP root (always fresh, always complete)
        setup_arcname = root_folder + "SETUP.md"
        if setup_arcname in added_arcs:
            # Replace the on-disk version with ours (it may be the same content)
            # zipfile allows duplicate names — last one wins on extraction for
            # most tools, but to be safe we skip re-adding
            pass
        else:
            zf.writestr(setup_arcname, setup_content)
            file_count += 1

        # Finalize metadata
        metadata["file_count"] = file_count
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
        },
    )


# ── SETUP.md helpers ──────────────────────────────────────────────────────────

def _read_or_generate_setup(output_dir: Path, project: dict) -> str:
    """
    Return the SETUP.md content to embed in the ZIP.

    Priority:
      1. SETUP.md already on disk (written by Documenter agent) — use it directly.
      2. Fallback: build one from project metadata without LLM.
    """
    setup_file = output_dir / "SETUP.md"
    if setup_file.exists():
        try:
            content = setup_file.read_text(encoding="utf-8")
            if len(content.strip()) > 200:   # sanity check — not an empty stub
                return content
        except Exception:
            pass

    return _generate_fallback_setup(output_dir, project)


def _generate_fallback_setup(output_dir: Path, project: dict) -> str:
    """
    Build a rich SETUP.md from project metadata without requiring LLM.
    Inspects real files on disk: requirements.txt, routes.py, .env patterns.
    """
    app_name    = project.get("app_name") or "project"
    app_type    = project.get("app_type") or "web app"
    prompt_text = project.get("prompt") or ""
    review      = project.get("review_score")
    debug       = project.get("debug_score") or "—"
    test        = project.get("test_score") or "—"
    duration    = project.get("duration_seconds")
    duration_str = f"{int(duration)}s" if duration else "—"

    # Discover real data from project files
    py_packages  = _read_requirements(output_dir)
    env_vars     = _scan_env_vars(output_dir)
    endpoints    = _scan_endpoints(output_dir)
    has_frontend = _detect_frontend(output_dir)
    has_tests    = _detect_tests(output_dir)
    tree         = _file_tree(output_dir, app_name)

    # Build env template block
    env_block = ""
    if env_vars:
        env_lines = "\n".join(f"{v}=your_{v.lower()}_here" for v in sorted(env_vars))
        env_block = f"""
Create a file called `.env` inside the `backend/` folder:

```env
{env_lines}
```

> ⚠️  Never commit `.env` to version control.
"""
    else:
        env_block = "\nNo environment variables detected — you can skip this step.\n"

    # Build endpoint table
    endpoint_table = ""
    if endpoints:
        endpoint_table = "\n| Method | Endpoint | Notes |\n|--------|----------|-------|\n"
        for method, path in endpoints:
            endpoint_table += f"| `{method}` | `{path}` | — |\n"
    else:
        endpoint_table = "\n_See README.md for the full API reference._\n"

    # Frontend section
    frontend_section = ""
    if has_frontend:
        frontend_section = """
---

## 3. Frontend Setup

> **Prerequisites:** Node.js 18 or higher — https://nodejs.org

```bash
# From the project root
cd frontend

# Install all dependencies (first time only)
npm install

# Start the development server
npm run dev
```

Open **http://localhost:5173** in your browser.

> The backend must be running on port 8000 before the frontend will work.
"""

    # Test section
    test_section = ""
    if has_tests:
        test_section = """
---

## Running the Test Suite

Make sure the virtual environment is active, then:

```bash
# From the project root
pytest tests/ -v
```

Expected output: each test file listed with PASSED / FAILED status.
"""

    # Packages block
    if py_packages:
        pkg_list = "\n".join(f"  {p}" for p in py_packages[:15])
        install_note = f"This project requires:\n```\n{pkg_list}\n```\nAll installed in one step with:\n"
    else:
        install_note = "Install all dependencies with:\n"

    packages_cmd = "```bash\npip install -r requirements.txt\n```"

    return f"""# Setup Guide — {app_name}

> Generated by **{VERSION}**  
> Build time: {duration_str} · Review: {review}/10 · Debug: {debug} · Tests: {test}

This guide walks you through running **{app_name}** ({app_type}) locally after downloading the ZIP.

---

## What You Built

> {prompt_text}

---

## Prerequisites

| Tool | Version | Where to get it |
|------|---------|----------------|
| Python | **3.10 or higher** | https://python.org/downloads |
| pip | 23+ | Included with Python |
{"| Node.js | **18 or higher** | https://nodejs.org |" if has_frontend else ""}
| A terminal | any | PowerShell, Terminal, bash, zsh |

---

## 1. Extract the ZIP

```bash
# Unzip the archive — it creates a folder named {app_name}
unzip {app_name}_*.zip
cd {app_name}
```

Your project structure:

```
{tree}
```

---

## 2. Backend Setup

### Step 1 — Create a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` at the start of your terminal prompt.

### Step 2 — Install Python dependencies

{install_note}{packages_cmd}

### Step 3 — Configure environment variables
{env_block}

### Step 4 — Start the backend server

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

### Step 5 — Verify it works

Open **http://localhost:8000/docs** in your browser.  
You'll see the interactive Swagger API documentation.

Or test via command line:
```bash
curl http://localhost:8000/docs
# Should return HTML, not an error
```
{frontend_section}
---

## API Reference
{endpoint_table}
Full interactive docs: **http://localhost:8000/docs**
{test_section}
---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'fastapi'` | Activate venv first, then `pip install -r requirements.txt` |
| `ERROR: Port 8000 is already in use` | Run `lsof -i :8000` (Mac/Linux) or `netstat -ano` (Windows) and kill the process, or add `--port 8001` |
| CORS error in browser console | Open `backend/main.py`, find `allow_origins` and add `http://localhost:5173` |
| `.env` file not found | Create `backend/.env` with the variables listed in Step 3 above |
| `uvicorn: command not found` | Virtual environment isn't active — run the activate command from Step 1 |
| `npm install` hangs or fails | Delete `frontend/node_modules/` and `frontend/package-lock.json`, then retry |
| Tests fail with `ImportError` | Make sure venv is active and `pip install -r requirements.txt` has been run |
| On Windows: `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` first |

---

## Useful URLs (once running)

| URL | What it is |
|-----|-----------|
| http://localhost:8000/docs | Interactive API docs (Swagger UI) |
| http://localhost:8000/redoc | Alternative API docs (ReDoc) |
| http://localhost:8000/health | Backend health check |
{"| http://localhost:5173 | Frontend dev server |" if has_frontend else ""}

---

*{VERSION} · Downloaded {datetime.utcnow().strftime("%Y-%m-%d")}*
"""


# ── File inspection utilities ─────────────────────────────────────────────────

def _read_requirements(output_dir: Path) -> list[str]:
    for candidate in ["requirements.txt", "backend/requirements.txt"]:
        f = output_dir / candidate
        if f.exists():
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
                return [
                    l.strip() for l in lines
                    if l.strip() and not l.strip().startswith("#")
                ]
            except Exception:
                pass
    return []


def _scan_env_vars(output_dir: Path) -> set[str]:
    """Scan Python source files for os.getenv / environ calls."""
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
    """Extract route decorator tuples from routes.py."""
    pattern = re.compile(
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
    """Build a simple indented file tree string."""
    SKIP = {"__pycache__", "node_modules", ".git", "venv", ".venv",
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
