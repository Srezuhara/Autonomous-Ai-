"""
tools/module_ref_check.py — a name the other file never defined
===============================================================

The defect that killed matrix row 3, and that nothing in the pipeline looked
for.

`backend/routes.py` was generated against a `backend/models.py` that does not
exist as written:

    routes.py   from . import models
                def create_supplier(supplier: models.SupplierCreate, ...)
                def create_product(product:  models.ProductCreate,  ...)

    models.py   class Base(DeclarativeBase)
                class Supplier(Base) ... class Product(Base) ...
                                     -> no *Create anywhere in the file

`prompts/backend_developer.txt` asked for "a flat file with Pydantic classes
only, no database code"; the model shipped SQLAlchemy ORM classes instead. Two
LLM calls agreed on a module name and disagreed about what is in it — the same
class of defect as `tools/schema_attr_check.py`, one level up: that one checks
the *fields* of a class both files agree exists, this one checks that the name
exists at all.

Why no existing check saw it
----------------------------
`schema_attr` answered `not_applicable — this project declares no pydantic
models`, which for a FastAPI build with 18 routes is a red flag reported as a
shrug: the models were missing, and their absence is precisely what made the
check decline to run. `runtime_smoke` saw the import blow up and could say only
that the app did not boot. Nothing said *which* name was missing, or where.

This does, by reading the source, before a single token is spent.

Precision over recall, the same stance as the other static checks: a false
positive spends an LLM call editing correct code and tells a user their working
build is broken. Anything that cannot be resolved with certainty is skipped —

  * a module doing `from x import *`, defining `__getattr__`, or assigning
    through `globals()`/`setattr` — any name may appear at runtime;
  * a module whose source does not parse (something else already reports that);
  * a name that two different files could both claim under the same import
    spelling;
  * a local binding that is reassigned anywhere in the reading file;
  * anything reached through `getattr` or a string.

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

_SKIP_DIRS = {"__pycache__", "venv", ".venv", "node_modules", ".git",
              "alembic", "migrations", "versions", "dist", "build"}

#: Attributes every module object carries. Reading one is not a missing name.
_MODULE_API = {
    "__name__", "__file__", "__doc__", "__dict__", "__path__", "__package__",
    "__spec__", "__loader__", "__all__", "__builtins__", "__version__",
}

#: A module that does any of these can grow names this check cannot see, so it
#: is never used to report an absence.
_OPEN_MARKERS = ("globals()", "setattr(", "__getattr__")


@dataclass
class RefIssue:
    """One read of a name the referenced project module does not define."""
    file:   str          # OUTPUT_DIR-relative, forward slashes
    line:   int
    module: str          # the project module that was referenced
    name:   str          # the name it does not define
    where:  str          # "import" | "attribute"
    at_import_time: bool = False
    in_test: bool = False   # a test module, not the shipped application
    defines: tuple = ()  # a sample of what it does define

    def __str__(self) -> str:
        # Naming what the module *does* define is what makes this repairable in
        # one call. Row 3's models.py held `Supplier`, `Product`, `Warehouse`
        # and `StockMovement` as ORM classes; a repair told only that
        # `SupplierCreate` is missing would plausibly delete the reference
        # instead of adding the schema that was asked for.
        have = ", ".join(self.defines) if self.defines else "no names at all"
        lead = (
            f"`from {self.module} import {self.name}` at line {self.line} fails"
            if self.where == "import"
            else f"`{self.module}.{self.name}` is read at line {self.line}"
        )
        if self.in_test:
            # A test module that cannot import is a broken suite, not a broken
            # application — the distinction §4.26 exists to preserve, and the
            # routing below still depends on it.
            #
            # What this no longer does is assert that the application is FINE.
            # `in_test` says where the name is READ; it says nothing about the
            # health of the module being read. On row 3 (2026-09-01) the text
            # read "the application itself is unaffected" while `app.main` was
            # dead of a NameError, and that sentence went into the remediation
            # advisory that drives an LLM — alongside "Add `router` to
            # `app.main`", which was the wrong repair for a file whose real
            # defect was that it ignored five aliases it had already imported.
            # Scope the claim to what this checker actually knows.
            when = ("when the test module is imported, so this test cannot run "
                    "(a finding about the test module, not about the "
                    "application)"
                    if self.at_import_time
                    else "when this test runs (a finding about the test "
                         "module, not about the application)")
        else:
            when = ("when the module is imported, so the application cannot "
                    "start" if self.at_import_time
                    else "on every call that reaches it")
        return (
            f"{lead}: `{self.module}` defines {have}, and no `{self.name}`. "
            f"This raises {when}. Add `{self.name}` to `{self.module}` — do NOT "
            f"delete the reference or point it at a different name, which "
            f"silently changes what this code does instead of fixing it."
        )


@dataclass
class RefReport:
    modules: dict = field(default_factory=dict)   # module path -> frozenset(names)
    open_modules: set = field(default_factory=set)
    ambiguous: set = field(default_factory=set)   # import spellings two files claim
    issues: list = field(default_factory=list)
    #: module path -> the file that defines it, PROJECT-relative like
    #: `RefIssue.file` (the root folder is prepended by `check_module_refs`,
    #: because repair paths are OUTPUT_DIR-relative and these are not). This is the
    #: file a repair has to edit, and it is NOT the file the issue is reported
    #: in: `RefIssue.file` is where the name is *read*. Row 3 (2026-09-02) died
    #: on exactly that distinction — 23 findings naming `backend.services`, two
    #: LLM repair passes spent rewriting `backend/routes.py`, which was correct.
    files: dict = field(default_factory=dict)


# ── What each module defines ──────────────────────────────────────────────────

def _bound_names(body) -> set:
    """
    Every name a module body binds, descending into the blocks that still run
    at import time.

    A conditional or `try`-guarded definition is a real definition — generated
    code writes `try: import ujson as json / except ImportError: import json`
    constantly — so this must not stop at the top-level statement list, or the
    check would report the fallback branch as missing.
    """
    names: set = set()
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                names |= _target_names(target)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            names |= _target_names(stmt.target)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, (ast.If, ast.While)):
            names |= _bound_names(stmt.body) | _bound_names(stmt.orelse)
        elif isinstance(stmt, ast.For):
            names |= _target_names(stmt.target)
            names |= _bound_names(stmt.body) | _bound_names(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            names |= _bound_names(stmt.body) | _bound_names(stmt.orelse)
            names |= _bound_names(stmt.finalbody)
            for handler in stmt.handlers:
                names |= _bound_names(handler.body)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if item.optional_vars is not None:
                    names |= _target_names(item.optional_vars)
            names |= _bound_names(stmt.body)
    return names


def _target_names(target) -> set:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        out: set = set()
        for elt in target.elts:
            out |= _target_names(elt)
        return out
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return set()


def _is_open(tree: ast.Module, source: str) -> bool:
    """Can this module grow names at runtime that the source does not show?"""
    if any(marker in source for marker in _OPEN_MARKERS):
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return True
    return False


#: Exceptions a defensive `try` catches when it is *deliberately* probing for a
#: name that may not be there. A read inside one is not a defect — it is the
#: author saying so.
_ATTR_GUARDS = {"AttributeError", "Exception", "BaseException"}
_IMPORT_GUARDS = {"ImportError", "ModuleNotFoundError", "AttributeError",
                  "Exception", "BaseException"}


def _guarded_lines(tree: ast.Module) -> tuple:
    """
    `(lines guarded against AttributeError, lines guarded against ImportError)`.

    `inventory_system_90ee973f` is why this exists. Its `routes.py` opens with

        try:
            LowStockReport = schemas.LowStockReport
        except AttributeError:
            class LowStockReport(BaseModel): ...

    which reads a name that really is absent from `schemas.py` and then supplies
    it. The code is correct and the application serves the route; reporting it
    would have told a working build it was broken, and spent an LLM call
    "fixing" a fallback. A bare `except` counts too.
    """
    attr_lines: set = set()
    import_lines: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        caught: set = set()
        bare = False
        for handler in node.handlers:
            if handler.type is None:
                bare = True
                continue
            for sub in ast.walk(handler.type):
                if isinstance(sub, ast.Name):
                    caught.add(sub.id)
                elif isinstance(sub, ast.Attribute):
                    caught.add(sub.attr)
        body_lines: set = set()
        for stmt in node.body:
            for sub in ast.walk(stmt):
                line = getattr(sub, "lineno", None)
                if line:
                    body_lines.add(line)
        if bare or (caught & _ATTR_GUARDS):
            attr_lines |= body_lines
        if bare or (caught & _IMPORT_GUARDS):
            import_lines |= body_lines
    return attr_lines, import_lines


def _is_test_module(rel: Path) -> bool:
    """A test file, by the two conventions pytest and this pipeline both use."""
    return (rel.name.startswith("test_") or rel.name.endswith("_test.py")
            or rel.name == "conftest.py"
            or any(part in ("tests", "test") for part in rel.parts[:-1]))


def _module_path(rel: Path) -> str:
    """`backend/models.py` -> `backend.models`; `backend/__init__.py` -> `backend`."""
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _own_definitions(body) -> set:
    """
    The names this module *writes*, as opposed to the ones it imports.

    Both matter, for different reasons. Membership is decided against every
    bound name, or a re-export would read as missing. But the repair prompt
    should name the classes the file actually declares — telling a model that
    `models.py` defines `Column, DateTime, Float, ForeignKey, Integer` invites
    it to reach for one of those instead of writing the schema that is absent.
    """
    names: set = set()
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                names |= _target_names(target)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            names |= _target_names(stmt.target)
        elif isinstance(stmt, (ast.If, ast.While)):
            names |= _own_definitions(stmt.body) | _own_definitions(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            names |= _own_definitions(stmt.body) | _own_definitions(stmt.orelse)
            for handler in stmt.handlers:
                names |= _own_definitions(handler.body)
    return names


def collect_modules(project: Path) -> tuple:
    """
    `({module path: frozenset(names)}, {open module paths}, {sources},
    {module path: frozenset(own definitions)})`.

    A package also "defines" its submodules, because `pkg.sub` is a legitimate
    read once `pkg.sub` has been imported anywhere.
    """
    modules: dict = {}
    own: dict = {}
    open_modules: set = set()
    sources: dict = {}   # module path -> (relative path, source, tree)

    for path in sorted(project.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(project)
        dotted = _module_path(rel)
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except Exception:
            # Unparseable: it may define anything, so nothing may be reported
            # about it. Something else already reports that it does not parse.
            open_modules.add(dotted)
            modules.setdefault(dotted, frozenset())
            own.setdefault(dotted, frozenset())
            continue
        modules[dotted] = frozenset(_bound_names(tree.body))
        own[dotted] = frozenset(_own_definitions(tree.body))
        sources[dotted] = (rel, source, tree)
        if _is_open(tree, source):
            open_modules.add(dotted)

    # Packages own their submodules.
    with_subs: dict = {}
    for dotted, names in modules.items():
        extra = {other.rsplit(".", 1)[-1] for other in modules
                 if other != dotted and other.startswith(dotted + ".")
                 and "." not in other[len(dotted) + 1:]}
        with_subs[dotted] = frozenset(names | extra)

    return with_subs, open_modules, sources, own


def _alias_index(modules: dict) -> tuple:
    """
    `({import spelling: module path}, {ambiguous spellings})`.

    A project is imported two ways here — `from . import models` inside the
    package, and a bare `import models` with the sys.path shim the debugger
    injects — so both spellings must resolve, and a spelling two files could
    both claim must resolve to neither.
    """
    index: dict = {}
    ambiguous: set = set()
    for dotted in modules:
        spellings = {dotted}
        parts = dotted.split(".")
        for i in range(1, len(parts)):
            spellings.add(".".join(parts[i:]))
        for spelling in spellings:
            if spelling == dotted and spelling in index and index[spelling] != dotted:
                ambiguous.add(spelling)
            elif spelling in index and index[spelling] != dotted:
                ambiguous.add(spelling)
            index[spelling] = dotted
    for spelling in ambiguous:
        index.pop(spelling, None)
    return index, ambiguous


# ── Reading the references ────────────────────────────────────────────────────

def _resolve_relative(node: ast.ImportFrom, package: str) -> str:
    """`from . import x` / `from ..pkg import y`, relative to the reading file."""
    parts = package.split(".") if package else []
    up = node.level - 1
    if up > len(parts):
        return ""
    base = parts[:len(parts) - up] if up else parts
    if node.module:
        base = base + node.module.split(".")
    return ".".join(base)


def _chain(node: ast.Attribute) -> tuple:
    """`a.b.c` -> `("a", ["b", "c"])`; anything else -> `("", [])`."""
    attrs = []
    cur = node
    while isinstance(cur, ast.Attribute):
        attrs.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return "", []
    return cur.id, list(reversed(attrs))


def _rebound_anywhere(tree: ast.Module, name: str) -> bool:
    """Is this local name assigned anywhere in the file after the import?

    If it is, the binding no longer certainly names the module, and reporting
    would be a guess.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if name in _target_names(target):
                    return True
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if name in _target_names(node.target):
                return True
        elif isinstance(node, ast.For):
            if name in _target_names(node.target):
                return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            every = (list(args.args) + list(args.posonlyargs)
                     + list(args.kwonlyargs))
            if any(a.arg == name for a in every):
                return True
    return False


