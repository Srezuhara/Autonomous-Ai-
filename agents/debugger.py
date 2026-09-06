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

def _statement_lines(source: str, start_pattern: str) -> set:
    """1-based line numbers of the statement `start_pattern` opens.

    A binding does not "use" itself, so its own lines must be excluded before
    asking whether anything else reads it. Spans the whole statement, because
    `create_engine(` is routinely multi-line — the very shape Phase 22 had to
    fix in `_comment_out_statement`.
    """
    lines = source.splitlines()
    out: set = set()
    for i, line in enumerate(lines):
        if not re.match(start_pattern, line):
            continue
        depth = line.count("(") - line.count(")")
        out.add(i + 1)
        j = i
        while depth > 0 and j + 1 < len(lines):
            j += 1
            depth += lines[j].count("(") - lines[j].count(")")
            out.add(j + 1)
    return out


def _name_is_used(source: str, name: str, ignore_lines: set = frozenset()) -> bool:
    """Does `name` still appear as a load anywhere outside the given lines?

    Two repair rules delete or comment out a binding: the `services.py`
    sibling-import stripper, and the `engine = create_engine(...)` disabler.
    Neither asked whether anything still referenced the name, and both were
    measured breaking working builds on 2026-09-01 by `tools/verify_repairs.py`:

      * `llm_api_key_dashboard` (9 files) and `bookmark_manager_a3ca5c18` (3) —
        `from auth import Token` removed while `Token` was still used.
      * `ai_pdf_reader` (2) — `engine = create_engine(...)` commented out with
        `SessionLocal = sessionmaker(bind=engine)` on the very next line.

    Removing a binding that is still read cannot help any build: it converts a
    possible problem into a certain `NameError`. AST where the file parses, a
    word-boundary regex where it does not — this runs on files mid-repair, which
    is exactly when they may not parse.
    """
    import ast as _ast

    try:
        tree = _ast.parse(source)
    except SyntaxError:
        for i, line in enumerate(source.splitlines(), 1):
            if i in ignore_lines:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(rf"\b{re.escape(name)}\b", line):
                return True
        return False

    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name) and node.id == name:
            if isinstance(node.ctx, _ast.Load) and node.lineno not in ignore_lines:
                return True
        elif isinstance(node, _ast.Attribute):
            base = node.value
            if (isinstance(base, _ast.Name) and base.id == name
                    and node.lineno not in ignore_lines):
                return True
    return False


def _syspath_block(rel_path: str) -> str:
    """The sys.path shim, with its walk-up clamped to the project's own root.

    `SYSPATH_BLOCK` above is fixed at three levels — `_here`, `_parent`,
    `_grandparent` — which is right for `<project>/backend/x.py` and wrong for a
    file at the project root. There, `_grandparent` is **the AI builder's own
    repo root**, and the shim inserts it at `sys.path[0]`.

    That is not a theoretical contamination. Measured 2026-09-01 by
    `tools/verify_repairs.py`: `inventory_system_f3dbcc61` has a root
    `__init__.py`, so importing `tests.test_main` executed it first, put
    `C:\...\Aiautonomous` at the front of the path, and
    `from main import app` resolved to **the builder's own `main.py`** instead of
    the project's `backend/main.py`. Seven files, every one of them correct.
    Any generated module whose name collides with one of ours — `main`,
    `config`, `tools`, `agents` — was resolvable to our copy.

    `run_python` appends the project's sibling source dirs at LOW priority
    precisely so the file's own directory wins; a shim that inserts an outside
    directory at position 0 defeats that.

    So: emit only as many levels as stay inside the project. Depth 0 (a file at
    the root) gets `_here` alone; the three-level form is unchanged for anything
    nested two deep or more, which is where it was doing its job.
    """
    parts = Path(str(rel_path).replace("\\", "/")).parts
    # parts[0] is the project folder and parts[-1] the filename, so what is left
    # is how far the file's own directory sits below the project root.
    depth = max(0, len(parts) - 2)
    levels = min(3, depth + 1)

    lines = [
        "import sys as _sys, os as _os",
        "_here = _os.path.dirname(_os.path.abspath(__file__))",
    ]
    if levels > 1:
        lines.append("_parent = _os.path.dirname(_here)")
    if levels > 2:
        lines.append("_grandparent = _os.path.dirname(_parent)")
    names = ["_here", "_parent", "_grandparent"][:levels]
    # NOT reversed. The loop inserts at position 0, so the project root does end
    # up ahead of the file's own directory — which looks backwards, and reversing
    # it was tried on 2026-09-01 and dropped: it fixed nothing (the one file it
    # was aimed at still resolved the same way, because `run_python` inserts the
    # project root ahead of `backend/` before this ever runs) and it made 34
    # files non-idempotent. A change that moves no verdict in the right
    # direction and regresses another measure is not an improvement.
    lines += [
        f"for _p in [{', '.join(names)}]:",
        "    if _p not in _sys.path:",
        "        _sys.path.insert(0, _p)",
    ]
    return "\n".join(lines) + "\n"


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
# A file being COMPLETED has to come back longer than it went in, by roughly one
# small function per missing name. 120 tokens is a generous CRUD helper.
_DEFINITION_TOKENS_EACH  = 120
# How many missing names to ask for in one call. Groq bills prompt and completion
# against a single 8,000-token minute, so the reply for a whole file's worth of
# missing functions cannot fit: on 2026-09-02 a 23-name repair was clamped to
# 2,626 output tokens, truncated three times and wrote nothing, for 19,749
# tokens. Five names is ~600 output tokens beside a ~1,200-token prompt.
_DEFINITIONS_PER_CALL    = 5

#: The two shapes `module_ref_check.RefIssue.__str__` produces, which is where
#: these findings come from. Parsed rather than passed as data because the
#: findings are also what the user reads, and one wording is easier to keep
#: honest than two representations of it. `test_phase23.py` pins this against the
#: real `RefIssue`, so a change to that wording fails there rather than here.
_MISSING_ATTR_RE   = re.compile(r"^`(?P<mod>[\w.]+)\.(?P<name>\w+)` is read at line")
_MISSING_IMPORT_RE = re.compile(r"^`from (?P<mod>[\w.]+) import (?P<name>\w+)` at line")


def _missing_names(findings) -> list:
    """The names a batch of `module_ref` findings says are missing, in order."""
    names: list = []
    for finding in findings or ():
        text = str(finding).strip()
        m = _MISSING_ATTR_RE.match(text) or _MISSING_IMPORT_RE.match(text)
        if m and m.group("name") not in names:
            names.append(m.group("name"))
    return names


#: `AttrIssue.__str__` from `tools/schema_attr_check.py`. Pinned by
#: `test_phase23.py` against the real dataclass, so a reworded finding fails
#: there rather than silently parsing to nothing during a live build.
_MISSING_FIELD_RE = re.compile(
    r"^`(?P<param>\w+)\.(?P<attr>\w+)` is read at line \d+, "
    r"but `(?P=param)` is a `(?P<model>\w+)`")


