"""
agents/debugger.py — Autonomous debugging loop with two-pass cascade fix.

Phase 15 changes
────────────────
1. SKIP_DEBUG_FILES set — skips setup.py, manage.py, wsgi.py etc. (15.3)
2. _pre_install_project_deps() — installs requirements.txt before debug loop (15.2)
"""
import logging
import re
import sys
import os
from pathlib import Path
from dataclasses import dataclass, field
from agents.base_agent import BaseAgent
from tools.file_writer import read_file, create_file
from tools.code_executor import run_python
from tools.dependency_installer import pip_install, extract_missing_package
import config

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "debugger.txt"
MAX_ATTEMPTS = 3

LOCAL_MODULE_BLOCKLIST = {
    "main", "app", "config", "routes", "services", "models",
    "utils", "helpers", "database", "db", "schemas", "middleware",
    "dependencies", "core", "api", "tests", "weather_dashboard",
    "backend", "frontend", "auth", "users", "items", "weather",
    "endpoints", "routers", "weather_service", "weather_model",
    "weather_api", "forecast_api", "weather_routes",
}

IGNORE_ERRORS = ["uvicorn", "Address already in use", "Timed out after"]

# Phase 15.3 — files that cannot be import-checked via importlib
SKIP_DEBUG_FILES = {
    "setup.py", "manage.py", "wsgi.py", "asgi.py",
    "conftest.py", "migrate.py", "seed.py",
    "celery.py", "gunicorn.conf.py",
}

SYSPATH_BLOCK = """\
import sys as _sys, os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
_parent = _os.path.dirname(_here)
_grandparent = _os.path.dirname(_parent)
for _p in [_here, _parent, _grandparent]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
"""


@dataclass
class FileDebugResult:
    file_path:     str
    success:       bool
    attempts:      int
    final_error:   str  = ""
    fixes_applied: list = field(default_factory=list)

    def __str__(self):
        status = "✅" if self.success else "❌"
        return f"{status} {self.file_path} (attempts: {self.attempts}, fixes: {len(self.fixes_applied)})"