def _import_time_lines(tree: ast.Module, defers_annotations: bool) -> set:
    """
    The line numbers of every expression Python evaluates while importing.

    Module-level code, decorators, base classes, default arguments — and
    parameter annotations too, unless the file opts into PEP 563 with
    `from __future__ import annotations`. This is the difference between "the
    application cannot start" and "this endpoint raises when called", and row 3
    is the first kind: its `models.SupplierCreate` sits in a signature in a file
    with no future import, so the module dies at import.
    """
    lines: set = set()

    def mark(node) -> None:
        for sub in ast.walk(node):
            line = getattr(sub, "lineno", None)
            if line:
                lines.add(line)

    def walk(body, at_module_level: bool) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in stmt.decorator_list:
                    mark(dec)
                args = stmt.args
                for default in list(args.defaults) + [d for d in args.kw_defaults if d]:
                    mark(default)
                if not defers_annotations:
                    every = (list(args.args) + list(args.posonlyargs)
                             + list(args.kwonlyargs)
                             + [a for a in (args.vararg, args.kwarg) if a])
                    for arg in every:
                        if arg.annotation is not None:
                            mark(arg.annotation)
                    if stmt.returns is not None:
                        mark(stmt.returns)
                # The body runs on call, not on import.
                continue
            if isinstance(stmt, ast.ClassDef):
                for dec in stmt.decorator_list:
                    mark(dec)
                for base in stmt.bases:
                    mark(base)
                for kw in stmt.keywords:
                    mark(kw.value)
                walk(stmt.body, at_module_level)
                continue
            if at_module_level:
                mark(stmt)
            if isinstance(stmt, (ast.If, ast.While, ast.For, ast.Try,
                                 ast.With, ast.AsyncWith)):
                for attr in ("body", "orelse", "finalbody"):
                    walk(getattr(stmt, attr, []) or [], at_module_level)
                for handler in getattr(stmt, "handlers", []) or []:
                    walk(handler.body, at_module_level)

    walk(tree.body, True)
    return lines