def _missing_fields(findings) -> list:
    """`[(model, attr), ...]` a batch of `schema_attr` findings says are missing."""
    out: list = []
    for finding in findings or ():
        m = _MISSING_FIELD_RE.match(str(finding).strip())
        if m:
            pair = (m.group("model"), m.group("attr"))
            if pair not in out:
                out.append(pair)
    return out


#: `MissingTable.__str__` from `tools/sql_schema_check.py`, pinned by
#: `test_phase23.py` against the real dataclass.
_MISSING_TABLE_RE = re.compile(
    r"^SQL in .* queries table `(?P<table>\w+)`, which this project never creates")


def _missing_tables(findings) -> list:
    """The table names a batch of `sql_schema` findings says are never created."""
    out: list = []
    for finding in findings or ():
        m = _MISSING_TABLE_RE.match(str(finding).strip())
        if m and m.group("table") not in out:
            out.append(m.group("table"))
    return out


#: `DeadEvent.__str__` from `tools/dead_event_check.py`, pinned by
#: `test_phase23.py` against the real dataclass.
_DEAD_EVENT_RE = re.compile(
    r"^`(?P<app>\w+)\.on_event\(\"(?P<event>\w+)\"\)` at line \d+ is dead "
    r"code:.*?— `(?P<handler>\w+)` never runs")


def _dead_event_handlers(findings) -> list:
    """`[(app, event, handler), ...]` a batch of `dead_events` findings names."""
    out: list = []
    for finding in findings or ():
        m = _DEAD_EVENT_RE.match(str(finding).strip())
        if m:
            triple = (m.group("app"), m.group("event"), m.group("handler"))
            if triple not in out:
                out.append(triple)
    return out


#: The calls that put routes on an app. Counted before and after an event repair
#: so a rewrite cannot make the finding go away by deleting the wiring it was
#: complaining about — see `_repair_dead_events`.
_WIRING_CALLS = ("include_router", "add_api_route", "mount")


def _wiring_calls(source: str) -> int:
    """How many route-wiring calls this source makes. -1 when it will not parse."""
    try:
        tree = ast.parse(source)
    except Exception:
        return -1
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _WIRING_CALLS
    )


def _declares_field(source: str, model: str, attr: str) -> bool:
    """Does `model` declare `attr` as a class-level name in this source?"""
    try:
        tree = ast.parse(source)
    except Exception:
        return False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == model):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if stmt.target.id == attr:
                    return True
            elif isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name) and t.id == attr:
                        return True
    return False


def _defines(source: str, name: str) -> bool:
    """Does this source bind `name` at the top level?"""
    try:
        tree = ast.parse(source)
    except Exception:
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return True
    return False


def _call_sites(file_path: str, names: list, per_name: int = 3) -> dict:
    """
    `{name: ["rel.py:12: services.create_supplier(supplier)", ...]}`.

    A definition written without seeing the call is a definition with a guessed
    signature. Measured on 2026-09-02: the repair added `create_supplier(name,
    contact_email)` while the route calls `services.create_supplier(supplier)`
    with a Pydantic model, so the endpoint traded `AttributeError` for
    `TypeError: missing 1 required positional argument`. The name existed and
    the call still failed.

    Text search rather than AST: the caller may be any of `services.create_x(`,
    `create_x(` after a from-import, or an aliased module, and all three read
    the same here.
    """
    found: dict = {}
    if not names:
        return found
    try:
        rel = Path(file_path)
        root = Path(config.OUTPUT_DIR) / rel.parts[0]
        if not root.is_dir():
            return found
        me = (Path(config.OUTPUT_DIR) / rel).resolve()
    except Exception:
        return found

    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            if path.resolve() == me:
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        shown = path.relative_to(root.parent).as_posix()
        for i, line in enumerate(lines, 1):
            for name in names:
                if f"{name}(" not in line:
                    continue
                hits = found.setdefault(name, [])
                if len(hits) < per_name:
                    hits.append(f"{shown}:{i}: {line.strip()[:160]}")
    return found