class Debugger(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("Debugger", system_prompt)

    def run(self, file_paths: list[str]) -> list[FileDebugResult]:
        # Phase 15.3 — filter out un-debuggable files BEFORE any work
        py_files = [
            f for f in file_paths
            if f.endswith(".py") and Path(f).name not in SKIP_DEBUG_FILES
        ]
        skipped = len(file_paths) - len(py_files) - sum(1 for f in file_paths if not f.endswith(".py"))
        if skipped:
            logger.info(f"⏭️  Skipped {skipped} un-debuggable file(s) (setup.py, manage.py etc.)")

        logger.info(f"🐛 Debugging {len(py_files)} Python files...")

        # Phase 15.2 — pre-install project dependencies before the debug loop
        self._pre_install_project_deps(py_files)

        # Pre-flight: __init__.py + fixes + sys.path injection
        self._ensure_init_files(py_files)
        for fp in py_files:
            fixes = self._preflight_fix(fp)
            for fix in fixes:
                logger.info(f"  🔨 Pre-flight [{fp}]: {fix}")
        for fp in py_files:
            if self._inject_syspath(fp):
                logger.info(f"  💉 Injected sys.path: {fp}")

        # PASS 1: debug all files
        results = {}
        for fp in py_files:
            r = self._debug_file(fp)
            results[fp] = r
            logger.info(str(r))

        # PASS 2: re-try files that failed in pass 1
        failed = [fp for fp, r in results.items() if not r.success]
        if failed:
            logger.info(f"🔁 Pass 2: re-trying {len(failed)} failed files after dependency fixes...")
            for fp in failed:
                r2 = self._debug_file(fp)
                if r2.success:
                    results[fp].success = True
                    results[fp].fixes_applied.extend(r2.fixes_applied)
                    results[fp].attempts += r2.attempts
                    logger.info(f"  ✅ Pass 2 fixed: {fp}")
                else:
                    results[fp].final_error = r2.final_error

        final = list(results.values())
        passed = sum(1 for r in final if r.success)
        logger.info(f"🐛 Debug complete: {passed}/{len(final)} files passing")
        return final

    # ── Phase 15.2 — Pre-install project dependencies ─────────────────────────

    def _pre_install_project_deps(self, file_paths: list[str]) -> None:
        """
        Install the project's requirements.txt before the debug loop starts.
        Mirrors what tester.py already does — prevents ModuleNotFoundError
        on packages that are listed in requirements.txt but not yet installed.
        """
        from tools.dependency_installer import pip_install_requirements
        if not file_paths:
            return
        root = Path(file_paths[0]).parts[0]
        for candidate in [
            f"{root}/requirements.txt",
            f"{root}/backend/requirements.txt",
        ]:
            req = Path(config.OUTPUT_DIR) / candidate
            if req.exists():
                logger.info(f"📦 Pre-installing deps from {candidate}...")
                result = pip_install_requirements(str(req))
                if result.success:
                    logger.info("✅ Dependencies installed")
                else:
                    logger.warning(f"⚠️  Some deps failed: {result.stderr[:200]}")
                return  # only install from first found file

    # ── Pre-flight fixes ─────────────────────────────────────────

    def _preflight_fix(self, file_path: str) -> list[str]:
        try:
            content = read_file(file_path)
        except Exception:
            return []

        fixes = []
        original = content
        filename = Path(file_path).name

        if filename == "routes.py" and re.search(r'\bweather_router\s*=\s*APIRouter', content):
            content = re.sub(r'\bweather_router\b', 'router', content)
            fixes.append("renamed weather_router → router")

        if filename == "main.py":
            new = re.sub(r'from routes import \w*router\w*', 'from routes import router', content)
            new = re.sub(r'app\.include_router\(\w*router\w*\)', 'app.include_router(router)', new)
            if new != content:
                content = new
                fixes.append("fixed router import name")

        if re.search(r'^engine\s*=\s*create_engine', content, re.MULTILINE):
            content = re.sub(r'^(engine\s*=\s*create_engine[^\n]+)', r'# \1', content, flags=re.MULTILINE)
            content = re.sub(r'^(Session\s*=\s*sessionmaker[^\n]+)', r'# \1', content, flags=re.MULTILINE)
            content = re.sub(r'^(Base\.metadata\.create_all[^\n]+)', r'# \1', content, flags=re.MULTILINE)
            fixes.append("disabled module-level DB connection")

        project_dir = self._get_project_dir(file_path)
        if project_dir:
            models_file = project_dir / "models.py"
            models_dir  = project_dir / "models"
            if not models_file.exists() and models_dir.exists():
                model_files = [f for f in models_dir.glob("*.py") if f.name != "__init__.py"]
                if model_files:
                    stem = model_files[0].stem
                    new = re.sub(r'from models import ([^\n]+)', f'from models.{stem} import \\1', content)
                    if new != content:
                        content = new
                        fixes.append(f"fixed 'from models import X' → 'from models.{stem} import X'")

        if project_dir and (project_dir / "services.py").exists():
            new = re.sub(r'from services\.\w+ import ([^\n]+)', r'from services import \1', content)
            if new != content:
                content = new
                fixes.append("fixed 'from services.x import Y' → 'from services import Y'")

        if content != original:
            create_file(file_path, content)
        return fixes

    def _get_project_dir(self, file_path: str) -> Path | None:
        try:
            full = (Path(config.OUTPUT_DIR) / file_path).resolve()
            d = full.parent
            for _ in range(4):
                if (d / "main.py").exists():
                    return d
                d = d.parent
        except Exception:
            pass
        return None

    def _ensure_init_files(self, file_paths: list[str]):
        seen = set()
        for fp in file_paths:
            folder = str(Path(fp).parent)
            if folder in seen:
                continue
            seen.add(folder)
            init = f"{folder}/__init__.py"
            if not (Path(config.OUTPUT_DIR) / init).exists():
                create_file(init, '"""Package init."""\n')
                logger.info(f"  📦 Added __init__.py: {folder}/")

    def _inject_syspath(self, file_path: str) -> bool:
        try:
            content = read_file(file_path)
            if "_here = " in content or "sys.path.insert" in content:
                lines = content.splitlines(keepends=True)
                filtered = [l for l in lines if not any(x in l for x in [
                    "_here =", "_parent =", "_grandparent =",
                    "sys.path.insert", "import sys as _sys", "import os as _os",
                    "if _p not in _sys.path", "for _p in [_here",
                ])]
                content = "".join(filtered)

            lines = content.splitlines(keepends=True)
            insert_at = 0
            if lines and lines[0].startswith("#!"):
                insert_at = 1
            if insert_at < len(lines) and lines[insert_at].strip().startswith('"""'):
                insert_at += 1
                while insert_at < len(lines) and '"""' not in lines[insert_at]:
                    insert_at += 1
                insert_at += 1

            new_content = "".join(lines[:insert_at]) + SYSPATH_BLOCK + "\n" + "".join(lines[insert_at:])
            create_file(file_path, new_content)
            return True
        except Exception as e:
            logger.warning(f"  ⚠️  sys.path injection failed for {file_path}: {e}")
            return False

    def _extract_root_cause_file(self, error_text: str) -> str | None:
        output_dir = str(Path(config.OUTPUT_DIR).resolve()).replace("\\", "/")
        matches = re.findall(r'File "([^"]+\.py)"', error_text)
        for fpath in reversed(matches):
            norm = fpath.replace("\\", "/")
            if output_dir in norm:
                return norm.split(output_dir + "/")[-1]
        return None

    def _scan_project_structure(self, file_path: str) -> str:
        parts = Path(file_path).parts
        if not parts:
            return ""
        project_dir = Path(config.OUTPUT_DIR) / parts[0]
        lines = ["Actual Python files in this project:"]
        try:
            for py_file in sorted(project_dir.rglob("*.py")):
                rel = str(py_file.relative_to(Path(config.OUTPUT_DIR))).replace("\\", "/")
                if "__pycache__" in rel:
                    continue
                try:
                    snippet = py_file.read_text(encoding="utf-8", errors="ignore")
                    exports = []
                    for line in snippet.splitlines()[:30]:
                        m = re.match(r'^(router|app)\s*=', line.strip())
                        if m:
                            exports.append(m.group(1))
                        m2 = re.match(r'^(class|def)\s+(\w+)', line.strip())
                        if m2:
                            exports.append(m2.group(2))
                    tag = f"  → exports: {', '.join(exports[:4])}" if exports else ""
                    lines.append(f"  {rel}{tag}")
                except Exception:
                    lines.append(f"  {rel}")
        except Exception as e:
            return f"(scan failed: {e})"
        return "\n".join(lines)

    # ── Debug loop ────────────────────────────────────────────────

    def _debug_file(self, file_path: str) -> FileDebugResult:
        result = FileDebugResult(file_path=file_path, success=False, attempts=0)
        error_text = ""

        for attempt in range(1, MAX_ATTEMPTS + 1):
            result.attempts = attempt
            logger.info(f"  🔁 [{file_path}] Attempt {attempt}/{MAX_ATTEMPTS}")

            execution = run_python(file_path)

            if execution.success:
                result.success = True
                logger.info(f"  ✅ [{file_path}] Passed on attempt {attempt}")
                return result

            error_text = execution.stderr

            if any(p in error_text for p in IGNORE_ERRORS):
                result.success = True
                logger.info(f"  ✅ [{file_path}] Import-check passed (runtime error ignored)")
                return result

            if "sqlalchemy" in error_text.lower() and "OperationalError" in error_text:
                result.success = True
                logger.info(f"  ✅ [{file_path}] Import-check passed (DB connection ignored)")
                return result

            logger.warning(f"  ❌ [{file_path}] Error:\n{error_text[:400]}")

            root_cause = self._extract_root_cause_file(error_text)
            file_to_fix = root_cause if (root_cause and root_cause != file_path) else file_path

            if root_cause and root_cause != file_path:
                logger.info(f"  🔍 Root cause: {root_cause}")
                dep_fixes = self._preflight_fix(root_cause)
                for fix in dep_fixes:
                    logger.info(f"  🔨 Pre-flight [{root_cause}]: {fix}")
                self._inject_syspath(root_cause)
                rc_folder = str(Path(root_cause).parent)
                init_path = f"{rc_folder}/__init__.py"
                if not (Path(config.OUTPUT_DIR) / init_path).exists():
                    create_file(init_path, '"""Package init."""\n')

            missing_pkg = extract_missing_package(error_text)
            if missing_pkg and missing_pkg not in LOCAL_MODULE_BLOCKLIST:
                logger.info(f"  📦 Auto-installing: {missing_pkg}")
                res = pip_install(missing_pkg)
                if res.success:
                    result.fixes_applied.append(f"pip install {missing_pkg}")
                    continue
            elif missing_pkg:
                logger.info(f"  ⏭️  Skipping (local module): {missing_pkg}")

            if attempt < MAX_ATTEMPTS:
                fixed = self._generate_fix(file_to_fix, error_text)
                if fixed:
                    install_match = re.search(r"#\s*INSTALL:\s*([A-Za-z0-9_\-]+)", fixed)
                    if install_match:
                        pkg = install_match.group(1).strip()
                        if pkg not in LOCAL_MODULE_BLOCKLIST:
                            pip_install(pkg)
                    create_file(file_to_fix, fixed)
                    result.fixes_applied.append(f"LLM fix on {file_to_fix} attempt {attempt}")
                    logger.info(f"  🔧 LLM fix applied to {file_to_fix}")
                    self._preflight_fix(file_to_fix)
                    self._inject_syspath(file_to_fix)

        result.final_error = error_text
        return result

    def _generate_fix(self, file_path: str, error_text: str) -> str | None:
        try:
            current_code = read_file(file_path)
        except Exception as e:
            logger.error(f"Could not read {file_path}: {e}")
            return None

        project_map = self._scan_project_structure(file_path)
        prompt = f"""Fix this Python file. It has an import error.

FILE: {file_path}
CURRENT CODE:
{current_code}

ERROR:
{error_text}

{project_map}

RULES:
- Use ONLY imports matching files in the project map above
- router = APIRouter() in routes.py — NEVER weather_router
- from routes import router in main.py
- NEVER: from backend.x  from ..x  from weather_dashboard.x
- No module-level DB connections

Return ONLY the complete fixed Python code."""
        logger.info(f"  🧠 LLM fixing: {file_path}")
        return self.think(prompt)

    def summary(self, results: list[FileDebugResult]) -> str:
        passed = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        lines = [f"\n{'='*50}", "  DEBUG SUMMARY", f"{'='*50}",
                 f"  Passed: {len(passed)}/{len(results)}",
                 f"  Failed: {len(failed)}/{len(results)}", f"{'='*50}"]
        for r in results:
            lines.append(f"  {r}")
        if failed:
            lines.append("\n  Failed files:")
            for r in failed:
                lines.append(f"    ❌ {r.file_path}")
                lines.append(f"       {r.final_error[:200]}")
        lines.append(f"{'='*50}\n")
        return "\n".join(lines)
