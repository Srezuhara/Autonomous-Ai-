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
import ast
import re
import sys
import os
from pathlib import Path
from dataclasses import dataclass, field
from agents.base_agent import BaseAgent
from tools.file_writer import read_file, create_file
from tools.code_executor import run_python
from tools.code_patcher import locate_block, splice, file_digest
from tools.runtime_smoke import _parse_frames
from tools.code_introspect import shadows_installed_package
from tools.repair_guard import (
    accept_generated_fix,
    top_level_symbols,
    _top_level_symbols_by_regex as _rg_symbols_by_regex,
)
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

# Directories whose Python files are executed BY a framework, with a context it
# supplies, and can never be imported standalone. Alembic's env.py is the case
# that shipped: `from alembic import context` gives a proxy module that is only
# populated while alembic is running a migration, so importing env.py directly
# raises "module 'alembic.context' has no attribute 'config'" no matter how
# correct the file is. Row 3 spent debugger attempts on it and then reported it
# as a failing backend file. Matching by directory rather than filename because
# `env.py` is far too common a name to skip everywhere.
FRAMEWORK_SCRIPT_DIRS = {"alembic", "migrations", "versions"}


def _is_framework_script(file_path: str) -> bool:
    """True for a file a framework runs for us, which no import check can load."""
    parts = [p.lower() for p in Path(str(file_path).replace("\\", "/")).parts]
    return any(p in FRAMEWORK_SCRIPT_DIRS for p in parts[:-1])

def _is_sibling_pkg_head(module: str) -> bool:
    """True for `backend`, a project-root package name, or any single segment.

    Used to spot `from backend import models`, where the sibling is the NAME
    rather than the module path.
    """
    return bool(module) and "." not in module


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


# A reply that must reproduce a block of code cannot be shorter than that block,
# but every prompt below asked for one under the Debugger's flat 1,600-token cap.
# Matrix row 3 (2026-08-28) is what that costs: a 10,775-character routes.py with
# twelve endpoints returning 500, whose repair came back compressed, lost a
# top-level name, and was rejected by the shrinkage guard — so the build shipped
# with the bug the smoke test had already found and named.
#
# There is deliberately NO ceiling here. Groq allows 8,000 tokens per minute
# covering prompt and completion together, and `llm_client` already discovers
# that from the `x-ratelimit-limit-tokens` header and clamps every request to fit
# (`_fit_output_budget_to_model_limit`). A second ceiling in this file could only
# be wrong: too low and it truncates, too high and it is never reached. Ask for
# what the text needs and let the one component that knows the limit enforce it.
_REWRITE_CHARS_PER_TOKEN = 3       # measured on this model's Python output (~3.3)
_REWRITE_HEADROOM        = 400     # a fix is usually a little longer than the bug

# Below this, repairing one block COSTS more than rewriting the file: the block
# prompt carries extra rules and a digest of the rest of the file, and on a
# 322-character module that scaffolding outweighs the body it saves (measured:
# 1,414 chars targeted vs 1,356 whole-file). Small files also give the model
# more to work with when sent whole, and skip the splice entirely.
_TARGETED_MIN_FILE_CHARS = 2000


def _shared_cause(error_text: str) -> str:
    """
    The exception type when many endpoints fail the same way, else "".

    A block repair fixes the block the traceback names. That is right when one
    endpoint is wrong, and useless when twenty are wrong for one reason — the
    cause is then somewhere no traceback points at, because the code that should
    have run never did.

    Both live examples say the same thing. Row 3 (2026-08-28): twelve endpoints,
    every one `OperationalError: no such table`, because `@router.on_event(
    "startup")` does not fire for an included router, so init_db() never ran.
    Repairing `list_suppliers` was applied and changed nothing — worse than
    nothing, since it edited code that was never wrong. Row 1, a day earlier:
    three endpoints, every one `AttributeError: 'generator' object has no
    attribute 'execute'`, and the fault was a duplicated `get_db`.

    In both, the repair belongs in a block the failures do not name. So the test
    is: more than one endpoint, one exception type, and more than one distinct
    function blamed. That last clause is what separates a shared cause from one
    broken handler probed twice.
    """
    entries = [ln for ln in (error_text or "").splitlines() if " (at " in ln]
    if len(entries) < 2:
        return ""

    types, functions = set(), set()
    for line in entries:
        head = line.split(" (at ", 1)[0]
        # "GET /x -> 500: OperationalError: no such table: supplier"
        message = head.split(": ", 1)[1] if ": " in head else head
        types.add(message.split(":", 1)[0].strip())
        frames = _parse_frames(line)
        if frames:
            functions.add(frames[-1]["function"])

    if len(types) == 1 and len(functions) > 1:
        return types.pop()
    return ""


