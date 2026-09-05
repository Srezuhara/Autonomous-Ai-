"""
tools/dead_event_check.py — a startup handler the framework never calls
=======================================================================

The defect that killed matrix row 3's third run (`e3894a9e`, `unusable`), and
that every other static check passed.

`backend/main.py` was generated like this:

    app = FastAPI(lifespan=lifespan)

    @app.on_event("startup")
    def include_routers():
        from routers import product
        app.include_router(product.router)

**Starlette ignores `on_event` when a `lifespan` is supplied.** The two are
alternative spellings of the same hook, not layers of it: the router takes the
lifespan context manager and drops `on_startup`/`on_shutdown` on the floor. So
`include_routers` never runs, no route is ever registered, and the application
answers 404 to every path it advertises.

Verified against the pinned versions rather than argued from the docs
(fastapi 0.136.1 / starlette 1.6.0): the app above serves `/ping` as **404**,
and `app.routes` is empty after the test client's startup completes.

Why no existing check saw it
----------------------------
Every static check passed this build:

    feature_coverage   verified, 6/6, "5 route(s)"   <- against zero live routes
    module_ref         verified
    schema_attr        verified
    sql_schema         not_applicable (correct: SQLAlchemy)
    debug_score 8/8, review_score 7.0, test_score 10/12

They all read the source, and in the source the routes are there. Only
`runtime_smoke` — the one check that EXECUTES the artifact — could say "the app
boots and declares 0 routes", and by then the build was finished. This module
moves that fact to where it can be repaired: before a token is spent, from the
text alone.

It is the fourth instance of the pattern §0.-9 named. The finding says "0
routes"; the file that must change is `main.py`; nothing connected the two.
`main.py` *was* repaired during that build — for an unrelated import error — and
the repair left the dead handler alone, because nothing told it.

Precision over recall, the same stance as the other static checks: a false
positive spends an LLM call editing correct code and tells a user their working
build is broken. Only what can be settled with certainty is reported —

  * the module must actually import FastAPI (a hand-rolled class with the same
    spelling is somebody else's object);
  * the app name must be bound exactly ONCE in the module, so the name the
    decorator uses is provably the object the lifespan was passed to;
  * `lifespan=None` is skipped — it is not a lifespan, and the framework then
    honours `on_event` normally. Measured, not assumed: `FastAPI(lifespan=None)`
    with an `on_event("startup")` serves its route 200.
  * a module whose source does not parse is skipped (something else reports it).

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

#: The two events the framework drops when a lifespan is supplied. `on_event`
#: accepts nothing else, but the string is read off the call rather than assumed
#: so that a finding names what the source actually said.
_EVENTS = ("startup", "shutdown")

#: Calls that wire routes onto an app. Only changes how the finding reads — a
#: dead `on_event` is a defect either way — but "no route is ever registered"
#: is the difference between a degraded build and an `unusable` one, and the
#: reader should not have to open the file to learn which.
_WIRING = {"include_router", "add_api_route", "mount", "add_route",
           "get", "post", "put", "patch", "delete"}


@dataclass
class DeadEvent:
    """One `@app.on_event(...)` that the supplied lifespan makes unreachable."""
    file: str                 # project-relative, posix separators
    line: int                 # the on_event decorator
    app: str                  # the name bound to the FastAPI(...) call
    event: str                # "startup" / "shutdown", as written
    handler: str              # the decorated function's name
    lifespan_line: int        # where the app was built
    registers_routes: bool    # does the body wire routes onto the app?
    in_test: bool = False

    def __str__(self) -> str:
        tail = (", so no route is ever registered and the app serves nothing"
                if self.registers_routes else ", so it never runs")
        return (
            "`{app}.on_event({q}{event}{q})` at line {line} is dead code: "
            "`{app}` was built with `FastAPI(lifespan=...)` at line {ls}, and "
            "the framework ignores event handlers when a lifespan is supplied "
            "— `{handler}` never runs{tail}. Move its body into the lifespan "
            "function, before the `yield`.".format(
                app=self.app, q='"', event=self.event, line=self.line,
                ls=self.lifespan_line, handler=self.handler, tail=tail)
        )


@dataclass
class DeadEventReport:
    files: int = 0
    apps: int = 0                       # FastAPI(lifespan=...) constructions seen
    issues: list = field(default_factory=list)
    skipped: list = field(default_factory=list)   # (file, why)


# ── Reading one module ────────────────────────────────────────────────────────

def _imports_fastapi(tree: ast.AST) -> bool:
    """Does this module import fastapi, under either spelling?

    Without this, a project defining its own `FastAPI` — or writing
    `from x import FastAPI` — would be judged against the framework's rules.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "fastapi":
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "fastapi":
                    return True
    return False


