"""
tools/await_sync_check.py — awaiting a function that is not async
=================================================================

The single defect that held row 6 to 3 of 22 endpoints.

`backend/routes.py` was generated with `async def` handlers calling a synchronous
service layer:

    routes.py    @router.get("/suppliers/")
                 async def list_suppliers():
                     return await services.get_suppliers()

    services.py  def get_suppliers() -> List[models.SupplierRead]:
                     ...

`services.py` declared **29 functions, none of them async**, and `routes.py`
wrote **21 `await services.*` calls**. Every one raises

    TypeError: object list can't be used in 'await' expression

at request time — never at import, so the module loads, the app boots, the
routes register, and each one 500s the moment it is called. Row 6 shipped
`done_with_context` with every static check verified and 19 of 22 endpoints
dead, which is the same shape `green-can-mean-never-ran` describes: the code is
structurally correct and the application does not work.

Two LLM calls agreed on a name and disagreed about whether it was a coroutine —
the same class as `schema_attr` (the fields of a class both files agree exists)
and `module_ref` (whether the name exists at all), one property further in.

Why nothing else saw it
-----------------------
`module_ref` verified: the names all exist. `schema_attr` verified: the fields
are declared. `route_presence` verified: 22 routes. `sql_schema` verified: 4
tables. Only `runtime_smoke` caught it, by calling the endpoints — and by then
the build was finished.

The repair is deterministic and costs nothing
---------------------------------------------
`await f(...)` where `f` is a plain `def` is fixed by deleting the `await`. No
model is needed, and `repair_await` does exactly that, which is why this module
carries its own repair rather than publishing a `repair_target`.

Precision over recall, the same stance as the other static checks:

  * the callee must resolve to a `def` in a project module this scan actually
    read — a third-party name is never judged;
  * a module using `import *`, `__getattr__` or `globals()` is skipped, since
    what a name means there cannot be settled by reading;
  * a name bound more than once in the reading module is skipped;
  * a sync function that RETURNS an awaitable is legal to await, so a callee
    whose body returns a call to a known async function is skipped;
  * a module that does not parse is skipped.

Deterministic and free: no LLM, no tokens.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import config
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)


@dataclass
class AwaitIssue:
    """One `await` on a function that is not a coroutine."""
    file: str          # project-relative, posix
    line: int
    callee: str        # as written: "services.get_suppliers" / "get_suppliers"
    defined_in: str    # the module that defines it, project-relative

    def __str__(self) -> str:
        return (
            f"`await {self.callee}(...)` at {self.file}:{self.line} awaits a "
            f"function that is not async — `{self.callee.split('.')[-1]}` is a "
            f"plain `def` in {self.defined_in}. Every call raises "
            f"\"TypeError: object ... can't be used in 'await' expression\" at "
            f"request time. Remove the `await`."
        )


@dataclass
class AwaitReport:
    files: int = 0
    awaits: int = 0
    issues: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


_OPEN_MARKERS = ("__getattr__", "globals()", "setattr(")


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    return (any(p in ("tests", "test") for p in parts[:-1])
            or parts[-1].startswith("test_")
            or parts[-1].endswith("_test.py"))


def _module_functions(tree: ast.AST) -> dict:
    """`{name: is_async}` for the module's top-level functions."""
    out: dict = {}
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef):
            out[node.name] = True
        elif isinstance(node, ast.FunctionDef):
            out[node.name] = False
    return out


