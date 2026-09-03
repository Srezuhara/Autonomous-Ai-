"""
tools/verify_corpus.py — run every verifier against every saved build
=====================================================================

A checker is a hypothesis until it has been run against a real build.

Six checkers were written on 2026-08-30 and **four of them reported a defect
that did not exist** — a package module imported bare, a feature phrase that was
never split like an identifier, an argparse regex that read `-d` instead of
`--dry-run`, a path resolved twice. Each was caught only by running it against a
project that had already shipped and disbelieving the result. The reverse
happened too: `web_asset_check` passed row 2's frontend, whose
`import React from "react"` no browser can resolve. A checker that finds nothing
has not proved anything either.

Nothing in the repo made that cheap. This does: one command runs every verifier
against every project in `generated_projects/`, and `--baseline` turns the
result into a regression test. A change to a checker that alters what it says
about a shipped build then has to be explained, in both directions — a check
that starts reporting a defect on a build known to work, and a check that goes
quiet on a build known to be broken, are the same class of mistake.

Costs nothing: no LLM, no tokens. Every verifier here is deterministic.

    python tools/verify_corpus.py                         # human-readable table
    python tools/verify_corpus.py --json before.json      # record
    python tools/verify_corpus.py --baseline before.json  # diff, exit 1 on change
    python tools/verify_corpus.py --only inventory_system_90ee973f

Projects are probed on a **throwaway clone**, because `runtime_smoke` boots the
app and a booted app writes its database. The corpus is evidence; it is never
mutated. Databases are stripped from the clone so a probe starts from the same
state every time — the discipline §0.6 used to measure row 3 honestly.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

from tools.build_shape import detect_shapes                # noqa: E402
from tools.cli_smoke import smoke_test_cli                 # noqa: E402
from tools.feature_coverage import check_feature_coverage  # noqa: E402
from tools.package_smoke import smoke_test_package         # noqa: E402
from tools.runtime_smoke import smoke_test_app             # noqa: E402
from tools.sql_schema_check import check_project_sql       # noqa: E402
from tools.generated_tests import run_generated_tests      # noqa: E402
from tools.module_ref_check import check_module_refs        # noqa: E402
from tools.static_smoke import smoke_test_static           # noqa: E402
from tools.verification import VerificationOutcome         # noqa: E402
from tools.web_asset_check import check_web_assets         # noqa: E402

try:
    from tools.schema_attr_check import check_schema_attributes
except Exception:                                    # not written yet
    check_schema_attributes = None

OUT = Path(config.OUTPUT_DIR)

# Not projects. `platform.db` is the real platform database; a clone of it
# proves nothing.
_NOT_PROJECTS = {"__pycache__", "platform.db", "token_ledger.json"}

# The clone prefix. Anything wearing it is this script's own scratch space and
# is never itself treated as a project — a crashed run leaves one behind.
_CLONE_PREFIX = "_corpus_probe_"

# `tools/verify_repairs.py` clones the same corpus for a different question, so
# its scratch space must not read as a project here either. A crashed run of
# EITHER tool leaves clones behind, and one probe measuring another probe's
# leftovers is how a corpus stops being evidence.
_REPAIR_PREFIX = "_repair_probe_"
_PROBE_PREFIXES = (_CLONE_PREFIX, _REPAIR_PREFIX)

# Intents the corpus cannot recover. `projects.prompt` is stored but the feature
# list the analyser produced is not, so feature_coverage would answer "not
# applicable" for every build and check nothing. This sidecar carries the
# requested features for the anchor fixtures, so the check is exercised on the
# builds whose behaviour is documented.
_INTENTS_FILE = Path(__file__).resolve().parent.parent / "corpus_intents.json"


def _load_intents() -> dict:
    try:
        return json.loads(_INTENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def project_names(only: str = "") -> list[str]:
    names = []
    for path in sorted(OUT.iterdir()):
        if not path.is_dir():
            continue
        if path.name in _NOT_PROJECTS or path.name.startswith(_PROBE_PREFIXES):
            continue
        if only and only not in path.name:
            continue
        names.append(path.name)
    return names


def _clone(name: str, prefix: str = _CLONE_PREFIX,
           src: Path | None = None) -> str:
    """A pristine copy under OUTPUT_DIR, since every verifier takes a root
    relative to it. Returns the clone's folder name.

    `src` allows a fixture that lives outside the corpus to be staged the same
    way; `prefix` is a parameter so `verify_repairs.py` can reuse this — the
    stripping below (caches, node_modules, and any database an earlier probe
    left behind) is exactly as necessary when the question is "does a repair
    make things worse" as when it is "does a checker tell the truth"."""
    dest = OUT / f"{prefix}{name}"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(
        src if src is not None else OUT / name, dest,
        ignore=shutil.ignore_patterns("__pycache__", "node_modules", ".git",
                                      "venv", "*.pyc"),
    )
    # A shipped artifact is code. A database left behind by an earlier probe is
    # state, and it makes "does this app work" depend on who ran it last.
    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        for stale in dest.rglob(pattern):
            try:
                stale.unlink()
            except Exception:
                pass
    return dest.name