def _is_fastapi_call(node: ast.AST) -> bool:
    """`FastAPI(...)` or `fastapi.FastAPI(...)`, and nothing else."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "FastAPI"
    if isinstance(func, ast.Attribute):
        return func.attr == "FastAPI"
    return False


def _live_lifespan(call: ast.Call) -> bool:
    """Was a real lifespan passed?

    `lifespan=None` is not one. The framework only replaces the event handlers
    when the argument is truthy, so the literal `None` is the documented way to
    say "no lifespan" and `on_event` keeps working — confirmed live, 200 not
    404. A name bound to `None` elsewhere would read as live here; that is the
    recall this module gives up to keep its false-positive rate at zero.
    """
    for kw in call.keywords:
        if kw.arg != "lifespan":
            continue
        if isinstance(kw.value, ast.Constant) and kw.value.value is None:
            return False
        return True
    return False


def _binding_counts(tree: ast.AST) -> dict:
    """How many times each bare name is bound anywhere in the module.

    A name bound once is a name the decorator provably refers to. A name bound
    twice may be the FastAPI app at one line and something else at the next, and
    this module will not guess which — see the module docstring.
    """
    counts: dict = {}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    def bump_target(target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            bump(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                bump_target(elt)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bump_target(target)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            bump_target(node.target)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bump(node.name)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bump_target(node.target)
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None:
                bump_target(node.optional_vars)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bump((alias.asname or alias.name).split(".")[0])
    return counts


def _lifespan_apps(tree: ast.AST) -> dict:
    """`{name: line}` for every `name = FastAPI(..., lifespan=<not None>)`."""
    apps: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not _is_fastapi_call(node.value) or not _live_lifespan(node.value):
            continue
        apps[target.id] = getattr(node, "lineno", 0)
    return apps


def _registers_routes(fn: ast.AST) -> bool:
    """Does this handler's body wire routes onto the app?"""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _WIRING:
                return True
        # `@app.get("/x")` written inside the handler is wiring too, and that is
        # a decorator rather than a Call this walk would otherwise credit.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                inner = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(inner, ast.Attribute) and inner.attr in _WIRING:
                    return True
    return False


def _event_name(dec: ast.Call) -> str:
    """The event string as written, or "" when it is not a literal."""
    if dec.args and isinstance(dec.args[0], ast.Constant):
        value = dec.args[0].value
        if isinstance(value, str):
            return value
    for kw in dec.keywords:
        if kw.arg == "event_type" and isinstance(kw.value, ast.Constant):
            if isinstance(kw.value.value, str):
                return kw.value.value
    return ""


def scan_source(source: str, rel: str = "", in_test: bool = False) -> list:
    """Every dead `on_event` in one module's text. Never raises."""
    try:
        tree = ast.parse(source)
    except Exception:
        return []       # something else already reports a file that will not parse

    if not _imports_fastapi(tree):
        return []

    apps = _lifespan_apps(tree)
    if not apps:
        return []

    counts = _binding_counts(tree)
    issues: list = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and func.attr == "on_event"):
                continue
            if not isinstance(func.value, ast.Name):
                continue
            name = func.value.id
            if name not in apps:
                continue
            # Bound more than once: the object this decorator runs against is
            # not provably the one the lifespan was given to.
            if counts.get(name, 0) != 1:
                continue
            event = _event_name(dec)
            if event and event not in _EVENTS:
                continue
            issues.append(DeadEvent(
                file=rel,
                line=getattr(dec, "lineno", getattr(node, "lineno", 0)),
                app=name,
                event=event or "startup",
                handler=node.name,
                lifespan_line=apps[name],
                registers_routes=_registers_routes(node),
                in_test=in_test,
            ))
    return issues


def count_lifespan_apps(source: str) -> int:
    """How many apps this source builds with a real lifespan. -1 if it will not parse.

    The dead-event repair's second guard. There are two ways to make this check
    fall silent without fixing anything, and deleting the handler is only the
    first — the other is to delete the `lifespan=` argument, after which
    `on_event` works again and the check correctly reports `not_applicable`.
    That reply looks repaired and is not: whatever the lifespan was doing —
    `create_all`, opening a pool — now sits in a function nothing calls. Caught
    on a clone of `e3894a9e` on 2026-09-05, where it left an app that registered
    its routes and never created its tables.
    """
    try:
        tree = ast.parse(source)
    except Exception:
        return -1
    return len(_lifespan_apps(tree))


