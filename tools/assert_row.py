"""tools/assert_row.py — the §B2 assertion table, executable.

Three handoffs have asked a reader to run these by hand. This runs all of them
against a finished build and says which failed, reading the verification record
from the API and re-checking the artifact on disk rather than trusting either
alone. Costs nothing: no LLM, no tokens.

    venv/Scripts/python.exe tools/assert_row.py <build_id> [server_log]
"""
import json, re, sys, urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\programes\comppython\Aiautonomous")
import config
sys.path.insert(0, str(Path(config.OUTPUT_DIR).parent))

BUILD = sys.argv[1]
LOG = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("server_row3_rerun.log")
OUT = Path(config.OUTPUT_DIR)

PASS, FAIL, NOTE = [], [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}]  {name}" + (f"  — {detail}" if detail else ""))
def note(name, detail):
    NOTE.append(name); print(f"  [note]  {name}: {detail}")

d = json.load(urllib.request.urlopen(f"http://localhost:8000/jobs/{BUILD}/status", timeout=20))
root = (d.get("output_path") or "").replace("\\", "/").split("/")[-1]
outcomes = d.get("verification") or []
by = {o["check"]: o for o in outcomes}

print(f"\n=== {BUILD}  ({root}) ===")
print(f"status: {d.get('status')}  |  shape: {d.get('build_shape')}")
print(f"smoke:  {d.get('smoke_summary')}")
print(f"reason: {d.get('completion_reason')}")
print(f"scores: debug {d.get('debug_score')}  review {d.get('review_score')}  test {d.get('test_score')}")
print()
for o in outcomes:
    print(f"  {o['status']:<16} {o['check']:<18} {o.get('detail','')}")
    for f in (o.get("findings") or [])[:3]:
        print(f"        - {str(f)[:150]}")
print()

# ── the driver's own verdict, from its own code ──────────────────────────────
sys.path.insert(0, r"C:\programes\comppython\Aiautonomous")
from run_live_matrix import verification_verdict, MANUAL_CHECKS
passes, why = verification_verdict({"verification": outcomes})
print(f"driver verdict: {'PASS' if passes else 'FAIL'} — {why}\n")

print("=== §B2 assertions ===")
check("terminal state is not `unusable`", d.get("status") != "unusable", str(d.get("status")))
check("zero not_run outcomes",
      not [o for o in outcomes if o["status"] == "not_run"],
      str([o["check"] for o in outcomes if o["status"] == "not_run"]))
check("module_ref is verified, not failed",
      by.get("module_ref", {}).get("status") == "verified",
      str(by.get("module_ref", {}).get("status")))
check("schema_attr reports nothing and is not not_applicable",
      by.get("schema_attr", {}).get("status") == "verified",
      str(by.get("schema_attr", {}).get("status")))
check("dead_events is verified or not_applicable, never failed",
      by.get("dead_events", {}).get("status") in ("verified", "not_applicable"),
      str(by.get("dead_events", {}).get("status")))
ran = [o for o in outcomes if o["status"] == "verified"
       and o["check"] in ("runtime_smoke", "cli_smoke", "package_smoke", "static_smoke")]
check("at least one check EXECUTED the artifact", bool(ran), str([o["check"] for o in ran]))
manual_failed = [o["check"] for o in outcomes
                 if o["check"] in MANUAL_CHECKS and o["status"] == "failed"]
note("checks routed to manual testing", str(manual_failed) or "none")

# ── the artifact itself ──────────────────────────────────────────────────────
print("\n=== the shipped artifact ===")
proj = OUT / root
pys = [p for p in proj.rglob("*.py") if "__pycache__" not in p.parts]
check("the project shipped python files", bool(pys), f"{len(pys)} file(s)")

# `include_router(router)` is CORRECT when the project defines one router and
# main.py does `from routes import router`. The §4.38 defect was a MULTI-router
# build whose five distinct aliases were all rewritten to the bare name, leaving
# four unbound. So the assertion is: no more routers defined than included, and
# every included name is bound where it is used. Counting the string alone
# reports a correct single-router build as broken, which this did on first use.
defined_routers, bare_includes, total_includes = 0, 0, 0
BOUND = re.compile(r"^[ \t]*(from .*import .*router|router[ ]*=)", re.M)
DEFINED = re.compile(r"^[ \t]*\w+[ ]*=[ ]*APIRouter\(", re.M)
INCLUDE = re.compile(r"include_router\([ ]*(\w+)")
for p in pys:
    text = p.read_text(encoding="utf-8", errors="ignore")
    defined_routers += len(DEFINED.findall(text))
    total_includes  += text.count("include_router(")
    for m in INCLUDE.finditer(text):
        if m.group(1) == "router" and not BOUND.search(text):
            bare_includes += 1
check("every included router name is bound in the file that includes it",
      bare_includes == 0, f"{bare_includes} unbound")
check("no router defined in the project goes un-included",
      total_includes >= defined_routers,
      f"{defined_routers} defined, {total_includes} included")
note("router shape", f"{defined_routers} router(s) defined, {total_includes} include(s)"
     + ("  — a single-router build exercises the alias case weakly"
        if defined_routers <= 1 else ""))

# module_ref, re-run against the shipped tree rather than trusting the record
from tools.module_ref_check import check_module_refs
live = check_module_refs(root)
check("module_ref re-run on disk agrees with the record",
      (live.status.value if hasattr(live.status, "value") else str(live.status)).lower().endswith(
          "verified" if by.get("module_ref", {}).get("status") == "verified" else "failed"),
      f"{live.status} with {len(live.findings)} finding(s)")

# dead_events on disk. Row 3's third run shipped an app that served nothing with
# four checks verified on it, so "the record says verified" is exactly the claim
# that needs re-checking against the artifact.
from tools.dead_event_check import check_dead_events
ev = check_dead_events(root)
check("no startup handler on disk is disabled by a supplied lifespan",
      not ev.findings, f"{ev.status} with {len(ev.findings)} finding(s)")
for f in ev.findings[:3]:
    print(f"        - {str(f)[:150]}")

# ── the log, which is readable now ───────────────────────────────────────────
print("\n=== the build log ===")
if LOG.is_file() and LOG.stat().st_size > 4000:
    text = LOG.read_text(encoding="utf-8", errors="ignore")
    check("phantom-defect count (`does not parse`) is 0",
          text.count("does not parse") == 0, str(text.count("does not parse")))
    fired = text.count("LLM completing:")
    note("definition repairs attempted", str(fired))
    note("definition repairs applied", str(text.count("Definition repair applied")))
    note("names added", str(text.count("Added ")))
    ratios = [l for l in text.splitlines() if "repair_guard:" in l]
    note("repair_guard near-miss lines (RATIO_LOG)", str(len(ratios)))
    for l in ratios[:5]:
        print(f"        {l.strip()[:150]}")
    no_leak = [l for l in text.splitlines()
               if "Aiautonomous" in l and "generated_projects" not in l
               and ("Traceback" in l or ".py\", line" in l)]
    check("no traceback names a repo file outside generated_projects",
          not no_leak, str(no_leak[:2]))
else:
    note("log", f"{LOG} is {LOG.stat().st_size if LOG.is_file() else 0} bytes — not usable")

print(f"\n{'='*60}")
print(f"  {len(PASS)} passed, {len(FAIL)} failed, {len(NOTE)} noted")
if FAIL:
    for f in FAIL: print(f"  [FAIL] {f}")
print(f"{'='*60}")
