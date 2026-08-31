"""
tools/cli_smoke.py — actually run the command-line tool
=======================================================

Nothing in this pipeline has ever executed a generated CLI.

The import check (`tools/code_executor.run_python`) imports the module, which
runs module-level code and stops there — everything under
`if __name__ == "__main__":` is by definition not executed by an import. The
runtime smoke test only understands web apps. The tester generates unit tests
for functions, not an invocation of the tool. So for matrix row 4 — a bulk file
renamer — the entire verification surface was "the files import", and the build
shipped `done_with_context` with a valid ZIP.

This runs the thing. Two probes, in order of what they prove:

  1. `--help`, which must exit 0. An argparse parser that cannot even build its
     own help text is broken beyond argument handling: a bad `type=`, a
     duplicate flag, a required argument on a subparser that does not exist.
  2. A real invocation in a throwaway directory, when the parser tells us enough
     to construct one safely.

Precision over recall, as in `tools/sql_schema_check.py`: a false positive here
spends an LLM repair call on correct code. When the tool wants arguments this
module cannot invent, it reports what it verified and stops — it does not guess
and then blame the tool for rejecting the guess.

Safety: the probe runs with `cwd` set to a fresh temporary directory, never the
project. A renamer that walks its working directory finds an empty sandbox
rather than the generated project, and a tool that writes files writes them
where they will be thrown away.

Deterministic apart from the subprocess itself; no LLM, no tokens.
"""

from __future__ import annotations

import logging
import re
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import config
from tools.build_shape import CliEntry, detect_shapes
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

# A `--help` that takes this long is itself a defect and still fails the check.
# The budget is nevertheless generous, because a *tight* one changes what the
# failure says: `ai_report_generator_c60361c0` really fails with
# `ImportError: cannot import name 'run_streamlit_ui'`, but its module-level
# `import streamlit` costs ~36s cold on Windows, so a 30s budget reported
# "timed out after 30s" and buried the actual diagnosis. Same verdict, useless
# reason. Overridable so a slow machine does not have to edit source.
CLI_TIMEOUT = int(os.getenv("CLI_SMOKE_TIMEOUT", "90"))

# Flags that must never be passed to a generated tool during verification: they
# ask it to do the destructive thing on purpose.
_DANGEROUS = re.compile(
    r"--(force|yes|no-confirm|overwrite|delete|purge|recursive|hard)\b", re.I
)


