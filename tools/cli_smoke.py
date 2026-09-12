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

# Positional names that want a path. Anything else gets a plain word.
_PATHISH = re.compile(
    r"(dir|directory|path|folder|src|source|dest|destination|target|input"
    r"|output|file|glob|root|base|location)", re.I
)

# What a HELP LINE has to say for its argument to be a path. Deliberately
# narrower than the name vocabulary above: an argument's description mentions
# "file" constantly ("Regular expression to match file names") and handing a
# directory to a regex argument reaches less code, not more.
_PATH_HELP = re.compile(r"\b(directory|directories|folder|folders|path|paths)\b",
                        re.I)

# The word handed to every non-path positional, and the sample files seeded
# for it to match. They share a stem on purpose: a tool given the pattern
# `sample` must find something to work on, because a run that matches nothing
# executes none of the code the probe is trying to reach. Row 4 on 2026-09-10
# crashed in the body of `for old, new in _iter_files(...)`, which an empty
# match set never enters.
_SAFE_WORD = "sample"
_SEED_FILES = ("sample_one.txt", "sample_two.txt", "sample_three.log")


def _seed_dir(sandbox: Path) -> Path:
    """A directory of throwaway files, made once, for path positionals.

    It is a SUBDIRECTORY of the sandbox rather than the sandbox itself, so the
    older probes -- which run the tool with no arguments in `cwd` -- still find
    the empty working directory they were written against.
    """
    data = sandbox / "sample_data"
    if not data.is_dir():
        data.mkdir(parents=True, exist_ok=True)
        for name in _SEED_FILES:
            (data / name).write_text("sample\n", encoding="utf-8")
    return data


def _value_for(name: str, flag: str = "", sandbox: Path = None,
               slot: int = 0, help_text: str = "") -> str:
    """A path for a path-shaped name, otherwise a word that varies by slot.

    Varying matters. The first word is `sample`, which the seeded files are
    named after so a pattern argument matches something; later ones differ
    from it so that a `pattern`/`replacement` pair describes a real change.
    Passing the same word twice made `bulk_file_renamer_fd473b61` rename each
    file to its own name -- which succeeds, hiding the second, failing rename
    that is its actual defect.
    """
    if (_PATHISH.search(name) or _PATHISH.search(flag or "")
            or _PATH_HELP.search(help_text or "")):
        return str(_seed_dir(sandbox)) if sandbox is not None else "."
    # A metavar like `SEARCH=REPLACE` or `old:new` states the format the tool
    # wants. Honour it: the alternative is a value the tool rejects, and a
    # rejected value reaches none of the code worth testing.
    for sep in ("=", ":"):
        if sep in name and not name.startswith("-"):
            return f"{_SAFE_WORD}{sep}{_SAFE_WORD}2"
    # A pattern the help calls a GLOB matches whole names: `sample` matches no
    # seeded file, the tool reports "No files matched" and exits 0 having run
    # none of its renaming code. `bulk_file_renamer_15bd514f` says "Glob
    # pattern to match files (e.g., '*.txt')".
    if slot == 0 and re.search(r"\bglob\b|wildcard", help_text or "", re.I):
        return f"{_SAFE_WORD}*"
    return _SAFE_WORD if slot == 0 else f"{_SAFE_WORD}{slot + 1}"


def _invent_args(positionals: list, sandbox: Path, help_text: str = ""):
    """Plausible values for a subcommand's positionals, or None to decline.

    Declines rather than guesses when there are more positionals than a tool
    of this shape plausibly has -- precision over recall, as everywhere else in
    this module: a wrong guess spends an LLM repair call on correct code.
    """
    if len(positionals) > 4:
        return None
    out = []
    words = 0
    for name in positionals:
        described = _arg_help(help_text, name)
        value = _value_for(name, "", sandbox, words, described)
        if not (_PATHISH.search(name) or _PATH_HELP.search(described)):
            words += 1
        out.append(value)
    return out


