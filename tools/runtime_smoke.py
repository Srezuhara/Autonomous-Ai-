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

    @property
    def ok(self) -> bool:
        # A route that answers at all is working: 4xx is a valid answer to an
        # unauthenticated / unparameterised probe. 5xx is the app breaking.
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
            routes.append((path, m))

    # raise_server_exceptions=True so the real exception reaches us. A bare
    # "500 Internal Server Error" tells the user nothing they can act on; the
    # AttributeError and the generated line that raised it tell them exactly
    # what to fix.
    client = TestClient(app, raise_server_exceptions=True)

    for path, method in routes[:25]:
        # Fill path params with a benign value so the URL is requestable.
        concrete = path
        while "{" in concrete and "}" in concrete:
            start = concrete.index("{")
            end = concrete.index("}", start)
            name = concrete[start + 1:end]
            filler = "1" if ("id" in name.lower() or "num" in name.lower()) else "test"
            concrete = concrete[:start] + filler + concrete[end + 1:]

        entry = {"path": path, "method": method, "status": None, "error": ""}
        try:
            fn = getattr(client, method.lower(), None)
            if fn is None:
                continue
            resp = fn(concrete) if method in ("GET", "DELETE") else fn(concrete, json={})
            entry["status"] = resp.status_code
            if resp.status_code >= 500:
                try:
                    entry["error"] = resp.text[:300]
                except Exception:
                    pass
        except Exception as e:
            # An unhandled exception in a handler IS a 500 — record it as one,
            # with the detail the HTTP response would have thrown away.
            entry["status"] = 500
            entry["error"] = describe(e)
        result["probes"].append(entry)

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
