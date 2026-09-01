"""
tools/verify_repairs.py — does a repair ever make things worse?
===============================================================

`tools/verify_corpus.py` replays **verifiers** over finished projects. It never
invokes `_preflight_fix`, the debugger's repair loop, the tester, or the backend
developer. That blind spot is not theoretical: on 2026-09-01 it cost a live row.

`agents/debugger.py::_preflight_fix` carried a single-router rule from the
`weather_router` era that rewrote every `app.include_router(<alias>)` to
`app.include_router(router)`. In a five-entity build that collapses five
distinct names onto one bound nowhere. It did the damage twice — once over every
file *before* any debugging, so correct generated code was broken before it was
ever checked, and again after each accepted LLM repair, because `_debug_file`
calls it on the line following `create_file(...)`. The debugger spent three
attempts, two passes and two remediation passes re-fixing a file this function
re-broke each time. 222,068 tokens, no progress, and the build shipped unusable.

It was green across 820 tests and every corpus sweep, and it could not have been
otherwise: **the corpus covers verifiers, not the agents that write and repair
code.** This asks the other question.

The properties
--------------
**P1 — do no harm.** A file that imported cleanly *before* the repairs must
still import after. Conditional by necessity: much of the corpus is broken
builds, so only the clean-before files can carry the assertion. This is exactly
what `_preflight_fix` violated.

**P2 — idempotence.** Running the sequence twice produces the same bytes as
running it once. A rule that keeps re-applying is how one file absorbed a whole
repair budget.

**P3 — a reviewed diff.** Every file the repairs modify is reported, attributed
to the individual rule that modified it. A change nobody has read is not
evidence (§4.41).

Costs nothing: no LLM, no tokens. Every step replayed here is deterministic —
the sequence stops immediately before `_debug_file`, which is where the LLM
starts.

    python tools/verify_repairs.py                          # table
    python tools/verify_repairs.py --json before.json        # record
    python tools/verify_repairs.py --baseline before.json    # diff, exit 1 on change
    python tools/verify_repairs.py --only inventory --show-diffs
    python tools/verify_repairs.py --no-import-check         # P2/P3 only, seconds
    python tools/verify_repairs.py --fixtures-only           # the shapes below

What it probes
--------------
Both `generated_projects/` and `repair_fixtures/`. The fixtures are not
decoration: **every build in the corpus is single-router**, so replaying these
repairs over the corpus alone would not have caught the defect above either. A
blind spot inside a blind spot. The fixtures are hand-written, minimal, and
known to import as they stand, so any change to one is suspicious and any break
is a defect. Three of the four repair bugs found on 2026-09-01 were found there
and nowhere else.

Probed on a throwaway clone, never on the corpus itself: these repairs rewrite
files in place, and the corpus is evidence.
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

from agents.debugger import (                              # noqa: E402
    Debugger,
    SKIP_DEBUG_FILES,
    _is_framework_script,
)
from tools.code_executor import run_python                 # noqa: E402
from tools.verify_corpus import (                          # noqa: E402
    OUT,
    _REPAIR_PREFIX,
    _clone,
    project_names,
)

logger = logging.getLogger(__name__)

# The deterministic prefix of `Debugger.run()` (agents/debugger.py:279-330), in
# order. `_pre_install_project_deps` is deliberately absent: it only pip-installs
# and touches no source, so replaying it would put the network in the middle of
# a deterministic probe without changing a single byte it measures.
STEPS = (
    "ensure_init",
    "preflight_fix",
    "rewrite_dotted_imports",
    "inject_syspath",
    "structural_imports",
)

# Hand-written projects for shapes `generated_projects/` does not contain.
# Every build in the corpus is single-router, which is exactly why replaying
# the repairs over the corpus alone would NOT have caught the defect this file
# was written for. A blind spot inside a blind spot; see repair_fixtures/README.
FIXTURES = Path(__file__).resolve().parent.parent / "repair_fixtures"


def fixture_names() -> list[str]:
    if not FIXTURES.is_dir():
        return []
    return sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


# Shorter than the pipeline's 90s. A file too slow to import inside this budget
# simply does not join the clean-before set, which only ever SHRINKS what P1
# asserts on — the safe direction. A file that imports in time and then stops
# importing is the finding, and no timeout can manufacture one.
_IMPORT_TIMEOUT = 30


# ── file selection, mirroring Debugger.run() ──────────────────────────────────

def _py_files(clone: str) -> list[str]:
    """Every path `Debugger.run()` would accept, OUTPUT_DIR-relative.

    The path convention matters: every repair resolves against
    `config.OUTPUT_DIR`, so a bare absolute path silently reads nothing.
    """
    root = OUT / clone
    out: list[str] = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = f"{clone}/{p.relative_to(root).as_posix()}"
        if p.name in SKIP_DEBUG_FILES or _is_framework_script(rel):
            continue
        out.append(rel)
    return out


def _read(rel: str) -> str:
    try:
        return (OUT / rel).read_text(encoding="utf-8")
    except Exception:
        return ""


def _snapshot(clone: str) -> dict[str, str]:
    """Every .py in the clone. Whole-tree, so a step that CREATES a file
    (`_ensure_init_files`) is visible rather than silently excluded."""
    root = OUT / clone
    snap: dict[str, str] = {}
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = f"{clone}/{p.relative_to(root).as_posix()}"
        try:
            snap[rel] = p.read_text(encoding="utf-8")
        except Exception:
            snap[rel] = ""
    return snap


def _changed(before: dict, after: dict) -> list[str]:
    names = set(before) | set(after)
    return sorted(n for n in names if before.get(n) != after.get(n))


def _udiff(rel: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}", n=2,
    ))


# ── the sequence ──────────────────────────────────────────────────────────────

def _apply_repairs(dbg: Debugger, clone: str, files: list[str]) -> dict:
    """Replay the pre-LLM sequence, attributing every change to one rule.

    The per-file steps are interleaved exactly as `Debugger.run()` interleaves
    them, rather than run as separate whole-corpus passes: both are file-local
    today, but a probe that reorders the thing it measures is not measuring it.
    """
    attribution: dict[str, list[tuple[str, str, str]]] = {s: [] for s in STEPS}

    snap = _snapshot(clone)
    dbg._ensure_init_files(files)
    after = _snapshot(clone)
    attribution["ensure_init"] = [
        (rel, snap.get(rel, ""), after.get(rel, "")) for rel in _changed(snap, after)
    ]

    for rel in files:
        b = _read(rel)
        dbg._preflight_fix(rel)
        a = _read(rel)
        if a != b:
            attribution["preflight_fix"].append((rel, b, a))
        b = a
        dbg._rewrite_dotted_imports(rel)
        a = _read(rel)
        if a != b:
            attribution["rewrite_dotted_imports"].append((rel, b, a))

    for rel in files:
        b = _read(rel)
        dbg._inject_syspath(rel)
        a = _read(rel)
        if a != b:
            attribution["inject_syspath"].append((rel, b, a))

    snap = _snapshot(clone)
    dbg._apply_structural_import_repairs(files)
    after = _snapshot(clone)
    attribution["structural_imports"] = [
        (rel, snap.get(rel, ""), after.get(rel, "")) for rel in _changed(snap, after)
    ]

    return attribution


def _import_ok(rel: str) -> tuple[bool, str]:
    try:
        r = run_python(rel, timeout=_IMPORT_TIMEOUT)
        return bool(r.success), (r.stderr or "").strip()
    except Exception as e:                                   # never fail the probe
        return False, f"{type(e).__name__}: {e}"


def _last_line(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:200] if lines else ""


# ── one project ───────────────────────────────────────────────────────────────

def probe_one(name: str, import_check: bool = True, keep: bool = False,
              src: Path | None = None) -> dict:
    clone = _clone(name, prefix=_REPAIR_PREFIX, src=src)
    try:
        files = _py_files(clone)
        if not files:
            return {"files": 0, "changed": {}, "clean_before": 0,
                    "harm": [], "not_idempotent": [], "note": "no debuggable .py files"}

        dbg = Debugger()

        # P1, first half: what imported cleanly before anything touched it.
        clean_before: list[str] = []
        if import_check:
            for rel in files:
                ok, _ = _import_ok(rel)
                if ok:
                    clean_before.append(rel)

        attribution = _apply_repairs(dbg, clone, files)
        after_once = _snapshot(clone)

        # P1, second half: did any of them stop importing?
        harm: list[dict] = []
        if import_check:
            for rel in clean_before:
                ok, err = _import_ok(rel)
                if not ok:
                    harm.append({"file": rel.split("/", 1)[-1],
                                 "error": _last_line(err)})

        # P2: the same sequence again must be a no-op.
        _apply_repairs(dbg, clone, _py_files(clone))
        after_twice = _snapshot(clone)
        not_idempotent = [
            rel.split("/", 1)[-1] for rel in _changed(after_once, after_twice)
        ]

        changed = {
            step: sorted(rel.split("/", 1)[-1] for rel, _b, _a in rows)
            for step, rows in attribution.items() if rows
        }
        diffs = {
            step: [(rel.split("/", 1)[-1], _udiff(rel, b, a)) for rel, b, a in rows]
            for step, rows in attribution.items() if rows
        }

        return {
            "files":          len(files),
            "changed":        changed,
            "clean_before":   len(clean_before) if import_check else None,
            "harm":           harm,
            "not_idempotent": not_idempotent,
            "_diffs":         diffs,          # dropped before the baseline is written
        }
    finally:
        if not keep:
            shutil.rmtree(OUT / clone, ignore_errors=True)


# ── reporting ─────────────────────────────────────────────────────────────────

def _recordable(results: dict) -> dict:
    """The baseline without the diff text — diffs are for a human, and pinning
    them would turn every whitespace change into a regression."""
    out = {}
    for name, r in results.items():
        out[name] = {k: v for k, v in r.items() if not k.startswith("_")}
    return out


def print_table(results: dict, show_diffs: bool = False) -> None:
    for name, r in results.items():
        touched = sum(len(v) for v in r.get("changed", {}).values())
        print(f"\n{name}  [{r.get('files', 0)} file(s), "
              f"{r.get('clean_before')} clean before]")
        if not touched:
            print("  no file modified by any repair")
        for step in STEPS:
            names = r.get("changed", {}).get(step)
            if names:
                print(f"  ~ {step:<24} {len(names)} file(s): {', '.join(names[:4])}"
                      + (" ..." if len(names) > 4 else ""))
        for h in r.get("harm", []):
            print(f"  HARM  {h['file']} imported before, does not now")
            print(f"        {h['error']}")
        if r.get("not_idempotent"):
            print(f"  LOOP  not idempotent: {', '.join(r['not_idempotent'][:4])}")
        if show_diffs:
            for step, rows in (r.get("_diffs") or {}).items():
                for rel, d in rows:
                    print(f"\n  --- {step}: {rel} ---")
                    for line in d.splitlines():
                        print(f"  {line}")


def summarise(results: dict) -> tuple[int, int]:
    harm = sum(len(r.get("harm", [])) for r in results.values())
    loops = sum(len(r.get("not_idempotent", [])) for r in results.values())
    return harm, loops


def diff(baseline: dict, current: dict) -> list[str]:
    changes: list[str] = []
    for name in sorted(set(baseline) | set(current)):
        if name not in current:
            changes.append(f"{name}: gone from the corpus")
            continue
        if name not in baseline:
            changes.append(f"{name}: new in the corpus (no baseline)")
            continue
        old, new = baseline[name], current[name]
        for step in STEPS:
            o = set(old.get("changed", {}).get(step, []))
            n = set(new.get("changed", {}).get(step, []))
            for f in sorted(n - o):
                changes.append(f"{name}/{step}: NOW modifies {f}")
            for f in sorted(o - n):
                changes.append(f"{name}/{step}: no longer modifies {f}")
        ho = {h["file"] for h in old.get("harm", [])}
        hn = {h["file"] for h in new.get("harm", [])}
        for f in sorted(hn - ho):
            changes.append(f"{name}: NEW HARM — {f} imported before, does not now")
        for f in sorted(ho - hn):
            changes.append(f"{name}: harm resolved — {f}")
        lo = set(old.get("not_idempotent", []))
        ln = set(new.get("not_idempotent", []))
        for f in sorted(ln - lo):
            changes.append(f"{name}: NEW non-idempotent repair — {f}")
        for f in sorted(lo - ln):
            changes.append(f"{name}: idempotence restored — {f}")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Replay the debugger's deterministic repairs over every saved "
                    "build and assert they never make a working file worse.")
    ap.add_argument("--json", metavar="PATH", help="write the full result")
    ap.add_argument("--baseline", metavar="PATH",
                    help="diff against a recorded result; exit 1 on any change")
    ap.add_argument("--only", default="", metavar="SUBSTRING")
    ap.add_argument("--show-diffs", action="store_true",
                    help="print a unified diff for every file a repair modified")
    ap.add_argument("--no-import-check", action="store_true",
                    help="skip P1 (the slow half); P2 and P3 still run")
    ap.add_argument("--no-fixtures", action="store_true",
                    help="skip repair_fixtures/ and probe only the corpus")
    ap.add_argument("--fixtures-only", action="store_true",
                    help="probe only repair_fixtures/ — seconds, and it is where "
                         "the shapes the corpus lacks live")
    ap.add_argument("--keep-clones", action="store_true")
    ap.add_argument("--verbose", action="store_true",
                    help="let the repair passes log what they are doing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.ERROR,
        format="%(message)s",
    )

    # (display name, source dir or None for a corpus project)
    targets: list[tuple[str, Path | None]] = []
    if not args.no_fixtures:
        targets += [(f"fixture:{n}", FIXTURES / n)
                    for n in fixture_names() if args.only in n]
    if not args.fixtures_only:
        targets += [(n, None) for n in project_names(args.only)]
    if not targets:
        print(f"Nothing to probe in {OUT} or {FIXTURES}")
        return 1

    results: dict = {}
    for i, (name, src) in enumerate(targets, 1):
        if not args.quiet:
            print(f"[{i}/{len(targets)}] {name}", flush=True)
        try:
            results[name] = probe_one(
                name.replace("fixture:", "fx_"),
                import_check=not args.no_import_check,
                keep=args.keep_clones,
                src=src,
            )
        except Exception as e:
            results[name] = {"files": 0, "changed": {}, "clean_before": None,
                             "harm": [], "not_idempotent": [],
                             "error": f"{type(e).__name__}: {e}"}

    if not args.quiet:
        print_table(results, show_diffs=args.show_diffs)

    harm, loops = summarise(results)
    print(f"\n{'=' * 70}")
    print(f"  {len(results)} project(s) probed — "
          f"{harm} file(s) harmed, {loops} non-idempotent repair(s)")

    if args.json:
        Path(args.json).write_text(
            json.dumps(_recordable(results), indent=2, sort_keys=True),
            encoding="utf-8")
        print(f"  Wrote {args.json}")

    if args.baseline:
        base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        changes = diff(base, _recordable(results))
        if not changes:
            print("  No change against the baseline.")
            return 0
        print(f"  {len(changes)} change(s) against the baseline — explain each:")
        for c in changes:
            print(f"    * {c}")
        return 1

    # A harmed file is a failure whether or not a baseline was asked for.
    return 1 if harm else 0


if __name__ == "__main__":
    sys.exit(main())
