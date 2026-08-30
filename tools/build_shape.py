"""
tools/build_shape.py — what kind of thing did we just build?
============================================================

One detector, so every verifier agrees on what the project is.

Before this, four different parts of the pipeline sniffed the filesystem with
four different, independently-wrong rules:

  * `runtime_smoke._find_entry`  — three named directories, and a file had to
    contain the literal substring `"FastAPI("`.
  * `frontend_debugger`          — required `frontend/package.json`.
  * `tester._setup_vitest`       — required `frontend/package.json` AND
                                   `frontend/src/`.
  * `pipeline._audit_placeholders` — a suffix tuple that omits `.html`, `.css`
                                   and `.js` entirely.

Matrix row 4 is what that costs. The architect put a FastAPI app in
`bulk_file_renamer/main.py`; `_find_entry` looked in `backend/`, `src/` and the
project root, found nothing, and the pipeline logged "Runtime smoke test skipped
(no FastAPI entry point)". A web app shipped unprobed, and the log line was
later read as evidence that the non-web path worked correctly.

Why not use `intent["app_type"]`
--------------------------------
Because it is not load-bearing and never has been. It is free text from the LLM
(`prompts/intent_analyzer.txt` offers `web_app | dashboard | api | cli_tool |
bot`), never validated or normalised, and a repo-wide search finds it used only
for display: a summary table, a database column, some API echoes. Not one line
of generation or verification branches on it. The same is true of
`intent["frontend"]`, `["backend"]` and `["database"]`. Keying verification off
a field nothing else respects would make the checks as unreliable as the field.

What is on disk is the truth, so this reads what is on disk.

Deterministic and free — no LLM, no tokens.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

# Directories that never contain the thing we are looking for.
_SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", "venv", ".venv", "env",
    "dist", "build", ".pytest_cache", ".mypy_cache", "migrations",
    "alembic", "versions",
}

# Frameworks whose app object a runtime probe knows how to drive.
# The value is the constructor call that identifies it in source.
_WEB_FRAMEWORKS = {
    "fastapi": "FastAPI(",
    "flask":   "Flask(",
}

# A module-level name a web entry point conventionally binds its app to.
_APP_NAMES = ("app", "application", "api", "server")

# Factories that build the app instead of binding it at module level. The old
# probe required a module-level `app` and reported "module defines no `app`
# object" — a boot failure — for the perfectly ordinary factory pattern.
_APP_FACTORIES = ("create_app", "make_app", "get_app", "build_app")

_CLI_LIBRARIES = ("argparse", "click", "typer", "optparse")


def _iter_py(project_dir: Path):
    for path in sorted(project_dir.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.name.startswith("test_") or path.parent.name == "tests":
            continue
        yield path


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


@dataclass
class WebEntry:
    """A module that builds a web application."""
    path:       str          # OUTPUT_DIR-relative, forward slashes
    framework:  str          # "fastapi" | "flask"
    app_name:   str = ""     # module-level binding, if there is one
    factory:    str = ""     # factory function, if there is one instead

    @property
    def is_importable_app(self) -> bool:
        return bool(self.app_name or self.factory)


@dataclass
class CliEntry:
    """A module a person is meant to run."""
    path:       str
    library:    str          # "argparse" | "click" | ...
    has_main_guard: bool = False
    main_func:  str = ""


@dataclass
class BuildShapes:
    """
    Everything this project is. A build is commonly several at once — matrix
    row 2 is a web API *and* a static frontend — so these are not exclusive.
    """
    web_entries:      list[WebEntry] = field(default_factory=list)
    cli_entries:      list[CliEntry] = field(default_factory=list)
    html_files:       list[str] = field(default_factory=list)
    package_roots:    list[str] = field(default_factory=list)
    has_node_frontend: bool = False
    py_file_count:    int = 0

    @property
    def is_web(self) -> bool:
        return bool(self.web_entries)

    @property
    def is_cli(self) -> bool:
        return bool(self.cli_entries)

    @property
    def is_static_frontend(self) -> bool:
        return bool(self.html_files)

    @property
    def is_package(self) -> bool:
        """A library: importable, with no way to run it."""
        return bool(self.package_roots) and not self.is_web and not self.is_cli

    @property
    def primary_web_entry(self) -> WebEntry | None:
        """
        The entry a probe should drive.

        Prefer one that binds an app at module level over a bare factory, and a
        shallower path over a deeper one — a project with both `backend/main.py`
        and a helper that also constructs an app should be probed at the former.
        """
        if not self.web_entries:
            return None
        return sorted(
            self.web_entries,
            key=lambda e: (0 if e.app_name else 1, e.path.count("/"), e.path),
        )[0]

    def names(self) -> list[str]:
        out = []
        if self.is_web:
            out.append("web_api")
        if self.is_cli:
            out.append("cli")
        if self.is_static_frontend:
            out.append("static_frontend")
        if self.has_node_frontend:
            out.append("node_frontend")
        if self.is_package:
            out.append("package")
        return out or ["unknown"]

    def describe(self) -> str:
        return "+".join(self.names())


def _analyse_python(path: Path, text: str) -> tuple[WebEntry | None, CliEntry | None]:
    framework = ""
    for name, marker in _WEB_FRAMEWORKS.items():
        if marker in text:
            framework = name
            break

    cli_lib = ""
    for lib in _CLI_LIBRARIES:
        if re.search(rf"^\s*(?:import|from)\s+{lib}\b", text, re.MULTILINE):
            cli_lib = lib
            break

    if not framework and not cli_lib:
        return None, None

    app_name, factory, main_func = "", "", ""
    has_main_guard = "__main__" in text

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        # A broken file is exactly the case we still want detected: reporting
        # "no entry point" for a file that fails to parse would hide the defect
        # behind a skip. Fall back to patterns.
        if framework:
            m = re.search(
                r"^\s*(\w+)\s*=\s*\w*\(?\s*" + re.escape(_WEB_FRAMEWORKS[framework]),
                text, re.MULTILINE,
            )
            app_name = m.group(1) if m else ""
            if not app_name:
                for cand in _APP_NAMES:
                    if re.search(rf"^\s*{cand}\s*=", text, re.MULTILINE):
                        app_name = cand
                        break
        if cli_lib and re.search(r"^\s*def\s+main\b", text, re.MULTILINE):
            main_func = "main"
        return (
            WebEntry("", framework, app_name) if framework else None,
            CliEntry("", cli_lib, has_main_guard, main_func) if cli_lib else None,
        )

    marker = _WEB_FRAMEWORKS.get(framework, "")
    ctor = marker.rstrip("(")

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if framework and not app_name and _calls(node.value, ctor):
                    app_name = target.id
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _APP_FACTORIES and framework and not factory:
                # Only a factory that really constructs the app; a helper that
                # happens to share the name is not an entry point.
                if any(_calls(n, ctor) for n in ast.walk(node)):
                    factory = node.name
            if node.name == "main" and cli_lib:
                main_func = node.name

    web = WebEntry("", framework, app_name, factory) if framework else None
    cli = CliEntry("", cli_lib, has_main_guard, main_func) if cli_lib else None
    return web, cli


def _calls(node, ctor_name: str) -> bool:
    """True when `node` is a call to `ctor_name`, bare or dotted."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == ctor_name
    if isinstance(func, ast.Attribute):
        return func.attr == ctor_name
    return False