def check_project_module_refs(root: str) -> RefReport:
    """
    Every reference to a name a project module does not define.

    `root` is the project folder under OUTPUT_DIR — generated paths are
    OUTPUT_DIR-relative, and a bare open() silently reads nothing. Never raises.
    """
    report = RefReport()
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        if not project.is_dir():
            return report
    except Exception:
        return report

    try:
        modules, open_modules, sources, own = collect_modules(project)
    except Exception:
        return report
    if not modules:
        return report

    report.modules, report.open_modules = modules, open_modules
    report.files = {dotted: rel.as_posix() for dotted, (rel, _s, _t) in sources.items()}
    index, ambiguous = _alias_index(modules)
    report.ambiguous = ambiguous

    def resolve(spelling: str) -> str:
        """The project module an import spelling names, or "" when unknown."""
        target = index.get(spelling, "")
        if not target or target in open_modules:
            return ""
        return target

    for dotted, (rel, source, tree) in sources.items():
        try:
            issues = _check_file(tree, source, dotted, rel, modules, own,
                                 resolve)
        except Exception:
            continue
        report.issues.extend(issues)

    # The same missing name read in a create and an update handler is one
    # defect, and one repair.
    seen, unique = set(), []
    for issue in report.issues:
        key = (issue.file, issue.module, issue.name)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    report.issues = unique

    if report.issues:
        logger.info(
            f"🔗 Module reference check: {len(report.issues)} undefined "
            f"name(s) — "
            + "; ".join(f"{i.module}.{i.name}" for i in report.issues[:5])
        )
    return report


