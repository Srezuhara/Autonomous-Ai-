"""
Run the test suite the build ships (Phase 23, §4.24).

Row 2 shipped `tests/test_api.py` in which every test errored at fixture setup —
`reset_db()` did `conn = init_db(); conn.close()` and `init_db()` returns None —
while the build was legitimately recorded `verified: yes`. Nothing in the
six-check record executed the tests, so a suite that could not collect looked
exactly like one that passed. That is the same defect this whole phase keeps
finding: a signal that existed and nobody read.

Two things this check is deliberately NOT:

  * It is not a judgement on coverage. A project that ships no tests is
    NOT_APPLICABLE, not a failure — the architect decides that, and pretending
    otherwise would fail most of the corpus for a thing nobody asked for.
  * It is not a second runtime probe. `runtime_smoke` already answers "does the
    app serve". This answers the narrower question the shipped artifact makes on
    its own behalf: the repo contains tests, so do they run?

Runs in a throwaway copy. Generated tests write files — row 2's suite creates a
SQLite database in the working directory — and they must never do that inside
the project we are about to hand the user.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import config
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

# Generous: a suite that spins up a TestClient pays the FastAPI import cost, and
# a tight budget turns a real diagnosis into "timed out", which is the mistake
# `cli_smoke` made with its 30s (see §4.23).
TEST_TIMEOUT = int(os.getenv("GENERATED_TESTS_TIMEOUT", "180"))

_SKIP_DIRS = {
    ".git", "venv", ".venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", "build", "dist", ".mypy_cache",
}

# pytest's own exit codes, which say more than the boolean the shell sees.
_EXIT_OK = 0
_EXIT_TESTS_FAILED = 1
_EXIT_INTERRUPTED = 2
_EXIT_INTERNAL = 3
_EXIT_USAGE = 4
_EXIT_NO_TESTS = 5


def _find_test_files(project_dir: Path) -> list[Path]:
    """Every file pytest would collect, in a stable order."""
    found: list[Path] = []
    for path in project_dir.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        name = path.name
        if name.startswith("test_") or name.endswith("_test.py"):
            found.append(path)
    return sorted(found)


def _summarise(stdout: str, stderr: str) -> list[str]:
    """
    The lines a person would actually want, out of a wall of pytest output.

    Prefers the short-summary block, which names the failing test and the
    reason on one line each; falls back to error headers when the run died
    during collection and never reached a summary.
    """
    text = stdout or ""
    findings: list[str] = []

    # `-q` prints "short test summary info" with one FAILED/ERROR line per test.
    tail = text.split("short test summary info")[-1] if "short test summary info" in text else ""
    for line in tail.splitlines():
        line = line.strip()
        if line.startswith(("FAILED", "ERROR")):
            findings.append(line[:300])

    if not findings:
        # A collection error never reaches the summary block. The exception line
        # is the diagnosis, and it is the one thing worth carrying out.
        for line in (text + "\n" + (stderr or "")).splitlines():
            line = line.strip()
            if re.match(r"^E\s+\w*(Error|Exception)\b", line) or line.startswith(
                ("ImportError", "ModuleNotFoundError", "SyntaxError",
                 "AttributeError", "IndentationError")
            ):
                cleaned = re.sub(r"^E\s+", "", line)
                if cleaned not in findings:
                    findings.append(cleaned[:300])

    return findings[:8]


def _counts(stdout: str) -> dict:
    """passed/failed/error/skipped, from pytest's final tally line."""
    out = {}
    for word in ("passed", "failed", "error", "errors", "skipped"):
        m = re.search(rf"(\d+)\s+{word}\b", stdout or "")
        if m:
            key = "error" if word == "errors" else word
            out[key] = out.get(key, 0) + int(m.group(1))
    return out