def detect_shapes(project_dir: str | Path, rel_to: str | Path | None = None) -> BuildShapes:
    """
    Inspect a generated project and report every shape it contains.

    `rel_to` controls how paths are spelled in the result; pass
    `config.OUTPUT_DIR` to get the OUTPUT_DIR-relative form the pipeline uses
    everywhere else (`proj_ab12/backend/main.py`). See the two-path convention:
    a bare `open()` on one of these resolves against cwd and finds nothing.
    """
    project_dir = Path(project_dir)
    base = Path(rel_to) if rel_to is not None else project_dir.parent
    # Resolve both or `relative_to` fails whenever one side is absolute and the
    # other is not, and every path silently falls back to an absolute string.
    # Generated-file paths are OUTPUT_DIR-relative by convention; an absolute one
    # handed to `tools.file_writer` resolves against OUTPUT_DIR a second time and
    # finds nothing.
    try:
        project_dir = project_dir.resolve()
        base = base.resolve()
    except Exception:
        pass
    shapes = BuildShapes()
    if not project_dir.is_dir():
        return shapes

    def rel(path: Path) -> str:
        try:
            return str(path.relative_to(base)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    for path in _iter_py(project_dir):
        shapes.py_file_count += 1
        text = _read(path)
        if not text.strip():
            continue
        web, cli = _analyse_python(path, text)
        if web is not None:
            web.path = rel(path)
            shapes.web_entries.append(web)
        if cli is not None and (cli.has_main_guard or cli.main_func):
            # An `import argparse` with no way to invoke it is a helper, not a
            # command-line tool. Requiring one of the two keeps `models.py` from
            # being probed as a CLI.
            cli.path = rel(path)
            shapes.cli_entries.append(cli)

    for path in sorted(project_dir.rglob("*.html")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        shapes.html_files.append(rel(path))

    for path in sorted(project_dir.rglob("package.json")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        shapes.has_node_frontend = True
        break

    for path in sorted(project_dir.rglob("__init__.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if _read(path).strip():
            shapes.package_roots.append(rel(path.parent))

    return shapes
