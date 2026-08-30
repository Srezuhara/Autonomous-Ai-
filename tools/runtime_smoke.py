"""
tools/runtime_smoke.py — Phase 22
==================================
Boot the generated FastAPI app in a subprocess and actually call its routes.

WHY
---
Every gate before this one answers a weaker question than the user's:

  import check  → "does `python routes.py` exit 0?"   (module-level code only)
  debug score   → same question, retried
  static audit  → "does anything LOOK wrong on disk?"  (never executes)

None of them answer "does the app respond?". The todo_app build scored debug
3/3 while every endpoint was either an empty stub or a guaranteed 500 — the
phantom `from weather import get_weather` sat inside a handler body, so it only
raised when a request arrived, which nothing ever did.

This module sends the requests. It costs zero LLM tokens and is the first check
in the pipeline whose failure means "the shipped app does not work".

The probe runs in a subprocess because importing a generated app executes
arbitrary generated code, which can hang, exit, or corrupt the parent process.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)

SMOKE_TIMEOUT = 120

# Entry points to try, in order of likelihood.
_ENTRY_CANDIDATES = ("main.py", "app.py", "api.py", "server.py")


def _parse_frames(error: str) -> list:
    """
    The project files named in a probe error, in call order.

    Parsed from the `(at a.py:1 in f -> b.py:2 in g)` suffix the probe writes.
    Empty when the failure produced no traceback at all — a 500 the app
    returned deliberately, for instance.
    """
    match = re.search(r"\(at ([^)]+)\)\s*$", error or "")
    if not match:
        return []
    out = []
    for part in match.group(1).split("->"):
        frame = re.match(r"\s*(\S+\.py):(\d+) in (\S+)\s*$", part)
        if frame:
            out.append({
                "file": frame.group(1),
                "line": int(frame.group(2)),
                "function": frame.group(3),
            })
    return out


@dataclass
class RouteProbe:
    path:   str
    method: str
    status: int | None = None
    error:  str = ""
    constraint: bool = False

    @property
    def ok(self) -> bool:
        # A route that answers at all is working: 4xx is a valid answer to an
        # unauthenticated / unparameterised probe. 5xx is the app breaking.
        #
        # The exception is a 5xx raised by a database constraint rejecting the
        # synthetic body the probe invented (a supplier_id that does not exist,
        # a name already taken). That says nothing about the handler, and
        # blaming it would spend a repair call on correct code.
        if self.constraint:
            return True
        return self.status is not None and self.status < 500

    @property
    def frames(self) -> list:
        """The project files in this probe's traceback, in call order."""
        return _parse_frames(self.error)

    @property
    def blame_file(self) -> str:
        """
        The file a repair should be aimed at: the outermost project frame.

        That is the handler the router called. When a handler hands a helper
        the wrong thing, the exception surfaces in the helper — repairing there
        would harden the helper against bad input instead of fixing the caller.
        """
        frames = self.frames
        return frames[0]["file"] if frames else ""


@dataclass
class SmokeResult:
    ran:        bool = False
    app_loaded: bool = False
    probes:     list[RouteProbe] = field(default_factory=list)
    error:      str = ""
    entry:      str = ""

    @property
    def failures(self) -> list[RouteProbe]:
        return [p for p in self.probes if not p.ok]

    @property
    def total(self) -> int:
        return len(self.probes)

    @property
    def passed(self) -> int:
        return sum(1 for p in self.probes if p.ok)

    @property
    def blame_file(self) -> str:
        """
        The generated file to repair when the app never loaded.

        The *innermost* project frame — the opposite of RouteProbe.blame_file,
        and deliberately so. A 500 means the caller handed a helper something
        wrong, so the caller is at fault. A failed import means main.py did
        nothing but `from routes import router`; the module that raised is the
        one to repair — a bad response_model on a route decorator, say, which
        fails at import time and takes every endpoint with it.
        """
        frames = _parse_frames(self.error)
        return frames[-1]["file"] if frames else ""

    def summary(self) -> str:
        if not self.ran:
            return f"smoke test did not run ({self.error or 'no entry point'})"
        if not self.app_loaded:
            return f"app failed to load: {self.error}"
        if not self.probes:
            return "app loaded but declares no routes"
        return f"{self.passed}/{self.total} routes responded without a server error"


