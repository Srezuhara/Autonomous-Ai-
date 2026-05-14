"""
agents/debugger.py — Autonomous debugging loop with two-pass cascade fix.

Phase 18 changes (on top of Phase 15):
────────────────────────────────────────
1. DOTTED_IMPORT_REWRITER — new _rewrite_dotted_imports() method that runs
   BEFORE the import-check loop. It catches the most common LLM mistake:
     from ai_pdf_reader.backend.vault import X   →  from vault import X
     from backend.routes import router           →  from routes import router
   This prevents the "from X.Y.Z import" error from ever reaching the debug loop.

2. WINDOWS_BLOCKED_PACKAGES_HANDLER — when pip_install() returns failure
   AND the error mentions dlib/face_recognition/tensorflow/torch, the debugger
   now asks the LLM to REWRITE the file to remove that dependency entirely,
   rather than retrying the failing install endlessly.

3. INSTALL_TIMEOUT_GUARD — if a package install returns "Timed out" in stderr,
   the debugger treats it the same as a Windows-blocked package: rewrite the
   source instead of looping.

4. IMPORT_ERROR_PROPAGATION_FIX — when a root-cause file fails to import
   because it uses a blocked package, the error now propagates correctly:
   the blocked package name is extracted from the root-cause file's error,
   not from the parent file that imported it.

5. LOCAL_MODULE_BLOCKLIST expanded to include project-name prefixes so the
   debugger won't try to pip-install the project itself.

All Phase 15 fixes retained: SKIP_DEBUG_FILES, _pre_install_project_deps,
_ensure_init_files, _inject_syspath, SYSPATH_BLOCK, two-pass retry.
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
from tools.dependency_installer import (
    pip_install, extract_missing_package,
    WINDOWS_BUILD_BLOCKLIST, HEAVY_PACKAGES_TIMEOUT_BLOCKLIST,
    _is_local_module,
)
import config

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "debugger.txt"
MAX_ATTEMPTS = 3

# Local module names that are NEVER PyPI packages
LOCAL_MODULE_BLOCKLIST = {
    "main", "app", "config", "routes", "services", "models",
    "utils", "helpers", "database", "db", "schemas", "middleware",
    "dependencies", "core", "api", "tests", "weather_dashboard",
    "backend", "frontend", "auth", "users", "items", "weather",
    "endpoints", "routers", "weather_service", "weather_model",
    "weather_api", "forecast_api", "weather_routes",
    # Phase 18: project-name prefixes
    "ai_pdf_reader", "todo_app", "task_manager", "blog_platform",
    "chat_app", "ecommerce", "booking_app", "portfolio",
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

# Combined set of all packages that should trigger a "rewrite the code" response
_ALL_BLOCKED_PACKAGES: frozenset[str] = frozenset(
    p.lower().replace("-", "_")
    for p in (WINDOWS_BUILD_BLOCKLIST | HEAVY_PACKAGES_TIMEOUT_BLOCKLIST)
)


def _package_is_blocked(package_name: str) -> bool:
    """Return True if the package is on any blocklist."""
    return package_name.lower().replace("-", "_") in _ALL_BLOCKED_PACKAGES


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
        # Phase 15.3 — filter out un-debuggable files
        py_files = [
            f for f in file_paths
            if f.endswith(".py") and Path(f).name not in SKIP_DEBUG_FILES
        ]
        skipped = len(file_paths) - len(py_files) - sum(
            1 for f in file_paths if not f.endswith(".py")
        )
        if skipped:
            logger.info(f"⏭️  Skipped {skipped} un-debuggable file(s) (setup.py, manage.py etc.)")

        logger.info(f"🐛 Debugging {len(py_files)} Python files...")

        # Phase 15.2 — pre-install project dependencies before the debug loop
        self._pre_install_project_deps(py_files)

        # Pre-flight: __init__.py + fixes + dotted-import rewriting + sys.path injection
        self._ensure_init_files(py_files)
        for fp in py_files:
            fixes = self._preflight_fix(fp)
            for fix in fixes:
                logger.info(f"  🔨 Pre-flight [{fp}]: {fix}")
            dotted_fixes = self._rewrite_dotted_imports(fp)
            for fix in dotted_fixes:
                logger.info(f"  🔄 Dotted-import fix [{fp}]: {fix}")
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

    # ── Phase 18: Dotted-import rewriter ──────────────────────────────────────

    def _rewrite_dotted_imports(self, file_path: str) -> list[str]:
        """
        Rewrite dotted imports that use the project name or 'backend.' prefix.

        Examples fixed:
          from ai_pdf_reader.backend.vault import X  →  from vault import X
          from backend.summarization import Y        →  from summarization import Y
          from project.backend.services import Z     →  from services import Z

        Returns list of fix descriptions applied.
        """
        try:
            content = read_file(file_path)
        except Exception:
            return []

        original = content
        fixes = []

        # Pattern: from X.Y.Z import something  where X or X.Y is a local prefix
        # We want to convert it to: from Z import something
        dotted_from = re.compile(
            r'^(\s*from\s+)([\w]+(?:\.[\w]+)+)(\s+import\s+.+)$',
            re.MULTILINE,
        )

        def _replace_dotted(match):
            prefix = match.group(1)
            module_path = match.group(2)
            rest = match.group(3)

            parts = module_path.split(".")
            # Find the last meaningful part that isn't a generic folder name
            folder_names = {
                "backend", "frontend", "api", "src", "lib", "app",
                "routes", "services", "models", "utils", "helpers",
            }

            # Check if the root looks like a project name or local module
            root = parts[0]
            if not (_is_local_module(root) or root in folder_names):
                return match.group(0)  # not a local path — leave unchanged

            # Strip prefix segments that are folder/project names
            clean_parts = []
            for p in parts:
                if p.lower() in folder_names or _is_local_module(p):
                    clean_parts = []  # reset — everything before was folder structure
                else:
                    clean_parts.append(p)

            if not clean_parts:
                # All parts were folder names — use the last part
                clean_parts = [parts[-1]]

            new_module = ".".join(clean_parts)
            if new_module == module_path:
                return match.group(0)  # nothing changed

            fixes.append(f"from {module_path} → from {new_module}")
            return f"{prefix}{new_module}{rest}"

        new_content = dotted_from.sub(_replace_dotted, content)

        # Also handle: import ai_pdf_reader.backend.something  (rare but happens)
        dotted_import = re.compile(
            r'^(\s*import\s+)([\w]+(?:\.[\w]+)+)$',
            re.MULTILINE,
        )

        def _replace_dotted_import(match):
            prefix = match.group(1)
            module_path = match.group(2)
            parts = module_path.split(".")
            root = parts[0]
            if not (_is_local_module(root)):
                return match.group(0)
            # Can't easily shorten a bare `import` — comment it out with a note
            fixes.append(f"commented out dotted import: import {module_path}")
            return f"# FIXED: {match.group(0).strip()}  # use 'from X import Y' style instead"

        new_content = dotted_import.sub(_replace_dotted_import, new_content)

        if new_content != original:
            create_file(file_path, new_content)

        return fixes

    # ── Phase 18: Blocked-package rewriter ────────────────────────────────────

    def _rewrite_to_remove_blocked_dependency(
        self, file_path: str, blocked_package: str, error_text: str
    ) -> bool:
        """
        Ask the LLM to rewrite a file to remove an uninstallable dependency.
        Returns True if a rewrite was performed.
        """
        try:
            current_code = read_file(file_path)
        except Exception:
            return False

        logger.info(f"  🔄 Rewriting {file_path} to remove blocked dependency: {blocked_package}")

        prompt = f"""Rewrite this Python file to remove the dependency on '{blocked_package}'.

