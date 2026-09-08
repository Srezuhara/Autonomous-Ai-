"""
Phase 23 A2 — the live build matrix
====================================
Four builds of deliberately different shape, run sequentially against a live
server, with the result of each recorded from the database rather than from
whatever the API happened to say at the time.

The pass criterion was fixed before any build ran (`PHASE23_PLAN.md` A2):

    >= 3 of 4 reach `done` or `done_with_context` with a downloadable ZIP, and
    every build that boots reports 0 5xx from the runtime smoke test.

Run:
    venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1
    venv/Scripts/python.exe run_live_matrix.py                # all four rows
    venv/Scripts/python.exe run_live_matrix.py --rows 1,2     # just those
    venv/Scripts/python.exe run_live_matrix.py --dry-run      # no tokens spent

Budget reality: a build costs roughly 85-110K tokens against 200K per model per
day, so the whole matrix needs close to a full day's quota on both models. The
driver reads `/health` before each row and stops rather than starting a build it
cannot finish — a half-spent build teaches nothing and costs the same. The
floors are per model and the FAST one is the binding constraint; see
MIN_FAST_TOKENS_TO_START.

Both halves of the criterion are read from the API. The second — did the thing
that was built actually run — used to exist only in the server log, so this
driver could not evaluate its own criterion and said so in its report.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "http://localhost:8000"

# Enough headroom for one build. Below this, starting a row buys a quota wall
# rather than a result.
#
# There are two floors because there are two budgets, and the gate used to read
# the wrong one: it took `max()` across models, so a row started whenever EITHER
# model was rich. The split has since inverted — the tester, the reviewer and
# every remediation pass run on the fast model, and row 3 spent 97.5K on 20b
# against 38.5K on 120b. On 2026-08-30 a row started with the fast model at
# 73,286, ran it dry during the tester, and finished only because the dual-model
# fallback carried it to the heavy model. That is the safety net working, not
# the plan working.
#
# 90,000 is that measurement rounded up: the row cost 109,206 tokens in total
# and the fast model was the half that ran out.
MIN_FAST_TOKENS_TO_START  = 90_000
MIN_HEAVY_TOKENS_TO_START = 70_000

# Kept as the name older docs cite, and as the floor for a model the config does
# not identify as fast or heavy.
MIN_TOKENS_TO_START = MIN_HEAVY_TOKENS_TO_START

POLL_SECONDS = 15
BUILD_TIMEOUT_SECONDS = 45 * 60

#: The statuses a build can end on. Imported from the runner so this file and
#: the server cannot drift into two different ideas of when a build is over.
#:
#: They HAD drifted: the driver hardcoded four of the five and omitted
#: `unusable`, which is the status a build reaches precisely when the artifact
#: does not run. Row 2 on 2026-09-08 finished `unusable` in 28 minutes and the
#: driver went on polling a finished build until BUILD_TIMEOUT_SECONDS — 45
#: wasted minutes on the one row shape you most want to iterate on, and the
#: report was written 17 minutes after the build was already recorded.
try:
    from api_platform.runner import TERMINAL_STATUSES
except Exception:  # the driver must still run if the import path is odd
    TERMINAL_STATUSES = ("done", "done_with_context", "unusable",
                         "failed", "cancelled")

# The four shapes, and what each one is here to exercise. Row 2 and row 4 have
# never run: between them they hold every unknown this matrix exists to remove.
MATRIX = [
    {
        "row": 1,
        "shape": "simple FastAPI + SQLite CRUD",
        "exercises": "baseline; the runtime smoke test; the entry-point fix",
        "prompt": (
            "A simple FastAPI task manager with SQLite. One Task entity: id, "
            "title, done, created_at. CRUD endpoints to create, list, get, "
            "update and delete a task."
        ),
        "expect_boot": True,
    },
    {
        "row": 2,
        "shape": "medium FastAPI + JS frontend",
        "exercises": "frontend_generator, frontend_debugger, dangling-import guard",
        "prompt": (
            "A bookmark manager: FastAPI backend with SQLite storing bookmarks "
            "(id, url, title, tags, created_at) with full CRUD and tag "
            "filtering, plus a plain HTML/CSS/JavaScript frontend that lists "
            "bookmarks, adds one through a form and filters by tag."
        ),
        "expect_boot": True,
    },
    {
        "row": 3,
        "shape": "complex / multi-entity",
        "exercises": "the architecture cap at `complex`; architect variance",
        "prompt": (
            "An inventory system with FastAPI and SQLite covering four related "
            "entities — Supplier, Product, StockMovement and Warehouse — with "
            "CRUD for each, stock level queries per warehouse and a low-stock "
            "report endpoint."
        ),
        "expect_boot": True,
    },
    {
        "row": 4,
        "shape": "non-FastAPI (CLI)",
        "exercises": "the documented blind spot — the smoke test must skip cleanly",
        "prompt": (
            "A Python command line tool that renames files in bulk. It takes a "
            "directory, a match pattern and a replacement, supports a dry-run "
            "flag and writes an undo log so a rename can be reversed."
        ),
        "expect_boot": False,
    },
]


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get(path: str, timeout: int = 30):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(path: str, body: dict, timeout: int = 60):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def check_zip(build_id: str) -> dict:
    """
    Is the download a real archive?

    The route is `GET /projects/{id}/download`. There is no `/downloads/{id}`,
    and a wrong path used to come back as the SPA shell with HTTP 200 — so this
    checks the ZIP magic bytes, never the status code.
    """
    url = f"{BASE}/projects/{build_id}/download"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/zip"})
        with urllib.request.urlopen(req, timeout=120) as r:
            head = r.read(4)
            rest = r.read()
            return {
                "ok": head == b"PK\x03\x04",
                "status": r.status,
                "content_type": r.headers.get("content-type", ""),
                "bytes": len(head) + len(rest),
            }
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "content_type": "", "bytes": 0}
    except Exception as e:
        return {"ok": False, "status": 0, "content_type": str(e)[:60], "bytes": 0}


# ── Quota ─────────────────────────────────────────────────────────────────────

def daily_usage() -> dict:
    try:
        health = _get("/health")
    except Exception as e:
        print(f"  ! /health unreadable: {e}")
        return {}
    llm = health.get("llm") or {}
    return llm.get("daily_usage") or health.get("daily_usage") or {}


def print_quota(label: str) -> dict:
    usage = daily_usage()
    models = usage.get("models") or {}
    if not models:
        print(f"  {label}: no daily figures available")
        return models
    print(f"  {label}:")
    for model, rec in sorted(models.items()):
        estimated = (
            f", {rec['seeded_tokens']:,} reconstructed"
            if rec.get("seeded_tokens") else ""
        )
        print(
            f"    {model}: {rec.get('tokens_used', 0):,} used "
            f"({rec.get('percent_used', 0)}%), "
            f"{rec.get('tokens_remaining', 0):,} left{estimated}"
        )
    return models


def model_roles() -> tuple:
    """
    `(fast model id, heavy model id)` as this checkout is configured.

    Read from `llm_client`, which is where the split actually lives — `config`
    only knows a single `GROQ_MODEL`. Getting this wrong is silent and costs the
    whole point of the two floors: every model falls through to "unclassified"
    and the fast one is gated at the heavy floor again.
    """
    try:
        import llm_client
        return llm_client._FAST_MODEL, llm_client._HEAVY_MODEL
    except Exception:
        import os
        return (os.getenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b"),
                os.getenv("GROQ_MODEL_HEAVY", "openai/gpt-oss-120b"))


def budget_blocks_start(models: dict) -> str:
    """
    The reason not to start a build, or an empty string.

    Both models are checked against their own floor. Taking the best across
    models answers "is there budget somewhere", which is not the question — a
    row needs the FAST model most, and it is the one that runs out.
    """
    if not models:
        return ""          # no figures is not evidence of no budget

    fast, heavy = model_roles()
    blocked = []
    for model, rec in sorted(models.items()):
        left = rec.get("tokens_remaining", 0)
        if model == fast:
            floor, role = MIN_FAST_TOKENS_TO_START, "fast"
        elif model == heavy:
            floor, role = MIN_HEAVY_TOKENS_TO_START, "heavy"
        else:
            floor, role = MIN_TOKENS_TO_START, "unclassified"
        if left < floor:
            blocked.append(
                f"the {role} model {model} has {left:,} left, under its "
                f"{floor:,} floor"
            )
    return "; ".join(blocked)


# ── One row ───────────────────────────────────────────────────────────────────

def run_row(entry: dict) -> dict:
    print(f"\n{'=' * 70}")
    print(f"  Row {entry['row']} — {entry['shape']}")
    print(f"  Exercises: {entry['exercises']}")
    print(f"{'=' * 70}")

    started = _post("/projects/", {"prompt": entry["prompt"]})
    build_id = started["build_id"]
    print(f"  build_id: {build_id}")

    began = time.time()
    last_step = None
    while True:
        time.sleep(POLL_SECONDS)
        try:
            status = _get(f"/jobs/{build_id}/status")
        except Exception as e:
            print(f"  ! status unreadable: {e}")
            continue

        step = status.get("current_step")
        if step != last_step:
            print(f"  step {step}  ({int(time.time() - began)}s elapsed)")
            last_step = step

        state = (status.get("status") or "").lower()
        if state in TERMINAL_STATUSES:
            break
        if time.time() - began > BUILD_TIMEOUT_SECONDS:
            print(f"  ! giving up after {BUILD_TIMEOUT_SECONDS}s")
            break

    # The database is the record, not the poll response.
    project = _get(f"/projects/{build_id}")
    zip_result = check_zip(build_id)

    # Whether the thing that was built actually runs. This half of the criterion
    # used to live only in the server log, so the driver could not evaluate it
    # and the report had to send the operator to `grep`. /jobs/{id}/status
    # parses the stored VerificationOutcome list.
    verification, smoke_summary, build_shape = [], "", ""
    try:
        detail = _get(f"/jobs/{build_id}/status")
        verification  = detail.get("verification") or []
        smoke_summary = detail.get("smoke_summary") or ""
        build_shape   = detail.get("build_shape") or ""
    except Exception as e:
        print(f"  ! verification record unreadable: {e}")
    result = {
        "row": entry["row"],
        "shape": entry["shape"],
        "build_id": build_id,
        "status": project.get("status"),
        "completion_reason": project.get("completion_reason"),
        "progress_percent": project.get("progress_percent"),
        "duration_seconds": project.get("duration_seconds"),
        "total_tokens": project.get("total_tokens"),
        "tokens_by_model": project.get("tokens_by_model"),
        "file_count": project.get("file_count"),
        "zip": zip_result,
        "expect_boot": entry["expect_boot"],
        "verification": verification,
        "smoke_summary": smoke_summary,
        "build_shape": build_shape,
    }
    print(
        f"  -> {result['status']}  "
        f"{(result['total_tokens'] or 0):,} tokens  "
        f"{(result['duration_seconds'] or 0):.0f}s  "
        f"zip={'ok' if zip_result['ok'] else 'NOT A ZIP'} "
        f"({zip_result['bytes']:,} bytes)"
    )
    if result["completion_reason"]:
        print(f"     reason: {result['completion_reason']}")
    verdict, why = verification_verdict(result)
    print(f"     verified: {'yes' if verdict else 'NO'} — {why}")
    return result


# ── The second half of the criterion ──────────────────────────────────────────

#: Checks that are reported but do not decide a row. See `verification_verdict`.
#:
#: Must match `Pipeline._MANUAL_WHEN_WORKING`. §4.39 is what happens when the
#: record and the thing reading it disagree: a check the pipeline had routed to
#: manual testing still read as `failed` here, and would have failed a working
#: row. `feature_coverage` was added to both on 2026-09-01.
MANUAL_CHECKS = ("generated_tests", "feature_coverage")

#: Checks that RUN the artifact rather than reading it. Imported so this file
#: and the pipeline cannot drift into two different ideas of what counts as
#: evidence.
try:
    from tools.verification import EXECUTING_CHECKS
except Exception:  # the driver must still run if the import path is odd
    EXECUTING_CHECKS = frozenset({
        "runtime_smoke", "cli_smoke", "package_smoke", "generated_tests"})


def verification_verdict(row: dict) -> tuple:
    """
    `(passes, why)` for "does the thing this row built actually run".

    The first half of the criterion — a terminal state and a valid ZIP — was
    always measurable and was always the only half measured. Row 3 passed it on
    2026-08-28 while shipping twelve endpoints that returned 500.

    A row passes here when every check that ran either verified the artifact or
    correctly did not apply, AND at least one check actually executed it. The
    second clause is the point: four not-applicables are not evidence of
    anything, and NOT_RUN is a hole, never a pass.

    One check is excluded, deliberately (2026-08-31). `generated_tests` runs the
    suite the build *ships*, which is not the same question as whether the thing
    it built works — 34 of 41 saved builds fail it while serving every route
    they declare. Counting it here would fail rows whose application is
    demonstrably sound, and the pipeline already treats it the same way: those
    findings do not degrade a build that another check has executed and found
    working, they are handed to the user as manual testing. The result is still
    reported on every row, because a suite nobody can run is worth knowing about
    — it just does not decide the row.
    """
    outcomes = row.get("verification") or []
    if not outcomes:
        return False, ("no verification record — this build is unverified, or "
                       "it predates the record")

    judged  = [o for o in outcomes if o.get("check") not in MANUAL_CHECKS]
    failed  = [o for o in judged if o.get("status") == "failed"]
    not_run = [o for o in judged if o.get("status") == "not_run"]
    # "at least one check actually executed it" has to mean that. A verified
    # `sql_schema` or `feature_coverage` says the source reads correctly and
    # nothing was ever run: `project` and `todo_app` both passed this criterion
    # on `sql_schema` alone.
    ran     = [o for o in judged
               if o.get("status") == "verified"
               and o.get("check") in EXECUTING_CHECKS]
    inspected = [o for o in judged if o.get("status") == "verified"]

    noted = [
        o for o in outcomes
        if o.get("check") in MANUAL_CHECKS and o.get("status") == "failed"
    ]
    suffix = ""
    if noted:
        suffix = ("; for manual testing: "
                  + ", ".join(o.get("check", "?") for o in noted))

    if failed:
        return False, ("failed: "
                       + ", ".join(o.get("check", "?") for o in failed) + suffix)
    if not_run:
        return False, ("never ran: "
                       + ", ".join(o.get("check", "?") for o in not_run) + suffix)
    if not ran:
        if inspected:
            return False, (
                "nothing executed the artifact — it was only read statically ("
                + ", ".join(o.get("check", "?") for o in inspected) + ")" + suffix)
        return False, ("nothing executed the artifact — every check answered "
                       "'not applicable'" + suffix)
    return True, ("verified by "
                  + ", ".join(o.get("check", "?") for o in ran) + suffix)


# ── Report ────────────────────────────────────────────────────────────────────

def merge_previous(results: list, path: Path) -> list:
    """
    Carry forward rows from an earlier invocation that this one did not re-run.

    The driver used to overwrite its report wholesale, so `--rows 1` followed by
    `--rows 2,3` left a file describing rows 2 and 3 and no trace of row 1 —
    which is exactly what happened on 2026-08-28. Rows are keyed by number, and
    a row re-run always wins over the record of it.
    """
    if not path.is_file():
        return results

    fresh = {r["row"] for r in results}
    kept = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            # The table gained a Verified column, so the parser has to as
            # well. A carried row keeps its verdict as text and NOT as a
            # verification record: it was earned by a run this one did not
            # watch, and inventing outcomes for it would let a carried row
            # claim evidence nobody has.
            # The ZIP cell of a carried row is written as `yes *(earlier run)*`,
            # so the pattern has to accept the marker this file itself emits.
            # It did not: a row carried once was dropped the NEXT time the
            # driver ran, silently and with no exception to report, because a
            # non-matching line is simply skipped. On 2026-09-08 that erased
            # row 3 — a passing row — from the matrix, which is how a phase
            # criterion gets re-earned with a 130,000-token rebuild that had
            # already been paid for once.
            m = re.match(r"^\| (\d+) \| ([^|]+)\| `([^`]+)` \| (\w+) \| ([\d,]+) \|"
                         r" ([\d.]+)s \| ([^|]+)\| (\w+)"
                         r"(?: \*\(earlier run\)\*)? \|$", line.strip())
            if not m or int(m.group(1)) in fresh:
                continue
            kept.append({
                "row": int(m.group(1)), "shape": m.group(2).strip(),
                "status": m.group(3), "total_tokens": int(m.group(5).replace(",", "")),
                "duration_seconds": float(m.group(6)),
                "file_count": m.group(7).strip(),
                "zip": {"ok": m.group(8) == "yes", "status": "—",
                        "content_type": None, "bytes": 0},
                "build_id": "(from an earlier run)", "completion_reason": "",
                "progress_percent": None, "tokens_by_model": None,
                "expect_boot": True, "carried": True,
                "verification": [], "smoke_summary": "", "build_shape": "",
                "carried_verified": m.group(4) == "yes",
            })
    except Exception as e:
        print(f"  (could not merge previous report: {e})")
        return results

    if kept:
        print(f"  carried forward {len(kept)} row(s) from the previous report")
    return sorted(results + kept, key=lambda r: r["row"])


def write_report(results: list, path: Path) -> None:
    ok_states = {"done", "done_with_context"}
    shipped = [
        r for r in results
        if r["status"] in ok_states and r["zip"]["ok"]
    ]
    verdicts = {}
    for r in results:
        if r.get("carried"):
            ok = bool(r.get("carried_verified"))
            verdicts[r["row"]] = (
                ok, "as recorded by the run that produced it")
        else:
            verdicts[r["row"]] = verification_verdict(r)
    passing = [r for r in shipped if verdicts[r["row"]][0]]
    lines = [
        "# Phase 23 A2 — live matrix results",
        "",
        f"*Run {datetime.now().isoformat(timespec='seconds')}*",
        "",
        "Pass criterion (fixed before any build ran): **>= 3 of 4** reach `done` "
        "or `done_with_context` with a downloadable ZIP, and every build that "
        "boots reports **0 5xx** from the runtime smoke test.",
        "",
        f"**Result: {len(passing)} of {len(results)} rows meet BOTH halves"
        f"{' (matrix incomplete)' if len(results) < len(MATRIX) else ''}.** "
        f"{len(shipped)} shipped a valid ZIP.",
        "",
        "> Both halves are now read from the API. The second one — did the "
        "artifact actually run — used to exist only as a line in the server "
        "log, so this file reported the first half and told the reader to grep "
        "for the rest. A row passes it when every check either verified the "
        "artifact or correctly did not apply, and at least one check executed "
        "it: four not-applicables are not evidence, and a check that never ran "
        "is a hole, not a pass. `generated_tests` is reported but does not "
        "decide a row — it asks whether the suite the build *ships* runs, not "
        "whether the thing built works, and a build can serve every route it "
        "declares while its generated tests do not collect.",
        "",
        "| Row | Shape | Status | Verified | Tokens | Duration | Files | ZIP |",
        "|-----|-------|--------|----------|--------|----------|-------|-----|",
    ]
    for r in results:
        ok, why = verdicts[r["row"]]
        lines.append(
            f"| {r['row']} | {r['shape']} | `{r['status']}` | "
            f"{'yes' if ok else 'NO'} | "
            f"{(r['total_tokens'] or 0):,} | "
            f"{(r['duration_seconds'] or 0):.0f}s | {r.get('file_count', '—')} | "
            f"{'yes' if r['zip']['ok'] else 'NO'}"
            f"{' *(earlier run)*' if r.get('carried') else ''} |"
        )
    lines += [
        "",
        "## Per-row detail",
        "",
    ]
    for r in results:
        if r.get("carried"):
            continue          # its detail belongs to the run that produced it
        lines += [
            f"### Row {r['row']} — {r['shape']}",
            "",
            f"- build_id: `{r['build_id']}`",
            f"- status: `{r['status']}`"
            + (f" — {r['completion_reason']}" if r["completion_reason"] else ""),
            f"- progress: {r.get('progress_percent') or '—'}%",
            f"- tokens by model: `{r.get('tokens_by_model') or '—'}`",
            f"- download: HTTP {r['zip']['status']}, "
            f"{r['zip']['content_type'] or '—'}, {r['zip']['bytes']:,} bytes",
            f"- expected to boot: {'yes' if r['expect_boot'] else 'no (smoke test must skip cleanly)'}",
            f"- build shape: {r.get('build_shape') or '—'}",
            f"- smoke: {r.get('smoke_summary') or '—'}",
            f"- verified: **{'yes' if verdicts[r['row']][0] else 'NO'}** — "
            f"{verdicts[r['row']][1]}",
            "",
        ]
        outcomes = r.get("verification") or []
        if outcomes:
            lines += ["| Check | Status | What it did |",
                      "|---|---|---|"]
            for o in outcomes:
                lines.append(
                    f"| `{o.get('check', '?')}` | {o.get('status', '?')} | "
                    f"{(o.get('detail') or '—').replace('|', '/')} |"
                )
            lines.append("")
            for o in outcomes:
                for finding in (o.get("findings") or [])[:5]:
                    lines.append(f"- 🚨 {finding}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Report written to {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", default="", help="comma-separated row numbers")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and the budget, start nothing")
    parser.add_argument("--out", default="PHASE23_MATRIX_RESULTS.md")
    args = parser.parse_args()

    wanted = (
        [int(x) for x in args.rows.split(",") if x.strip()]
        if args.rows else [e["row"] for e in MATRIX]
    )
    rows = [e for e in MATRIX if e["row"] in wanted]
    if not rows:
        print(f"No rows match {args.rows!r}")
        return 2

    try:
        health = _get("/health")
    except Exception as e:
        print(f"No server at {BASE} ({e}).")
        print("Start it: venv/Scripts/python.exe start_server.py --no-reload --host 127.0.0.1")
        return 2
    print(f"Server: {health.get('status')}  |  rows: {[e['row'] for e in rows]}")
    models = print_quota("quota before")

    if args.dry_run:
        for entry in rows:
            print(f"\n  Row {entry['row']} — {entry['shape']}")
            print(f"    {entry['prompt']}")
        blocked = budget_blocks_start(models)
        print(f"\n  Would start: {'NO — ' + blocked if blocked else 'yes'}")
        return 0

    results = []
    for entry in rows:
        blocked = budget_blocks_start(print_quota("quota now"))
        if blocked:
            print(f"\n  Stopping before row {entry['row']}: {blocked}.")
            print("  A build that runs out mid-flight costs the same and proves nothing.")
            break
        try:
            results.append(run_row(entry))
        except KeyboardInterrupt:
            print("\n  Interrupted.")
            break
        except Exception as e:
            print(f"  ! row {entry['row']} raised: {e}")
            results.append({
                "row": entry["row"], "shape": entry["shape"], "build_id": "—",
                "status": f"driver error: {e}", "completion_reason": None,
                "progress_percent": None, "duration_seconds": 0,
                "total_tokens": 0, "tokens_by_model": None, "file_count": 0,
                "zip": {"ok": False, "status": 0, "content_type": "", "bytes": 0},
                "expect_boot": entry["expect_boot"],
                "verification": [], "smoke_summary": "", "build_shape": "",
            })

    print_quota("quota after")
    if results:
        out_path = Path(args.out)
    write_report(merge_previous(results, out_path), out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