def _raised_on_purpose(trace: str) -> bool:
    """Did the program raise this itself, on purpose?

    The deepest frame's source line settles it. `raise RuntimeError(...)` in
    the tool's own code is the tool REPORTING a problem -- a missing file, a
    subprocess that failed, input it will not accept -- and a probe that hands
    it invented arguments should expect exactly that. An exception the
    interpreter raised at an operation (`src.rename(dst)`, unpacking a
    generator) is the tool HAVING a problem.

    Without this, `test_coverage_tool` was flagged for saying "Failed to run
    pytest" after being pointed at a directory of dummy text files, which is
    the correct thing for it to do and would have spent a repair call on
    correct code.
    """
    frames = re.findall(
        r'File "[^"]+", line \d+, in [^\n]*\n(\s*)([^\n]*)', trace)
    if not frames:
        return False
    return frames[-1][1].strip().startswith("raise ")


def _project_frame(trace: str, project_dir: Path) -> str:
    """The deepest frame of a traceback that lies inside the project.

    That is the line to repair. For row 4 the mismatch was between
    `renamer.py`'s generator and the unpacking in `main.py`, and it is
    `main.py` that has to change.
    """
    best = ""
    for m in re.finditer(r'File "([^"]+)", line (\d+)', trace):
        try:
            f = Path(m.group(1)).resolve()
            f.relative_to(project_dir)
        except Exception:
            continue
        best = f"{f}:{m.group(2)}"
    return best


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
    # Run the child under UTF-8, and decode its output as UTF-8.
    #
    # Without this the check reports defects that belong to its own console.
    # Row 4 on 2026-09-08 was marked `unusable` — "the command-line tool fails
    # on `--help` (exit 1)" — because its argparse description contained a
    # non-breaking hyphen (U+2011) and Windows gave the child a cp1252 stdout,
    # so `print_help()` raised UnicodeEncodeError inside argparse. The same tool
    # exits 0 and prints correct help under a UTF-8 stdout. The artifact was
    # sound; the harness was measuring its own locale.
    #
    # `tools/assert_row.py` had this exact bug and was fixed the same way, after
    # it died mid-report on a `→` in a finding.
    #
    # NOTE this makes the check blind to a genuine portability defect: a tool
    # whose help text cannot be printed on a default Windows console is broken
    # for those users. That is a real finding, but it belongs to whatever
    # decides what the generator may emit — not to a smoke test whose question
    # is "does this program run", and not as a verdict of `unusable` on a
    # program that runs.
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            argv,
            capture_output=True, text=True, timeout=CLI_TIMEOUT,
            encoding="utf-8", errors="replace",
            cwd=str(sandbox), env=env,
            # A subcommand invoked for real may prompt for confirmation. With
            # inherited stdin that blocks until the timeout and reports as a
            # hang; with no stdin it gets EOF and carries on or exits.
            stdin=subprocess.DEVNULL,
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


# argparse prints a positional as its dest (lower case) and an option's value
# as its metavar, which defaults to the dest UPPER-CASED but is often a custom
# string: `SEARCH=REPLACE`, `old:new`, `N`. Requiring a plain uppercase word
# missed `-p SEARCH=REPLACE`, so `-p` was read as a valueless flag and then
# swallowed the `directory` positional that followed it — the tool never ran
# (`bulk_file_renamer_a3cd2a11`, 2026-09-10). A metavar is anything that is not
# a plain lower-case word.
_METAVAR = re.compile(r"(?=.*[^a-z0-9_-])\S+")
_WORD = re.compile(r"[A-Za-z_][\w-]*")


def _arg_help(text: str, name: str) -> str:
    """The description argparse printed for one argument.

    `bulk_file_renamer_ef6ae132` is why this exists. Its positional was named
    `root`, which no name vocabulary had, so the probe passed the word
    `sample`, the tool matched nothing in a directory that did not exist, and
    exited 0 having never reached the `re.sub` on line 75 that raises
    `NameError: name 're' is not defined` on every real run. The build was
    recorded `done` with cli_smoke verified. Its own help said "Root directory
    to search for files" the whole time.

    The usage block is cut off first. Click wraps a long usage line, leaving
    an argument name alone on an indented line, and the `\\s{2,}` below --
    which has to span a newline, because argparse prints a long option's help
    on the next line -- then took the docstring after the blank line as that
    argument's description. `REPLACEMENT` in `bulk_file_renamer_111cf8e7` read
    "Rename files in DIRECTORY ..." and was handed a directory.
    """
    usage = re.search(r"(?is)^usage:\s*(.+?)(?:\n\s*\n|\Z)", text)
    if usage:
        text = text[usage.end():]
    pattern = (r"(?im)^\s{2,}(?:" + re.escape(name) +
               r"|-\w,\s+--" + re.escape(name.lstrip("-")) +
               r"|--" + re.escape(name.lstrip("-")) +
               r")(?:\s+[A-Z][A-Z0-9_]*)?\s{2,}(.+)$")
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def _usage_of(text: str) -> str:
    """The usage line of a --help output, flattened to one line."""
    m = re.search(r"(?is)^usage:\s*(.+?)(?:\n\s*\n|\Z)", text)
    return " ".join(m.group(1).split()) if m else ""


