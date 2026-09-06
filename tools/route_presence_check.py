"""
tools/route_presence_check.py — a web API that declares no route at all
=======================================================================

The symptom, checked directly, after two consecutive rows shipped it from
causes with nothing in common.

    e3894a9e  routers registered inside an `@app.on_event("startup")`
              that a supplied `lifespan=` disables            -> 0 routes
    9733027d  six `APIRouter()` objects declared and wired,
              and not one route handler anywhere              -> 0 routes

`tools/dead_event_check.py` was written from the first and is correct; it
stayed silent on the second, exactly as it should. That is the argument for
this module. Every check on this project has been written from the one row that
produced it, so each is narrow by construction — the repairs generalise across
architectures and the checks do not, because nothing generates the *next* cause.

A `web_api` build that declares no route serves nothing, whatever the reason.
That is decidable from the text, and it does not need to know why.

What row 4 actually shipped
---------------------------
`backend/routes.py`, in full, 23 lines:

    # Define placeholder routers for each resource
    suppliers_router = APIRouter()
    products_router  = APIRouter()
    ...
    router = APIRouter()
    router.include_router(suppliers_router, prefix="/suppliers", ...)

`assert_row`'s router assertions **passed** on this — six routers defined, six
included, every name bound — because they count definitions and includes and
never ask whether a handler exists. `feature_coverage` read
`verified, 6/6, "0 route(s)"`. Only `runtime_smoke` caught it, after the build.

Precision over recall, the same stance as the other static checks:

  * only when the project **is** a web API (`BuildShapes.is_web`). A library or
    CLI that imports fastapi for something else is not judged by this.
  * a route registered through `add_api_route` / `add_route` /
    `add_websocket_route` counts, even though this cannot resolve its path —
    the question is whether ANY route exists, and a call site is enough to say
    yes. Silence is the safe answer.
  * test modules never count toward the total and never make it fire.
  * a module that does not parse is skipped; something else reports that.

Deterministic and free: no LLM, no tokens.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from tools.build_shape import detect_shapes
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

#: Decorator attributes that declare a route: `@app.get(...)`,
#: `@router.post(...)`, `@router.api_route(...)`, `@app.websocket(...)`.
_ROUTE_DECORATORS = {
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
    "route", "api_route", "websocket",
}

#: Calls that register a route without a decorator. A project doing
#: `for path, fn in TABLE: app.add_api_route(path, fn)` declares routes this
#: module cannot enumerate — but it can see that it declares some, which is the
#: only question being asked.
_ROUTE_CALLS = {"add_api_route", "add_route", "add_websocket_route"}

#: Constructors whose presence says "this file meant to serve routes". Used to
#: name the repair target: the file holding a bare router is the file that must
#: gain the handlers.
_ROUTER_CTORS = {"APIRouter", "FastAPI"}


@dataclass
class RouteSite:
    """One place a route is declared."""
    file: str
    line: int
    how: str       # "@router.get" / "add_api_route"


@dataclass
class RoutePresenceReport:
    files: int = 0
    routes: list = field(default_factory=list)       # RouteSite, app modules only
    test_routes: int = 0                             # declared in test modules
    router_files: list = field(default_factory=list) # files constructing a router
    routers: dict = field(default_factory=dict)      # file -> [router variable, ...]
    skipped: list = field(default_factory=list)


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    return (any(p in ("tests", "test") for p in parts[:-1])
            or parts[-1].startswith("test_")
            or parts[-1].endswith("_test.py"))


def scan_source(source: str, rel: str = "") -> tuple[list, bool]:
    """`([RouteSite, ...], constructs_a_router)` for one module. Never raises."""
    sites, builds_router, _ = _scan(source, rel)
    return sites, builds_router


def router_names(source: str) -> list:
    """The names bound to `APIRouter()` in this text, in source order.

    Published so a repair can ask for handlers **one resource at a time**.
    A single call asking for every handler in a four-entity CRUD app cannot fit
    Groq's 8,000-token minute — the same wall `_repair_missing_definitions` hit,
    which is why that one appends in batches.
    """
    return _scan(source, "")[2]


def _scan(source: str, rel: str) -> tuple[list, bool, list]:
    try:
        tree = ast.parse(source)
    except Exception:
        return [], False, []

    sites: list = []
    builds_router = False
    routers: list = []

    # `name = APIRouter()` — the routers a repair would hang handlers on.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
            if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
                continue
            fn = value.func
            name = (fn.id if isinstance(fn, ast.Name)
                    else fn.attr if isinstance(fn, ast.Attribute) else "")
            if name == "APIRouter" and target.id not in routers:
                routers.append(target.id)

    for node in ast.walk(tree):
        # `@router.get("/x")` — a decorator, with or without arguments.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                inner = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(inner, ast.Attribute) and inner.attr in _ROUTE_DECORATORS:
                    sites.append(RouteSite(
                        file=rel, line=getattr(dec, "lineno", node.lineno),
                        how=f"@{getattr(inner.value, 'id', '?')}.{inner.attr}"))
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr in _ROUTE_CALLS:
                    sites.append(RouteSite(
                        file=rel, line=getattr(node, "lineno", 0),
                        how=func.attr))
            # `APIRouter()` / `FastAPI()` — not a route, but it says this file
            # intended to serve them.
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute) else "")
            if name in _ROUTER_CTORS:
                builds_router = True

    return sites, builds_router, routers


def count_routes(source: str) -> int:
    """How many routes this text declares. The debugger's landing check.

    A repair that rewrites the file and adds no handler has not fixed anything,
    and must not be recorded as a repair.
    """
    sites, _ = scan_source(source)
    return len(sites)


def check_project_routes(root: str) -> RoutePresenceReport:
    """Scan every python file under an OUTPUT_DIR-relative project root."""
    report = RoutePresenceReport()
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
        sites, builds_router, routers = _scan(source, rel)
        if _is_test(rel):
            # §4.26: a route declared in a test is not the application's route,
            # and a test module must never be able to make this check pass.
            report.test_routes += len(sites)
            continue
        report.routes.extend(sites)
        if builds_router:
            report.router_files.append(rel)
        if routers:
            report.routers[rel] = routers

    return report


def _repair_targets(root: str, report: RoutePresenceReport, finding: str) -> dict:
    """
    `{OUTPUT_DIR-relative file: [finding]}` — the file that must GAIN handlers.

    Handlers belong where the `APIRouter()` objects are, which is **not** where
    the app is assembled. Row 4 had `backend/main.py` building the `FastAPI()`
    and `backend/routes.py` holding six bare `APIRouter()`s; picking the
    shallowest path chose `main.py` and would have written CRUD handlers into
    the wrong file. So a file with bare routers wins, and the one with the most
    of them wins among those.

    Falling back to `router_files` covers the app-only shape — a project whose
    `FastAPI()` has no handlers and no separate router module. When nothing
    builds a router at all there is no file to edit and nothing is published:
    the finding still stands, and still fails the build.
    """
    if report.routers:
        where = sorted(report.routers,
                       key=lambda f: (-len(report.routers[f]), f.count("/"), f))[0]
    elif report.router_files:
        where = sorted(report.router_files, key=lambda p: (p.count("/"), p))[0]
    else:
        return {}
    return {f"{root}/{where}": [finding]}


def check_route_presence(root: str) -> VerificationOutcome:
    """The same check as a VerificationOutcome, for the verification surface."""
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        if not project.is_dir():
            return VerificationOutcome.not_applicable(
                "route_presence", detail="the project directory does not exist")
        shapes = detect_shapes(project, rel_to=base)
    except Exception as e:
        return VerificationOutcome.not_run(
            "route_presence", detail=f"cannot read the project: {e}")

    if not shapes.is_web:
        return VerificationOutcome.not_applicable(
            "route_presence",
            detail=("this project is not a web API, so it is not expected to "
                    "declare routes"),
        )

    report = check_project_routes(root)
    detail = (f"{len(report.routes)} route(s) declared across "
              f"{report.files} python file(s)")

    if report.routes:
        return VerificationOutcome.verified("route_presence", detail=detail,
                                            shape=shapes.describe())

    # Zero routes, and the project IS a web API. It serves nothing.
    where = (f" `{report.router_files[0]}` builds a router and declares nothing "
             f"on it." if report.router_files else "")
    extra = (f" ({report.test_routes} route(s) are declared in test modules, "
             f"which are not the application's.)" if report.test_routes else "")
    finding = (
        f"the application declares no routes at all, so it serves nothing and "
        f"every requested endpoint is missing.{where} Add the "
        f"`@router.get/post/put/delete` handlers.{extra}"
    )

    outcome = VerificationOutcome.failed(
        "route_presence", [finding], detail=detail, shape=shapes.describe(),
        evidence={
            "routes": 0,
            "routes_in_tests": report.test_routes,
            "router_files": list(report.router_files),
            # `{file: [router variable, ...]}` — what a repair hangs handlers
            # on, one resource per call. Asking for a four-entity CRUD app's
            # handlers in one reply cannot fit Groq's 8,000-token minute.
            "routers": {f: r for f, r in report.routers.items() if r},
            # OUTPUT_DIR-relative, because that is what the debugger resolves
            # against.
            "repair_targets": _repair_targets(root, report, finding),
        },
    )
    outcome.mark_fatal(
        "the application declares no routes, so it answers 404 to every path "
        "it advertises"
    )
    return outcome
