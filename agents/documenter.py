"""
agents/documenter.py — Generates README.md + SETUP.md for generated projects.

Changes in this version
────────────────────────
1. Generates TWO files instead of one:
   - README.md  — project overview, features, API reference (as before)
   - SETUP.md   — detailed, step-by-step setup guide written into the project
                  folder so it ends up INSIDE the downloaded ZIP

2. SETUP.md is built from actual project data:
   - Real env vars extracted from services.py / main.py
   - Real Python packages from requirements.txt
   - Real API endpoints from routes.py
   - Whether a frontend folder exists (decides if Node.js section is added)
   - OS-specific notes (Windows / macOS / Linux)

3. DocResult now also stores setup_path for the downloader to reference.
"""
import logging
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
from agents.base_agent import BaseAgent
from tools.file_writer import read_file, create_file, list_files
from llm_client import GroqDailyQuotaError
import config

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "documenter.txt"


@dataclass
class DocResult:
    app_name:    str
    readme_path: str = ""
    setup_path:  str = ""
    sections:    list = field(default_factory=list)
    error:       str = ""

    def __str__(self):
        if self.error:
            return f"❌ {self.app_name} — {self.error}"
        files = " + ".join(p for p in [self.readme_path, self.setup_path] if p)
        return f"✅ {self.app_name} — wrote {files} ({len(self.sections)} sections)"