def _outcome_record(o: VerificationOutcome) -> dict:
    return {
        "status":   o.status.value,
        "detail":   o.detail,
        "findings": sorted(o.findings),
    }


def _unclone(record: dict, name: str) -> dict:
    """Put the real project name back into every path a verifier reported.

    Findings quote OUTPUT_DIR-relative paths, which on a clone name the clone.
    Left alone, a baseline would be pinned to the scratch prefix and every
    finding would read as being about a directory that no longer exists.
    """
    clone = f"{_CLONE_PREFIX}{name}"

    def fix(text: str) -> str:
        return text.replace(clone, name)

    for check in record.get("checks", {}).values():
        check["detail"] = fix(check.get("detail", ""))
        check["findings"] = sorted(fix(f) for f in check.get("findings", []))
    return record


def _runtime_record(root: str) -> dict:
    """The web probe, in the same shape as a VerificationOutcome.

    It still returns a bare SmokeResult, so translate here rather than pretend
    the two already speak the same language.
    """
    smoke = smoke_test_app(root)
    if not smoke.ran or not smoke.entry:
        return {"status": "not_applicable" if not smoke.entry else "not_run",
                "detail": smoke.summary(), "findings": []}
    if not smoke.app_loaded:
        return {"status": "failed", "detail": smoke.summary(),
                "findings": [f"the application does not start: {smoke.error[:160]}"]}
    if not smoke.probes:
        return {"status": "failed", "detail": smoke.summary(),
                "findings": ["the application starts but declares no routes"]}
    findings = [f"{p.method} {p.path} -> {p.status}" for p in smoke.failures]
    return {
        "status":   "failed" if findings else "verified",
        "detail":   smoke.summary(),
        "findings": sorted(findings),
    }


