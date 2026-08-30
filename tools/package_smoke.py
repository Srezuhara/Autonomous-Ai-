"""
tools/package_smoke.py — can anyone actually import this library?
=================================================================

A project with no web app and no command line is a library: the product is the
public API, and the only way to know it works is to import it and look.

The pipeline's import check (`tools/code_executor.run_python`) does import each
file, one at a time, with the file's own directory on `sys.path`. That is not
the same thing as a user importing the package:

  * a user writes `import mytool`, which runs `mytool/__init__.py` and every
    re-export in it. The per-file check imports `mytool/helpers.py` directly and
    may never execute `__init__.py` at all;
  * `__init__.py` is where `from .helpers import Thing` lives, so a name that
    was renamed, moved or never written shows up there and nowhere else;
  * `__all__` is a promise about the public API. A name listed there that does
    not exist is a broken import for anyone following the README.

This became worth having when the architect stopped being forced to bolt a
FastAPI app onto every request: a library request now produces a library, and
before this nothing would ever have run it as one.

Precision over recall, as everywhere else in verification: a name that cannot be
resolved for a reason we are not sure about is skipped rather than blamed.

Deterministic apart from the subprocess; no LLM, no tokens.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import config
from tools.build_shape import detect_shapes
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

IMPORT_TIMEOUT = 60

# Run the import in a child process: a generated package can execute anything at
# import time, and it must not be able to corrupt the builder's own interpreter.
_PROBE = r'''
import importlib, json, sys, traceback

result = {"imported": False, "error": "", "exported": [], "missing": []}
try:
    module = importlib.import_module("__PACKAGE__")
    result["imported"] = True

    names = list(getattr(module, "__all__", []) or [])
    for name in names:
        if hasattr(module, name):
            result["exported"].append(name)
        else:
            result["missing"].append(name)

    if not names:
        # No __all__: report the public names it does expose, so the caller can
        # say whether the package is empty.
        result["exported"] = [
            n for n in dir(module) if not n.startswith("_")
        ][:50]
except BaseException as e:
    tb = traceback.format_exc(limit=6)
    result["error"] = "{}: {}".format(type(e).__name__, str(e)[:300])
    result["traceback"] = tb[-800:]

sys.stdout.write("<<<PKG_JSON>>>" + json.dumps(result))
'''


def _package_dirs(project_dir: Path) -> list[Path]:
    """Importable package directories, outermost first."""
    out = []
    for init in sorted(project_dir.rglob("__init__.py")):
        if any(p in {"__pycache__", "node_modules", "venv", ".venv", "tests"}
               for p in init.parts):
            continue
        pkg = init.parent
        # Only top-level packages: a subpackage is imported by its parent.
        if (pkg.parent / "__init__.py").is_file():
            continue
        out.append(pkg)
    return out


def _declared_all(init_path: Path) -> list[str]:
    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                try:
                    value = ast.literal_eval(node.value)
                    return [str(v) for v in value]
                except Exception:
                    return []
    return []


def smoke_test_package(root: str) -> VerificationOutcome:
    """Import every top-level package this project defines. Never raises."""
    try:
        project_dir = (Path(config.OUTPUT_DIR) / root).resolve()
    except Exception as e:
        return VerificationOutcome.not_run(
            "package_smoke", detail=f"cannot resolve project dir: {e}"
        )
    if not project_dir.is_dir():
        return VerificationOutcome.not_run(
            "package_smoke", detail="project directory does not exist"
        )

    shapes = detect_shapes(project_dir, rel_to=Path(config.OUTPUT_DIR))
    # A web app or a CLI has its own verifier that exercises far more than an
    # import. This is for the project whose product IS the importable API.
    if shapes.is_web or shapes.is_cli:
        return VerificationOutcome.not_applicable(
            "package_smoke", shape=shapes.describe(),
            detail="this project is run, not imported; its own verifier covers it",
        )

    packages = _package_dirs(project_dir)
    if not packages:
        return VerificationOutcome.not_applicable(
            "package_smoke", shape=shapes.describe(),
            detail="this project defines no importable package",
        )

    findings: list[str] = []
    evidence: dict = {"packages": []}

    for pkg in packages:
        record = _import_one(pkg, findings)
        evidence["packages"].append(record)

    detail = "imported " + ", ".join(p["package"] for p in evidence["packages"])
    if findings:
        return VerificationOutcome.failed(
            "package_smoke", findings, shape="package",
            detail=detail, evidence=evidence,
        )
    return VerificationOutcome.verified(
        "package_smoke", shape="package", detail=detail, evidence=evidence
    )


def _import_one(pkg: Path, findings: list[str]) -> dict:
    name = pkg.name
    record: dict = {"package": name, "imported": False, "exported": 0}

    probe = _PROBE.replace("__PACKAGE__", name)
    fd, probe_path = tempfile.mkstemp(suffix="_pkg_probe.py", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(probe)

        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        root_dir = str(pkg.parent)
        env["PYTHONPATH"] = (
            f"{root_dir}{os.pathsep}{existing}" if existing else root_dir
        )

        proc = subprocess.run(
            [sys.executable, probe_path],
            capture_output=True, text=True, timeout=IMPORT_TIMEOUT,
            cwd=root_dir, env=env,
        )
        raw = proc.stdout or ""
        marker = "<<<PKG_JSON>>>"
        if marker not in raw:
            findings.append(
                f"the package `{name}` could not be imported: "
                f"{(proc.stderr or 'the probe produced no output').strip()[-300:]}"
            )
            return record

        payload = json.loads(raw.split(marker, 1)[1])
        record["imported"] = bool(payload.get("imported"))
        record["exported"] = len(payload.get("exported", []))

        if not payload.get("imported"):
            findings.append(
                f"`import {name}` fails: {payload.get('error', 'unknown error')}"
            )
            return record

        missing = payload.get("missing", [])
        if missing:
            findings.append(
                f"`{name}.__all__` promises {', '.join(missing[:6])}, which the "
                f"package does not define — anyone following the README gets an "
                f"ImportError"
            )

        declared = _declared_all(pkg / "__init__.py")
        if not declared and record["exported"] == 0:
            findings.append(
                f"the package `{name}` imports but exposes no public names at "
                f"all, so there is no API to use"
            )
    except subprocess.TimeoutExpired:
        findings.append(
            f"importing the package `{name}` timed out after {IMPORT_TIMEOUT}s"
        )
    except Exception as e:
        # The probe itself failing is not evidence about the package.
        logger.warning(f"package_smoke probe error for {name}: {e}")
    finally:
        try:
            os.unlink(probe_path)
        except Exception:
            pass

    return record
