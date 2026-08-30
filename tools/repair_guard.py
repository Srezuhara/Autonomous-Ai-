"""
tools/repair_guard.py — is this LLM reply a repair, or damage?
==============================================================

One implementation of the "should I write this over the original?" question,
shared by every agent that overwrites a generated file with an LLM's reply.

Why it is here rather than on the Debugger
------------------------------------------
The Debugger has grown a careful set of guards, each paid for by a live failure:
a truncated `routes.py` "repaired" into 413 chars of imports with no `router`
left, which compiled, was recorded as a success, and left the application
non-existent.

Two other agents overwrite generated files with an LLM reply and had **no guard
at all** — the only check was `if fixed and fixed.strip()`:

  * `BackendDeveloper._verify_and_repair` — a three-line reply could replace a
    three-hundred-line module, and the re-scan that follows would report the
    result "clean", because an empty file has no defects.
  * `Tester._test_file` — same shape, on the test files.

Duplicating the guards would mean three copies drifting apart. They live here,
`Debugger` delegates to them, and the other callers use them directly.

Everything in this module is deterministic and costs no tokens.
"""

from __future__ import annotations

import ast
import logging
import re

logger = logging.getLogger(__name__)


# Top-level definitions, found by pattern rather than by `ast`. The file being
# repaired is usually a *syntax error* — that is why it is being repaired — so
# anything that needs to parse it first cannot run when it matters most.
TOP_LEVEL_SYMBOL_RE = re.compile(
    r"^(?:async\s+def\s+(?P<afn>\w+)"
    r"|def\s+(?P<fn>\w+)"
    r"|class\s+(?P<cls>\w+)"
    r"|(?P<var>[A-Za-z_]\w*)\s*(?::[^=\n]+)?=(?!=))",
    re.MULTILINE,
)

TOP_LEVEL_IMPORT_RE = re.compile(
    r"^(?:from\s+[\w.]+\s+import|import)\s+(?P<names>[^\n#]+)",
    re.MULTILINE,
)

# A reply that pastes several modules into one file announces itself with a
# path-comment header per file.
_FILE_HEADER_RE = re.compile(
    r"^\s*#\s*(?:[\w_\-]+/)*backend/[^/\s]+\.py\s*$", re.MULTILINE
)

# Below this size a file has too little structure for the symbol comparison to
# mean anything, so shrinkage is the only signal left — see accept_generated_fix.
_SMALL_FILE_CHARS = 120


def _top_level_symbols_by_regex(source: str, defined_only: bool = False) -> set[str]:
    """The pre-AST fallback, for source that will not parse."""
    names: set[str] = set()
    for m in TOP_LEVEL_SYMBOL_RE.finditer(source):
        name = m.group("afn") or m.group("fn") or m.group("cls") or m.group("var")
        if name and not name.startswith("_"):
            names.add(name)
    if defined_only:
        return names
    for m in TOP_LEVEL_IMPORT_RE.finditer(source):
        for part in m.group("names").split(","):
            part = part.strip().strip("()").strip()
            if not part:
                continue
            bound = part.split(" as ")[-1].strip().split(".")[0]
            if bound and bound != "*" and not bound.startswith("_"):
                names.add(bound)
    return names