class Documenter(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("Documenter", system_prompt)

    def run(
        self,
        intent:         dict,
        architecture:   dict,
        backend_files:  list[str],
        review_results: list = None,
    ) -> DocResult:
        app_name = intent.get("app_name", "project")
        root     = architecture.get("root_folder", app_name)
        logger.info(f"📝 Generating documentation for: {app_name}")

        context = self._gather_context(root, backend_files)

        review_summary = ""
        if review_results:
            scores = [r.score for r in review_results if r.score]
            avg    = sum(scores) / len(scores) if scores else 0
            review_summary = f"\nCode quality avg score: {avg:.1f}/10"

        # ── README.md ──────────────────────────────────────────────────────────
        readme_path  = ""
        setup_path   = ""
        sections     = []
        error        = ""

        try:
            prompt = f"""Generate a README.md for this project.

APP SPEC:
{json.dumps(intent, indent=2)}

PROJECT FILES:
{context}
{review_summary}

Generate the complete README.md following the format in your instructions.
Use the actual endpoint paths, env vars, and file names from the project files above."""

            readme_content = self.think(prompt)
            if readme_content:
                readme_path = f"{root}/README.md"
                create_file(readme_path, readme_content)
                sections = [
                    line.strip() for line in readme_content.splitlines()
                    if line.startswith("## ") or line.startswith("# ")
                ]
                logger.info(f"  📄 README.md written ({len(sections)} sections)")
            else:
                error = "LLM returned empty README"

        # Phase 21 fix: quota death during README generation used to be recorded
        # as a DocResult error nobody inspected, so the build was marked a clean
        # `done` while shipping no README. Propagate instead — the pipeline's
        # finalisation already wraps this call and writes SESSION_CONTEXT.md.
        except GroqDailyQuotaError:
            logger.error("LLM daily quota exhausted during README generation.")
            raise
        except Exception as e:
            error = str(e)
            logger.error(f"README generation failed: {e}")

        # ── SETUP.md ───────────────────────────────────────────────────────────
        try:
            setup_content = self._generate_setup(root, intent, backend_files, architecture)
            setup_path = f"{root}/SETUP.md"
            create_file(setup_path, setup_content)
            logger.info(f"  📄 SETUP.md written")
        except Exception as e:
            logger.warning(f"SETUP.md generation failed (non-fatal): {e}")
            setup_path = ""

        result = DocResult(
            app_name=app_name,
            readme_path=readme_path,
            setup_path=setup_path,
            sections=sections,
            error=error,
        )
        logger.info(str(result))
        return result

    # ── Phase 21: SESSION_CONTEXT.md / BUILD_CONTEXT.md handoff generator ──────

    def generate_session_context(
        self,
        intent:           dict,
        architecture:     dict,
        backend_files:    list[str],
        frontend_files:   list[str]   = None,
        completed_steps:  list[str]   = None,
        pending_steps:    list[str]   = None,
        reason:           str         = "quota_exhausted",
        quota_snapshot:   dict        = None,
        remediation:      Any         = None,
        progress_percent: float       = 0.0,
        debug_results:    list        = None,
        review_results:   list        = None,
        test_results:     list        = None,
        error_detail:     str         = "",
    ) -> str:
        """
        Write SESSION_CONTEXT.md (+ BUILD_CONTEXT.md alias) into the project root.

        Called when a build is interrupted by quota exhaustion or completes with
        unresolved remediation issues. The document tells a developer exactly what
        exists, what is missing, and what to do next.

        CRITICAL: this method must never make an LLM call on its primary path —
        the main trigger is quota exhaustion, so the entire document is built
        from local file inspection and the pipeline's own result objects.

        Returns the written path (e.g. "my_app/SESSION_CONTEXT.md"), or "" if the
        write failed. Never raises — a failure here must not sink the build.
        """
        app_name = intent.get("app_name", "project")
        root     = architecture.get("root_folder", app_name)

        backend_files   = backend_files   or []
        frontend_files  = frontend_files  or []
        completed_steps = completed_steps or []
        pending_steps   = pending_steps   or []

        try:
            content = self._build_session_context(
                app_name         = app_name,
                root             = root,
                intent           = intent,
                architecture     = architecture,
                backend_files    = backend_files,
                frontend_files   = frontend_files,
                completed_steps  = completed_steps,
                pending_steps    = pending_steps,
                reason           = reason,
                quota_snapshot   = quota_snapshot or {},
                remediation      = remediation,
                progress_percent = progress_percent,
                debug_results    = debug_results  or [],
                review_results   = review_results or [],
                test_results     = test_results   or [],
                error_detail     = error_detail,
            )
        except Exception as e:
            logger.error(f"SESSION_CONTEXT.md build failed: {e}", exc_info=True)
            return ""

        written = ""
        # The plan document names both filenames; BUILD_CONTEXT.md is an alias so
        # either name a developer looks for is present in the ZIP.
        for filename in ("SESSION_CONTEXT.md", "BUILD_CONTEXT.md"):
            path = f"{root}/{filename}"
            try:
                create_file(path, content)
                written = written or path
                logger.info(f"  📄 {filename} written ({len(content)} chars)")
            except Exception as e:
                logger.warning(f"Could not write {filename}: {e}")

        return written

    def _build_session_context(
        self,
        app_name:         str,
        root:             str,
        intent:           dict,
        architecture:     dict,
        backend_files:    list[str],
        frontend_files:   list[str],
        completed_steps:  list[str],
        pending_steps:    list[str],
        reason:           str,
        quota_snapshot:   dict,
        remediation:      Any,
        progress_percent: float,
        debug_results:    list,
        review_results:   list,
        test_results:     list,
        error_detail:     str,
    ) -> str:
        """Assemble the markdown body. Pure string building — no LLM, no raising."""
        all_files = list(backend_files) + list(frontend_files)
        loc       = self._count_lines(all_files)
        tree      = self._build_file_tree(root)
        env_vars  = self._extract_env_vars(root, backend_files)
        packages  = self._extract_requirements(root)
        endpoints = self._extract_endpoints(root, backend_files)
        has_tests = self._has_tests(root)
        stamp     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        reason_title, reason_body = self._explain_reason(
            reason, quota_snapshot, error_detail
        )

        # ── 📊 Progress ───────────────────────────────────────────────────────
        step_lines = [f"- [x] {s}" for s in completed_steps]
        step_lines += [f"- [ ] {s}" for s in pending_steps]
        steps_block = "\n".join(step_lines) or "_No step information recorded._"

        quota_block = self._format_quota_block(quota_snapshot)

        # ── 📁 Artifact inventory ─────────────────────────────────────────────
        health_rows = self._file_health_rows(
            all_files, debug_results, review_results, test_results
        )
        missing = self._missing_files(architecture, all_files, root)
        missing_block = (
            "\n".join(f"- `{p}` — {d}" for p, d in missing)
            if missing else
            "_Every file in the architecture was generated._"
        )

        # ── 🛠️ Remaining work ─────────────────────────────────────────────────
        todos: list[str] = []
        if remediation is not None:
            for item in getattr(remediation, "unresolved", []) or []:
                todos.append(f"- [ ] {item}")
        for path, desc in missing:
            todos.append(f"- [ ] Implement `{path}` — {desc}")
        if not has_tests and backend_files:
            todos.append("- [ ] Add a pytest suite under `tests/` — none was generated")
        todos_block = "\n".join(todos) or "_No outstanding issues were recorded._"

        remediation_block = self._format_remediation_block(remediation)

        env_template = (
            f"```env\n{env_vars.strip()}\n```"
            if env_vars else
            "_No environment variables were detected in the generated code._"
        )
        endpoint_block = (
            f"```\n{endpoints}\n```"
            if endpoints else
            "_No routes.py endpoints detected yet._"
        )
        packages_block = (
            f"```\n{packages.strip()}\n```"
            if packages else
            "_No requirements.txt found — install FastAPI and Uvicorn manually._"
        )

        return f"""# 🧩 Session Context — {app_name}

> **This build did not finish cleanly.** Everything generated so far is intact and
> included in this folder. This document tells you exactly where the build stopped
> and what to do next.

| | |
|---|---|
| **Project** | {app_name} |
| **Type** | {intent.get('app_type', '—')} |
| **Complexity** | {intent.get('complexity', '—')} |
| **Stopped because** | {reason_title} |
| **Progress** | **{progress_percent:.0f}% complete** |
| **Files generated** | {len(all_files)} ({len(backend_files)} backend, {len(frontend_files)} frontend) |
| **Lines of code** | ~{loc:,} |
| **Generated at** | {stamp} |

---

## 📊 Progress

{reason_body}

### Pipeline steps

{steps_block}

{quota_block}

---

## 📁 Artifact Inventory

### Project tree

```
{tree}
```

### File health

{health_rows}

### Files in the plan that were never generated

{missing_block}

---

## 🛠️ Remaining Work

{todos_block}

{remediation_block}

---

## 🚀 How to Finish This Build

### Option A — Resume the automated build (recommended)

{self._resume_instructions(reason, quota_snapshot)}

The builder is idempotent per build: re-running the same prompt produces a fresh
project folder, so nothing in this folder is overwritten.

### Option B — Finish it by hand

**1. Set up the environment**

```bash
# Windows (PowerShell)
python -m venv venv
.\\venv\\Scripts\\Activate.ps1

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

**2. Install dependencies**

{packages_block}

```bash
pip install -r requirements.txt
```

**3. Configure environment variables**

{env_template}

**4. Run the backend**

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000/docs**.

**5. Endpoints detected so far**

{endpoint_block}

**6. Run the tests**

```bash
{"pytest tests/ -v" if has_tests else "# No test suite was generated — see Remaining Work above."}
```

**7. Work through the Remaining Work checklist above**, starting with any file
listed as `import failed` in the File health table — a broken import blocks
everything downstream of it.

---

*Generated by AI App Builder · Phase 21 session handoff · {stamp}*
"""

    # ── Session-context helpers ───────────────────────────────────────────────

    def _explain_reason(
        self, reason: str, quota_snapshot: dict, error_detail: str
    ) -> tuple[str, str]:
        """Return (short title, markdown paragraph) explaining why the build stopped."""
        detail = f"\n\n> Details: `{error_detail}`" if error_detail else ""

        if reason == "quota_exhausted":
            model = quota_snapshot.get("heavy_model") or "the configured model"
            return (
                "🔑 LLM daily quota exhausted",
                "The build stopped because every available Groq API key hit its daily "
                f"quota (model `{model}`). This is an organization-level limit, so "
                "rotating keys does not help — the quota has to reset, or new keys have "
                "to be added. **No work was lost**: every file generated before the "
                "limit was hit is in this folder." + detail,
            )
        if reason == "remediation_incomplete":
            return (
                "🛠️ Automatic repair could not fix everything",
                "The build completed all nine pipeline steps, but verification found "
                "issues the automatic repair passes could not resolve. The code is "
                "packaged and downloadable — the checklist below lists exactly what "
                "still needs attention." + detail,
            )
        if reason == "step_failed":
            return (
                "💥 A pipeline step failed",
                "A build step failed outright, but usable code had already been "
                "generated, so the build was packaged instead of discarded." + detail,
            )
        return (
            "⚠️ Build ended early",
            "The build ended before completing normally. Everything generated so far "
            "is preserved in this folder." + detail,
        )

    def _resume_instructions(self, reason: str, quota_snapshot: dict) -> str:
        if reason == "quota_exhausted":
            hint = quota_snapshot.get("reset_hint") or (
                "Groq free-tier daily quotas reset at 00:00 UTC."
            )
            return (
                f"{hint}\n\n"
                "Once quota is available again, either:\n\n"
                "- add fresh `GROQ_API_KEY` values to `.env`, restart the server, and "
                "call `POST /admin/reset-keys`; **or**\n"
                "- wait for the daily reset,\n\n"
                "then submit the **same prompt** again from the dashboard (or "
                "`POST /projects`) to rebuild from scratch with full quota."
            )
        return (
            "Submit the same prompt again from the dashboard (or `POST /projects`). "
            "The builder will regenerate the project into a fresh folder; use the "
            "checklist above to confirm the new run resolved these issues."
        )

    def _format_quota_block(self, snapshot: dict) -> str:
        if not snapshot:
            return ""
        lines = [
            "### 🔑 API key status at the time of the interruption",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total keys | {snapshot.get('total_keys', '—')} |",
            f"| Keys still usable | {snapshot.get('available_keys', '—')} |",
            f"| Keys exhausted (any model) | {snapshot.get('exhausted_keys', '—')} |",
            f"| Heavy model (`{snapshot.get('heavy_model', '—')}`) | "
            f"{'exhausted' if snapshot.get('heavy_exhausted') else 'available'} |",
            f"| Fast model (`{snapshot.get('fast_model', '—')}`) | "
            f"{'exhausted' if snapshot.get('fast_exhausted') else 'available'} |",
        ]
        if snapshot.get("reset_hint"):
            lines += ["", f"> {snapshot['reset_hint']}"]
        return "\n".join(lines)

    def _format_remediation_block(self, remediation: Any) -> str:
        if remediation is None or not getattr(remediation, "ran", False):
            return ""
        repaired = getattr(remediation, "repaired_files", []) or []
        lines = [
            "### 🔧 What the automatic repair already tried",
            "",
            f"- Repair passes run: **{getattr(remediation, 'passes', 0)}**",
            f"- LLM-backed repair: **{'yes' if getattr(remediation, 'llm_used', False) else 'no (quota unavailable — structural repairs only)'}**",
        ]
        if repaired:
            lines.append(f"- Files repaired: {', '.join(f'`{p}`' for p in repaired[:10])}")
        return "\n".join(lines)

    def _count_lines(self, file_paths: list[str]) -> int:
        total = 0
        for fp in file_paths:
            try:
                total += len(read_file(fp).splitlines())
            except Exception:
                pass
        return total

    def _file_health_rows(
        self,
        all_files:      list[str],
        debug_results:  list,
        review_results: list,
        test_results:   list,
    ) -> str:
        """Markdown table of per-file debug / review / test status."""
        if not all_files:
            return "_No files were generated._"

        def _index(results: list) -> dict:
            out = {}
            for r in results or []:
                fp = getattr(r, "file_path", None) or (
                    r.get("file_path") if isinstance(r, dict) else None
                )
                if fp:
                    out[str(fp).replace("\\", "/")] = r
            return out

        dbg, rev, tst = _index(debug_results), _index(review_results), _index(test_results)

        rows = [
            "| File | Imports | Review | Tests |",
            "|------|---------|--------|-------|",
        ]
        for fp in all_files:
            key = str(fp).replace("\\", "/")

            d = dbg.get(key)
            debug_cell = "—" if d is None else (
                "✅ ok" if getattr(d, "success", False) else "❌ import failed"
            )

            r = rev.get(key)
            score = getattr(r, "score", None) if r is not None else None
            review_cell = f"{score}/10" if score else "—"

            t = tst.get(key)
            if t is None:
                test_cell = "—"
            elif getattr(t, "skipped", False):
                test_cell = f"skipped ({getattr(t, 'skip_reason', 'no reason')})"
            else:
                test_cell = f"{getattr(t, 'passed', 0)}/{getattr(t, 'tests_generated', 0)} passing"

            rows.append(f"| `{key}` | {debug_cell} | {review_cell} | {test_cell} |")
        return "\n".join(rows)

    def _missing_files(
        self, architecture: dict, all_files: list[str], root: str
    ) -> list[tuple[str, str]]:
        """Architecture files that were planned but never written to disk."""
        written = {str(f).replace("\\", "/") for f in all_files}
        missing = []
        for spec in architecture.get("files", []) or []:
            path = spec.get("path")
            if not path:
                continue
            full = f"{root}/{path}".replace("\\", "/")
            if full not in written:
                missing.append((path, spec.get("description", "no description")))
        return missing

    # ── SETUP.md builder ───────────────────────────────────────────────────────

    def _generate_setup(
        self,
        root:          str,
        intent:        dict,
        backend_files: list[str],
        architecture:  dict,
    ) -> str:
        """
        Build a detailed SETUP.md by inspecting actual project files.
        Falls back to a templated version if the LLM call fails.
        """
        app_name    = intent.get("app_name", "project")
        description = intent.get("description", "")
        features    = intent.get("features", [])

        # Inspect actual project structure
        env_vars       = self._extract_env_vars(root, backend_files)
        py_packages    = self._extract_requirements(root)
        endpoints      = self._extract_endpoints(root, backend_files)
        has_frontend   = self._has_frontend(root, architecture)
        has_tests      = self._has_tests(root)
        project_tree   = self._build_file_tree(root)

        # Ask LLM to write the SETUP.md using real data as context
        prompt = f"""Write a detailed SETUP.md for a developer who just downloaded this project as a ZIP.

PROJECT: {app_name}
DESCRIPTION: {description}
FEATURES: {', '.join(features) if features else 'See README'}

ACTUAL DATA EXTRACTED FROM PROJECT FILES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Python packages (from requirements.txt):
{py_packages or '  fastapi, uvicorn, python-dotenv (inferred)'}

Environment variables (from source code):
{env_vars or '  No env vars detected'}

API endpoints (from routes.py):
{endpoints or '  See README for endpoint list'}

Has frontend directory: {has_frontend}
Has test suite: {has_tests}

Project file tree:
{project_tree}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Write SETUP.md with these sections IN ORDER:

# Setup Guide — {app_name}

## Prerequisites
List exact version requirements (Python 3.10+, Node.js 18+ if frontend exists, pip, git).

## 1. Extract the ZIP
Show the unzip command and what the resulting folder looks like.

## 2. Backend Setup
Step-by-step with REAL package names from the requirements list above.
Include:
  a. Create virtual environment (show both Windows and macOS/Linux commands)
  b. Activate it (both OS variants)
  c. Install dependencies: `pip install -r requirements.txt`
  d. Create .env file with REAL env var names from above (show a template)
  e. Start the server: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
  f. Verify: `curl http://localhost:8000/health` or visit http://localhost:8000/docs

## 3. Frontend Setup  (ONLY include this section if has_frontend is True)
  a. `cd frontend`
  b. `npm install`
  c. `npm run dev`
  d. Visit http://localhost:5173

## 4. API Reference
Small table of REAL endpoints from above. Columns: Method | Path | What it does.

## 5. Running Tests  (ONLY include this section if has_tests is True)
  `cd tests && pytest -v`

## 6. Troubleshooting
5-6 most common errors with exact fix commands:
  - ModuleNotFoundError → pip install command
  - Port already in use → how to kill or change port
  - CORS errors → where to change origins in main.py
  - Missing .env → which vars are required
  - npm install fails → delete node_modules and retry

## 7. Project Structure
Paste the file tree from above with one-line comment per important file.

Rules:
- Use ONLY the real data provided above (real package names, real env vars, real endpoints)
- Show BOTH Windows and Unix commands wherever they differ
- Every code block must have a language tag (bash, python, env, etc.)
- Be specific — no "replace with your value" without saying WHICH value
- Return ONLY the markdown. No explanation outside the document."""

        try:
            content = self.think(prompt)
            if content and len(content.strip()) > 200:
                return content
        # Phase 21 fix: propagate quota death rather than silently downgrading to
        # the template. SETUP.md still gets written by the fallback path in
        # _finalise_with_context / the downloads route, so nothing is lost — but
        # the build now correctly reports WHY it degraded.
        except GroqDailyQuotaError:
            logger.error("LLM daily quota exhausted during SETUP.md generation.")
            raise
        except Exception as e:
            logger.warning(f"LLM SETUP.md generation failed, using template: {e}")

        # Fallback: build template from real data without LLM
        return self._build_fallback_setup(
            app_name, py_packages, env_vars, endpoints,
            has_frontend, has_tests, project_tree
        )

    # ── Project inspection helpers ─────────────────────────────────────────────

    def _extract_env_vars(self, root: str, backend_files: list[str]) -> str:
        """Extract os.getenv / environ calls from source files."""
        vars_found = set()
        patterns   = [
            re.compile(r'os\.getenv\(["\']([A-Z_][A-Z0-9_]+)["\']'),
            re.compile(r'os\.environ\[["\']([A-Z_][A-Z0-9_]+)["\']'),
            re.compile(r'os\.environ\.get\(["\']([A-Z_][A-Z0-9_]+)["\']'),
            re.compile(r'environ\.get\(["\']([A-Z_][A-Z0-9_]+)["\']'),
        ]

        priority = ["services.py", "main.py", "config.py", "weather_api.py",
                    "weather_service.py", "routes.py"]

        for filename in priority:
            for fp in backend_files:
                if Path(fp).name == filename:
                    try:
                        src = read_file(fp)
                        for pat in patterns:
                            vars_found.update(pat.findall(src))
                    except Exception:
                        pass

        if not vars_found:
            return ""
        lines = [f"  {v}=" for v in sorted(vars_found)]
        return "\n".join(lines)

    def _extract_requirements(self, root: str) -> str:
        """Read requirements.txt and return the content."""
        for candidate in [
            f"{root}/requirements.txt",
            f"{root}/backend/requirements.txt",
        ]:
            try:
                content = read_file(candidate)
                # Return only real package lines (skip comments and blanks)
                lines = [
                    l.strip() for l in content.splitlines()
                    if l.strip() and not l.strip().startswith("#")
                ]
                return "\n".join(f"  {l}" for l in lines[:20])
            except Exception:
                pass
        return ""

    def _extract_endpoints(self, root: str, backend_files: list[str]) -> str:
        """Extract @router.METHOD and @app.METHOD decorator lines from routes.py."""
        pattern = re.compile(
            r'@(?:router|app)\.(get|post|put|patch|delete)\(["\']([^"\']+)["\']'
        )
        for fp in backend_files:
            if Path(fp).name == "routes.py":
                try:
                    src   = read_file(fp)
                    found = pattern.findall(src)
                    if found:
                        lines = [f"  {method.upper():8} {path}" for method, path in found]
                        return "\n".join(lines)
                except Exception:
                    pass
        return ""

    def _has_frontend(self, root: str, architecture: dict) -> bool:
        """True if project has a frontend directory with an index file."""
        project_dir = Path(config.OUTPUT_DIR) / root
        for candidate in ["frontend", "src", "public"]:
            d = project_dir / candidate
            if d.exists() and d.is_dir():
                # Must have at least one HTML or JS file
                if any(d.rglob("*.html")) or any(d.rglob("*.js")) or any(d.rglob("*.tsx")):
                    return True
        # Also check architecture
        files = architecture.get("files", [])
        frontend_types = {"javascript", "jsx", "typescript", "tsx", "html", "css"}
        return any(f.get("type") in frontend_types for f in files)

    def _has_tests(self, root: str) -> bool:
        """True if project has a tests/ directory with test files."""
        tests_dir = Path(config.OUTPUT_DIR) / root / "tests"
        if tests_dir.exists():
            return any(tests_dir.glob("test_*.py"))
        return False

    def _build_file_tree(self, root: str) -> str:
        """Build a concise file tree of the project (max 25 lines)."""
        project_dir = Path(config.OUTPUT_DIR) / root
        if not project_dir.exists():
            return f"{root}/"

        SKIP = {"__pycache__", "node_modules", ".git", "venv", ".venv",
                "env", "dist", ".pytest_cache", "*.pyc"}

        lines = [f"{root}/"]
        try:
            for path in sorted(project_dir.rglob("*")):
                rel = path.relative_to(project_dir)
                parts = rel.parts
                # Skip hidden / build dirs
                if any(p.startswith(".") or p in SKIP for p in parts):
                    continue
                if path.is_dir():
                    indent = "  " * (len(parts) - 1)
                    lines.append(f"{indent}├── {parts[-1]}/")
                else:
                    indent = "  " * (len(parts) - 1)
                    lines.append(f"{indent}│   {parts[-1]}")
                if len(lines) > 25:
                    lines.append("  ... (truncated)")
                    break
        except Exception:
            pass
        return "\n".join(lines)

    # ── Fallback SETUP.md (no LLM) ─────────────────────────────────────────────

    def _build_fallback_setup(
        self,
        app_name:     str,
        py_packages:  str,
        env_vars:     str,
        endpoints:    str,
        has_frontend: bool,
        has_tests:    bool,
        project_tree: str,
    ) -> str:
        env_template = ""
        if env_vars:
            env_template = f"\nCreate a `.env` file in the `backend/` folder:\n\n```env\n{env_vars}\n```\n"

        frontend_section = ""
        if has_frontend:
            frontend_section = """
## 3. Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install Node.js dependencies
npm install

# Start development server (visit http://localhost:5173)
npm run dev
```

> **Note:** The backend must be running on port 8000 before starting the frontend.
"""

        test_section = ""
        if has_tests:
            test_section = """
## 5. Running Tests

```bash
# From the project root
pytest tests/ -v
```
"""

        endpoint_table = ""
        if endpoints:
            endpoint_table = (
                "\n| Method | Path | Description |\n"
                "|--------|------|-------------|\n"
            )
            for line in endpoints.strip().splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    method, path = parts
                    endpoint_table += f"| `{method}` | `{path}` | — |\n"

        packages_install = (
            "```bash\npip install -r requirements.txt\n```"
            if py_packages else
            "```bash\npip install fastapi uvicorn python-dotenv httpx\n```"
        )

        return f"""# Setup Guide — {app_name}

Generated by **AI App Builder**. Follow the steps below to run this project locally.

---

## Prerequisites

| Tool | Minimum Version | Download |
|------|----------------|----------|
| Python | 3.10+ | https://python.org/downloads |
| pip | 23+ | bundled with Python |
{"| Node.js | 18+ | https://nodejs.org |" if has_frontend else ""}
| Git | any | https://git-scm.com |

---

## 1. Extract the ZIP

```bash
# The ZIP extracts into a folder named after the project
unzip {app_name}_*.zip
cd {app_name}
```

---

## 2. Backend Setup

### a) Create a virtual environment

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

### b) Install dependencies

{packages_install}

### c) Configure environment variables
{env_template if env_template else "No environment variables required for this project."}

### d) Start the backend server

```bash
# Run from the backend/ directory
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### e) Verify it's running

Visit **http://localhost:8000/docs** in your browser — you should see the interactive API docs.

```bash
# Or test via curl
curl http://localhost:8000/health
```

---
{frontend_section}
## {'4' if has_frontend else '3'}. API Reference
{endpoint_table if endpoint_table else "_See README.md for the full endpoint list._"}

---
{test_section}
## {'6' if has_frontend and has_tests else '4' if has_frontend or has_tests else '4'}. Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` inside the venv |
| Port 8000 already in use | `lsof -i :8000` then `kill <PID>`, or use `--port 8001` |
| Port 5173 already in use | Pass `--port 5174` to `npm run dev` |
| CORS errors in browser | Add your frontend URL to `allow_origins` in `backend/main.py` |
| `.env` not found | Create `.env` in `backend/` with the variables listed in section 2c |
| `npm install` fails | Delete `node_modules/` and `package-lock.json`, then retry |
| Tests fail with `ImportError` | Activate venv first, then `pip install -r requirements.txt` |

---

## {'7' if has_frontend and has_tests else '5'}. Project Structure

```
{project_tree}
```

---

*Generated by AI App Builder · {app_name}*
"""

    # ── Context gatherer (for README) ─────────────────────────────────────────

    def _gather_context(self, root: str, backend_files: list[str]) -> str:
        """Read key files to give the LLM accurate content for README."""
        snippets = []
        priority = ["main.py", "routes.py", "services.py", "weather_api.py", "models.py"]

        for filename in priority:
            for fp in backend_files:
                if Path(fp).name == filename:
                    try:
                        content   = read_file(fp)
                        lines     = content.splitlines()
                        key_lines = [
                            l for l in lines
                            if (l.startswith("import ") or
                                l.startswith("from ") or
                                l.startswith("@app.") or
                                l.startswith("@router.") or
                                l.startswith("async def ") or
                                l.startswith("def ") or
                                "APIRouter" in l or
                                "FastAPI" in l or
                                "os.getenv" in l or
                                "environ" in l)
                        ]
                        snippet = "\n".join(key_lines[:20])
                        snippets.append(f"--- {fp} ---\n{snippet}")
                    except Exception:
                        pass
                    break

        return "\n\n".join(snippets) if snippets else "No backend files available."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    documenter = Documenter()
    intent = {
        "app_name": "weather_dashboard",
        "app_type": "dashboard",
        "description": "Weather dashboard showing temperature, humidity and 5-day forecast",
        "features": ["current weather", "5-day forecast", "humidity tracking"],
        "tech_stack": {"backend": "FastAPI", "frontend": "React + Tailwind", "other": ["OpenWeatherMap API"]},
    }
    arch = {"root_folder": "weather_dashboard", "files": [
        {"path": "frontend/src/App.js", "type": "javascript"}
    ]}
    result = documenter.run(intent, arch, ["weather_dashboard/backend/main.py"])
    print(result)