# The probe script runs INSIDE the generated project. Keep it dependency-free
# beyond fastapi itself, and never let it raise out of main().
_PROBE_SRC = r'''
import json, sys, os, warnings
warnings.filterwarnings("ignore")

result = {"app_loaded": False, "probes": [], "error": ""}

def emit():
    sys.stdout.write("<<<SMOKE_JSON>>>" + json.dumps(result))
    sys.stdout.flush()

try:
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (here, os.path.dirname(here)):
        if p not in sys.path:
            sys.path.insert(0, p)

    project_root = os.path.dirname(here)

    def describe(exc):
        """
        Type, message, and every frame inside the generated project.

        The chain matters, not just its end. A handler that passes the wrong
        object to a helper blows up *in the helper*, so recording only the last
        frame sent the repair to the file that raised rather than the file that
        was wrong — and a "fix" there means teaching the helper to accept bad
        input. The caller is the first project frame; both are reported, in
        call order, so the repair can be aimed and given its context.
        """
        import traceback
        label = "{}: {}".format(type(exc).__name__, str(exc)[:200])
        try:
            frames = traceback.extract_tb(exc.__traceback__)
            chain = []
            for fr in frames:
                if fr.filename.startswith("<"):
                    continue        # <frozen importlib._bootstrap>, <string>, ...
                fn = os.path.abspath(fr.filename)
                if not fn.startswith(project_root) or "site-packages" in fn:
                    continue
                # This probe is written into the project directory, so it is a
                # "project frame" too — and it is always the outermost one.
                # Leaving it in makes it the blamed file for every failure.
                if os.path.basename(fn) == "_smoke_probe.py":
                    continue
                rel = os.path.relpath(fn, project_root).replace("\\", "/")
                chain.append("{}:{} in {}".format(rel, fr.lineno, fr.name))
            if chain:
                return "{} (at {})".format(label, " -> ".join(chain[-4:]))
        except Exception:
            pass
        return label

    import importlib
    module = importlib.import_module("__ENTRY_MODULE__")
    app = getattr(module, "app", None)
    if app is None:
        result["error"] = "module defines no `app` object"
        emit(); raise SystemExit(0)

    from fastapi.testclient import TestClient
    result["app_loaded"] = True

    # Enumerate declared routes, skipping FastAPI's own docs endpoints.
    SKIP = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
    routes = []
    for r in getattr(app, "routes", []):
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if not path or not methods or path in SKIP:
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            routes.append((path, m, r))

    # ---- Synthesised request bodies -------------------------------------
    # Sending `json={}` makes every POST/PUT fail validation and return 422,
    # which `RouteProbe.ok` counts as a pass -- so the handler body never runs
    # and a write path is scored green without executing a single line of it.
    # Row 3 on 2026-08-30 shipped `16/16` while every POST /suppliers/ raised
    # AttributeError, because routes.py read `sup.contact` and schemas.py
    # declared `contact_email`. Build a minimal body that satisfies the route's
    # own request model so the handler actually executes.
    #
    # Precision over recall (as in tools/sql_schema_check): when a field cannot
    # be synthesised confidently we fall back to `{}` and accept the old 422
    # rather than invent a value that could fail validation for our reasons.
    import datetime as _dt, enum as _enum, typing as _t, uuid as _uuid

    def _example_value(ann, depth=0):
        if ann is None or depth > 3:
            return None
        try:
            origin = _t.get_origin(ann)
            args = _t.get_args(ann)
        except Exception:
            origin, args = None, ()
        if origin is not None:
            is_union = origin is _t.Union
            if not is_union:
                try:
                    import types as _types
                    is_union = origin is getattr(_types, "UnionType", None)
                except Exception:
                    pass
            if is_union:
                for a in args:
                    if a is type(None):
                        continue
                    return _example_value(a, depth + 1)
                return None
            if origin in (list, set, tuple, frozenset):
                return []
            if origin is dict:
                return {}
        try:
            if isinstance(ann, type):
                if issubclass(ann, _enum.Enum):
                    vals = list(ann)
                    return vals[0].value if vals else None
                # bool before int, datetime before date: each is a subclass of
                # the next and would otherwise be answered by the wrong branch.
                if issubclass(ann, bool):
                    return True
                if issubclass(ann, int):
                    return 1
                if issubclass(ann, float):
                    return 1.0
                if issubclass(ann, _dt.datetime):
                    return "2024-01-01T00:00:00"
                if issubclass(ann, _dt.date):
                    return "2024-01-01"
                if issubclass(ann, _uuid.UUID):
                    return "00000000-0000-0000-0000-000000000000"
                if issubclass(ann, (str, bytes)):
                    return "test"
                if getattr(ann, "model_fields", None) is not None:
                    return _example_model(ann, depth + 1)
                if getattr(ann, "__fields__", None) is not None:
                    return _example_model(ann, depth + 1)
        except Exception:
            return None
        return None

    def _example_model(model, depth=0):
        """Required fields only -- the smallest body the model will accept."""
        out = {}
        mf = getattr(model, "model_fields", None)
        if mf is not None:                                   # pydantic v2
            for name, f in mf.items():
                try:
                    if not f.is_required():
                        continue
                except Exception:
                    continue
                v = _example_value(getattr(f, "annotation", None), depth)
                if v is None:
                    return None
                out[getattr(f, "alias", None) or name] = v
            return out
        for name, f in (getattr(model, "__fields__", None) or {}).items():
            if not getattr(f, "required", False):
                continue
            ann = getattr(f, "outer_type_", None) or getattr(f, "type_", None)
            v = _example_value(ann, depth)
            if v is None:
                return None
            out[getattr(f, "alias", None) or name] = v
        return out

    def _synth_body(route):
        bf = getattr(route, "body_field", None)
        if bf is None:
            return {}
        ann = getattr(bf, "type_", None)
        if ann is None:
            ann = getattr(getattr(bf, "field_info", None), "annotation", None)
        v = _example_value(ann, 0)
        return v if isinstance(v, (dict, list)) else {}

    def _is_constraint(text):
        """
        A database constraint rejecting OUR invented row is not a code defect.

        The body above is synthetic: supplier_id=1 need not exist, and "test"
        may already be taken. Blaming the handler for that would spend an LLM
        call editing correct code -- the false positive sql_schema_check was
        built to avoid.
        """
        t = (text or "").lower()
        return any(s in t for s in (
            "integrityerror", "unique constraint", "foreign key constraint",
            "not null constraint", "check constraint", "duplicate key",
            "unique failed", "foreign key failed",
        ))

    # raise_server_exceptions=True so the real exception reaches us. A bare
    # "500 Internal Server Error" tells the user nothing they can act on; the
    # AttributeError and the generated line that raised it tell them exactly
    # what to fix.
    #
    # The `with` is load-bearing. Starlette runs lifespan/startup ONLY when the
    # TestClient is entered as a context manager. Without it, a correct app that
    # creates its tables in an asynccontextmanager lifespan -- which is exactly
    # what prompts/backend_developer.txt tells the generator to write -- is
    # probed against a database with no tables, and every data route answers
    # "no such table". Twelve of row 3's nineteen, twice, blamed on generated
    # code that was right. Worse, the debugger then "fixed" it by creating
    # tables at module import, the one pattern the prompt forbids.
    client_cm = TestClient(app, raise_server_exceptions=True)
    try:
        client = client_cm.__enter__()
        lifespan_ran = True
    except BaseException as e:
        # Startup itself failed. That is a real defect and the app is genuinely
        # broken, but it must be reported as one error rather than as N route
        # failures that all say the same thing.
        result["error"] = "lifespan/startup failed: " + describe(e)
        client = TestClient(app, raise_server_exceptions=True)
        lifespan_ran = False

    for path, method, route_obj in routes[:25]:
        # Fill path params with a benign value so the URL is requestable.
        concrete = path
        while "{" in concrete and "}" in concrete:
            start = concrete.index("{")
            end = concrete.index("}", start)
            name = concrete[start + 1:end]
            filler = "1" if ("id" in name.lower() or "num" in name.lower()) else "test"
            concrete = concrete[:start] + filler + concrete[end + 1:]

        entry = {"path": path, "method": method, "status": None, "error": "",
                 "constraint": False}
        try:
            fn = getattr(client, method.lower(), None)
            if fn is None:
                continue
            if method in ("GET", "DELETE"):
                resp = fn(concrete)
            else:
                try:
                    body = _synth_body(route_obj)
                except Exception:
                    body = {}
                resp = fn(concrete, json=body)
            entry["status"] = resp.status_code
            if resp.status_code >= 500:
                try:
                    entry["error"] = resp.text[:300]
                except Exception:
                    pass
                entry["constraint"] = _is_constraint(entry["error"])
        except Exception as e:
            # An unhandled exception in a handler IS a 500 — record it as one,
            # with the detail the HTTP response would have thrown away.
            entry["status"] = 500
            entry["error"] = describe(e)
            entry["constraint"] = _is_constraint(entry["error"])
        result["probes"].append(entry)

    # Shutdown, so anything the lifespan opened is closed before we report.
    if lifespan_ran:
        try:
            client_cm.__exit__(None, None, None)
        except BaseException:
            pass

except SystemExit:
    raise
except BaseException as e:
    try:
        result["error"] = describe(e)
    except BaseException:
        result["error"] = "{}: {}".format(type(e).__name__, str(e)[:400])

emit()
'''


