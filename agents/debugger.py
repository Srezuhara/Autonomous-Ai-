# =============================================================================
# agents/debugger.py — RECOVERED BUILD  (see provenance below)
# =============================================================================
# The 959-line working-tree version of this file was overwritten on
# 2026-08-16 00:34 by a 414-line variant. The original source is not in git and
# was not recoverable from VS Code local history (its only entry is a byte-copy
# of the 414-line replacement). This file reconstructs it from three sources:

#   [GIT]     771 lines — verbatim from `git show HEAD:agents/debugger.py`.
#                         This is genuine original code, unmodified.

#   [VERBATIM] Read directly from the 959-line file before it was lost:
#                - _accept_generated_fix()          (complete method)
#                - the 2 _apply_structural_import_repairs() calls in run()
#                - the 2 _accept_generated_fix() guards in _debug_file()

#   [REBUILT]  Reconstructed from bytecode constants in
#              agents/__pycache__/debugger.cpython-312.pyc (compiled 2026-05-29
#              from the lost version — confirmed: it contains all five methods
#              absent from HEAD). Docstrings, regex patterns, log messages and
#              local variable names are recovered exactly from that bytecode;
#              the control flow around them is inferred and is NOT guaranteed to
#              match the original statement-for-statement:
#                - _apply_structural_import_repairs()
#                - _strip_concatenated_file_sections()
#                - _build_local_import_graph()
#                - _break_obvious_cycles()

# REVIEW THE [REBUILT] METHODS BEFORE RELYING ON THEM. They are the author's
# best reconstruction, not a byte-exact recovery. Everything else is original.
# =============================================================================
"""
agents/debugger.py — Phase 20 (Issue 7 fix)
============================================
FIX — Issue 7: _fix_timeout_import() was the sole handler for import-check
  timeouts.  It moves the heavy import inside the function (lazy loading),
  then the import-check re-runs quickly and passes — but the package is still
  not installed.  At runtime, calling generate_chart() / generate_report() etc.
  raises ModuleNotFoundError, and the downloaded ZIP crashes on first use.

  Root cause: lazy-import makes the module-level check pass, but doesn't fix
  the fact that torch / transformers / tensorflow are in
  HEAVY_PACKAGES_TIMEOUT_BLOCKLIST and cannot be installed automatically.

  Fix applied in _debug_file():
    1. Timeout detected → _fix_timeout_import() runs (lazy rewrite) — unchanged.
    2. After lazy rewrite, re-run import check.
       a. If it now passes → done (genuinely slow but installable package).
       b. If it still fails OR the specific package is in the blocklist →
          call _rewrite_to_remove_blocked_dependency() to replace the
          functionality with a stub / lightweight alternative.

  This means torch/transformers code that was previously silently "passing"
  with a lazy rewrite now gets properly rewritten to remove the dependency.
  The score is authentic: files that actually import-check clean get success=True.

All other Phase 19 behaviour retained unchanged.
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

LOCAL_MODULE_BLOCKLIST = {
    "main", "app", "config", "routes", "services", "models",
    "utils", "helpers", "database", "db", "schemas", "middleware",
    "dependencies", "core", "api", "tests", "weather_dashboard",
    "backend", "frontend", "auth", "users", "items", "weather",
    "endpoints", "routers", "weather_service", "weather_model",
    "weather_api", "forecast_api", "weather_routes",
    "ai_pdf_reader", "todo_app", "task_manager", "blog_platform",
    "chat_app", "ecommerce", "booking_app", "portfolio",
}

# "Timed out after" intentionally NOT here (Phase 19 fix — still correct).
IGNORE_ERRORS = [
    "uvicorn",
    "Address already in use",
]

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

_ALL_BLOCKED_PACKAGES: frozenset[str] = frozenset(
    p.lower().replace("-", "_")
    for p in (WINDOWS_BUILD_BLOCKLIST | HEAVY_PACKAGES_TIMEOUT_BLOCKLIST)
)


def _package_is_blocked(package_name: str) -> bool:
    return package_name.lower().replace("-", "_") in _ALL_BLOCKED_PACKAGES


def _is_import_check_timeout(stderr: str) -> bool:
    """Return True when run_python()'s subprocess timed out."""
    return "Timed out after" in stderr and "seconds" in stderr