def _check_file(tree, source: str, dotted: str, rel: Path, modules: dict,
                own: dict, resolve) -> list:
    """Every undefined reference one file makes into another project module."""
    issues: list = []
    package = dotted.rsplit(".", 1)[0] if "." in dotted else ""
    defers = "from __future__ import annotations" in source
    in_test = _is_test_module(rel)
    hot = _import_time_lines(tree, defers)
    guarded_attr, guarded_import = _guarded_lines(tree)
    file_rel = str(rel).replace("\\", "/")

    def sample(target: str) -> tuple:
        declared = sorted(n for n in own.get(target, frozenset())
                          if not n.startswith("_"))
        if declared:
            return tuple(declared[:15])
        names = sorted(n for n in modules.get(target, frozenset())
                       if not n.startswith("_"))
        return tuple(names[:15])

    # `from X import name` — the harshest form: it fails at import, always.
    bindings: dict = {}          # local name -> project module path
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            spelling = (_resolve_relative(node, package) if node.level
                        else (node.module or ""))
            target = resolve(spelling)
            if not target:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if node.lineno in guarded_import:
                    continue
                if alias.name in modules.get(target, frozenset()):
                    # A name, or a submodule of a package: both are legitimate,
                    # and a submodule binding is itself a module.
                    sub = f"{target}.{alias.name}"
                    # A submodule binding is itself a module — but only bind it
                    # when it is one this check may speak about. Going through
                    # the package (`from . import open_mod`) reached it without
                    # ever consulting `resolve`, so a module doing
                    # `import *` was checked anyway.
                    if sub in modules and resolve(sub):
                        bindings[alias.asname or alias.name] = sub
                    continue
                issues.append(RefIssue(
                    file=file_rel, line=node.lineno, module=target,
                    name=alias.name, where="import", at_import_time=True,
                    in_test=in_test, defines=sample(target),
                ))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target = resolve(alias.name)
                if alias.asname:
                    if target:
                        bindings[alias.asname] = target
                elif "." not in alias.name and target:
                    bindings[alias.name] = target

    # `binding.name` — resolved through packages, so `backend.models.Supplier`
    # works when only `import backend` bound a name.
    for local, target in list(bindings.items()):
        if _rebound_anywhere(tree, local):
            del bindings[local]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        head, attrs = _chain(node)
        if not head or head not in bindings or not attrs:
            continue
        target = bindings[head]
        # Descend through submodules; the last hop is the name being read.
        while len(attrs) > 1 and f"{target}.{attrs[0]}" in modules:
            target = f"{target}.{attrs[0]}"
            attrs = attrs[1:]
        if len(attrs) != 1:
            continue
        name = attrs[0]
        if name.startswith("_") or name in _MODULE_API:
            continue
        if target in modules and f"{target}.{name}" in modules:
            continue          # a submodule not yet imported here; not our call
        if name in modules.get(target, frozenset()):
            continue
        if getattr(node, "lineno", 0) in guarded_attr:
            continue
        # The descent above can land on a module the index refuses to speak
        # about — an open one, or a spelling two files could both claim. Ask
        # again about wherever it actually ended up.
        if not resolve(target):
            continue
        issues.append(RefIssue(
            file=file_rel, line=getattr(node, "lineno", 0), module=target,
            name=name, where="attribute",
            at_import_time=getattr(node, "lineno", 0) in hot,
            in_test=in_test, defines=sample(target),
        ))

    return issues