def _drop_prog(tokens: list) -> list:
    """A usage line's tokens without the program name.

    The program name is usually one token, but Click prints a module run with
    `-m` as `python -m pkg.cli` -- three. Dropping one left `-m` to be read as
    a required option owning `pkg.cli` as its metavar, and the probe invoked
    `bulk_file_renamer_111cf8e7` as `-m <dir> sample`: Click exited 2, nothing
    of the tool ran, and the build was recorded verified (2026-09-10).
    """
    if (len(tokens) >= 3 and tokens[1] == "-m"
            and re.search(r"python[\d.]*(\.exe)?$", tokens[0], re.I)):
        return tokens[3:]
    return tokens[1:]


def _entries(block: str) -> list:
    """The entries of an indented help block, continuation lines joined.

    An entry starts at the block's own indent; a line indented further is its
    description wrapping, and must not be read as an entry of its own -- Click
    wraps `rename  Rename files in DIRECTORY matching PATTERN to` onto a line
    that can begin with a bare upper-case word.
    """
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return []
    indent = len(lines[0]) - len(lines[0].lstrip())
    out: list = []
    for ln in lines:
        if len(ln) - len(ln.lstrip()) <= indent or not out:
            out.append(ln.strip())
        else:
            out[-1] += " " + ln.strip()
    return out


def _click_block(text: str, title: str) -> str:
    """The body of a Click `Title:` section, up to the next blank line."""
    m = re.search(r"(?m)^" + title + r":[ \t]*\n((?:[ \t]+\S[^\n]*\n?)+)", text)
    return m.group(1) if m else ""


def _click_commands(text: str) -> list:
    """Subcommand names from Click's `Commands:` block.

    argparse names its subcommands in braces -- `{rename,undo}` -- and that is
    all this module used to read. Click prints no braces anywhere: the usage
    line says `COMMAND [ARGS]...` and the names appear only as the first word
    of each entry in this block.
    """
    names = []
    for entry in _entries(_click_block(text, "Commands")):
        m = re.match(r"([A-Za-z][\w-]*)(?:\s{2,}|$)", entry)
        if m:
            names.append(m.group(1))
    return names


def _click_required(text: str) -> list:
    """`(flag, metavar)` for each option Click marks `[required]`.

    Click's usage line never names an option -- it prints `[OPTIONS]` whatever
    is required -- so a required option is visible only here. Missing it means
    the probe invokes the tool without it, Click answers with a usage error,
    and the check reports a tool it never ran. The long flag is preferred
    because it is what the entry is named by in the rest of the help.
    """
    out = []
    for entry in _entries(_click_block(text, "Options")):
        if "[required]" not in entry:
            continue
        spec = re.split(r"\s{2,}", entry, maxsplit=1)[0]
        flags = re.findall(r"(?:^|[\s,/])(--?[A-Za-z][\w-]*)", spec)
        if not flags:
            continue
        flag = next((f for f in flags if f.startswith("--")), flags[0])
        rest = re.sub(r"--?[A-Za-z][\w-]*[,/]?", " ", spec).split()
        out.append((flag, rest[0] if rest else None))
    return out


def _required_options(help_text: str) -> list:
    """Every required option, from the usage line and from Click's block."""
    usage = _usage_of(help_text)
    required = _walk_usage(usage)[1] if usage else []
    seen = {f for f, _ in required}
    return required + [(f, m) for f, m in _click_required(help_text)
                       if f not in seen]