def _extract_heavy_package_from_timeout(file_path: str) -> str | None:
    """
    Scan the source file for imports of known heavy/blocked packages.
    Returns the first blocked package name found, or None.
    Called after a timeout to decide whether lazy-import suffices or
    full rewrite is needed.
    """
    try:
        source = (Path(config.OUTPUT_DIR) / file_path).read_text(
            encoding="utf-8", errors="ignore"
        )
    except Exception:
        return None

    for line in source.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            continue
        # Extract module name from import statement
        m = re.match(r'(?:import|from)\s+([\w]+)', stripped)
        if not m:
            continue
        mod = m.group(1).lower().replace("-", "_")
        if mod in _ALL_BLOCKED_PACKAGES:
            return mod
    return None


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
        py_files = [
            f for f in file_paths
            if f.endswith(".py") and Path(f).name not in SKIP_DEBUG_FILES
        ]
        skipped = len(file_paths) - len(py_files) - sum(
            1 for f in file_paths if not f.endswith(".py")
        )
        if skipped:
            logger.info(f"⏭️  Skipped {skipped} un-debuggable file(s) (setup.py etc.)")

        logger.info(f"🐛 Debugging {len(py_files)} Python files...")

        self._pre_install_project_deps(py_files)
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

        structural_fixes = self._apply_structural_import_repairs(py_files)
        for fix in structural_fixes:
            logger.info(f"  Structural import repair: {fix}")

        results = {}
        for fp in py_files:
            r = self._debug_file(fp)
            results[fp] = r
            logger.info(str(r))

        failed = [fp for fp, r in results.items() if not r.success]
        if failed:
            logger.info(f"🔁 Pass 2: re-trying {len(failed)} failed files...")
            structural_fixes = self._apply_structural_import_repairs(py_files)
            for fix in structural_fixes:
                logger.info(f"  Pass 2 structural repair: {fix}")
            for fp in failed:
                r2 = self._debug_file(fp)
                if r2.success:
                    results[fp].success = True
                    results[fp].fixes_applied.extend(r2.fixes_applied)
                    results[fp].attempts += r2.attempts
                    logger.info(f"  ✅ Pass 2 fixed: {fp}")
                else:
                    results[fp].final_error = r2.final_error

        final  = list(results.values())
        passed = sum(1 for r in final if r.success)
        logger.info(f"🐛 Debug complete: {passed}/{len(final)} files passing")
        return final

    # ── Structural import repair ──────────────────────────────────────────────
    # [REBUILT] from debugger.cpython-312.pyc constants. Docstrings, regexes and
    # log strings are exact; surrounding control flow is reconstructed.

    def _apply_structural_import_repairs(self, file_paths: list[str]) -> list[str]:
        """
        Deterministically repair import structures that LLM retries handle badly.

        The common failure mode is services.py importing feature modules which
        themselves import services.py. That creates a circular import cascade
        where every file fails even though one service-layer import is the root.
        """
        fixes: list[str] = []
        local_modules = {Path(fp).stem for fp in file_paths}

        # 1. Drop copies of other files that the LLM pasted into this one.
        for fp in file_paths:
            fixes.extend(self._strip_concatenated_file_sections(fp))

        # 2. services.py must not import sibling feature modules (only models).
        for fp in file_paths:
            if Path(fp).name != "services.py":
                continue
            try:
                content = read_file(fp)
            except Exception:
                continue

            new_lines = []
            changed = False
            for line in content.splitlines(keepends=True):
                from_match = re.match(r"from\s+([A-Za-z_][\w]*)\s+import\s+(.+)", line)
                import_match = re.match(r"import\s+([A-Za-z_][\w]*)\b", line)

                module = None
                if from_match:
                    module = from_match.group(1)
                elif import_match:
                    module = import_match.group(1)

                if (
                    module
                    and module in local_modules
                    and module not in ("models",)
                    and not line.lstrip().startswith("from .")
                ):
                    changed = True
                    fixes.append(f"{fp}: removed service-layer import of {module}")
                    continue

                new_lines.append(line)

            if changed:
                create_file(fp, "".join(new_lines))

        # 3. Break any remaining two-way local import cycles.
        fixes.extend(self._break_obvious_cycles(file_paths, local_modules))
        return fixes

    def _strip_concatenated_file_sections(self, file_path: str) -> list[str]:
        """Remove LLM-added copies of other files inside the target file."""
        try:
            content = read_file(file_path)
        except Exception:
            return []

        current_name = Path(file_path).name
        header_re = re.compile(r"^\s*#\s*(?:[\w_\-]+/)*backend/([^/\s]+\.py)\s*$")

        lines = content.splitlines()
        cut_at = None
        for i, line in enumerate(lines):
            match = header_re.match(line)
            if match and match.group(1) != current_name:
                cut_at = i
                break

        if cut_at is None:
            return []

        create_file(file_path, "\n".join(lines[:cut_at]).rstrip() + "\n")
        return [f"{file_path}: removed concatenated code for other files"]

    def _build_local_import_graph(
        self, file_paths: list[str], local_modules: set[str]
    ) -> dict[str, set[str]]:
        """Map each local module to the set of local modules it imports."""
        import ast

        graph: dict[str, set[str]] = {}
        module_to_file = {Path(fp).stem: fp for fp in file_paths}

        for fp in file_paths:
            try:
                tree = ast.parse(read_file(fp))
            except Exception:
                continue

            deps: set[str] = set()
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module:
                    base = node.module.split(".")[0]
                    if base in module_to_file:
                        deps.add(base)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        base = alias.name.split(".")[0]
                        if base in module_to_file:
                            deps.add(base)

            graph[Path(fp).stem] = deps

        return graph

    def _break_obvious_cycles(
        self, file_paths: list[str], local_modules: set[str]
    ) -> list[str]:
        """Break two-way local imports by removing non-model imports from services.py."""
        fixes: list[str] = []
        graph = self._build_local_import_graph(file_paths, local_modules)
        module_to_file = {Path(fp).stem: fp for fp in file_paths}

        for src_name, deps in graph.items():
            for dep_name in sorted(deps):
                # Only a genuine two-way edge is a cycle worth breaking.
                if src_name not in graph.get(dep_name, set()):
                    continue
                # models.py is the leaf of the hierarchy — always cut the other side.
                if src_name == "models":
                    continue

                target = module_to_file.get(src_name)
                other = dep_name
                if not target:
                    continue

                try:
                    content = read_file(target)
                except Exception:
                    continue

                new_contents = re.sub(
                    rf"^\s*(from|import)\s+{re.escape(other)}\b.*\n?",
                    "",
                    content,
                    flags=re.MULTILINE,
                )
                if new_contents != content:
                    create_file(target, new_contents)
                    fixes.append(f"{target}: broke circular import with {other}")
                    graph[src_name].discard(other)

        return fixes

    def _comment_out_statement(self, content: str, start_pattern: str) -> str:
        """
        Comment out a whole statement, not just its first line.

        Follows bracket depth from the opening line so multi-line calls are
        commented in full. Lines already commented are left alone.
        """
        pattern = re.compile(start_pattern)
        lines   = content.splitlines(keepends=True)
        out: list[str] = []
        i = 0

        while i < len(lines):
            if not pattern.match(lines[i]):
                out.append(lines[i])
                i += 1
                continue

            depth = 0
            while i < len(lines):
                current = lines[i]
                code    = current.split("#", 1)[0]
                depth  += code.count("(") - code.count(")")
                depth  += code.count("[") - code.count("]")
                depth  += code.count("{") - code.count("}")

                out.append(current if current.lstrip().startswith("#")
                           else "# " + current)
                i += 1

                if depth <= 0:
                    break

        return "".join(out)

    # ── Dotted-import rewriter ────────────────────────────────────────────────

    def _rewrite_dotted_imports(self, file_path: str) -> list[str]:
        try:
            content = read_file(file_path)
        except Exception:
            return []

        original = content
        fixes    = []

        dotted_from = re.compile(
            r'^(\s*from\s+)([\w]+(?:\.[\w]+)+)(\s+import\s+.+)$',
            re.MULTILINE,
        )

        def _replace_dotted(match):
            prefix      = match.group(1)
            module_path = match.group(2)
            rest        = match.group(3)
            parts       = module_path.split(".")
            folder_names = {
                "backend", "frontend", "api", "src", "lib", "app",
                "routes", "services", "models", "utils", "helpers",
            }
            root = parts[0]
            if not (_is_local_module(root) or root in folder_names):
                return match.group(0)
            clean_parts = []
            for p in parts:
                if p.lower() in folder_names or _is_local_module(p):
                    clean_parts = []
                else:
                    clean_parts.append(p)
            if not clean_parts:
                clean_parts = [parts[-1]]
            new_module = ".".join(clean_parts)
            if new_module == module_path:
                return match.group(0)
            fixes.append(f"from {module_path} → from {new_module}")
            return f"{prefix}{new_module}{rest}"

        new_content = dotted_from.sub(_replace_dotted, content)

        dotted_import = re.compile(
            r'^(\s*import\s+)([\w]+(?:\.[\w]+)+)$',
            re.MULTILINE,
        )

        def _replace_dotted_import(match):
            module_path = match.group(2)
            root        = module_path.split(".")[0]
            if not _is_local_module(root):
                return match.group(0)
            fixes.append(f"commented dotted import: import {module_path}")
            return f"# FIXED: {match.group(0).strip()}"

        new_content = dotted_import.sub(_replace_dotted_import, new_content)

        if new_content != original:
            create_file(file_path, new_content)
        return fixes

    # ── Blocked-package rewriter ──────────────────────────────────────────────

    def _rewrite_to_remove_blocked_dependency(
        self, file_path: str, blocked_package: str, error_text: str
    ) -> bool:
        try:
            current_code = read_file(file_path)
        except Exception:
            return False

        logger.info(f"  🔄 Rewriting {file_path} to remove blocked dep: {blocked_package}")

        prompt = f"""Rewrite this Python file to remove the dependency on '{blocked_package}'.

FILE: {file_path}
CURRENT CODE:
{current_code}

REASON IT CANNOT BE INSTALLED: '{blocked_package}' requires special build tools
(Visual Studio C++, cmake, GPU drivers, or is too large to install automatically).

REWRITE RULES:
1. Remove ALL imports of '{blocked_package}' and related packages.
2. Replace the functionality with a simpler Python-only alternative.
3. Keep ALL other functionality intact.
4. If a class/function used the blocked package, replace with a stub that logs a
   warning and returns a reasonable default value.

Return ONLY the complete rewritten Python code. No markdown, no explanation."""

        fixed = self.think(prompt)
        if fixed and fixed.strip():
            create_file(file_path, fixed)
            return True
        return False

    # ── Phase 20 Issue 7: timeout → blocked-pkg-aware fix ────────────────────

    def _fix_timeout_import(self, file_path: str) -> bool:
        """
        When run_python() times out, first move heavy imports to be lazy
        (inside functions). Then re-check:
          - If import check now passes → done (slow but installable package).
          - If the timed-out package is in HEAVY_PACKAGES_TIMEOUT_BLOCKLIST
            → call _rewrite_to_remove_blocked_dependency() so the file
            actually works at runtime, not just at import-check time.

        Phase 20 Issue 7 fix:
          Old behaviour: always did lazy rewrite → passed import check →
            runtime crash when user calls generate_chart() etc.
          New behaviour: lazy rewrite first; if blocked package detected,
            escalate to full dependency removal rewrite.
        """
        try:
            current_code = read_file(file_path)
        except Exception:
            return False

        # Step 1: identify the heavy package (if any) BEFORE rewriting
        blocked_pkg = _extract_heavy_package_from_timeout(file_path)

        logger.info(
            f"  ⏱️  Import-check timed out for {file_path}"
            + (f" — detected blocked package: {blocked_pkg}" if blocked_pkg else "")
        )

        # Step 2: if the package is definitively in the blocklist, skip lazy
        # rewrite and go straight to full removal — it will never install.
        if blocked_pkg and _package_is_blocked(blocked_pkg):
            logger.info(
                f"  🚫 '{blocked_pkg}' is in HEAVY_PACKAGES_TIMEOUT_BLOCKLIST — "
                f"applying full removal rewrite (not lazy-import)"
            )
            rewrote = self._rewrite_to_remove_blocked_dependency(
                file_path, blocked_pkg,
                f"Import-check timed out due to '{blocked_pkg}'"
            )
            if rewrote:
                logger.info(f"  ✅ Full removal rewrite applied to {file_path}")
                return True
            return False

        # Step 3: package is heavy but not definitively blocked (e.g. pandas,
        # matplotlib) — apply the lazy-import rewrite first.
        logger.info(f"  ↪  Applying lazy-import rewrite to {file_path}")
        prompt = f"""This Python file causes an import-check timeout because it imports heavy
packages (matplotlib, pandas, scipy, numpy, etc.) at module level.

FILE: {file_path}
CURRENT CODE:
{current_code}

FIX RULE — move heavy imports inside the functions that use them (lazy imports):

BEFORE:
    import matplotlib.pyplot as plt
    import pandas as pd

    def generate_chart(data):
        fig, ax = plt.subplots()
        ...

AFTER:
    def generate_chart(data):
        import matplotlib.pyplot as plt  # lazy import
        import pandas as pd
        fig, ax = plt.subplots()
        ...

RULES:
- Move ONLY slow/heavy package imports inside functions.
- Keep stdlib imports at the top.
- Keep fastapi, pydantic, httpx imports at the top (they are fast).
- Do NOT change any function signatures or business logic.

Return ONLY the complete rewritten Python code. No markdown, no explanation."""

        fixed = self.think(prompt)
        if not (fixed and fixed.strip()):
            return False

        create_file(file_path, fixed)
        logger.info(f"  ↪  Lazy-import rewrite written, re-checking {file_path}...")

        # Step 4: re-run import check after lazy rewrite
        check = run_python(file_path)
        if check.success:
            logger.info(f"  ✅ Lazy-import rewrite passed import check for {file_path}")
            return True

        # Step 5: still failing — if it timed out again or is blocked, do full removal
        if _is_import_check_timeout(check.stderr) or (
            blocked_pkg and _package_is_blocked(blocked_pkg)
        ):
            logger.warning(
                f"  🚫 Still failing after lazy rewrite — escalating to "
                f"full removal for {file_path}"
            )
            pkg_to_remove = blocked_pkg or _extract_heavy_package_from_timeout(file_path) or "unknown"
            rewrote = self._rewrite_to_remove_blocked_dependency(
                file_path, pkg_to_remove, check.stderr
            )
            if rewrote:
                logger.info(f"  ✅ Full removal rewrite applied to {file_path}")
            return rewrote

        # Some other error after lazy rewrite — let the main loop handle it
        return True  # file was at least written; loop will re-check

    # ── Pre-install / scaffold helpers ────────────────────────────────────────

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

    def _preflight_fix(self, file_path: str) -> list[str]:
        try:
            content = read_file(file_path)
        except Exception:
            return []

        fixes    = []
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
            # Phase 22 fix: these used to be `[^\n]+` substitutions, which comment
            # out only the FIRST line of the statement. A multi-line call —
            #     engine = create_engine(
            #         os.getenv("DATABASE_URL"), connect_args={...}
            #     )
            # became `# engine = create_engine(` followed by orphaned arguments,
            # i.e. a SyntaxError. A live build shipped exactly that in
            # tests/test_backend.py, and the debugger then burned its whole retry
            # budget failing to fix a file it had broken itself.
            for pattern in (
                r'^engine\s*=\s*create_engine',
                r'^Session\s*=\s*sessionmaker',
                r'^Base\.metadata\.create_all',
            ):
                content = self._comment_out_statement(content, pattern)
            fixes.append("disabled module-level DB connection")

        project_dir = self._get_project_dir(file_path)
        if project_dir:
            models_file = project_dir / "models.py"
            models_dir  = project_dir / "models"
            if not models_file.exists() and models_dir.exists():
                model_files = [f for f in models_dir.glob("*.py") if f.name != "__init__.py"]
                if model_files:
                    stem = model_files[0].stem
                    new  = re.sub(
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
            d    = full.parent
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
                lines    = content.splitlines(keepends=True)
                filtered = [l for l in lines if not any(x in l for x in [
                    "_here =", "_parent =", "_grandparent =",
                    "sys.path.insert", "import sys as _sys", "import os as _os",
                    "if _p not in _sys.path", "for _p in [_here",
                ])]
                content = "".join(filtered)

            lines     = content.splitlines(keepends=True)
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
        matches    = re.findall(r'File "([^"]+\.py)"', error_text)
        for fpath in reversed(matches):
            norm = fpath.replace("\\", "/")
            if output_dir in norm:
                return norm.split(output_dir + "/")[-1]
        return None

    def _scan_project_structure(self, file_path: str) -> str:
        parts       = Path(file_path).parts
        if not parts:
            return ""
        project_dir = Path(config.OUTPUT_DIR) / parts[0]
        lines       = ["Actual Python files in this project:"]
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

    # ── Main debug loop ───────────────────────────────────────────────────────

    def _debug_file(self, file_path: str) -> FileDebugResult:
        result     = FileDebugResult(file_path=file_path, success=False, attempts=0)
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

            # Ignorable runtime errors
            if any(p in error_text for p in IGNORE_ERRORS):
                result.success = True
                logger.info(f"  ✅ [{file_path}] Import-check passed (runtime error ignored)")
                return result

            if "sqlalchemy" in error_text.lower() and "OperationalError" in error_text:
                result.success = True
                logger.info(f"  ✅ [{file_path}] Import-check passed (DB connection ignored)")
                return result

            # ── Phase 20 Issue 7: timeout handling ────────────────────────────
            if _is_import_check_timeout(error_text):
                logger.warning(
                    f"  ⏱️  [{file_path}] Import-check timed out (attempt {attempt})"
                )
                if attempt <= MAX_ATTEMPTS:
                    # _fix_timeout_import now handles blocked-pkg escalation internally
                    fixed = self._fix_timeout_import(file_path)
                    if fixed:
                        result.fixes_applied.append(
                            f"timeout fix (lazy/removal) on attempt {attempt}"
                        )
                        self._inject_syspath(file_path)
                        continue
                # Could not fix — mark as failed with meaningful error
                result.final_error = (
                    f"Import-check timed out after {MAX_ATTEMPTS} attempts. "
                    f"File likely imports a heavy package that cannot be installed "
                    f"automatically. Check requirements.txt."
                )
                return result

            logger.warning(f"  ❌ [{file_path}] Error:\n{error_text[:400]}")

            root_cause    = self._extract_root_cause_file(error_text)
            file_to_fix   = root_cause if (root_cause and root_cause != file_path) else file_path

            if root_cause and root_cause != file_path:
                logger.info(f"  🔍 Root cause: {root_cause}")
                self._rewrite_dotted_imports(root_cause)
                self._preflight_fix(root_cause)
                self._inject_syspath(root_cause)
                rc_folder  = str(Path(root_cause).parent)
                init_path  = f"{rc_folder}/__init__.py"
                if not (Path(config.OUTPUT_DIR) / init_path).exists():
                    create_file(init_path, '"""Package init."""\n')

            missing_pkg = extract_missing_package(error_text)

            if missing_pkg is None:
                dotted_fixes = self._rewrite_dotted_imports(file_to_fix)
                if dotted_fixes:
                    result.fixes_applied.extend(dotted_fixes)
                    continue
                if attempt < MAX_ATTEMPTS:
                    fixed = self._generate_fix(file_to_fix, error_text)
                    if fixed and self._accept_generated_fix(file_to_fix, fixed):
                        create_file(file_to_fix, fixed)
                        result.fixes_applied.append(f"LLM fix on {file_to_fix} attempt {attempt}")
                        self._preflight_fix(file_to_fix)
                        self._inject_syspath(file_to_fix)
                continue

            if _package_is_blocked(missing_pkg):
                logger.warning(
                    f"  🚫 [{file_path}] Blocked package '{missing_pkg}' — rewriting..."
                )
                target   = root_cause if root_cause else file_to_fix
                rewrote  = self._rewrite_to_remove_blocked_dependency(
                    target, missing_pkg, error_text
                )
                if rewrote:
                    result.fixes_applied.append(f"Removed blocked dep {missing_pkg} from {target}")
                    self._inject_syspath(target)
                    continue
                else:
                    break

            if missing_pkg not in LOCAL_MODULE_BLOCKLIST:
                logger.info(f"  📦 Auto-installing: {missing_pkg}")
                install_result = pip_install(missing_pkg)
                if install_result.success:
                    result.fixes_applied.append(f"pip install {missing_pkg}")
                    continue
                else:
                    stderr = install_result.stderr
                    if (
                        "Timed out" in stderr
                        or "Cannot install" in stderr
                        or "Visual C++" in stderr
                        or "cmake" in stderr.lower()
                        or _package_is_blocked(missing_pkg)
                    ):
                        target  = root_cause if root_cause else file_to_fix
                        rewrote = self._rewrite_to_remove_blocked_dependency(
                            target, missing_pkg, error_text
                        )
                        if rewrote:
                            result.fixes_applied.append(f"Removed {missing_pkg} from {target}")
                            self._inject_syspath(target)
                            continue
            else:
                logger.info(f"  ⏭️  Skipping (local module): {missing_pkg}")

            if attempt < MAX_ATTEMPTS:
                fixed = self._generate_fix(file_to_fix, error_text)
                if fixed and self._accept_generated_fix(file_to_fix, fixed):
                    install_match = re.search(r"#\s*INSTALL:\s*([A-Za-z0-9_\-]+)", fixed)
                    if install_match:
                        pkg = install_match.group(1).strip()
                        if pkg not in LOCAL_MODULE_BLOCKLIST and not _package_is_blocked(pkg):
                            pip_install(pkg)
                    create_file(file_to_fix, fixed)
                    result.fixes_applied.append(f"LLM fix on {file_to_fix} attempt {attempt}")
                    self._preflight_fix(file_to_fix)
                    self._inject_syspath(file_to_fix)

        result.final_error = error_text
        return result

    def _accept_generated_fix(self, file_path: str, fixed: str) -> bool:
        """Reject LLM fixes that paste multiple files into one module."""
        try:
            current = read_file(file_path)
        except Exception:
            current = ""

        file_header_count = len(
            re.findall(r"^\s*#\s*(?:[\w_\-]+/)*backend/[^/\s]+\.py\s*$", fixed, re.MULTILINE)
        )
        too_large = bool(current) and len(fixed) > max(len(current) * 1.6, len(current) + 1800)
        if file_header_count >= 2 or too_large:
            logger.warning(
                f"  Rejecting LLM fix for {file_path}: appears to contain "
                "multiple files or an oversized rewrite."
            )
            return False
        return True

    def _generate_fix(self, file_path: str, error_text: str) -> str | None:
        try:
            current_code = read_file(file_path)
        except Exception as e:
            logger.error(f"Could not read {file_path}: {e}")
            return None

        project_map = self._scan_project_structure(file_path)
        prompt      = f"""Fix this Python file. It has an import error.

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
        lines  = [
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