def _accept_definitions(current: str, fragment: str, wanted: list) -> tuple:
    """
    Should this fragment be appended? `(accept, reason_if_not, cleaned_text)`.

    The third element is what the caller must append — the fragment with any
    markdown fence removed. Returning it is not tidiness: validating the cleaned
    text and appending the raw one would write a fence into a .py file that had
    just been import-checked without it.

    `repair_guard.accept_generated_fix` cannot answer this: its `too_large` rule
    exists to stop a REWRITE ballooning, and a file being completed is supposed
    to grow. What has to be checked instead is that the fragment is only new
    definitions — the property that makes appending safe, since a name that is
    never re-typed cannot be dropped.
    """
    if not fragment or not fragment.strip():
        return False, "empty reply", ""
    text = fragment.strip()
    if text.startswith("```") or "```" in text:
        text = re.sub(r"^```[a-zA-Z]*\n?|```", "", text).strip()
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return False, f"does not parse ({e.msg})", ""

    defined = [
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not defined:
        return False, "no definition in the reply", ""
    landed = [n for n in defined if n in wanted]
    if not landed:
        return False, f"defines {defined[:3]}, none of which were asked for", ""
    # A name the file already has would shadow the working one further down.
    clashes = [n for n in defined if _defines(current, n)]
    if clashes:
        return False, f"redefines {clashes[:3]}, which the file already has", ""
    # There is deliberately no size rule here. One was tried — reject a fragment
    # longer than 90% of the file — and it was measured wrong on the first real
    # input: five supplier CRUD functions are legitimately about as long as the
    # 3,630-character file they belong to, so batch 1 of 5 was refused and those
    # five names stayed missing. Size does not distinguish "the whole file came
    # back" from "this file is small". The clash rule above does, exactly: a
    # reply containing the file re-defines what the file already defines.
    return True, "", text

def _accept_routes(current: str, fragment: str) -> tuple:
    """
    Should this fragment of route handlers be appended? `(accept, why_not, text)`.

    `_accept_definitions` cannot answer it: that one requires the reply to define
    names from a `wanted` list, and a route repair has no such list — the finding
    says "this application declares no routes", not which handlers are missing.
    Passing an empty `wanted` made it reject every reply with "none of which were
    asked for", which is how this channel was inert when first driven at a clone
    on 2026-09-05, before it had ever run live.

    What replaces the name check is the property that actually matters here: the
    fragment must **declare at least one route**. A reply full of helper
    functions is not a fix for "there are no routes".

    The clash rule is kept exactly as it is, and it is doing the same job: a
    reply that re-emits the whole file re-defines what the file already defines,
    which is how a "rewrite" is told apart from an append without a size rule.
    """
    if not fragment or not fragment.strip():
        return False, "empty reply", ""
    text = fragment.strip()
    if text.startswith("```") or "```" in text:
        text = re.sub(r"^```[a-zA-Z]*\n?|```", "", text).strip()
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return False, f"does not parse ({e.msg})", ""

    defined = [
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not defined:
        return False, "no definition in the reply", ""

    try:
        from tools.route_presence_check import count_routes
        routes = count_routes(text)
    except Exception:
        routes = 0
    if routes <= 0:
        return False, f"defines {defined[:3]} but declares no route", ""

    # The clash rule has to cover ASSIGNMENTS here, not just def/class, and that
    # is not a refinement — it is the difference between a fix and a fake one.
    # Driven at a clone on 2026-09-05, a reply that re-emitted the whole file
    # plus one handler was ACCEPTED, because row 4's `routes.py` defines no
    # functions at all: it is nothing but `x = APIRouter()` assignments, so
    # there was no def to clash on. Appending it rebinds every router name, the
    # `include_router` calls above have already run against the OLD objects, and
    # the new handlers hang off routers nothing includes. `count_routes` then
    # reads 1 and the check goes green over an app that still serves nothing.
    frag_syms = top_level_symbols(text, defined_only=True)
    cur_syms = top_level_symbols(current, defined_only=True)
    clashes = sorted(frag_syms & cur_syms)
    if clashes:
        return False, f"redefines {clashes[:3]}, which the file already has", ""
    return True, "", text


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
        missing_definitions: dict | None = None,
        missing_fields: dict | None = None,
        missing_tables: dict | None = None,
        dead_events: dict | None = None,
        missing_routes: dict | None = None,
    ) -> list[FileDebugResult]:
        """
        `runtime_errors` maps a file to a failure the *running* app produced —
        a 5xx from the smoke test, with its traceback. The import check cannot
        see those: the module imports fine, and the handler only breaks once a
        request arrives. Without them a file like this is "passing" and the
        repair passes skip it, which is exactly what happened to a build whose
        three DB routes returned 500 on every call.

        `missing_fields` is the same idea one level in: a file to the fields
        other modules read from the models it defines and the models do not
        declare (`schema_attr`'s findings). Same reason for its own channel, and
        the same rule about which file is repaired — the model's, never the
        reader's.

        `missing_definitions` maps a file to the names OTHER modules read from it
        and it does not define (`module_ref`'s findings, one line each). It needs
        its own channel for the same reason `runtime_errors` did — such a file
        imports perfectly, so every gate here passes it — but it is the opposite
        defect: nothing is wrong *in* this file, it is incomplete. Row 3 on
        2026-09-02 shipped `services.py` defining 3 of the 23 functions its
        routes call, and both repair passes rewrote the routes.

        `dead_events` maps a file to `@app.on_event(...)` handlers the app's own
        `lifespan=` argument makes unreachable (`dead_events`' findings). It is
        the same shape of gap once more, and the most invisible of the four: such
        a file imports cleanly, runs cleanly, passes every static check, and the
        application it builds still serves nothing. Row 3's third run on
        2026-09-03 shipped `unusable` with four checks verified and
        `feature_coverage` reporting 6/6 against zero live routes.

        `missing_routes` maps a file holding bare `APIRouter()` objects to the
        fact that the application declares no route at all (`route_presence`'s
        finding). It is the symptom `dead_events` catches one cause of, and it
        needs the same kind of channel for the same reason — such a file imports
        perfectly, so nothing else here looks at it.
        """
        runtime_errors = runtime_errors or {}
        missing_definitions = missing_definitions or {}
        missing_fields = missing_fields or {}
        missing_tables = missing_tables or {}
        dead_events = dead_events or {}
        missing_routes = missing_routes or {}
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
            r = self._debug_file(
                fp,
                runtime_error=runtime_errors.get(fp, ""),
                missing_defs=missing_definitions.get(fp, ()),
                missing_flds=missing_fields.get(fp, ()),
                missing_tbls=missing_tables.get(fp, ()),
                dead_evts=dead_events.get(fp, ()),
                no_routes=bool(missing_routes.get(fp)),
            )
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

            # The directory listing, read once, because the check below must be
            # CASE-SENSITIVE and `Path.is_file()` is not: Windows and macOS both
            # answer True for `Supplier.py` when only `supplier.py` exists.
            #
            # That is not a corner case, it is the dominant Python convention —
            # `class Supplier` living in `supplier.py`. With `is_file()`, the
            # imported NAME `Supplier` resolved to the module `supplier`, and
            # `from supplier import Supplier` was rewritten to `import Supplier`:
            # a class imported as though it were a module, so the package stopped
            # importing. Found 2026-09-01 by `tools/verify_repairs.py` against
            # `repair_fixtures/multi_model_pkg`, which is a shape no build in the
            # corpus has.
            try:
                _entries = {e.name for e in directory.iterdir()}
            except OSError:
                _entries = set()

            def _is_sibling(name: str) -> bool:
                if not name or not name.isidentifier():
                    return False
                if f"{name}.py" in _entries:
                    return True
                return (name in _entries
                        and (directory / name / "__init__.py").is_file())

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
                    # Only if nothing still reads what the import binds.
                    # Deleting a used name turns a possible circular import into
                    # a certain NameError — 12 of the 21 files this rule was
                    # measured breaking on 2026-09-01.
                    bound = []
                    if from_match:
                        bound = [
                            a.split(" as ")[-1].strip()
                            for a in from_match.group(2).split(",")
                        ]
                    elif import_match:
                        bound = [import_match.group(1)]
                    bound = [b for b in bound if b.isidentifier()]
                    line_no = content.splitlines(keepends=True).index(line) + 1 \
                        if line in content.splitlines(keepends=True) else 0
                    still_used = any(
                        _name_is_used(content, b, ignore_lines={line_no})
                        for b in bound
                    )
                    if still_used:
                        new_lines.append(line)
                        continue
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

        if (
            filename == "routes.py"
            and re.search(r'\bweather_router\s*=\s*APIRouter', content)
            # Only when the name is free. If `routes.py` already defines its
            # own `router`, this rename puts two routers on one name and the
            # later binding silently wins — the same single-router assumption
            # that broke main.py below.
            and not re.search(r'^router\s*=\s*APIRouter', content, re.MULTILINE)
        ):
            content = re.sub(r'\bweather_router\b', 'router', content)
            fixes.append("renamed weather_router → router")

        if filename == "main.py":
            new = re.sub(r'from routes import \w*router\w*', 'from routes import router', content)
            # Collapsing every `include_router(X)` to `include_router(router)`
            # is only correct in the single-router layout this rule was written
            # for: `routes.py` exports one `router`, and the rename above has
            # just made that its name. A multi-entity build does the opposite —
            # `from routers.suppliers import router as suppliers_router`, once
            # per entity — and rewriting those aliases to a bare `router`
            # discards four of five distinct names and leaves one bound nowhere.
            #
            # That is not hypothetical: it is how row 3 died on 2026-09-01. This
            # rule turned correct generated code into `app.include_router(router)`
            # five times over, reported it as "fixed router import name", and then
            # re-applied itself after every LLM repair the guard had accepted — so
            # the debugger spent three attempts, two passes and two remediation
            # passes re-fixing a file this function re-broke each time.
            # 222,068 tokens, no progress, and the build shipped unusable.
            #
            # So rewrite a name only when it cannot already resolve: this file
            # does not bind it, and it does bind `router`.
            bound = top_level_symbols(new)
            if "router" in bound:
                def _collapse(m: 're.Match') -> str:
                    return (
                        m.group(0) if m.group(1) in bound
                        else 'app.include_router(router)'
                    )
                new = re.sub(
                    r'app\.include_router\((\w*router\w*)\)', _collapse, new
                )
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
            # Commenting out `engine = create_engine(...)` while
            # `SessionLocal = sessionmaker(bind=engine)` sits on the next line
            # guarantees a NameError. `ai_pdf_reader` shipped exactly that, and
            # the import check has an OperationalError bypass anyway, so leaving
            # a live connection alone costs nothing here.
            for name, pattern in (
                ("engine",  r'^engine\s*=\s*create_engine'),
                ("Session", r'^Session\s*=\s*sessionmaker'),
                (None,      r'^Base\.metadata\.create_all'),
            ):
                if name and _name_is_used(
                    content, name,
                    ignore_lines=_statement_lines(content, pattern),
                ):
                    continue
                content = self._comment_out_statement(content, pattern)
            if content != original:
                fixes.append("disabled module-level DB connection")

        project_dir = self._get_project_dir(file_path)
        if project_dir:
            models_file = project_dir / "models.py"
            models_dir  = project_dir / "models"
            if not models_file.exists() and models_dir.exists():
                new, note = self._retarget_models_package(content, models_dir)
                if new != content:
                    content = new
                    fixes.append(note)

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

    def _retarget_models_package(self, content: str, models_dir: Path):
        """`from models import X` where `models` is a package, not a module.

        The rule this replaces rewrote every such line to name `glob("*.py")[0]`
        — whichever file the filesystem happened to return first — regardless of
        which module actually defined X. On a four-entity project that is wrong
        for three of the four, and `glob` is not sorted, so it was not even
        stable across machines.

        Measured 2026-09-01 by `tools/verify_repairs.py` against
        `repair_fixtures/multi_model_pkg`: `from models import Product, Supplier`
        became `from models.product import Product, Supplier` and the package
        stopped importing. The same shape as the router defect found the same
        session — a single-entity assumption applied to a name it never checked.

        A package whose `__init__.py` re-exports the names needs no repair, and
        that is the ordinary idiom. Otherwise a line is retargeted only when
        exactly ONE module supplies every name it asks for: two sources cannot be
        written as one import, and guessing between them is the bug itself.
        """
        init = models_dir / "__init__.py"
        exported: set = set()
        if init.exists():
            try:
                exported = top_level_symbols(init.read_text(encoding="utf-8"))
            except Exception:
                exported = set()

        provides: dict = {}
        for f in sorted(models_dir.glob("*.py")):
            if f.name == "__init__.py":
                continue
            try:
                provides[f.stem] = top_level_symbols(f.read_text(encoding="utf-8"))
            except Exception:
                provides[f.stem] = set()

        note = ""

        def repl(m):
            nonlocal note
            asked = {n.split(" as ")[0].strip() for n in m.group(1).split(",")}
            asked = {n for n in asked if n and n.isidentifier()}
            if not asked or asked <= exported:
                return m.group(0)      # the package already answers this
            owners = [stem for stem, syms in provides.items() if asked <= syms]
            if len(owners) != 1:
                return m.group(0)      # ambiguous, or nothing supplies it
            note = ("fixed 'from models import X' -> "
                    f"'from models.{owners[0]} import X'")
            return f"from models.{owners[0]} import {m.group(1)}"

        return re.sub(r'from models import ([^\n]+)', repl, content), note

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

    # The markers that identify a shim this method injected earlier. Kept as a
    # constant because the strip below and the re-insert above it must agree:
    # anything the block writes and the strip does not remove accumulates.
    _SHIM_MARKERS = (
        "_here =", "_parent =", "_grandparent =",
        "sys.path.insert", "import sys as _sys", "import os as _os",
        "if _p not in _sys.path", "for _p in [_here",
    )

    def _inject_syspath(self, file_path: str) -> bool:
        try:
            content = read_file(file_path)
            on_disk = content
            if "_here = " in content or "sys.path.insert" in content:
                lines    = content.splitlines(keepends=True)
                # The strip used to remove the block's code lines but not the
                # blank line it is re-inserted with (`SYSPATH_BLOCK + "\n"`),
                # so every pass over a file added one blank line and rewrote
                # it. Measured 2026-09-01 by `tools/verify_repairs.py`: **531
                # of 531 corpus files were modified by this method and 535
                # were non-idempotent** — it was the entire non-idempotence
                # signal, which is to say it hid any other.
                filtered = []
                dropped  = False
                for l in lines:
                    if any(x in l for x in self._SHIM_MARKERS):
                        dropped = True
                        continue
                    if dropped and not l.strip():
                        dropped = False      # exactly the one blank we re-add
                        continue
                    dropped = False
                    filtered.append(l)
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
                + _syspath_block(file_path) + "\n"
                + "".join(lines[insert_at:])
            )
            # Nothing to do is not the same as work done. Rewriting a file whose
            # shim is already correct churns its mtime and its digest on every
            # pass, and made this method look like it had touched every file in
            # the project when it had changed nothing.
            if new_content == on_disk:
                return False
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

    def _debug_file(self, file_path: str, runtime_error: str = "",
                    missing_defs: tuple = (),
                    missing_flds: tuple = (),
                    missing_tbls: tuple = (),
                    dead_evts: tuple = (),
                    no_routes: bool = False) -> FileDebugResult:
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
            # A file can be both wrong and incomplete, and these are different
            # repairs: one rewrites what is there, the other adds what is not.
            # Run this second so the definitions are added to whatever the
            # runtime repair left behind, rather than being overwritten by it.
            _try_definition_repair()
            _try_field_repair()
            _try_table_repair()
            # Last, and deliberately so: this one rewrites the file that BUILDS
            # the app, and it must act on whatever the earlier repairs left
            # behind rather than being overwritten by them.
            _try_dead_event_repair()
            # Last of all: this one APPENDS handlers, so it must run after every
            # repair that rewrites the file, or its work is overwritten.
            _try_route_repair()

        def _try_definition_repair() -> None:
            nonlocal definition_repair_tried
            if missing_defs and not definition_repair_tried:
                definition_repair_tried = True
                self._repair_missing_definitions(
                    file_path, list(missing_defs), result)

        def _try_field_repair() -> None:
            nonlocal field_repair_tried
            if missing_flds and not field_repair_tried:
                field_repair_tried = True
                self._repair_missing_fields(
                    file_path, list(missing_flds), result)

        def _try_table_repair() -> None:
            nonlocal table_repair_tried
            if missing_tbls and not table_repair_tried:
                table_repair_tried = True
                self._repair_missing_tables(
                    file_path, list(missing_tbls), result)

        def _try_route_repair() -> None:
            nonlocal route_repair_tried
            if no_routes and not route_repair_tried:
                route_repair_tried = True
                self._repair_missing_routes(file_path, result)

        def _try_dead_event_repair() -> None:
            nonlocal dead_event_repair_tried
            if dead_evts and not dead_event_repair_tried:
                dead_event_repair_tried = True
                self._repair_dead_events(
                    file_path, list(dead_evts), result)

        runtime_repair_tried = False
        definition_repair_tried = False
        field_repair_tried = False
        table_repair_tried = False
        dead_event_repair_tried = False
        route_repair_tried = False

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

    def _accept_generated_fix(self, file_path: str, fixed: str,
                              allow_removed: set | None = None) -> bool:
        """
        Reject LLM "fixes" that damage the file instead of repairing it.

        The rules are in tools/repair_guard.accept_generated_fix; this resolves
        the OUTPUT_DIR-relative path the rest of the debugger speaks in and logs
        the refusal.

        `allow_removed` is passed through for the one repair whose job is to
        delete a top-level name — see `_repair_dead_events`. Every caller that
        omits it keeps the unconditional rule.
        """
        try:
            current = read_file(file_path)
        except Exception:
            current = ""

        ok, reason = accept_generated_fix(current, fixed,
                                          allow_removed=allow_removed)
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

    def _repair_missing_definitions(
        self, file_path: str, findings: list, result: FileDebugResult
    ) -> bool:
        """
        Complete a file that imports cleanly and is missing definitions.

        This APPENDS, in batches, and does not rewrite. Three measurements from
        the 2026-09-02 probe forced that shape, and each one kills the
        whole-file version outright:

        * **Groq bills prompt and completion against one 8,000-token minute.**
          `services.py` needed 23 functions; the output budget was clamped to
          2,626 tokens, every attempt came back truncated at `finish_reason=
          length`, and each retry doubled an ask that was clamped straight back.
          Three attempts, 19,749 tokens, nothing written.
        * **`accept_generated_fix` rejects growth by design** — `too_large` is
          `len(fixed) > max(len(current) * 1.6, len(current) + 1800)`. A file
          that must gain 23 functions is an "oversized rewrite" under a rule
          written to stop a rewrite ballooning. Correct rule, wrong repair.
        * A rewrite has to re-emit every existing name to keep it, which is the
          one way this repair could make things worse.

        Appending removes all three: cost is proportional to what is missing,
        the reply is small enough to fit a minute, and a name that is never
        re-typed cannot be dropped. The file is still import-checked after each
        batch and restored if the batch broke it.
        """
        if not findings:
            return False
        try:
            original = read_file(file_path)
        except Exception as e:
            logger.warning(f"  ⚠️  [{file_path}] Cannot read for definition repair: {e}")
            return False

        wanted = _missing_names(findings)
        if not wanted:
            logger.warning(
                f"  ⚠️  [{file_path}] No name could be read out of "
                f"{len(findings)} finding(s) — not guessing")
            return False

        logger.info(
            f"  🧩 [{file_path}] Completing: {len(wanted)} name(s) other modules "
            f"read and this file does not define"
        )

        batches = [
            findings[i:i + _DEFINITIONS_PER_CALL]
            for i in range(0, len(findings), _DEFINITIONS_PER_CALL)
        ]
        current = original
        added_total: list[str] = []

        for n, batch in enumerate(batches, 1):
            names = _missing_names(batch)
            if not names:
                continue
            fragment = self._generate_missing_definitions_fix(
                file_path, current, batch)
            ok, why, cleaned = _accept_definitions(current, fragment, names)
            if not ok:
                logger.warning(
                    f"  ⚠️  [{file_path}] Batch {n}/{len(batches)} rejected: {why}")
                continue

            candidate = current.rstrip() + "\n\n\n" + cleaned + "\n"
            create_file(file_path, candidate)
            self._preflight_fix(file_path)
            self._inject_syspath(file_path)

            verify = run_python(file_path)
            if not verify.success and not any(p in verify.stderr for p in IGNORE_ERRORS):
                logger.warning(
                    f"  ↩️  [{file_path}] Batch {n}/{len(batches)} broke the import "
                    f"check — restoring what worked")
                create_file(file_path, current)
                continue

            current = read_file(file_path)
            landed = [n_ for n_ in names if _defines(current, n_)]
            added_total.extend(landed)
            logger.info(
                f"  ✅ [{file_path}] Batch {n}/{len(batches)}: added "
                f"{len(landed)}/{len(names)} name(s)")

        if not added_total:
            logger.warning(f"  ⚠️  [{file_path}] Definition repair added nothing")
            return False

        result.fixes_applied.append(
            f"Added {len(added_total)} missing definition(s) to {file_path}")
        logger.info(
            f"  ✅ [{file_path}] Definition repair applied: "
            f"{len(added_total)}/{len(wanted)} name(s)")
        return True

    def _repair_missing_routes(
        self, file_path: str, result: FileDebugResult
    ) -> bool:
        """
        Give an application that declares no routes some routes.

        APPENDS, one router at a time, for exactly the reasons
        `_repair_missing_definitions` does — and this is the repair that proved
        those reasons on a live row. On `9733027d` the BackendDeveloper
        diagnosed this defect itself ("this file creates an APIRouter but
        defines no route handlers") and its whole-file repair was thrown away by
        `accept_generated_fix` as *"an oversized rewrite"*. An empty router
        gaining a full CRUD set can only grow, and the guard forbids growth.

        So: one call per router, appending, each batch import-checked, and the
        landing check is a **re-count of the declared routes** — not "the file
        changed", which a reply full of comments would satisfy.
        """
        try:
            original = read_file(file_path)
        except Exception as e:
            logger.warning(f"  ⚠️  [{file_path}] Cannot read for route repair: {e}")
            return False

        try:
            from tools.route_presence_check import router_names, count_routes
        except Exception as e:
            logger.warning(f"  ⚠️  [{file_path}] route_presence unavailable: {e}")
            return False

        routers = router_names(original)
        if not routers:
            logger.warning(
                f"  ⚠️  [{file_path}] No APIRouter to hang handlers on — "
                f"not guessing")
            return False

        # A parent router that only aggregates others gets no handlers of its
        # own. Row 4's `router` existed solely to `include_router` the other
        # five, and writing CRUD onto it would have produced a second, duplicate
        # set of paths.
        aggregators = {
            m.group(1) for m in re.finditer(
                r"(\w+)\.include_router\s*\(", original)
        }
        targets = [r for r in routers if r not in aggregators] or routers

        logger.info(
            f"  🛣️  [{file_path}] Declaring routes on {len(targets)} router(s): "
            f"{', '.join(targets)}"
        )

        current = original
        before_total = count_routes(current)

        for n, router in enumerate(targets, 1):
            fragment = self._generate_missing_routes_fix(
                file_path, current, router)
            ok, why, cleaned = _accept_routes(current, fragment)
            if not ok:
                logger.warning(
                    f"  ⚠️  [{file_path}] Router {n}/{len(targets)} "
                    f"({router}) rejected: {why}")
                continue

            candidate = current.rstrip() + "\n\n\n" + cleaned + "\n"
            # The reply is only worth writing if it actually declares routes.
            if count_routes(candidate) <= count_routes(current):
                logger.warning(
                    f"  ⚠️  [{file_path}] Router {n}/{len(targets)} ({router}) "
                    f"added no route — discarding the batch")
                continue

            create_file(file_path, candidate)
            self._preflight_fix(file_path)
            self._inject_syspath(file_path)

            verify = run_python(file_path)
            if not verify.success and not any(p in verify.stderr for p in IGNORE_ERRORS):
                logger.warning(
                    f"  ↩️  [{file_path}] Router {n}/{len(targets)} ({router}) "
                    f"broke the import check — restoring what worked")
                create_file(file_path, current)
                continue

            current = read_file(file_path)
            logger.info(
                f"  ✅ [{file_path}] Router {n}/{len(targets)} ({router}): "
                f"{count_routes(current)} route(s) declared so far")

        added = count_routes(current) - before_total
        if added <= 0:
            logger.warning(
                f"  ⚠️  [{file_path}] Route repair declared no routes — "
                f"restoring the original")
            create_file(file_path, original)
            return False

        result.fixes_applied.append(
            f"Declared {added} route(s) in {file_path}")
        logger.info(f"  ✅ [{file_path}] Route repair applied: {added} route(s)")
        return True

    def _generate_missing_routes_fix(
        self, file_path: str, current_code: str, router: str
    ) -> str | None:
        """
        Ask for one router's handlers ONLY — never the file back.

        The same stance as `_generate_missing_definitions_fix`: the file goes in
        for context and must not come back out, because a reply that re-emits it
        is a rewrite, and a rewrite of a file that must grow is what the guard
        refuses.
        """
        project_map = self._scan_project_structure(file_path)
        resource = re.sub(r"_?router$", "", router) or "resource"
        prompt = f"""This file builds an APIRouter called `{router}` and declares NO
route handlers on it, so the application serves nothing and every requested
endpoint is missing.

FILE: {file_path}
CURRENT CONTENT OF THAT FILE (for context — do NOT return it):
{current_code}

{project_map}

WRITE THE ROUTE HANDLERS FOR `{router}` ONLY — the "{resource}" resource.

RULES:
- Return ONLY new `@{router}.get/post/put/delete(...)` handler functions. Do NOT
  return the file, do NOT repeat anything already in it, and do NOT re-declare
  `{router}` — it already exists above your code.
- A full CRUD set for this one resource: list, get one, create, update, delete.
  Nothing for any other router.
- Use the request/response models and the DB session dependency this project
  already defines — the map above names them. Import nothing that does not
  exist; a name this project does not have is a new failure, not a fix.
- The parameters must match the models. A handler taking fields the schema does
  not declare is the same defect one level down.
- No placeholders, no `pass`, no `TODO`, no `raise NotImplementedError`. A
  handler that does not work is worse than one that is missing, because it
  reports as present.

Return ONLY the handler functions, as plain Python."""
        logger.info(f"  🧠 LLM declaring routes for {router}: {file_path}")
        return self.think(prompt, max_tokens=_rewrite_budget(self, current_code))

    def _repair_missing_fields(
        self, file_path: str, findings: list, result: FileDebugResult
    ) -> bool:
        """
        Add fields to models that other modules read and the model does not
        declare (`schema_attr`'s findings).

        Unlike `_repair_missing_definitions` this REWRITES the file rather than
        appending, and that is the right shape here for the reason the other one
        is not: a field belongs inside an existing class, so there is nothing to
        append to the end of the file. The whole-file guard applies again too —
        `accept_generated_fix` rejects a reply that drops a top-level name, which
        is the real risk when a models file is re-emitted, and its `too_large`
        rule is no obstacle because adding a field is not growth of that order.
        """
        wanted = _missing_fields(findings)
        if not wanted:
            return False
        try:
            original = read_file(file_path)
        except Exception as e:
            logger.warning(f"  ⚠️  [{file_path}] Cannot read for field repair: {e}")
            return False

        logger.info(
            f"  🧾 [{file_path}] Declaring {len(wanted)} field(s) other modules read"
        )
        fixed = self._generate_missing_fields_fix(file_path, original, findings)
        if not fixed or not self._accept_generated_fix(file_path, fixed):
            logger.warning(f"  ⚠️  [{file_path}] Field repair rejected or empty")
            return False

        create_file(file_path, fixed)
        self._preflight_fix(file_path)
        self._inject_syspath(file_path)

        verify = run_python(file_path)
        if not verify.success and not any(p in verify.stderr for p in IGNORE_ERRORS):
            logger.warning(
                f"  ↩️  [{file_path}] Field repair broke the import check — "
                f"restoring the original")
            create_file(file_path, original)
            return False

        current = read_file(file_path)
        landed = [(m, a) for m, a in wanted if _declares_field(current, m, a)]
        if not landed:
            # The file still imports, so nothing is broken — but nothing was
            # fixed either, and saying "repaired" would retire the issue and
            # ship the defect. Put the original back so the next pass sees the
            # same problem rather than a rewrite that did not address it.
            logger.warning(
                f"  ↩️  [{file_path}] Field repair declared none of "
                f"{[f'{m}.{a}' for m, a in wanted]} — restoring the original")
            create_file(file_path, original)
            return False

        result.fixes_applied.append(
            f"Declared {len(landed)} missing field(s) in {file_path}")
        logger.info(
            f"  ✅ [{file_path}] Field repair applied: {len(landed)}/{len(wanted)}")
        return True

    def _repair_missing_tables(
        self, file_path: str, findings: list, result: FileDebugResult
    ) -> bool:
        """
        Add a CREATE TABLE for a table the code queries and nothing creates.

        Rewrites, like the field repair and for the same reason: the statement
        belongs beside the other CREATE TABLEs, inside whatever function already
        runs them. Verified by re-parsing the schema out of the result, so
        "it wrote something" cannot pass for "the table exists now".
        """
        wanted = _missing_tables(findings)
        if not wanted:
            return False
        try:
            original = read_file(file_path)
        except Exception as e:
            logger.warning(f"  ⚠️  [{file_path}] Cannot read for schema repair: {e}")
            return False

        logger.info(
            f"  🗄️  [{file_path}] Creating {len(wanted)} table(s) the code queries"
        )
        fixed = self._generate_missing_tables_fix(file_path, original, findings)
        if not fixed or not self._accept_generated_fix(file_path, fixed):
            logger.warning(f"  ⚠️  [{file_path}] Schema repair rejected or empty")
            return False

        create_file(file_path, fixed)
        self._preflight_fix(file_path)
        self._inject_syspath(file_path)

        verify = run_python(file_path)
        if not verify.success and not any(p in verify.stderr for p in IGNORE_ERRORS):
            logger.warning(
                f"  ↩️  [{file_path}] Schema repair broke the import check — "
                f"restoring the original")
            create_file(file_path, original)
            return False

        try:
            from tools.sql_schema_check import parse_schema
            now = set(parse_schema(read_file(file_path)))
        except Exception:
            now = set()
        landed = [t for t in wanted if t in now]
        if not landed:
            logger.warning(
                f"  ↩️  [{file_path}] Schema repair created none of {wanted} — "
                f"restoring the original")
            create_file(file_path, original)
            return False

        result.fixes_applied.append(
            f"Created {len(landed)} missing table(s) in {file_path}")
        logger.info(
            f"  ✅ [{file_path}] Schema repair applied: {len(landed)}/{len(wanted)}")
        return True

    def _repair_dead_events(
        self, file_path: str, findings: list, result: FileDebugResult
    ) -> bool:
        """
        Move an `@app.on_event(...)` body somewhere the framework will run it.

        Rewrites, like the field and schema repairs: the code has to move INTO
        the lifespan function, and there is nothing to append.

        The landing check is stricter here than anywhere else, because the
        cheapest way to make this finding go away is to delete the handler — and
        that leaves the routes exactly as unregistered as they were while
        reporting a repair. So two things are asserted, not one: the dead handler
        is gone AND the file still makes at least as many `include_router` /
        `add_api_route` / `mount` calls as it did before. A rewrite that silences
        the check by deleting the wiring is restored, the same way a field repair
        that declared no field is.
        """
        wanted = _dead_event_handlers(findings)
        if not wanted:
            return False
        try:
            original = read_file(file_path)
        except Exception as e:
            logger.warning(f"  ⚠️  [{file_path}] Cannot read for event repair: {e}")
            return False

        before = _wiring_calls(original)
        try:
            from tools.dead_event_check import count_lifespan_apps
            lifespans_before = count_lifespan_apps(original)
        except Exception:
            lifespans_before = -1
        logger.info(
            f"  🪦 [{file_path}] Rehoming {len(wanted)} unreachable handler(s) "
            f"({before} route-wiring call(s) to preserve)"
        )
        fixed = self._generate_dead_events_fix(file_path, original, findings)
        # The handlers named in the findings are the ONLY names this repair may
        # delete — deleting them is what it is for. Everything else in the file
        # is still guarded, so a reply that takes the routes with it is refused.
        if not fixed or not self._accept_generated_fix(
                file_path, fixed, allow_removed={h for _, _, h in wanted}):
            logger.warning(f"  ⚠️  [{file_path}] Event repair rejected or empty")
            return False

        create_file(file_path, fixed)
        self._preflight_fix(file_path)
        self._inject_syspath(file_path)

        verify = run_python(file_path)
        if not verify.success and not any(p in verify.stderr for p in IGNORE_ERRORS):
            logger.warning(
                f"  ↩️  [{file_path}] Event repair broke the import check — "
                f"restoring the original")
            create_file(file_path, original)
            return False

        current = read_file(file_path)
        try:
            from tools.dead_event_check import has_dead_events
            still_dead = has_dead_events(current)
        except Exception:
            still_dead = True
        if still_dead:
            logger.warning(
                f"  ↩️  [{file_path}] Event repair left the handler unreachable — "
                f"restoring the original")
            create_file(file_path, original)
            return False

        # The second way to silence this check without fixing anything: delete
        # the `lifespan=` argument instead of the handler. `on_event` then works
        # again and the check goes `not_applicable` — but whatever the lifespan
        # was doing now sits in a function nothing calls, so the app registers
        # its routes and never creates its tables.
        try:
            from tools.dead_event_check import count_lifespan_apps
            lifespans_after = count_lifespan_apps(current)
        except Exception:
            lifespans_after = lifespans_before
        if lifespans_before > 0 and lifespans_after < lifespans_before:
            logger.warning(
                f"  ↩️  [{file_path}] Event repair removed the lifespan "
                f"({lifespans_before} -> {lifespans_after}) instead of moving "
                f"the handler — restoring the original")
            create_file(file_path, original)
            return False

        after = _wiring_calls(current)
        if after < before:
            # The finding is gone because the code is gone. That is the defect
            # with its evidence removed, which is worse than the defect.
            logger.warning(
                f"  ↩️  [{file_path}] Event repair dropped route wiring "
                f"({before} -> {after}) — restoring the original")
            create_file(file_path, original)
            return False

        result.fixes_applied.append(
            f"Rehomed {len(wanted)} unreachable startup handler(s) in {file_path}")
        logger.info(
            f"  ✅ [{file_path}] Event repair applied: {len(wanted)} handler(s), "
            f"{after} wiring call(s) intact")
        return True

    def _generate_dead_events_fix(
        self, file_path: str, current_code: str, findings: list
    ) -> str | None:
        """
        The prompt for a file whose startup handler the framework never calls.

        It has to say plainly what the model will otherwise do, which is delete
        the handler: the finding reads "this code never runs", and removing code
        that never runs is a defensible edit in isolation and catastrophic here,
        because the code that never runs is what registers the routes.
        """
        wanted = "\n".join(f"- {f}" for f in findings)
        names = ", ".join(f"`{h}`" for _, _, h in _dead_event_handlers(findings))
        prompt = f"""This file builds a FastAPI application with a `lifespan=` argument
AND registers `@app.on_event(...)` handlers. When a lifespan is supplied the
framework IGNORES every `on_event` handler, so the code in {names} never runs.
The application starts cleanly and serves nothing.

FILE: {file_path}
CURRENT CODE:
{current_code}

EXACTLY WHAT TO DO:
- Move the BODY of each `on_event("startup")` handler into the lifespan
  function, BEFORE the `yield`, keeping the statements in their existing order
  and after whatever the lifespan already does.
- Move the BODY of each `on_event("shutdown")` handler into the lifespan
  function AFTER the `yield`.
- Delete the now-empty handler function and its `@app.on_event(...)` decorator.

WHY, IN FULL:
{wanted}

RULES:
- Router registration is the whole point. Every `include_router`,
  `add_api_route` and `mount` call in this file must still be there when you are
  done, against the same app object, with the same arguments.
- Do NOT solve this by deleting the handler and its body. The body is what
  registers the application's routes; deleting it makes the check pass and the
  application still serve nothing.
- Do NOT solve this by removing the `lifespan=` argument. Whatever the lifespan
  does — creating tables, opening a pool — is needed too.
- Router registration belongs at module level if it can go there. Moving it into
  the lifespan is correct and always works; module level is better when the
  imports allow it.
- Change nothing else. Keep every import, every route and every middleware call
  this file already has.

Return ONLY the complete fixed Python code for this file."""
        logger.info(f"  🧠 LLM rehoming startup handlers: {file_path}")
        return self.think(prompt, max_tokens=_rewrite_budget(self, current_code))

    def _generate_missing_tables_fix(
        self, file_path: str, current_code: str, findings: list
    ) -> str | None:
        """
        The prompt for a schema that is missing a table its own code queries.

        The trap it has to close is named in the finding: changing the QUERY to
        use a table that does exist makes the error disappear and reads the wrong
        rows, which is the same class of "repair" as defaulting a missing field
        to None.
        """
        wanted = "\n".join(f"- {f}" for f in findings)
        prompt = f"""This file creates the database schema. Other code in this project
queries tables that it never creates, so every request that reaches one of those
queries fails with `no such table`.

FILE: {file_path}
CURRENT CODE:
{current_code}

TABLES THE CODE QUERIES THAT THIS FILE NEVER CREATES:
{wanted}

RULES:
- Add a CREATE TABLE for each one, in the same place and the same style as the
  tables this file already creates: same helper, same `IF NOT EXISTS`, same
  column conventions, run at the same point in startup.
- Infer the columns from the queries in the project — the SELECT, INSERT and
  UPDATE statements that use the table name each column belongs to. A foreign
  key to another table should be an INTEGER referencing that table's id.
- Do NOT change any query to use a different table. Making the error disappear
  by reading a table that already exists returns the wrong rows.
- Keep every table this file already creates, and every other name in it,
  exactly as they are.

Return ONLY the complete fixed Python code for this file."""
        logger.info(f"  🧠 LLM creating tables: {file_path}")
        return self.think(prompt, max_tokens=_rewrite_budget(self, current_code))

    def _generate_missing_fields_fix(
        self, file_path: str, current_code: str, findings: list
    ) -> str | None:
        """
        The prompt for a model that is missing a field its callers read.

        The finding already carries the instruction and the trap — "Either use
        the field that exists, or add `price` to ProductCreate ... do NOT replace
        the read with a .get() or a default, which writes an empty value into the
        database instead" — so it is passed through verbatim. The caller cannot
        be edited from here in any case: this file is the model, not the reader.
        """
        wanted = "\n".join(f"- {f}" for f in findings)
        # The findings explain the defect; this says the edit in one line each.
        # Measured on 2026-09-03: with the prose alone the repair returned a
        # file that did not declare the field about half the time, and the
        # post-check correctly restored the original — a correct outcome, but a
        # wasted call. The instruction and the reasoning are different jobs.
        pairs = "\n".join(
            f"- add `{attr}` to class `{model}`"
            for model, attr in _missing_fields(findings))
        prompt = f"""This file defines pydantic models. Other modules read fields from
them that they do not declare, so every call that reaches one raises
AttributeError.

FILE: {file_path}
CURRENT CODE:
{current_code}

EXACTLY WHAT TO ADD:
{pairs}

WHY, IN FULL:
{wanted}

RULES:
- Add each missing field to the model named, with a sensible type annotation
  that matches how the caller uses it. A price is a float, a count is an int, a
  name is a str, a flag is a bool.
- Give a field a default ONLY if the caller can reasonably omit it. A field the
  caller always sets is required.
- Change nothing else. Keep every model, every field and every import this file
  already has — other modules import them and a dropped name is a new failure.
- Do not silence the problem: do not delete the model, do not make it accept
  arbitrary extra fields, and do not add a catch-all `dict` field.

Return ONLY the complete fixed Python code for this file."""
        logger.info(f"  🧠 LLM declaring fields: {file_path}")
        return self.think(prompt, max_tokens=_rewrite_budget(self, current_code))

    def _generate_missing_definitions_fix(
        self, file_path: str, current_code: str, findings: list
    ) -> str | None:
        """
        Ask for the missing definitions ONLY — never the file back.

        It has to say the opposite of the runtime prompt. That one says "the bug
        is in THIS file, do not make the other module tolerate it"; here the
        other module is right and this file is missing what it reads. The
        findings already carry that instruction verbatim — "Add `get_suppliers`
        to `backend.services` — do NOT delete the reference" — so they are passed
        through rather than paraphrased.

        The file goes in the prompt (the new code has to use the same connection
        helper, tables and return shapes) but must not come back out of it.
        """
        project_map = self._scan_project_structure(file_path)
        wanted = "\n".join(f"- {f}" for f in findings)
        # What the callers actually pass. Without this the signature is a guess,
        # and a guessed signature turns AttributeError into TypeError.
        sites = _call_sites(file_path, _missing_names(findings))
        calls = ""
        if sites:
            lines = [
                f"{name}:" + "".join(
                    chr(10) + "    " + hit for hit in hits)
                for name, hits in sites.items()
            ]
            calls = ("HOW EACH ONE IS CALLED — the parameters must match these "
                     "calls exactly:" + chr(10) + chr(10).join(lines) + chr(10))
        prompt = f"""This Python file is INCOMPLETE. It imports and runs correctly,
but other modules read names from it that it does not define, so every call that
reaches one of them raises AttributeError or ImportError.

FILE: {file_path}
CURRENT CONTENT OF THAT FILE (for context — do NOT return it):
{current_code}

{project_map}

ADD DEFINITIONS FOR EXACTLY THESE, AND NOTHING ELSE:
{wanted}

{calls}

RULES:
- Return ONLY the new top-level definitions, ready to append to the end of that
  file. No imports, no existing code, no markdown fences, no explanation.
- The callers are correct and this file is not. Do not rename anything, do not
  change what the callers do.
- Implement each one for real, in the style already in the file above: the same
  connection helper, the same table and column names, the same return shapes.
  A stub that returns None, an empty list, or raises NotImplementedError is
  worse than the error it replaces — it turns a loud failure into a wrong answer
  that reaches the database.
- Take each signature from the calls listed above: same number of parameters, in
  the same order. If a caller passes one object (a Pydantic model, say), the
  function takes one object — not its fields spread out.
- Use only names the file already imports. Do not add new dependencies.

Return ONLY the new definitions."""
        budget = _DEFINITION_TOKENS_EACH * max(1, len(findings)) + _REWRITE_HEADROOM
        logger.info(f"  🧠 LLM completing: {file_path} (+{len(findings)} name(s))")
        return self.think(prompt, max_tokens=budget)

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