def _repair_targets(root: str, report: RefReport) -> dict:
    """
    `{OUTPUT_DIR-relative file: [finding, ...]}` for the files that must GAIN a
    definition, or `{}` when there is nothing a repair could act on.

    Three exclusions, each deliberate:

    * **Test modules.** §4.26 settled that a broken suite is not a broken build,
      and these findings are routed to manual testing rather than counted; a
      repair target would drag them back into the build's verdict by the back
      door.
    * **Open modules.** A module doing `globals()`/`__getattr__` may already
      define the name in a way this check cannot see, so nothing may be asserted
      about it — and a repair would add a duplicate.
    * **Modules with no file of their own.** A package, or a spelling two files
      could claim: there is no single file to edit.
    """
    targets: dict = {}
    for issue in report.issues:
        if issue.in_test or issue.module in report.open_modules:
            continue
        rel = report.files.get(issue.module)
        if not rel:
            continue
        targets.setdefault(f"{root}/{rel}", []).append(str(issue))
    return targets


def check_module_refs(root: str) -> VerificationOutcome:
    """The same check as a VerificationOutcome, for the verification surface."""
    report = check_project_module_refs(root)

    checkable = [m for m in report.modules if m not in report.open_modules]
    if len(report.modules) < 2:
        return VerificationOutcome.not_applicable(
            "module_ref",
            detail=("this project has fewer than two python modules, so there "
                    "are no cross-module references to check"),
        )

    in_tests = sum(1 for i in report.issues if i.in_test)
    detail = (
        f"{len(checkable)} module(s) checked name-by-name "
        f"({len(report.open_modules)} skipped as open)"
    )
    if in_tests:
        detail += f"; {in_tests} of the finding(s) are in test modules"
    if not report.issues:
        return VerificationOutcome.verified("module_ref", detail=detail)

    outcome = VerificationOutcome.failed(
        "module_ref", [str(i) for i in report.issues], detail=detail,
        evidence={
            "undefined": [f"{i.module}.{i.name}" for i in report.issues],
            # The file each defect must be repaired IN, which is the module that
            # should DEFINE the name — not the one that reads it. Without this
            # the findings are advisory text: they reach the reader and the
            # remediation advisory, and nothing can act on them. Row 3
            # (2026-09-02) shipped 21 of 22 endpoints returning 500 with the
            # repair named in every one of its 23 findings; both LLM passes
            # rewrote the *referencing* file, because a 5xx traceback names the
            # caller and that was the only channel that produced a repair target.
            #
            # OUTPUT_DIR-relative, because that is what the debugger resolves
            # against; `report.files` is project-relative.
            "repair_targets": _repair_targets(root, report),
            # Findings the pipeline should hand to the user as manual testing
            # rather than count against the build, *if* something else has
            # executed the artifact and found it sound. A test module that
            # cannot import is a broken suite; §4.26 settled that this is not a
            # broken build. The same defect in the application is not routed.
            "manual_findings": [str(i) for i in report.issues if i.in_test],
        },
    )
    # Only the shipped application can be fatal. A test module that cannot
    # import is a broken suite, and §4.26 settled that a broken suite is not a
    # broken build — letting one set `unusable` here would reintroduce exactly
    # the verdict that decision removed.
    fatal = [i for i in report.issues if i.at_import_time and not i.in_test]
    if fatal:
        outcome.evidence["undefined_at_import"] = [
            f"{i.module}.{i.name}" for i in fatal]
        outcome.mark_fatal(
            f"{fatal[0].module}.{fatal[0].name} does not exist and is read "
            f"while {fatal[0].file} is imported, so the module cannot load"
        )
    return outcome