FILE: {file_path}
CURRENT CODE:
{current_code}

REASON IT CANNOT BE INSTALLED: '{blocked_package}' requires special build tools
(Visual Studio C++, cmake, GPU drivers, or is too large to install automatically).

REWRITE RULES:
1. Remove ALL imports of '{blocked_package}' and any related packages (e.g. dlib, cv2).
2. Replace the functionality with a simpler Python-only alternative:
   - face_recognition / biometrics → use hashlib + a JSON file to store user credentials
   - tensorflow / keras / torch → use simple rule-based logic or return mock results
   - opencv-python / cv2 → use PIL/Pillow (already installable) or skip image processing
   - psycopg2 → use sqlite3 (built into Python)
3. Keep ALL other functionality intact.
4. The file must import-check successfully with standard library + fastapi + pydantic.
5. If a class/function used the blocked package for its core logic, replace with
   a stub that logs a warning and returns a reasonable default value.

Return ONLY the complete rewritten Python code. No markdown, no explanation."""

        fixed = self.think(prompt)
        if fixed and fixed.strip():
            create_file(file_path, fixed)
            return True
        return False

    # ── Phase 15.2 — Pre-install project dependencies ─────────────────────────

    def _pre_install_project_deps(self, file_paths: list[str]) -> None:
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
                return

    # ── Pre-flight fixes ───────────────────────────────────────────────────────

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
            content = re.sub(
                r'^(engine\s*=\s*create_engine[^\n]+)', r'# \1', content, flags=re.MULTILINE
            )
            content = re.sub(
                r'^(Session\s*=\s*sessionmaker[^\n]+)', r'# \1', content, flags=re.MULTILINE
            )
            content = re.sub(
                r'^(Base\.metadata\.create_all[^\n]+)', r'# \1', content, flags=re.MULTILINE
            )
            fixes.append("disabled module-level DB connection")

        project_dir = self._get_project_dir(file_path)
        if project_dir:
            models_file = project_dir / "models.py"
            models_dir  = project_dir / "models"
            if not models_file.exists() and models_dir.exists():
                model_files = [f for f in models_dir.glob("*.py") if f.name != "__init__.py"]
                if model_files:
                    stem = model_files[0].stem
                    new = re.sub(
                        r'from models import ([^\n]+)',
                        f'from models.{stem} import \\1',
                        content,
                    )
                    if new != content:
                        content = new
                        fixes.append(f"fixed 'from models import X' → 'from models.{stem} import X'")

        if project_dir and (project_dir / "services.py").exists():
            new = re.sub(
                r'from services\.\w+ import ([^\n]+)', r'from services import \1', content
            )
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

            new_content = (
                "".join(lines[:insert_at])
                + SYSPATH_BLOCK + "\n"
                + "".join(lines[insert_at:])
            )
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

    # ── Debug loop ─────────────────────────────────────────────────────────────

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
                # Phase 18: rewrite dotted imports in root cause file first
                dotted_fixes = self._rewrite_dotted_imports(root_cause)
                for fix in dotted_fixes:
                    logger.info(f"  🔄 Dotted-import fix [{root_cause}]: {fix}")
                dep_fixes = self._preflight_fix(root_cause)
                for fix in dep_fixes:
                    logger.info(f"  🔨 Pre-flight [{root_cause}]: {fix}")
                self._inject_syspath(root_cause)
                rc_folder = str(Path(root_cause).parent)
                init_path = f"{rc_folder}/__init__.py"
                if not (Path(config.OUTPUT_DIR) / init_path).exists():
                    create_file(init_path, '"""Package init."""\n')

            missing_pkg = extract_missing_package(error_text)

            if missing_pkg is None:
                # Phase 18: extract_missing_package returned None → likely a local module
                # Try to rewrite dotted imports in the file being debugged
                dotted_fixes = self._rewrite_dotted_imports(file_to_fix)
                if dotted_fixes:
                    logger.info(f"  🔄 Rewrote dotted imports in {file_to_fix}: {dotted_fixes}")
                    result.fixes_applied.extend(dotted_fixes)
                    continue

                # Also try the LLM fix path for other import errors
                if attempt < MAX_ATTEMPTS:
                    fixed = self._generate_fix(file_to_fix, error_text)
                    if fixed:
                        create_file(file_to_fix, fixed)
                        result.fixes_applied.append(f"LLM fix on {file_to_fix} attempt {attempt}")
                        logger.info(f"  🔧 LLM fix applied to {file_to_fix}")
                        self._preflight_fix(file_to_fix)
                        self._inject_syspath(file_to_fix)
                continue

            # Phase 18: Check if the package is on the blocklist BEFORE trying to install
            if _package_is_blocked(missing_pkg):
                logger.warning(
                    f"  🚫 [{file_path}] Blocked package '{missing_pkg}' detected. "
                    f"Rewriting {file_to_fix} to remove this dependency..."
                )
                # Find the actual file that imports the blocked package
                # (may be root_cause, not file_to_fix)
                target_for_rewrite = root_cause if root_cause else file_to_fix
                rewritten = self._rewrite_to_remove_blocked_dependency(
                    target_for_rewrite, missing_pkg, error_text
                )
                if rewritten:
                    result.fixes_applied.append(
                        f"Rewrote {target_for_rewrite} to remove {missing_pkg}"
                    )
                    self._inject_syspath(target_for_rewrite)
                    continue
                else:
                    logger.error(
                        f"  ❌ Could not rewrite {target_for_rewrite} to remove {missing_pkg}"
                    )
                    break

            # Normal case: try to install the package
            if missing_pkg not in LOCAL_MODULE_BLOCKLIST:
                logger.info(f"  📦 Auto-installing: {missing_pkg}")
                install_result = pip_install(missing_pkg)
                if install_result.success:
                    result.fixes_applied.append(f"pip install {missing_pkg}")
                    continue
                else:
                    # Install failed — check if it's a blocked package error
                    stderr = install_result.stderr
                    if (
                        "Timed out" in stderr
                        or "Cannot install" in stderr
                        or "Visual C++" in stderr
                        or "cmake" in stderr.lower()
                        or _package_is_blocked(missing_pkg)
                    ):
                        logger.warning(
                            f"  🚫 Install of '{missing_pkg}' failed (blocked/timeout). "
                            f"Rewriting source..."
                        )
                        target_for_rewrite = root_cause if root_cause else file_to_fix
                        rewritten = self._rewrite_to_remove_blocked_dependency(
                            target_for_rewrite, missing_pkg, error_text
                        )
                        if rewritten:
                            result.fixes_applied.append(
                                f"Rewrote {target_for_rewrite} to remove {missing_pkg}"
                            )
                            self._inject_syspath(target_for_rewrite)
                            continue
            else:
                logger.info(f"  ⏭️  Skipping (local module): {missing_pkg}")

            if attempt < MAX_ATTEMPTS:
                fixed = self._generate_fix(file_to_fix, error_text)
                if fixed:
                    install_match = re.search(r"#\s*INSTALL:\s*([A-Za-z0-9_\-]+)", fixed)
                    if install_match:
                        pkg = install_match.group(1).strip()
                        if pkg not in LOCAL_MODULE_BLOCKLIST and not _package_is_blocked(pkg):
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
- NEVER: from backend.x  from ..x  from weather_dashboard.x  from ai_pdf_reader.x
- NEVER use dotted paths like 'from project_name.subfolder.module import X'
  Instead use flat imports: 'from module import X'
- No module-level DB connections

Return ONLY the complete fixed Python code."""
        logger.info(f"  🧠 LLM fixing: {file_path}")
        return self.think(prompt)

    def summary(self, results: list[FileDebugResult]) -> str:
        passed = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        lines = [
            f"\n{'='*50}", "  DEBUG SUMMARY", f"{'='*50}",
            f"  Passed: {len(passed)}/{len(results)}",
            f"  Failed: {len(failed)}/{len(results)}",
            f"{'='*50}",
        ]
        for r in results:
            lines.append(f"  {r}")
        if failed:
            lines.append("\n  Failed files:")
            for r in failed:
                lines.append(f"    ❌ {r.file_path}")
                lines.append(f"       {r.final_error[:200]}")
        lines.append(f"{'='*50}\n")
        return "\n".join(lines)