def top_level_symbols(source: str, defined_only: bool = False) -> set[str]:
    """
    Names a sibling module could import from this file.

    An import binds a module-level name just as a `def` does: after
    `from crud import get_db`, `from routes import get_db` still resolves.
    Counting only definitions made the guard reject the *correct* repair for a
    duplicated dependency — the fix is to delete the local copy and import the
    real one, which looked to the guard like deleting `get_db`.

    Parsed properly where the source parses; the regex remains for the case it
    does not, which is common here because these are broken files.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return _top_level_symbols_by_regex(source, defined_only)

    names: set[str] = set()

    def add(name: str) -> None:
        # Private/underscore-prefixed helpers and the sys.path preamble the
        # architect injects are noise here, not API.
        if name and not name.startswith("_"):
            names.add(name)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and not defined_only:
            for alias in node.names:
                if alias.name == "*":
                    continue
                add(alias.asname or alias.name.split(".")[0])
    return names


def accept_generated_fix(current: str, fixed: str, label: str = "") -> tuple[bool, str]:
    """
    Should `fixed` be written over `current`? Returns (accept, reason_if_not).

    Takes the current source rather than a path so it has no opinion about how
    the caller reads files — `Debugger` resolves OUTPUT_DIR-relative paths
    through `tools.file_writer`, and a caller that already has the text in hand
    should not have to round-trip through disk to use this.

    Three ways an LLM reply damages a file instead of repairing it:

    1. It pastes several modules into one.
    2. It deletes the contents. An empty module imports perfectly, so "the
       import check passes" is a target the model can hit by removing code —
       and it does.
    3. It drops a top-level name another module imports.
    """
    file_header_count = len(_FILE_HEADER_RE.findall(fixed))
    too_large = bool(current) and len(fixed) > max(len(current) * 1.6, len(current) + 1800)
    if file_header_count >= 2 or too_large:
        return False, "appears to contain multiple files or an oversized rewrite"

    if not current.strip():
        return True, ""

    # A repair that drops a top-level name is removing something another module
    # may import. `router` disappearing is exactly how a working app became
    # unimportable while every check still passed. What the file *defines* must
    # stay reachable from it — but an import satisfies that as well as a `def`
    # does. The correct repair for a duplicated dependency is to delete the
    # local copy and import the real one, and comparing definitions to
    # definitions rejected exactly that, leaving the endpoint broken.
    lost = top_level_symbols(current, defined_only=True) - top_level_symbols(fixed)
    if lost:
        return False, (
            f"it removes top-level {', '.join(sorted(lost))} — a repair must "
            "not delete the definitions other modules import"
        )

    # Belt and braces for the case where the deletion takes the symbols with it
    # in a file too broken to pattern-match reliably.
    #
    # The 0.5 ratio applied only above 400 chars, which left two holes a repair
    # could walk through: a file of 400 chars or fewer could be reduced to
    # nothing, and any file could legally lose 49.9% of itself. A short module
    # is still the whole of `models.py` for a small project. Below
    # _SMALL_FILE_CHARS there is genuinely too little structure to judge, so the
    # floor stops there rather than pretending to an accuracy it lacks.
    if len(current) > _SMALL_FILE_CHARS and len(fixed) < len(current) * 0.6:
        return False, (
            f"shrinks the file from {len(current)} to {len(fixed)} chars. "
            "Deleting code is not a repair, even though an empty module "
            "imports cleanly"
        )

    return True, ""


def accept_python_reply(current: str, fixed: str) -> tuple[bool, str]:
    """
    `accept_generated_fix` plus "and the result is actually Python".

    The Debugger can skip the parse check because it re-runs the import check
    afterwards and restores the original when that fails. Callers with no such
    backstop — BackendDeveloper's self-verification pass, the Tester — need the
    syntax check here or they write a file nothing can import.
    """
    if not fixed or not fixed.strip():
        return False, "the reply was empty"
    ok, reason = accept_generated_fix(current, fixed)
    if not ok:
        return False, reason
    try:
        ast.parse(fixed)
    except SyntaxError as e:
        return False, f"the reply does not parse ({e})"
    return True, ""


def count_test_functions(source: str) -> int:
    """How many `test_*` functions this file defines, at any nesting level."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return len(re.findall(r"^\s*(?:async\s+)?def\s+test_\w+", source, re.MULTILINE))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def accept_test_reply(current: str, fixed: str) -> tuple[bool, str]:
    """
    The acceptance rule for a repaired TEST file, which is not the rule for
    source.

    `accept_generated_fix`'s symbol check is wrong here: renaming a test is a
    legitimate repair, and every test name is a top-level symbol, so the check
    would reject good fixes. What matters instead is the **count**.

    A test repair is asked to make a red suite green, and deleting the failing
    test does that perfectly. That is the §0.7 failure mode in a new place — the
    silencing repair scored higher than the correct one — so the one thing a
    repair may never do is come back with fewer tests than it was given.
    """
    if not fixed or not fixed.strip():
        return False, "the reply was empty"
    try:
        ast.parse(fixed)
    except SyntaxError as e:
        return False, f"the reply does not parse ({e})"

    if not current.strip():
        return True, ""

    had, now = count_test_functions(current), count_test_functions(fixed)
    if now < had:
        return False, (
            f"it drops {had - now} of {had} test function(s) — making the suite "
            "green by deleting the failing test is not a repair"
        )
    if len(current) > _SMALL_FILE_CHARS and len(fixed) < len(current) * 0.6:
        return False, (
            f"shrinks the test file from {len(current)} to {len(fixed)} chars"
        )
    return True, ""