def _walk_usage(usage: str) -> tuple:
    """`(positionals, required_options, subcommands)` from one usage line.

    Written as a walk rather than a filter because argparse prints an option
    and its metavar as two separate tokens: `-p PATTERN`. Reading tokens
    independently makes `PATTERN` look exactly like a required positional, and
    the probe then passes a stray argument, argparse exits 2, and the tool is
    recorded as fine having never run a line of its own code. That is how
    `bulk_file_renamer_fd473b61` -- which renames its files and then dies
    with a FileNotFoundError -- was reported verified.

    Bracketed groups are optional and skipped whole, so `[-r ROOT]` consumes
    both of its tokens.
    """
    positionals: list = []
    required: list = []
    subcommands: list = []

    tokens = _drop_prog(usage.split())
    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.startswith("{") and token.rstrip(".").endswith("}"):
            subcommands.extend(
                t for t in token.rstrip(".").strip("{}").split(",") if t)
            i += 1
            continue

        if token.startswith("["):
            # An optional group: skip until its brackets balance.
            depth = token.count("[") - token.count("]")
            i += 1
            while depth > 0 and i < len(tokens):
                depth += tokens[i].count("[") - tokens[i].count("]")
                i += 1
            continue

        if token.startswith("-"):
            # A REQUIRED option. It owns the next token if that token looks
            # like argparse's default metavar (the dest, upper-cased).
            if i + 1 < len(tokens) and _METAVAR.fullmatch(tokens[i + 1]):
                required.append((token, tokens[i + 1]))
                i += 2
            else:
                required.append((token, None))
                i += 1
            continue

        # Click prints a required variadic argument as `FILES...`.
        if _WORD.fullmatch(token.removesuffix("...")):
            positionals.append(token.removesuffix("..."))
        i += 1

    return positionals, required, subcommands


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
        positionals, _required, subcommands = _walk_usage(usage)

    if not subcommands:
        block = re.search(
            r"(?is)\n\s*(?:positional arguments|commands|subcommands):\s*\n(.+?)"
            r"(?:\n\s*\n|\Z)", text
        )
        if block:
            # Only a brace group that STARTS an entry names subcommands.
            # `bulk_file_renamer_912f9b22` has none; its `pattern` help says
            # "placeholders: {index} for sequential number", and an unanchored
            # search made `index` a subcommand. The probe ran `index <dir>
            # sample`, argparse exited 2, and the build was recorded verified.
            for entry in _entries(block.group(1)):
                inner = re.match(r"\{([^}]+)\}", entry)
                if inner:
                    subcommands.extend(
                        t for t in inner.group(1).split(",") if t)
                    break

    if not subcommands:
        subcommands = _click_commands(text)

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
        evidence["repair_targets"] = _repair_targets(evidence, findings)
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

    # No finding is not the same as a pass. Every silent `verified` on a
    # row-4 build was a probe that ran the tool and was turned away by its
    # argument parser -- `--help` only, a stray `-m`, a subcommand that did not
    # exist -- so the tool's own code never executed. Say which invocations
    # were refused, and when all of them were, say the check did not run.
    refused = [f"{e['path']} {a['sub']}".strip()
               for e in evidence["entries"]
               for a in e.get("invocations", []) if a.get("refused")]
    if not any(_reached(e) for e in evidence["entries"]):
        return VerificationOutcome.not_run(
            "cli_smoke", shape="cli", evidence=evidence,
            detail=detail + " -- but no invocation got past the argument "
                   "parser, so none of the tool's own code ran"
                   + (f" (refused: {', '.join(refused)})" if refused else ""),
        )
    if refused:
        detail += ("; not reached, refused as a usage error: "
                   + ", ".join(refused))
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
            before = len(findings)
            helps: dict = {}
            for sub in subcommands[:4]:
                # Each subcommand must at least be able to describe itself.
                sub_code, sub_out, sub_err = _run(
                    argv + [sub, "--help"], run_dir, sandbox
                )
                if sub_code != 0:
                    findings.append(
                        f"`{entry.path} {sub} --help` fails (exit {sub_code}): "
                        f"{(sub_err or sub_out).strip()[:200]}"
                    )
                    continue
                helps[sub] = sub_out + sub_err
                # ...and then it must survive being run. Describing itself only
                # proves argparse built its parsers. Row 4 on 2026-09-10 was
                # recorded `verified` on exactly that evidence while every
                # `rename` died with a TypeError, because nothing here had ever
                # invoked a subcommand with arguments.
                _probe_subcommand(
                    argv, sub, (sub_out + sub_err), run_dir, sandbox,
                    entry, project_dir, findings, record,
                )
            # Then the one thing no single invocation can show: whether the
            # subcommand that undoes the work can undo work really done.
            _probe_workflow(argv, helps, sandbox, run_dir, entry,
                            project_dir, findings, record)
            record["ok"] = len(findings) == before
            return record

        required = _required_options(combined)

        if positionals or required:
            # Running with NO arguments should be a clean usage error (argparse
            # exits 2), never a traceback — a tool that crashes instead of
            # explaining itself is a defect.
            code2, out2, err2 = _run(argv, run_dir, sandbox)
            record["bare_exit"] = code2
            if ("Traceback (most recent call last)" in err2
                    and not _raised_on_purpose(err2)):
                findings.append(
                    f"the command-line tool {entry.path} raises an unhandled "
                    f"exception when run without arguments instead of printing "
                    f"usage: {err2.strip()[-300:]}"
                )
                record["ok"] = False
                return record
            # ...and then it must survive being run for real, exactly as a
            # subcommand does. Its arguments being REQUIRED OPTIONS rather than
            # positionals is a spelling difference, not a reason to check less:
            # `bulk_rename_cli` takes `-p PATTERN -r REPLACEMENT` and used to
            # reach this line having executed none of its own code.
            before = len(findings)
            _probe_invocation(argv, None, combined, run_dir, sandbox,
                              entry, project_dir, findings, record)
            record["ok"] = len(findings) == before
            record["note"] = (
                f"requires {', '.join(positionals + [f for f, _ in required])}"
            )
            return record

        # No required arguments and no subcommands: it should just run.
        if _DANGEROUS.search(combined):
            record["ok"] = True
            record["note"] = "destructive flags present; ran --help only"
            return record

        code3, out3, err3 = _run(argv, run_dir, sandbox)
        record["bare_exit"] = code3
        record["bare_ran"] = not _refused(code3, out3, err3)
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