def run_generated_tests(root: str, timeout: int = None) -> VerificationOutcome:
    """
    Execute the project's own test suite in a sandbox. Never raises.

    `root` is the project folder name under OUTPUT_DIR.
    """
    timeout = TEST_TIMEOUT if timeout is None else timeout

    try:
        project_dir = (Path(config.OUTPUT_DIR) / root).resolve()
    except Exception as e:
        return VerificationOutcome.not_run(
            "generated_tests", detail=f"cannot resolve project dir: {e}"
        )
    if not project_dir.is_dir():
        return VerificationOutcome.not_run(
            "generated_tests", detail="project directory does not exist"
        )

    test_files = _find_test_files(project_dir)
    if not test_files:
        return VerificationOutcome.not_applicable(
            "generated_tests", detail="this project ships no test files",
        )

    rel = [str(p.relative_to(project_dir)).replace("\\", "/") for p in test_files]

    try:
        import pytest  # noqa: F401
    except Exception:
        return VerificationOutcome.not_run(
            "generated_tests",
            detail="pytest is not importable in this interpreter, so the "
                   f"{len(rel)} shipped test file(s) could not be executed",
        )

    sandbox = None
    try:
        sandbox = Path(tempfile.mkdtemp(prefix="gentests_"))
        work = sandbox / project_dir.name
        shutil.copytree(
            project_dir, work,
            ignore=shutil.ignore_patterns(*_SKIP_DIRS),
        )

        env = dict(os.environ)
        # Mirror how the debugger imports a generated project: the root and its
        # backend package must both be importable, because generated tests
        # write `from backend.main import app` and `from main import app` about
        # equally often.
        parts = [str(work), str(work / "backend"), str(work / "src")]
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join([p for p in parts if p] + ([existing] if existing else []))
        # A generated suite that reads DATABASE_URL should get a throwaway one
        # rather than inheriting whatever the platform is pointed at.
        env.setdefault("DATABASE_URL", ":memory:")

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *rel, "-q", "--no-header",
             "-p", "no:cacheprovider"],
            cwd=str(work), env=env, capture_output=True, text=True,
            timeout=timeout,
        )
        code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""

    except subprocess.TimeoutExpired:
        return VerificationOutcome.failed(
            "generated_tests",
            findings=[
                f"the project's own test suite ({len(rel)} file(s)) did not "
                f"finish within {timeout}s — a shipped suite that hangs is a "
                f"suite the user cannot run"
            ],
            detail=f"timed out after {timeout}s",
        )
    except Exception as e:
        return VerificationOutcome.not_run(
            "generated_tests",
            detail=f"the check itself raised {type(e).__name__}: {e}",
        )
    finally:
        if sandbox is not None:
            shutil.rmtree(sandbox, ignore_errors=True)

    tally = _counts(out)
    shown = ", ".join(f"{v} {k}" for k, v in sorted(tally.items())) or "no tally reported"

    if code == _EXIT_OK:
        return VerificationOutcome.verified(
            "generated_tests",
            detail=f"ran the project's own suite: {len(rel)} file(s), {shown}",
            evidence={"files": rel, "counts": tally},
        )

    if code == _EXIT_NO_TESTS:
        return VerificationOutcome.failed(
            "generated_tests",
            findings=[
                f"the project ships {len(rel)} test file(s) but pytest collected "
                f"0 tests from them — the suite is inert"
            ],
            detail="pytest exit 5 (no tests collected)",
            evidence={"files": rel},
        )

    if code in (_EXIT_USAGE, _EXIT_INTERNAL):
        return VerificationOutcome.not_run(
            "generated_tests",
            detail=f"pytest could not run (exit {code}): "
                   f"{(err or out).strip()[-300:]}",
            evidence={"files": rel},
        )

    findings = _summarise(out, err)
    if not findings:
        findings = [
            f"the project's own test suite exits {code} and reports {shown}"
        ]

    # An error is worse than a failure: a failing assertion means the suite ran
    # and disagreed with the code, while an error usually means it never got as
    # far as running at all.
    errored = tally.get("error", 0)
    lead = (
        f"the project's own test suite does not run: {errored} of its tests "
        f"error before executing"
        if errored else
        f"the project's own test suite fails: {shown}"
    )

    return VerificationOutcome.failed(
        "generated_tests",
        findings=[lead] + findings,
        detail=f"pytest exit {code}, {shown}",
        evidence={"files": rel, "counts": tally},
    )