def _sql_record(root: str) -> dict:
    project_dir = OUT / root
    files = [
        str(p.relative_to(OUT)).replace("\\", "/")
        for p in sorted(project_dir.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]
    report = check_project_sql(root, files)
    findings = sorted(str(i) for i in getattr(report, "issues", []))
    findings += sorted(str(m) for m in getattr(report, "missing", []))
    if findings:
        return {
            "status":   "failed",
            "detail":   f"{len(files)} python file(s) scanned",
            "findings": findings,
        }

    # "Nothing to check" is not "checked and sound". `project` and `todo_app`
    # contain no code at all — only handoff markdown — and this reported
    # `verified` for both, which was the only verified check they had and was
    # enough to pass the row criterion. A check with no subject must say so,
    # the way `schema_attr` and `web_assets` already do.
    has_sql = bool(getattr(report, "tables", None)) or bool(
        getattr(report, "statements", None))
    if not files or not has_sql:
        return {
            "status":   "not_applicable",
            "detail":   ("this project contains no SQL to check"
                         if files else "this project contains no python files"),
            "findings": [],
        }

    return {
        "status":   "verified",
        "detail":   f"{len(files)} python file(s) scanned",
        "findings": findings,
    }


def _guarded(check: str, fn, root: str) -> dict:
    """A verifier that raises is NOT_RUN, never a pass. Same rule the pipeline
    applies — a crashed check is a hole in the evidence."""
    try:
        return _outcome_record(fn(root))
    except Exception as e:
        return {"status": "not_run", "findings": [],
                "detail": f"the check itself raised {type(e).__name__}: {e}"}


def verify_one(name: str, intents: dict, keep: bool = False) -> dict:
    clone = _clone(name)
    try:
        shapes = detect_shapes(OUT / clone, rel_to=OUT)
        record = {"shape": shapes.describe(), "checks": {}}

        record["checks"]["runtime_smoke"] = _runtime_record(clone)
        for check, fn in (
            ("cli_smoke",     smoke_test_cli),
            ("web_assets",    check_web_assets),
            ("package_smoke", smoke_test_package),
            ("generated_tests", run_generated_tests),
            ("static_smoke",    smoke_test_static),
            ("module_ref",      check_module_refs),
        ):
            record["checks"][check] = _guarded(check, fn, clone)

        intent = intents.get(name, {})
        record["checks"]["feature_coverage"] = _guarded(
            "feature_coverage", lambda r: check_feature_coverage(r, intent), clone)

        record["checks"]["sql_schema"] = _sql_record(clone)

        if check_schema_attributes is not None:
            record["checks"]["schema_attr"] = _guarded(
                "schema_attr", check_schema_attributes, clone)

        return _unclone(record, name)
    finally:
        if not keep:
            shutil.rmtree(OUT / clone, ignore_errors=True)


# ── Reporting ─────────────────────────────────────────────────────────────────

_MARK = {"verified": "OK  ", "not_applicable": "n/a ",
         "not_run": "??  ", "failed": "FAIL"}


def print_table(results: dict) -> None:
    for name, record in results.items():
        print(f"\n{name}  [{record['shape']}]")
        for check, r in record["checks"].items():
            mark = _MARK.get(r["status"], "    ")
            head = f"  {mark} {check:<17} {r['status']:<15}"
            if r["findings"]:
                head += f"{len(r['findings'])} finding(s)"
            print(head)
            for finding in r["findings"][:3]:
                print(f"         - {finding[:150]}")
            if len(r["findings"]) > 3:
                print(f"         - ... {len(r['findings']) - 3} more")


def diff(baseline: dict, current: dict) -> list[str]:
    """Every way the two disagree, in words an operator can act on."""
    changes: list[str] = []
    for name in sorted(set(baseline) | set(current)):
        if name not in current:
            changes.append(f"{name}: gone from the corpus")
            continue
        if name not in baseline:
            changes.append(f"{name}: new in the corpus (no baseline)")
            continue
        old, new = baseline[name], current[name]
        if old.get("shape") != new.get("shape"):
            changes.append(
                f"{name}: shape {old.get('shape')!r} -> {new.get('shape')!r}")
        for check in sorted(set(old["checks"]) | set(new["checks"])):
            o = old["checks"].get(check)
            n = new["checks"].get(check)
            if o is None:
                changes.append(f"{name}/{check}: new check ({n['status']})")
                continue
            if n is None:
                changes.append(f"{name}/{check}: check no longer runs")
                continue
            if o["status"] != n["status"]:
                changes.append(f"{name}/{check}: {o['status']} -> {n['status']}")
            for f in [f for f in n["findings"] if f not in o["findings"]]:
                changes.append(f"{name}/{check}: NEW finding: {f[:160]}")
            for f in [f for f in o["findings"] if f not in n["findings"]]:
                changes.append(f"{name}/{check}: finding GONE: {f[:160]}")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description="Run every verifier against every saved build.")
    ap.add_argument("--json", metavar="PATH", help="write the full result")
    ap.add_argument("--baseline", metavar="PATH",
                    help="diff against a recorded result; exit 1 on any change")
    ap.add_argument("--only", default="", metavar="SUBSTRING")
    ap.add_argument("--keep-clones", action="store_true",
                    help="leave the probe clones on disk for inspection")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    intents = _load_intents()
    names = project_names(args.only)
    if not names:
        print(f"No projects found in {OUT}")
        return 1

    results: dict = {}
    for i, name in enumerate(names, 1):
        if not args.quiet:
            print(f"[{i}/{len(names)}] {name}", flush=True)
        try:
            results[name] = verify_one(name, intents, keep=args.keep_clones)
        except Exception as e:
            results[name] = {"shape": "unreadable", "checks": {
                "corpus_runner": {"status": "not_run", "findings": [],
                                  "detail": f"{type(e).__name__}: {e}"}}}

    if not args.quiet:
        print_table(results)

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nWrote {args.json}")

    if args.baseline:
        base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        changes = diff(base, results)
        print(f"\n{'=' * 70}")
        if not changes:
            print("  No change against the baseline.")
            return 0
        print(f"  {len(changes)} change(s) against the baseline — explain each:")
        for c in changes:
            print(f"    * {c}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