def _refused(code: int, out: str, err: str) -> bool:
    """Did the argument parser turn this invocation away before the tool ran?

    argparse and Click both answer arguments they cannot accept with exit 2
    and a usage banner. An invocation refused that way executed none of the
    tool's own code, whatever it was handed. Both halves are required: a tool
    may choose exit 2 for its own reasons, and that is the tool running.
    """
    return code == 2 and re.search(r"(?im)^usage:", (err or "") + (out or "")) \
        is not None


def _reached(record: dict) -> bool:
    """Did any invocation of this entry point get past its argument parser?"""
    if record.get("bare_ran"):
        return True
    return any(a.get("ran") and not a.get("refused")
               for a in record.get("invocations", []))


def _probe_subcommand(argv, sub, sub_help, run_dir, sandbox,
                      entry, project_dir, findings, record):
    """One subcommand, invoked for real. See `_probe_invocation`."""
    return _probe_invocation(argv, sub, sub_help, run_dir, sandbox,
                             entry, project_dir, findings, record)


def _probe_invocation(argv, sub, sub_help, run_dir, sandbox,
                      entry, project_dir, findings, record):
    """Run one subcommand for real, and judge it ONLY on unhandled exceptions.

    Not on the exit code. A tool may legitimately exit non-zero because the
    invented pattern matched nothing, because a file it wanted is absent, or
    because it validates its input more strictly than this module can guess --
    all of which are the tool working. A traceback is not ambiguous in that
    way: no correct command-line program answers plausible arguments with a
    stack trace, so it is the one signal worth acting on here.
    """
    attempts = record.setdefault("invocations", [])
    label = sub or "(no subcommand)"
    prefix = [sub] if sub else []

    if _DANGEROUS.search(sub_help):
        attempts.append({"sub": label, "ran": False,
                         "why": "destructive flags present"})
        return

    usage = _usage_of(sub_help)
    positionals, _, _ = _walk_usage(usage) if usage else ([], [], [])
    required = _required_options(sub_help)
    # The usage line for a subcommand's own help starts with the subcommand
    # name. Drop it; it is not an argument.
    if sub and positionals and positionals[0] == sub:
        positionals = positionals[1:]

    args = _invent_args(positionals, sandbox, sub_help)
    if args is None or len(required) > 4:
        attempts.append({
            "sub": label, "ran": False,
            "why": f"{len(positionals)} positional(s), {len(required)} "
                   f"required option(s) to invent"})
        return

    # Required options first, then positionals, which is the order argparse
    # prints them and the order a user would type.
    argl: list = []
    words = 0
    for flag, metavar in required:
        argl.append(flag)
        if metavar:
            described = _arg_help(sub_help, flag)
            argl.append(_value_for(metavar, flag, sandbox, words, described))
            if not (_PATHISH.search(metavar) or _PATHISH.search(flag)
                    or _PATH_HELP.search(described)):
                words += 1
    argl.extend(args)

    def _run_fresh(extra: list) -> tuple:
        """One invocation in its own seeded, throwaway working directory.

        Seeded at the ROOT, unlike the older probes: a tool whose paths are
        options rather than positionals defaults to the current directory, and
        an empty one means the probe reaches none of its code. A fresh
        directory per invocation keeps the dry run and the real run from
        seeing each other's effects.
        """
        work = Path(tempfile.mkdtemp(prefix="cli_smoke_run_"))
        try:
            for name in _SEED_FILES:
                (work / name).write_text("sample\n", encoding="utf-8")
            _seed_dir(work)
            return _run(argv + prefix + argl + extra, run_dir, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # A tool that offers `--dry-run` is offering to predict its own work. Ask
    # it to, then ask it to do the work, and compare — see below.
    dry_code, dry_out, dry_err = (None, "", "")
    if "--dry-run" in sub_help:
        dry_code, dry_out, dry_err = _run_fresh(["--dry-run"])

    code, out, err = _run_fresh([])
    attempts.append({"sub": label, "ran": True, "args": argl,
                     "exit": code, "dry_run_exit": dry_code,
                     "refused": _refused(code, out, err)})

    # A traceback out of EITHER invocation is a defect.
    for stream in (err, dry_err):
        if ("Traceback (most recent call last)" in stream
                and not _raised_on_purpose(stream)):
            err = stream
            break
    else:
        # No traceback. The tool may still have contradicted itself: a dry run
        # that succeeds says "these are the renames I would do", and a real run
        # that then fails says it could not do them. `bulk_file_renamer_a3cd2a11`
        # previewed two renames and answered `unhashable type: 'list'` with a
        # clean exit 1 and no traceback, because it caught its own exception —
        # which the traceback rule alone can never see. Exit codes are not
        # judged anywhere else here, deliberately: a tool may exit 1 because
        # nothing matched. It may not promise the work and then fail it.
        if dry_code == 0 and code not in (0, 2):
            report = (dry_err or dry_out or "").strip()
            failure = (err or out or "").strip()
            findings.append(
                f"`{entry.path}{(' ' + sub) if sub else ''}` previews its work "
                f"successfully with --dry-run and then fails to do it "
                f"(exit {code}): {failure[-240:]}"
            )
            record["ok"] = False
            record.setdefault("crashed", []).append(
                {"sub": label, "error": failure[-200:], "where": ""})
        return

    last = [ln for ln in err.strip().splitlines() if ln.strip()][-1][:200]
    where = _project_frame(err, project_dir)
    findings.append(
        f"`{entry.path}{(' ' + sub) if sub else ''}` raises an unhandled "
        f"exception on a normal invocation "
        f"({' '.join(prefix + argl)[:120]}): {last}"
        + (f" -- raised at {where}" if where else "")
        + ". The tool builds its help text and then fails at the thing it "
          "exists to do."
    )
    record["ok"] = False
    record.setdefault("crashed", []).append(
        {"sub": label, "error": last, "where": where})


# Subcommands whose whole job is to reverse another one. Only these get the
# stateful probe below: handing a file one subcommand wrote to an arbitrary
# other subcommand, and judging what comes back, would be guessing at what the
# tool means. An undo has one meaning -- the files are back.
_INVERSE = re.compile(r"^(undo|revert|rollback|restore|unrename)$", re.I)


def _snapshot(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file()}


def _reader_of(problem: str, project_dir: Path) -> str:
    """The one project file that reads the key a caught error names.

    `bulk_file_renamer_111cf8e7` answered its own undo log with "Undo failed:
    'src'" and exit 1 -- no traceback, so no frame to blame. The key is the
    evidence: exactly one non-test file subscripts `["src"]`, and that reader
    is what disagrees with the writer. Anything less certain returns "", and
    the finding then publishes no repair target at all -- handing the entry
    point to the debugger for a defect it does not contain is how a crash
    gets silenced instead of fixed.
    """
    for key in re.findall(r"'([A-Za-z_][\w-]{0,40})'", problem or ""):
        pat = re.compile(r"""\[\s*['"]%s['"]\s*\]|\.get\(\s*['"]%s['"]"""
                         % (re.escape(key), re.escape(key)))
        hits = []
        for f in project_dir.rglob("*.py"):
            rel = f.relative_to(project_dir).as_posix()
            if "test" in rel.lower() or "__pycache__" in rel:
                continue
            try:
                for n, line in enumerate(
                        f.read_text(encoding="utf-8").splitlines(), 1):
                    if pat.search(line):
                        hits.append(f"{f}:{n}")
                        break
            except Exception:
                continue
        if len(hits) == 1:
            return hits[0]
    return ""


def _probe_workflow(argv, helps, sandbox, run_dir, entry, project_dir,
                    findings, record):
    """Run the forward subcommand for real, then ask its inverse to undo it.

    The row-4 prompt asks for "an undo log so a rename can be reversed", and
    no probe could see whether that works: `undo` needs the log a real
    `rename` wrote, so run alone it is either refused (a log path invented
    here does not exist) or reads an empty directory and has nothing to do.
    `bulk_file_renamer_111cf8e7` renamed correctly, wrote `{"original",
    "new"}` entries, and its undo read `entry["src"]` -- caught, logged, exit
    1 -- and was recorded verified.

    Judged on the SYMPTOM, not the exit code alone: after the inverse, every
    file the forward run moved must be back. That also catches a repair that
    stops the crash by making undo do nothing, which exit codes cannot.
    Declines whenever it cannot be sure what it is asking: the forward run
    must have moved at least one file, and the inverse must take at most one
    argument and no required options.
    """
    invs = record.get("invocations", [])
    producer = next((a for a in invs
                     if a.get("ran") and a.get("exit") == 0
                     and not a.get("refused")
                     and not _INVERSE.match(a.get("sub", ""))), None)
    if producer is None:
        return
    flows = record.setdefault("workflow", [])
    for inv in invs:
        sub = inv.get("sub", "")
        if not _INVERSE.match(sub) or sub not in helps:
            continue
        text = helps[sub]
        usage = _usage_of(text)
        pos = _walk_usage(usage)[0] if usage else []
        if pos and pos[0] == sub:
            pos = pos[1:]
        if _DANGEROUS.search(text) or _required_options(text) or len(pos) > 1:
            flows.append({"sub": sub, "ran": False,
                          "why": "destructive flags, required options or "
                                 "more than one argument"})
            continue

        # Which argument does the inverse want? Its help decides the ORDER,
        # never the verdict: every plausible argument is tried, each after a
        # fresh forward run, and undo fails only if none of them brings the
        # files back. `bulk_file_renamer_15bd514f`'s undo takes "Base directory
        # where the undo log resides"; handing it the log file would have
        # been this module's mistake, reported as the tool's.
        wants_dir = bool(pos) and bool(
            re.search(r"dir|folder|root|base", pos[0], re.I)
            or _PATH_HELP.search(_arg_help(text, pos[0])))
        choices = (["<data>", "<work>", "<file>"] if wants_dir
                   else ["<file>", "<data>", "<work>"]) if pos else [None]

        attempts: list = []
        for choice in choices:
            got = _replay_and_invert(argv, producer, sub, choice, sandbox,
                                     run_dir, project_dir)
            if got is None:
                continue
            attempts.append(got)
            if got["verdict"] == "restored":
                break
        if not attempts:
            flows.append({"sub": sub, "after": producer["sub"], "ran": False,
                          "why": "the forward run moved no file, or wrote "
                                 "nothing to hand back"})
            continue
        ran = [a for a in attempts if a["verdict"] != "refused"]
        for a in attempts:
            flows.append({"sub": sub, "after": producer["sub"],
                          "ran": a["verdict"] != "refused", "arg": a["arg"],
                          "exit": a["exit"],
                          "restored": a["verdict"] == "restored"})
        if not ran:
            continue
        # It got past the parser, so it is no longer unreached.
        inv["refused"] = False
        inv["via"] = f"after a real `{producer['sub']}`"
        if any(a["verdict"] == "restored" for a in ran):
            continue

        # None of them worked. Report the attempt the help pointed at first.
        a = ran[0]
        where = (_project_frame(a["err"], project_dir) if a["trace"]
                 else _reader_of(a["problem"], project_dir))
        findings.append(
            f"`{entry.path} {sub}` cannot reverse a real "
            f"`{producer['sub']}`: {a['problem']}"
            + (f" -- handed the file `{producer['sub']}` itself wrote, "
               f"`{a['arg']}`, which contains: {a['log'][:240]}"
               if a["log"] else
               (f" -- handed `{a['arg']}`" if a["arg"] else ""))
            + (f" -- read at {where}" if where else "")
            + (f". {a['moved']} file(s) it moved were not put back"
               if not a["restored"] else "")
            + ". The undo half of the tool does not undo."
        )
        record["ok"] = False
        record.setdefault("crashed", []).append(
            {"sub": sub, "error": a["problem"], "where": where,
             "no_target": not where})


def _replay_and_invert(argv, producer, sub, choice, sandbox, run_dir,
                       project_dir):
    """One forward run, then the inverse, in a fresh directory.

    `choice` names the inverse's argument: `<file>` the file the forward run
    wrote, `<data>` the directory it renamed in, `<work>` its working
    directory, None no argument. Returns None when there is nothing to judge
    -- the forward run moved nothing, or wrote no file to hand back.
    """
    work = Path(tempfile.mkdtemp(prefix="cli_smoke_flow_"))
    try:
        for name in _SEED_FILES:
            (work / name).write_text("sample\n", encoding="utf-8")
        data = _seed_dir(work)
        old = str(_seed_dir(sandbox))
        args = [str(data) if a == old else a for a in producer["args"]]
        before = _snapshot(work)
        code, _, _ = _run(argv + [producer["sub"]] + args, run_dir, work)
        changed = _snapshot(work)
        moved = before - changed
        if code != 0 or not moved:
            return None
        # What the forward run wrote, other than the files it renamed -- which
        # keep the seed word in their names, since only the pattern changed.
        written = sorted(
            (n for n in changed - before
             if _SAFE_WORD not in n.rsplit("/", 1)[-1]),
            key=lambda n: (not re.search(r"log|undo|journal|history", n, re.I),
                           n))
        if choice == "<file>":
            if not written:
                return None
            arg, log = written[0], ""
            try:
                log = " ".join((work / arg).read_text(
                    encoding="utf-8", errors="replace").split())
            except Exception:
                pass
            call = [str(work / arg)]
        elif choice in ("<data>", "<work>"):
            target = data if choice == "<data>" else work
            arg, log, call = target.relative_to(work).as_posix() or ".", "", \
                [str(target)]
        else:
            arg, log, call = "", "", []

        u_code, u_out, u_err = _run(argv + [sub] + call, run_dir, work)
        if _refused(u_code, u_out, u_err):
            return {"verdict": "refused", "arg": arg, "exit": u_code}
        after = _snapshot(work)
        restored = before <= after
        trace = ("Traceback (most recent call last)" in u_err
                 and not _raised_on_purpose(u_err))
        lines = [ln for ln in (u_err or u_out or "").strip().splitlines()
                 if ln.strip()]
        ok = restored and u_code == 0 and not trace
        return {
            "verdict": "restored" if ok else "failed",
            "arg": arg, "exit": u_code, "err": u_err, "trace": trace,
            "restored": restored, "moved": len(moved), "log": log,
            "problem": (lines[-1][:200] if lines and (trace or u_code != 0)
                        else f"exit {u_code}, and the renamed files are "
                             f"still renamed"),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _repair_targets(evidence: dict, findings: list) -> dict:
    """`{file: [finding, ...]}` for the file the traceback actually blames.

    Like `call_arity` and unlike `module_ref`: the callee is usually right and
    the caller wrong, so the file to repair is the one the deepest project
    frame names -- which for a package entry point is often not the file this
    check is nominally probing.
    """
    targets: dict = {}
    out_dir = Path(config.OUTPUT_DIR).resolve()
    for record in evidence.get("entries", []):
        for crash in record.get("crashed", []):
            if crash.get("no_target"):
                continue
            where = (crash.get("where") or "").rsplit(":", 1)[0]
            rel = record["path"]
            if where:
                try:
                    rel = Path(where).resolve().relative_to(out_dir).as_posix()
                except Exception:
                    rel = record["path"]
            hit = next((f for f in findings
                        if crash.get("error", "")[:60] in f), None)
            targets.setdefault(rel, []).append(
                hit or f"{crash.get('sub')}: {crash.get('error')}")
    return targets