def _returns_awaitable(tree: ast.AST, name: str, async_names: set) -> bool:
    """Does this sync function return a call to something known to be async?

    `def f(): return g()` where `g` is `async def` produces a coroutine, and
    `await f()` is then correct. Rare in generated CRUD and legal everywhere, so
    it is skipped rather than reported.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != name:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call):
                fn = sub.value.func
                called = (fn.id if isinstance(fn, ast.Name)
                          else fn.attr if isinstance(fn, ast.Attribute) else "")
                if called in async_names:
                    return True
            # `return await ...` means it is a coroutine already, but a plain
            # `def` cannot contain `await` — so this only appears in broken code
            # and is not a reason to stay silent.
    return False


def _is_open(source: str) -> bool:
    return any(m in source for m in _OPEN_MARKERS) or "import *" in source


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


def check_project_awaits(root: str) -> AwaitReport:
    """Every `await` on a non-async project function. Never raises."""
    report = AwaitReport()
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        if not project.is_dir():
            return report
        paths = [p for p in sorted(project.rglob("*.py"))
                 if "__pycache__" not in p.parts]
    except Exception:
        return report

    # Pass 1: what every module defines, and whether it is async.
    sources: dict = {}
    trees: dict = {}
    functions: dict = {}          # module stem -> {name: is_async}
    open_modules: set = set()

    for path in paths:
        rel = str(path.relative_to(project)).replace("\\", "/")
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except Exception:
            report.skipped.append((rel, "does not parse"))
            continue
        stem = path.stem
        sources[stem], trees[stem] = source, tree
        functions[stem] = _module_functions(tree)
        if _is_open(source):
            open_modules.add(stem)

    async_names = {n for fns in functions.values()
                   for n, is_async in fns.items() if is_async}

    # Pass 2: the awaits.
    for path in paths:
        rel = str(path.relative_to(project)).replace("\\", "/")
        stem = path.stem
        if stem not in trees or _is_test(rel):
            continue
        report.files += 1
        tree = trees[stem]
        counts = _binding_counts(tree)

        # `from services import get_suppliers` -> {get_suppliers: services}
        direct: dict = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[-1]
                if mod not in functions:
                    continue
                for alias in node.names:
                    if alias.name != "*":
                        direct[alias.asname or alias.name] = mod

        for node in ast.walk(tree):
            if not isinstance(node, ast.Await):
                continue
            report.awaits += 1
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            fn = call.func

            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                mod, name = fn.value.id, fn.attr
                written = f"{mod}.{name}"
            elif isinstance(fn, ast.Name):
                mod, name = direct.get(fn.id, ""), fn.id
                written = fn.id
            else:
                continue

            if not mod or mod not in functions or mod in open_modules:
                continue
            # A name rebound in the reading module may not be the import.
            if counts.get(mod, 0) > 1:
                continue
            is_async = functions[mod].get(name)
            if is_async is None or is_async:
                continue
            if _returns_awaitable(trees[mod], name, async_names):
                continue

            report.issues.append(AwaitIssue(
                file=rel, line=getattr(node, "lineno", 0),
                callee=written, defined_in=f"{mod}.py"))

    if report.issues:
        logger.info(
            "⏳ Await check: {n} await(s) on non-async function(s) — {w}".format(
                n=len(report.issues),
                w="; ".join(f"{i.file}:{i.line}" for i in report.issues[:5])))
    return report


def repair_await(source: str, callees: set) -> tuple:
    """Strip `await` from calls to the named sync functions. `(new_source, n)`.

    Deterministic, and the reason this module repairs rather than publishing a
    `repair_target`: `await f(...)` where `f` is a plain `def` is fixed by
    deleting four characters, and no model is needed to decide that.

    Text-level on purpose. `ast.unparse` would reformat the whole file, and a
    repair that rewrites lines it was not asked about is exactly what the
    shrink/growth guards exist to catch.
    """
    if not callees:
        return source, 0
    pattern = re.compile(
        r"\bawait\s+(?=(?:" + "|".join(re.escape(c) for c in sorted(callees))
        + r")\s*\()")
    fixed, n = pattern.subn("", source)
    return fixed, n


def check_await_sync(root: str) -> VerificationOutcome:
    """The same check as a VerificationOutcome, for the verification surface."""
    report = check_project_awaits(root)

    if not report.awaits:
        return VerificationOutcome.not_applicable(
            "await_sync",
            detail="this project awaits nothing, so there is no coroutine "
                   "mismatch to find")

    detail = f"{report.awaits} await(s) checked across {report.files} file(s)"
    if not report.issues:
        return VerificationOutcome.verified("await_sync", detail=detail)

    outcome = VerificationOutcome.failed(
        "await_sync", [str(i) for i in report.issues], detail=detail,
        evidence={
            "awaited_sync": [f"{i.callee} ({i.defined_in})" for i in report.issues],
            # `{file: [callee, ...]}` — the caller is the file that must change,
            # and the fix is deletion, so the pipeline repairs it directly rather
            # than sending it to a model.
            "await_targets": _await_targets(root, report),
        },
    )
    # Every call raises, so an application whose handlers do this serves nothing
    # usable — row 6 answered 3 of 22 endpoints because of it.
    outcome.mark_fatal(
        f"{len(report.issues)} call(s) await a function that is not async, so "
        f"every request that reaches one raises TypeError")
    return outcome


def _await_targets(root: str, report: AwaitReport) -> dict:
    targets: dict = {}
    for issue in report.issues:
        targets.setdefault(f"{root}/{issue.file}", []).append(issue.callee)
    return {k: sorted(set(v)) for k, v in targets.items()}