def _find_entry(project_dir: Path) -> Path | None:
    """Locate the module that defines the FastAPI `app`."""
    search_dirs = [project_dir / "backend", project_dir, project_dir / "src"]
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for name in _ENTRY_CANDIDATES:
            candidate = directory / name
            if not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "FastAPI(" in text:
                return candidate
    return None


def smoke_test_app(root: str, timeout: int = SMOKE_TIMEOUT) -> SmokeResult:
    """
    Boot the generated app and probe every declared route.

    `root` is the project folder name under OUTPUT_DIR. Never raises.
    """
    result = SmokeResult()

    try:
        project_dir = (Path(config.OUTPUT_DIR) / root).resolve()
    except Exception as e:
        result.error = f"cannot resolve project dir: {e}"
        return result

    if not project_dir.is_dir():
        result.error = "project directory does not exist"
        return result

    entry = _find_entry(project_dir)
    if entry is None:
        result.error = "no FastAPI entry point found"
        return result

    result.entry = str(entry.relative_to(project_dir)).replace("\\", "/")

    probe_src  = _PROBE_SRC.replace("__ENTRY_MODULE__", entry.stem)
    probe_path = entry.parent / "_smoke_probe.py"

    try:
        probe_path.write_text(probe_src, encoding="utf-8")
    except Exception as e:
        result.error = f"could not write probe: {e}"
        return result

    try:
        proc = subprocess.run(
            [sys.executable, str(probe_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(entry.parent),
        )
        result.ran = True
        raw = proc.stdout or ""
        marker = "<<<SMOKE_JSON>>>"
        if marker in raw:
            payload = json.loads(raw.split(marker, 1)[1])
            result.app_loaded = payload.get("app_loaded", False)
            result.error      = payload.get("error", "")
            for p in payload.get("probes", []):
                result.probes.append(RouteProbe(
                    path=p.get("path", ""), method=p.get("method", ""),
                    status=p.get("status"), error=p.get("error", ""),
                    constraint=bool(p.get("constraint", False)),
                ))
        else:
            err = (proc.stderr or "").strip()
            result.error = err[-400:] if err else "probe produced no output"
    except subprocess.TimeoutExpired:
        result.ran   = True
        result.error = f"probe timed out after {timeout}s"
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    finally:
        try:
            probe_path.unlink()
        except Exception:
            pass

    return result