def has_dead_events(source: str) -> bool:
    """Is the defect still present in this text?

    The debugger's landing check: a repair that rewrites the file but leaves the
    handler dead has not fixed anything, and must not be recorded as a repair.
    """
    return bool(scan_source(source))


# ── Reading a project ─────────────────────────────────────────────────────────

def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    return (any(p in ("tests", "test") for p in parts[:-1])
            or parts[-1].startswith("test_")
            or parts[-1].endswith("_test.py"))


def check_project_dead_events(root: str) -> DeadEventReport:
    """Scan every python file under an OUTPUT_DIR-relative project root."""
    report = DeadEventReport()
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        if not project.is_dir():
            return report
        paths = [p for p in sorted(project.rglob("*.py"))
                 if "__pycache__" not in p.parts]
    except Exception:
        return report

    for path in paths:
        rel = str(path.relative_to(project)).replace("\\", "/")
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            report.skipped.append((rel, f"unreadable: {e}"))
            continue
        report.files += 1
        try:
            tree = ast.parse(source)
        except Exception:
            report.skipped.append((rel, "does not parse"))
            continue
        if _imports_fastapi(tree):
            report.apps += len(_lifespan_apps(tree))
        report.issues.extend(scan_source(source, rel, in_test=_is_test(rel)))

    if report.issues:
        logger.info(
            "🪦 Dead event check: {n} unreachable handler(s) — {where}".format(
                n=len(report.issues),
                where="; ".join(f"{i.file}:{i.line}" for i in report.issues[:5]))
        )
    return report


def _repair_targets(root: str, report: DeadEventReport) -> dict:
    """
    `{OUTPUT_DIR-relative file: [finding, ...]}` — the file that BUILDS the app,
    which is always the file the handler is written in.

    Test modules are excluded for the reason §4.26 settled and `module_ref`
    already follows: a dead handler in a test is a broken test, and those
    findings are routed to manual testing rather than counted against the build.
    A repair target would drag them back into the verdict by the back door.
    """
    targets: dict = {}
    for issue in report.issues:
        if issue.in_test:
            continue
        targets.setdefault(f"{root}/{issue.file}", []).append(str(issue))
    return targets


def check_dead_events(root: str) -> VerificationOutcome:
    """The same check as a VerificationOutcome, for the verification surface."""
    report = check_project_dead_events(root)

    if not report.apps:
        return VerificationOutcome.not_applicable(
            "dead_events",
            detail=("this project builds no FastAPI app with a lifespan, so "
                    "there is no handler here that a lifespan could disable"),
        )

    detail = (f"{report.apps} app(s) built with a lifespan, "
              f"across {report.files} python file(s)")
    if not report.issues:
        return VerificationOutcome.verified("dead_events", detail=detail)

    in_tests = sum(1 for i in report.issues if i.in_test)
    if in_tests:
        detail += f"; {in_tests} of the finding(s) are in test modules"

    outcome = VerificationOutcome.failed(
        "dead_events", [str(i) for i in report.issues], detail=detail,
        evidence={
            "dead_handlers": [f"{i.file}:{i.line} {i.app}.on_event({i.event})"
                              for i in report.issues],
            # The file that must change. It is the same file the handler is
            # written in, which makes this the cheapest of the four instances of
            # the pattern to target — and it was still missed, because nothing
            # published it. OUTPUT_DIR-relative, because that is what the
            # debugger resolves against.
            "repair_targets": _repair_targets(root, report),
            # §4.26: a broken suite is not a broken build.
            "manual_findings": [str(i) for i in report.issues if i.in_test],
        },
    )

    # A handler that wires routes and never runs leaves an app that answers 404
    # to every path it advertises. That is `unusable`, and row 3 shipped exactly
    # that with three good scores and four verified checks on it.
    fatal = [i for i in report.issues if i.registers_routes and not i.in_test]
    if fatal:
        outcome.evidence["routes_never_registered"] = [
            f"{i.file}:{i.line}" for i in fatal]
        outcome.mark_fatal(
            f"{fatal[0].handler} registers the application's routes and the "
            f"supplied lifespan means it never runs, so the app serves nothing"
        )
    return outcome