def _rewrite_budget(agent, current_code: str) -> int:
    """Output cap for a prompt that must return code, sized to the code."""
    needed = len(current_code or "") // _REWRITE_CHARS_PER_TOKEN + _REWRITE_HEADROOM
    return max(agent._token_budget, needed)


class Debugger(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("Debugger", system_prompt)

    def run(
        self,
        file_paths: list[str],
        runtime_errors: dict | None = None,
    ) -> list[FileDebugResult]:
        """
        `runtime_errors` maps a file to a failure the *running* app produced —
        a 5xx from the smoke test, with its traceback. The import check cannot
        see those: the module imports fine, and the handler only breaks once a
        request arrives. Without them a file like this is "passing" and the
        repair passes skip it, which is exactly what happened to a build whose
        three DB routes returned 500 on every call.
        """
        runtime_errors = runtime_errors or {}
        py_files = [
            f for f in file_paths
            if f.endswith(".py")
            and Path(f).name not in SKIP_DEBUG_FILES
            and not _is_framework_script(f)
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
            r = self._debug_file(fp, runtime_error=runtime_errors.get(fp, ""))
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

    def _normalise_sibling_imports(self, file_paths: list) -> list:
        """
        Rewrite package-qualified and relative imports to the flat sibling form
        `prompts/backend_developer.txt` mandates and the sys.path shim supports.

        The prompt could not be plainer — "All backend/ files are siblings ...
        NEVER: from backend.x  from ..x" — and the model ignores it anyway: 39
        violations across 10 of the saved builds, measured 2026-08-31.

        Row 3 is what it costs. `main.py` used the forbidden
        `from backend import models` beside the correct
        `from routes import router`, while `routes.py` used `from . import
        models`. Mixed like that the package is unimportable either way round:
        loading `routes` flat breaks its relative import, and the shim that puts
        `backend/` on the path is what makes the flat load happen. Every file
        obeying one convention works; the mixture cannot.

        Deterministic, zero-token, and conservative: a line is rewritten ONLY
        when the module it names resolves to a real sibling file next to the
        importer. Anything that does not resolve is left exactly as it is —
        a third-party package called `backend` is not this function's business.
        """
        import ast

        fixes: list = []
        for fp in file_paths:
            if not str(fp).endswith(".py"):
                continue
            try:
                content = read_file(fp)
            except Exception:
                continue
            if "import" not in content:
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                # Unparseable files are somebody else's repair; guessing at
                # import lines with a regex here is how good code gets broken.
                continue

            directory = (Path(config.OUTPUT_DIR) / fp).parent

            def _is_sibling(name: str) -> bool:
                if not name or not name.isidentifier():
                    return False
                return ((directory / f"{name}.py").is_file()
                        or (directory / name / "__init__.py").is_file())

            replacements: dict = {}
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if getattr(node, "end_lineno", None) is None:
                    continue

                module = node.module or ""
                level = node.level or 0
                names = [(a.name, a.asname) for a in node.names]

                if level == 0 and not module:
                    continue

                # `from . import models`  /  `from backend import models`
                # The imported NAMES are the sibling modules.
                if (level and not module) or (
                        not level and _is_sibling_pkg_head(module)
                        and all(_is_sibling(n) for n, _ in names)):
                    if not all(_is_sibling(n) for n, _ in names):
                        continue
                    parts = [f"{n} as {a}" if a else n for n, a in names]
                    new = f"import {', '.join(parts)}"
                else:
                    # `from .services import f` / `from backend.services import f`
                    # / `from proj.backend.services import f` — the LAST segment
                    # of the dotted path is the sibling module.
                    tail = module.rsplit(".", 1)[-1] if module else ""
                    if not tail or not _is_sibling(tail):
                        continue
                    if not level and tail == module:
                        continue  # already flat
                    parts = [f"{n} as {a}" if a else n for n, a in names]
                    new = f"from {tail} import {', '.join(parts)}"

                replacements[(node.lineno, node.end_lineno)] = new

            if not replacements:
                continue

            lines = content.splitlines(keepends=True)
            out, i, changed = [], 0, 0
            while i < len(lines):
                span = next((k for k in replacements if k[0] == i + 1), None)
                if span is None:
                    out.append(lines[i])
                    i += 1
                    continue
                indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
                out.append(f"{indent}{replacements[span]}\n")
                changed += 1
                i = span[1]  # skip the statement's remaining lines

            if not changed:
                continue

            new_content = "".join(out)
            try:
                ast.parse(new_content)
            except SyntaxError:
                logger.warning(
                    f"  \u26a0\ufe0f  import normalisation would break {fp}; left alone")
                continue

            create_file(fp, new_content)
            fixes.append(fp)
            logger.info(
                f"  \U0001f9ed Normalised {changed} import(s) in {fp} to the flat "
                "sibling form the prompt requires")

        return fixes

    def _apply_structural_import_repairs(self, file_paths: list[str]) -> list[str]:
        """
        Deterministically repair import structures that LLM retries handle badly.

        The common failure mode is services.py importing feature modules which
        themselves import services.py. That creates a circular import cascade
        where every file fails even though one service-layer import is the root.
        """
        fixes: list[str] = []
        local_modules = {Path(fp).stem for fp in file_paths}

        # 0. Put every sibling import into the one convention the prompt
        #    mandates. Runs first: the later rules reason about which modules a
        #    file imports, and they should see the normalised form.
        fixes.extend(self._normalise_sibling_imports(file_paths))

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

        fixed = self.think(prompt, max_tokens=_rewrite_budget(self, current_code))
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

        fixed = self.think(prompt, max_tokens=_rewrite_budget(self, current_code))
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
            # See architect._ensure_init_files: a folder named after an
            # installed package must not become one, or it shadows the real
            # thing on sys.path.
            if shadows_installed_package(folder):
                continue
            init = f"{folder}/__init__.py"
            if not (Path(config.OUTPUT_DIR) / init).exists():
                create_file(init, '"""Package init."""\n')
                logger.info(f"  📦 Added __init__.py: {folder}/")

    @staticmethod
    def _after_future_imports(content: str, lines: list, insert_at: int) -> int:
        """
        The first line index at which code may be inserted.

        Parsed with `ast` rather than scanned, because a `__future__` import can
        span lines (`from __future__ import (annotations,
 generator_stop)`)
        and a regex that misses the closing paren inserts into the middle of a
        statement. Falls back to a line scan when the file does not parse —
        which is exactly when this runs, since it is repairing a broken build.
        """
        try:
            import ast
            tree = ast.parse(content)
            last = 0
            for node in tree.body:
                if (isinstance(node, ast.ImportFrom)
                        and node.module == "__future__"):
                    last = max(last, getattr(node, "end_lineno", node.lineno))
                elif isinstance(node, ast.Expr) and isinstance(
                        getattr(node, "value", None), ast.Constant):
                    continue  # the docstring, already accounted for
                else:
                    break  # `__future__` imports cannot follow real code
            if last:
                return max(insert_at, last)
        except Exception:
            pass

        # Unparseable: scan conservatively. Only advance past lines that are
        # plainly part of a __future__ import, and stop at the first thing that
        # is not, so a broken file never has code inserted into a statement.
        idx, depth = insert_at, 0
        while idx < len(lines):
            stripped = lines[idx].strip()
            if depth == 0:
                if not stripped.startswith("from __future__"):
                    break
            depth += lines[idx].count("(") - lines[idx].count(")")
            idx += 1
            if depth <= 0:
                depth = 0
                insert_at = idx
        return insert_at

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

            # `from __future__ import ...` MUST be the first statement after the
            # docstring — the interpreter refuses the file otherwise. Injecting
            # above one turns a perfectly good module into
            # `SyntaxError: from __future__ imports must occur at the beginning
            # of the file`, and the app never imports.
            #
            # Row 3 (2026-08-31) died exactly here: `backend/models.py` was
            # generated correctly with `from __future__ import annotations` on
            # line 1, this block was prepended above it, and the build shipped
            # `unusable` with the whole API unimportable. The generated code was
            # right and the pipeline broke it.
            insert_at = self._after_future_imports(content, lines, insert_at)

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

    # ── The definition the traceback does not carry ───────────────────────────

    _ATTR_ERROR_RE = re.compile(
        r"""AttributeError:\s*['"]?(\w+)['"]?\s+object\s+has\s+no\s+attribute\s+['"](\w+)['"]""",
        re.IGNORECASE,
    )

    def _definition_context(self, file_path: str, error_text: str) -> str:
        """
        The source of the class an AttributeError names, from wherever it lives.

        `AttributeError: 'SupplierCreate' object has no attribute 'contact'`
        tells the model the class and the missing attribute, and nothing about
        what the class DOES have. The project map lists class names only. So the
        repair cannot tell whether the fix is to rename the read or to add the
        field — and on 2026-08-30 it did neither, rewriting `prod.sku` as
        `data.get("sku")` and binding a silent None into a NOT NULL column.

        §0.2's fourth blame rule already covers this: a bad symbol imported from
        elsewhere is repaired where it is defined. Showing the definition is the
        cheaper half of applying it — the repair stays aimed at the caller, but
        it can now see what it is calling into.

        Base classes are followed because that is where the fields usually are:
        `class SupplierCreate(SupplierBase): pass` carries none of its own.
        """
        matches = self._ATTR_ERROR_RE.findall(error_text or "")
        if not matches:
            return ""

        parts = Path(file_path).parts
        if not parts:
            return ""
        project_dir = Path(config.OUTPUT_DIR) / parts[0]

        wanted = []
        for cls, _attr in matches:
            if cls not in wanted:
                wanted.append(cls)
        wanted = wanted[:3]                      # bounded: this rides every retry

        sources: dict[str, str] = {}
        try:
            for py_file in sorted(project_dir.rglob("*.py")):
                if "__pycache__" in str(py_file):
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8", errors="ignore")
                    tree = ast.parse(text)
                except Exception:
                    continue
                rel = str(py_file.relative_to(Path(config.OUTPUT_DIR))).replace("\\", "/")
                if rel == file_path:
                    continue                     # the model already has this one
                by_name = {
                    n.name: n for n in tree.body if isinstance(n, ast.ClassDef)
                }
                pending, seen = list(wanted), set()
                while pending:
                    name = pending.pop(0)
                    if name in seen or name in sources or name not in by_name:
                        continue
                    seen.add(name)
                    node = by_name[name]
                    try:
                        segment = ast.get_source_segment(text, node)
                    except Exception:
                        segment = None
                    if not segment:
                        continue
                    sources[name] = f"# from {rel}\n{segment}"
                    # follow bases defined in this same file — the fields are
                    # nearly always on the base, not on the named subclass.
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id in by_name:
                            pending.append(base.id)
        except Exception:
            return ""

        if not sources:
            return ""
        body = "\n\n".join(sources[k] for k in sources)
        return (
            "DEFINITIONS THE TRACEBACK REFERS TO (read these before choosing a "
            "fix — the correct field name is here):\n" + body
        )

    def _scan_project_structure(self, file_path: str) -> str:
        parts       = Path(file_path).parts
        if not parts:
            return ""
        project_dir = Path(config.OUTPUT_DIR) / parts[0]
        lines       = ["Actual Python files in this project:"]
        # Bounded: this is resent on every repair attempt, and an unbounded walk
        # grows the prompt with the project. 40 modules is far more than any
        # generated app has needed and keeps the cost flat.
        MAX_ENTRIES = 40
        try:
            for py_file in sorted(project_dir.rglob("*.py")):
                if len(lines) > MAX_ENTRIES:
                    lines.append(f"  …and more (listing capped at {MAX_ENTRIES})")
                    break
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

    def _debug_file(self, file_path: str, runtime_error: str = "") -> FileDebugResult:
        result     = FileDebugResult(file_path=file_path, success=False, attempts=0)
        error_text = ""

        # The request-time repair used to be gated on `attempt == 1`, inside the
        # branch where the import check had just passed. So a file that failed
        # its import check first, was repaired, and passed on attempt 2 never had
        # its 500 looked at — the smoke test found a real request-time failure
        # and the one pass that could act on it was skipped. Gate on "have we
        # tried yet" instead of on which attempt it is.
        def _try_runtime_repair() -> None:
            nonlocal runtime_repair_tried
            if runtime_error and not runtime_repair_tried:
                runtime_repair_tried = True
                self._repair_runtime_error(file_path, runtime_error, result)

        runtime_repair_tried = False

        for attempt in range(1, MAX_ATTEMPTS + 1):
            result.attempts = attempt
            logger.info(f"  🔁 [{file_path}] Attempt {attempt}/{MAX_ATTEMPTS}")

            execution = run_python(file_path)

            if execution.success:
                result.success = True
                logger.info(f"  ✅ [{file_path}] Passed on attempt {attempt}")
                _try_runtime_repair()
                return result

            error_text = execution.stderr

            # Ignorable runtime errors
            if any(p in error_text for p in IGNORE_ERRORS):
                result.success = True
                logger.info(f"  ✅ [{file_path}] Import-check passed (runtime error ignored)")
                _try_runtime_repair()
                return result

            if "sqlalchemy" in error_text.lower() and "OperationalError" in error_text:
                result.success = True
                logger.info(f"  ✅ [{file_path}] Import-check passed (DB connection ignored)")
                _try_runtime_repair()
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

    # The guards below live in tools/repair_guard.py so the two other agents
    # that overwrite a generated file with an LLM reply — BackendDeveloper's
    # self-verification pass and the Tester — use the same ones instead of
    # having none. These remain as the Debugger's entry points.

    @classmethod
    def _top_level_symbols(cls, source: str, defined_only: bool = False) -> set[str]:
        return top_level_symbols(source, defined_only=defined_only)

    @classmethod
    def _top_level_symbols_by_regex(
        cls, source: str, defined_only: bool = False
    ) -> set[str]:
        return _rg_symbols_by_regex(source, defined_only=defined_only)

    def _accept_generated_fix(self, file_path: str, fixed: str) -> bool:
        """
        Reject LLM "fixes" that damage the file instead of repairing it.

        The rules are in tools/repair_guard.accept_generated_fix; this resolves
        the OUTPUT_DIR-relative path the rest of the debugger speaks in and logs
        the refusal.
        """
        try:
            current = read_file(file_path)
        except Exception:
            current = ""

        ok, reason = accept_generated_fix(current, fixed)
        if not ok:
            logger.warning(f"  Rejecting LLM fix for {file_path}: {reason}.")
        return ok

    # A traceback's useful end is its last few frames plus the exception line;
    # the head is mostly interpreter machinery and absolute Windows paths, which
    # are pure prompt cost. Uncapped stderr was being sent verbatim on every one
    # of the Debugger's calls — 44% of a build's total.
    _MAX_ERROR_CHARS = 1200

    @staticmethod
    def _is_import_error(error_text: str) -> bool:
        return any(
            marker in error_text
            for marker in ("ImportError", "ModuleNotFoundError", "No module named",
                           "cannot import name", "attempted relative import")
        )

    @classmethod
    def _trim_error(cls, error_text: str) -> str:
        """Keep the tail — that is where the exception actually is."""
        text = (error_text or "").strip()
        if len(text) <= cls._MAX_ERROR_CHARS:
            return text
        return "…(earlier frames trimmed)…\n" + text[-cls._MAX_ERROR_CHARS:]

    def _repair_runtime_error(
        self, file_path: str, runtime_error: str, result: FileDebugResult
    ) -> bool:
        """
        One repair pass for a file that imports cleanly but fails on a request.

        The file is only replaced if the repair survives the same import check
        the rest of the debugger relies on; otherwise the original is restored.
        A request-time bug is bad, but a module that no longer imports is worse,
        and this pass has no test of its own to catch that — the pipeline
        re-runs the smoke test afterwards to say whether it actually worked.
        """
        try:
            original = read_file(file_path)
        except Exception as e:
            logger.warning(f"  ⚠️  [{file_path}] Cannot read for runtime repair: {e}")
            return False

        logger.info(f"  🔥 [{file_path}] Repairing a request-time failure")
        fixed = self._generate_fix(file_path, runtime_error, runtime=True)
        if not fixed or not self._accept_generated_fix(file_path, fixed):
            logger.warning(f"  ⚠️  [{file_path}] Runtime repair rejected or empty")
            return False

        create_file(file_path, fixed)
        self._preflight_fix(file_path)
        self._inject_syspath(file_path)

        verify = run_python(file_path)
        if not verify.success and not any(p in verify.stderr for p in IGNORE_ERRORS):
            logger.warning(
                f"  ↩️  [{file_path}] Runtime repair broke the import check — "
                f"restoring the original"
            )
            create_file(file_path, original)
            return False

        result.fixes_applied.append(f"Runtime repair on {file_path}")
        logger.info(f"  ✅ [{file_path}] Runtime repair applied")
        return True

    def _generate_fix(
        self, file_path: str, error_text: str, runtime: bool = False
    ) -> str | None:
        try:
            current_code = read_file(file_path)
        except Exception as e:
            logger.error(f"Could not read {file_path}: {e}")
            return None

        # The project map exists to tell the model which modules and symbols are
        # importable. That is only useful for an import error — on a SyntaxError
        # it is several hundred wasted tokens per attempt, and the file itself
        # carries everything needed to fix it.
        #
        # Note what is deliberately NOT trimmed: the file. Every call here is a
        # fresh, stateless request, so sending less of the source on a retry
        # would hand the model less to work with than the attempt that already
        # failed — and Fix 4's guard would then reject the weaker result, costing
        # more calls than it saved.
        import_error = self._is_import_error(error_text)
        # A request-time failure is nearly always about how this module uses
        # another one, so the map earns its tokens here just as it does for an
        # import error — the file alone does not show what it is calling into.
        project_map  = (
            self._scan_project_structure(file_path)
            if (import_error or runtime) else ""
        )
        problem      = "an import error" if import_error else "an error"

        if runtime:
            # An AttributeError names a class but not its fields, and the map
            # lists names only. Without the definition the repair cannot tell a
            # rename from a missing field, and silences the error instead.
            definitions = self._definition_context(file_path, error_text)
            if definitions:
                project_map = (project_map + "\n\n" + definitions).strip()
            targeted = self._generate_targeted_runtime_fix(
                file_path, current_code, error_text, project_map
            )
            if targeted:
                return targeted
            return self._generate_runtime_fix(
                file_path, current_code, error_text, project_map
            )

        prompt      = f"""Fix this Python file. It has {problem}.

FILE: {file_path}
CURRENT CODE:
{current_code}

ERROR:
{self._trim_error(error_text)}

{project_map}

RULES:
- Use ONLY imports matching files in the project map above
- router = APIRouter() in routes.py — NEVER weather_router
- from routes import router in main.py
- NEVER: from backend.x  from ..x  from weather_dashboard.x
- No module-level DB connections

Return ONLY the complete fixed Python code."""
        logger.info(f"  🧠 LLM fixing: {file_path}")
        return self.think(prompt, max_tokens=_rewrite_budget(self, current_code))

    def _generate_targeted_runtime_fix(
        self, file_path: str, current_code: str, error_text: str, project_map: str
    ) -> str | None:
        """
        Repair the one block the traceback points at, instead of the whole file.

        Groq bills prompt and completion against a single 8,000-token minute, so
        a full-file rewrite pays for the file twice and is simply impossible
        above roughly 11KB. Row 3's routes.py was 10,775 characters — right on
        the wall — and its repair was rejected for dropping a top-level name it
        had been forced to re-type. Sending one 408-character handler instead is
        3% of the cost, and code that is never re-emitted cannot be dropped, so
        the shrinkage guard has nothing left to catch.

        Returns None whenever the block cannot be identified, which hands the
        caller back to the full-file path unchanged.
        """
        if len(current_code or "") < _TARGETED_MIN_FILE_CHARS:
            return None

        shared = _shared_cause(error_text)
        if shared:
            # Every endpoint failing the same way means the fault is not in the
            # block any one of them names. Hand this to the full-file prompt,
            # which is the only one that can see the code that never ran.
            logger.info(
                f"  \U0001f9ee [{file_path}] {shared} on several endpoints at once — "
                f"a shared cause, so repairing one block cannot fix it; "
                f"using the whole-file prompt"
            )
            return None

        frames = _parse_frames(error_text)
        if not frames:
            return None

        # The frames name paths relative to the project root ("backend/routes.py")
        # while file_path carries the build folder too. Match on the tail, and
        # take the LAST matching frame: for a chain inside one file that is the
        # innermost, which is where the exception actually came from.
        target = None
        for frame in frames:
            if file_path.replace(chr(92), "/").endswith(frame["file"]):
                target = frame
        if target is None:
            return None

        block = locate_block(
            current_code, line=target.get("line"), function=target.get("function")
        )
        if block is None:
            logger.debug(
                f"  [{file_path}] no block found at line {target.get('line')}; "
                f"falling back to a full-file rewrite"
            )
            return None

        # A block that is most of the file buys nothing, and the full-file prompt
        # gives the model more to work with for the same money.
        if len(block.source) > len(current_code) * 0.6:
            return None

        digest = file_digest(current_code, exclude=block)
        prompt = f"""Fix ONE block of a Python file. The application imports and
starts correctly, but this code fails at REQUEST time with a server error.

FILE: {file_path}
THE FAILING BLOCK (lines {block.start_line}-{block.end_line}):
{block.source}

RUNTIME FAILURE (traceback frames are in call order, caller first):
{self._trim_error(error_text)}

{digest}

{project_map}

RULES:
- Return a replacement for THAT BLOCK ONLY. Do not return the rest of the file.
- Keep the same top-level name and signature: something else imports it.
- Keep every decorator the block already has, unchanged unless the decorator is
  itself the bug (a response_model naming a class that is not a Pydantic model,
  for instance).
- A FastAPI dependency that uses `yield` is a generator function. Never call it
  directly: pass the function itself to Depends(...) and let FastAPI resolve it.
  `db = get_db()` gives you a generator, not a connection or session.
- Never silence the error instead of fixing it. Replacing `obj.field` with
  `obj.dict().get("field")`, wrapping the access in try/except, or defaulting it
  to None makes the exception disappear and writes a wrong value — a None bound
  into a NOT NULL column is worse than the 500 you started with. If an attribute
  does not exist, the definitions above have the name that does: use it.
- Use only the imports listed above; do not add new dependencies or new files.
- Start at column zero, exactly as the block does.

Return ONLY the replacement code for that block."""

        logger.info(
            f"  \U0001f3af [{file_path}] Targeted repair of {block.name!r} "
            f"(lines {block.start_line}-{block.end_line}, "
            f"{len(block.source)} of {len(current_code)} chars)"
        )
        reply = self.think(prompt, max_tokens=_rewrite_budget(self, block.source))
        if not reply or not reply.strip():
            return None

        patched = splice(current_code, block, reply)
        if patched is None:
            logger.warning(
                f"  [{file_path}] Targeted repair did not splice cleanly; "
                f"falling back to a full-file rewrite"
            )
            return None
        return patched


    def _generate_runtime_fix(
        self, file_path: str, current_code: str, error_text: str, project_map: str
    ) -> str | None:
        """
        The prompt for a failure that only happens once a request arrives.

        It differs from the import-error prompt in what it must not do. The
        traceback names where the exception surfaced, which is often a helper
        that was handed the wrong thing; "fix" there means teaching the helper
        to tolerate bad input, and the endpoint stays broken. The file being
        repaired is the caller, and the rule says so.

        The FastAPI dependency rule is spelled out because it is the failure
        that was actually observed: a router defined its own `get_db()` that
        called a generator dependency as though it returned a value, then
        yielded the generator, so every database route raised
        `'generator' object has no attribute 'execute'` on every request.
        """
        prompt = f"""Fix this Python file. The application imports and starts
correctly, but this endpoint fails at REQUEST time with a server error.

FILE: {file_path}
CURRENT CODE:
{current_code}

RUNTIME FAILURE (traceback frames are in call order, caller first):
{self._trim_error(error_text)}

{project_map}

RULES:
- The bug is in THIS file. The traceback may end in another module because this
  file passed it the wrong value — fix the call here, do not make the other
  module tolerate it.
- A FastAPI dependency that uses `yield` is a generator function. Never call it
  directly: pass the function itself to Depends(...) and let FastAPI resolve it.
  `db = get_db()` gives you a generator, not a connection or session.
- Do not wrap an existing generator dependency in a second one that yields the
  result of calling it.
- Never silence the error instead of fixing it. Replacing `obj.field` with
  `obj.dict().get("field")`, wrapping the access in try/except, or defaulting it
  to None makes the exception disappear and writes a wrong value — a None bound
  into a NOT NULL column is worse than the 500 you started with. If an attribute
  does not exist, the definition above has the name that does: use it.
- Keep every route, every top-level name and every signature this file already
  has. Something else imports them.
- Do not add new dependencies or new files.

Return ONLY the complete fixed Python code."""
        logger.info(f"  🧠 LLM repairing runtime failure: {file_path}")
        return self.think(prompt, max_tokens=_rewrite_budget(self, current_code))

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
