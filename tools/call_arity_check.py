"""
tools/call_arity_check.py — a call that cannot match the definition
==================================================================

The other half of row 6, and the gap §0.-2 named and did not close.

`module_ref` asks whether a name exists. It does not ask whether the CALL works,
and §0.-2 recorded exactly that after a probe added all 23 missing names and the
endpoints still 500'd: *"the name existing is not the call working"*. Row 6 is
what it costs.

    main.py      conn = services.get_connection(DB_PATH)
    services.py  def get_connection() -> sqlite3.Connection:

One argument, zero parameters. It raises inside the lifespan, so `init_db(conn)`
on the next line never runs, no table is ever created, and every database
endpoint answers `OperationalError: no such table: supplier`. `module_ref`
verified the build: `get_connection` exists. `sql_schema` verified it: four
tables are created — in code that never executes.

Measured on that build, and the numbers are the argument for this module:

    as shipped                    3/22 endpoints
    fixing the awaits only        3/22
    fixing this one call only     3/22
    fixing BOTH                  17/22

Two independent defects, each individually fatal, one of them a single
argument. See `tools/await_sync_check.py` for the other.

Precision over recall, the same stance as the other static checks:

  * the callee must resolve to a plain function in a project module this scan
    read — a third-party name is never judged;
  * a definition taking `*args`/`**kwargs` accepts anything, so it is skipped;
  * a DECORATED definition is skipped: a decorator may return something with a
    different signature, and FastAPI's `Depends`/route decorators do exactly
    that;
  * a method call is skipped — `self` binding is not modelled here;
  * a module using `import *`, `__getattr__` or `globals()` is skipped;
  * a name bound more than once in the reading module is skipped;
  * a call using `*x` or `**y` at the call site is skipped, since the count is
    not knowable by reading.

Deterministic and free: no LLM, no tokens.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

_OPEN_MARKERS = ("__getattr__", "globals()", "setattr(")


@dataclass
class ArityIssue:
    file: str
    line: int
    callee: str        # as written
    given: int         # positional arguments at the call site
    lo: int            # required positional parameters
    hi: int            # accepted positional parameters
    defined_in: str
    signature: str
    keyword: str = ""   # set when the mismatch is a keyword, not a count
    duplicate: bool = False

    def __str__(self) -> str:
        want = (f"{self.lo}" if self.lo == self.hi
                else f"{self.lo} to {self.hi}")
        if self.keyword:
            what = ("a value for `{k}` both positionally and by keyword"
                    if self.duplicate else
                    "the keyword argument `{k}=`, which the definition does "
                    "not accept").format(k=self.keyword)
            return (
                f"`{self.callee}(...)` at {self.file}:{self.line} passes "
                f"{what} — `{self.signature}` in {self.defined_in}. The call "
                f"raises TypeError every time it runs. Fix the CALL to match "
                f"the definition, or the definition to match its callers."
            )
        return (
            f"`{self.callee}(...)` at {self.file}:{self.line} passes "
            f"{self.given} positional argument(s) to a function that takes "
            f"{want} — `{self.signature}` in {self.defined_in}. The call raises "
            f"TypeError every time it runs. Fix the CALL to match the "
            f"definition, or the definition to match its callers."
        )


@dataclass
class ArityReport:
    files: int = 0
    calls: int = 0
    issues: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    return (any(p in ("tests", "test") for p in parts[:-1])
            or parts[-1].startswith("test_")
            or parts[-1].endswith("_test.py"))


def _signature(node) -> tuple | None:
    """`(lo, hi, names, keywords, text)` for a definition whose arity can be
    judged; `keywords` is every name a keyword argument may use.

    `None` when it cannot be: varargs, kwargs, or any decorator.
    """
    if node.decorator_list:
        return None
    a = node.args
    if a.vararg is not None or a.kwarg is not None:
        return None
    positional = list(a.posonlyargs) + list(a.args)
    names = [p.arg for p in positional]
    hi = len(positional)
    lo = hi - len(a.defaults)
    keywords = {p.arg for p in a.args} | {p.arg for p in a.kwonlyargs}
    try:
        text = f"def {node.name}({ast.unparse(a)})"
    except Exception:
        text = f"def {node.name}(...)"
    return lo, hi, names, keywords, text


def _module_signatures(tree: ast.AST) -> dict:
    out: dict = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = _signature(node)
            if sig is not None:
                out[node.name] = sig
    return out


def _binding_counts(tree: ast.AST) -> dict:
    counts: dict = {}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    bump(t.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bump(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bump((alias.asname or alias.name).split(".")[0])
    return counts


def check_project_arity(root: str) -> ArityReport:
    """Every call that cannot match its definition. Never raises."""
    report = ArityReport()
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        if not project.is_dir():
            return report
        paths = [p for p in sorted(project.rglob("*.py"))
                 if "__pycache__" not in p.parts]
    except Exception:
        return report

    trees: dict = {}
    sigs: dict = {}
    open_modules: set = set()

    for path in paths:
        rel = str(path.relative_to(project)).replace("\\", "/")
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except Exception:
            report.skipped.append((rel, "does not parse"))
            continue
        trees[path.stem] = tree
        sigs[path.stem] = _module_signatures(tree)
        if any(m in source for m in _OPEN_MARKERS) or "import *" in source:
            open_modules.add(path.stem)

    for path in paths:
        rel = str(path.relative_to(project)).replace("\\", "/")
        stem = path.stem
        if stem not in trees or _is_test(rel):
            continue
        report.files += 1
        tree = trees[stem]
        counts = _binding_counts(tree)

        direct: dict = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[-1]
                if mod in sigs:
                    for alias in node.names:
                        if alias.name != "*":
                            direct[alias.asname or alias.name] = mod

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                mod, name, written = fn.value.id, fn.attr, f"{fn.value.id}.{fn.attr}"
            elif isinstance(fn, ast.Name):
                mod, name, written = direct.get(fn.id, ""), fn.id, fn.id
            else:
                continue
            if not mod or mod not in sigs or mod in open_modules:
                continue
            if mod != stem and counts.get(mod, 0) > 1:
                continue
            sig = sigs[mod].get(name)
            if sig is None:
                continue
            # A call that unpacks cannot be counted by reading.
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            if any(k.arg is None for k in node.keywords):
                continue

            report.calls += 1
            lo, hi, names, keywords, text = sig
            given = len(node.args)
            kw = {k.arg for k in node.keywords}
            # A keyword may satisfy a positional parameter.
            supplied = given + len({n for n in names[given:]} & kw)
            issue = dict(file=rel, line=getattr(node, "lineno", 0),
                         callee=written, given=given, lo=lo, hi=hi,
                         defined_in=f"{mod}.py", signature=text)
            if given > hi or supplied < lo:
                report.issues.append(ArityIssue(**issue))
                continue
            # A keyword the definition has no parameter for, or one naming a
            # parameter already filled positionally. Both raise TypeError on
            # every call, and counting positionals alone passed them: row 2's
            # `crud.list_bookmarks(db, tag_name=tag)` against
            # `def list_bookmarks(conn)` was recorded verified (2026-09-10)
            # while GET /bookmarks/ answered 500 on every request.
            unexpected = sorted(kw - keywords)
            dup = sorted(set(names[:given]) & kw)
            if unexpected or dup:
                report.issues.append(ArityIssue(
                    **issue, keyword=(unexpected or dup)[0],
                    duplicate=not unexpected))

    if report.issues:
        logger.info(
            "🔢 Call arity check: {n} call(s) that cannot match — {w}".format(
                n=len(report.issues),
                w="; ".join(f"{i.file}:{i.line}" for i in report.issues[:5])))
    return report


def _repair_targets(root: str, report: ArityReport) -> dict:
    """`{file: [finding, ...]}` for the CALLER, which is what must change.

    The opposite of `module_ref`, deliberately. There the finding named a file
    that must gain a definition; here the definition is right and the call is
    wrong, so the file to repair is the one the traceback would name for once.
    """
    targets: dict = {}
    for issue in report.issues:
        targets.setdefault(f"{root}/{issue.file}", []).append(str(issue))
    return targets


def check_call_arity(root: str) -> VerificationOutcome:
    """The same check as a VerificationOutcome, for the verification surface."""
    report = check_project_arity(root)

    if not report.calls:
        return VerificationOutcome.not_applicable(
            "call_arity",
            detail=("no call in this project resolves to a project function "
                    "whose signature can be checked"))

    detail = f"{report.calls} call(s) checked against their definitions"
    if not report.issues:
        return VerificationOutcome.verified("call_arity", detail=detail)

    return VerificationOutcome.failed(
        "call_arity", [str(i) for i in report.issues], detail=detail,
        evidence={
            "mismatched": [f"{i.callee} ({i.given} given, {i.lo}-{i.hi} taken)"
                           for i in report.issues],
            "repair_targets": _repair_targets(root, report),
        },
    )