def _run(argv: list[str], import_root: Path, sandbox: Path) -> tuple[int, str, str]:
    """
    Run the tool from inside `sandbox`, resolving imports against `import_root`.

    Those must be two different directories. The tool has to run somewhere
    disposable — a bulk renamer that walks its working directory should find an
    empty temp dir, not the generated project — but `-m package.module` and a
    flat script's sibling imports both need the project on the path. So cwd is
    the sandbox and the import root goes on PYTHONPATH.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{import_root}{os.pathsep}{existing}" if existing else str(import_root)
    )
    try:
        proc = subprocess.run(
            argv,
            capture_output=True, text=True, timeout=CLI_TIMEOUT,
            cwd=str(sandbox), env=env,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {CLI_TIMEOUT}s"
    except Exception as e:
        return -1, "", f"{type(e).__name__}: {e}"


def _module_argv(entry_abs: Path, project_dir: Path) -> tuple[list[str], Path]:
    """
    How to invoke this file, and from where.

    A module inside a package is run with `-m package.module`, because that is
    how its relative imports resolve and how a user would run it. A flat script
    is run by path.
    """
    parts = [entry_abs.stem]
    directory = entry_abs.parent
    while (directory / "__init__.py").is_file() and directory.parent != directory:
        parts.insert(0, directory.name)
        directory = directory.parent

    if len(parts) > 1:
        return [sys.executable, "-m", ".".join(parts)], directory
    # An absolute path, because the process runs from the sandbox.
    return [sys.executable, str(entry_abs)], directory


def _parse_help(text: str) -> tuple[list[str], list[str]]:
    """
    (required positionals, subcommands) as argparse's help prints them.

    Read from the usage line rather than by importing the module, because the
    module may not import cleanly and this must still work when it does not.
    """
    positionals: list[str] = []
    subcommands: list[str] = []

    usage = ""
    m = re.search(r"(?is)^usage:\s*(.+?)(?:\n\s*\n|\Z)", text)
    if m:
        usage = " ".join(m.group(1).split())

    if usage:
        # Drop the program name, then keep bare words: `{a,b,c}` is a subcommand
        # choice, `[x]` is optional, `-x`/`--x` is a flag, `WORD` is required.
        for token in usage.split()[1:]:
            if token.startswith("{") and token.endswith("}"):
                subcommands.extend(t for t in token.strip("{}").split(",") if t)
            elif token.startswith(("-", "[")):
                continue
            elif re.fullmatch(r"[A-Za-z_][\w-]*", token):
                positionals.append(token)

    if not subcommands:
        block = re.search(
            r"(?is)\n\s*(?:positional arguments|commands|subcommands):\s*\n(.+?)"
            r"(?:\n\s*\n|\Z)", text
        )
        if block:
            inner = re.search(r"\{([^}]+)\}", block.group(1))
            if inner:
                subcommands.extend(t for t in inner.group(1).split(",") if t)

    return positionals, subcommands


def smoke_test_cli(root: str, timeout: int = CLI_TIMEOUT) -> VerificationOutcome:
    """
    Run every CLI entry point this project declares. Never raises.

    `root` is the project folder name under OUTPUT_DIR.
    """
    global CLI_TIMEOUT
    CLI_TIMEOUT = timeout

    try:
        project_dir = (Path(config.OUTPUT_DIR) / root).resolve()
    except Exception as e:
        return VerificationOutcome.not_run(
            "cli_smoke", detail=f"cannot resolve project dir: {e}"
        )
    if not project_dir.is_dir():
        return VerificationOutcome.not_run(
            "cli_smoke", detail="project directory does not exist"
        )

    shapes = detect_shapes(project_dir, rel_to=Path(config.OUTPUT_DIR))
    if not shapes.cli_entries:
        return VerificationOutcome.not_applicable(
            "cli_smoke", shape=shapes.describe(),
            detail="this project declares no command-line entry point",
        )

    findings: list[str] = []
    evidence: dict = {"entries": []}
    checked = 0

    for entry in shapes.cli_entries:
        entry_abs = (Path(config.OUTPUT_DIR) / entry.path).resolve()
        if not entry_abs.is_file():
            continue
        checked += 1
        record = _probe_one(entry, entry_abs, project_dir, findings)
        evidence["entries"].append(record)

    if not checked:
        return VerificationOutcome.not_run(
            "cli_smoke", shape=shapes.describe(),
            detail="CLI entry points were declared but none could be read",
        )

    detail = f"ran {checked} CLI entry point(s): " + ", ".join(
        e["path"] for e in evidence["entries"]
    )
    if findings:
        outcome = VerificationOutcome.failed(
            "cli_smoke", findings, shape="cli", detail=detail, evidence=evidence
        )
        # A tool whose --help does not work is not a tool with a problem; it is
        # a tool nobody can run. Say so in a field rather than leaving the
        # terminal status to recognise the wording.
        for record in evidence["entries"]:
            if record.get("fatal"):
                outcome.mark_fatal(record["fatal"])
        return outcome
    return VerificationOutcome.verified(
        "cli_smoke", shape="cli", detail=detail, evidence=evidence
    )


def _probe_one(
    entry: CliEntry, entry_abs: Path, project_dir: Path, findings: list[str]
) -> dict:
    argv, run_dir = _module_argv(entry_abs, project_dir)
    # Every key present from the start: a caller reading `record["positionals"]`
    # should not have to know which early return it came back from.
    record: dict = {
        "path": entry.path, "library": entry.library,
        "help_exit": None, "bare_exit": None,
        "subcommands": [], "positionals": [], "ok": False, "note": "",
    }

    sandbox = Path(tempfile.mkdtemp(prefix="cli_smoke_"))
    try:
        # ── 1. --help ─────────────────────────────────────────────────────────
        code, out, err = _run(argv + ["--help"], run_dir, sandbox)
        record["help_exit"] = code
        combined = (out + err).strip()

        if code != 0:
            findings.append(
                f"the command-line tool {entry.path} fails on `--help` "
                f"(exit {code}): {(err or out).strip()[:300]}"
            )
            record["ok"] = False
            record["fatal"] = f"{entry.path} fails on --help"
            return record

        if not combined:
            findings.append(
                f"the command-line tool {entry.path} prints nothing for "
                f"`--help`, so it offers the user no way to discover its usage"
            )
            record["ok"] = False
            record["fatal"] = f"{entry.path} prints nothing for --help"
            return record

        # ── 2. a real invocation, when we can build one safely ────────────────
        positionals, subcommands = _parse_help(combined)
        record["subcommands"] = subcommands
        record["positionals"] = positionals

        if subcommands:
            # Each subcommand must at least be able to describe itself.
            for sub in subcommands[:4]:
                sub_code, sub_out, sub_err = _run(
                    argv + [sub, "--help"], run_dir, sandbox
                )
                if sub_code != 0:
                    findings.append(
                        f"`{entry.path} {sub} --help` fails (exit {sub_code}): "
                        f"{(sub_err or sub_out).strip()[:200]}"
                    )
            record["ok"] = True
            return record

        if positionals:
            # Required arguments we cannot invent. Running with none should be a
            # clean usage error (argparse exits 2), never a traceback — a tool
            # that crashes instead of explaining itself is a defect.
            code2, out2, err2 = _run(argv, run_dir, sandbox)
            record["bare_exit"] = code2
            if "Traceback (most recent call last)" in err2:
                findings.append(
                    f"the command-line tool {entry.path} raises an unhandled "
                    f"exception when run without arguments instead of printing "
                    f"usage: {err2.strip()[-300:]}"
                )
                record["ok"] = False
                return record
            record["ok"] = True
            record["note"] = (
                f"requires {', '.join(positionals)}; verified --help and the "
                f"no-argument path only"
            )
            return record

        # No required arguments and no subcommands: it should just run.
        if _DANGEROUS.search(combined):
            record["ok"] = True
            record["note"] = "destructive flags present; ran --help only"
            return record

        code3, out3, err3 = _run(argv, run_dir, sandbox)
        record["bare_exit"] = code3
        if code3 != 0:
            findings.append(
                f"the command-line tool {entry.path} takes no required "
                f"arguments but exits {code3} when run: "
                f"{(err3 or out3).strip()[-300:]}"
            )
            record["ok"] = False
            return record

        record["ok"] = True
        return record
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
