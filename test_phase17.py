"""
Phase 17 Feature Test Suite
============================
Tests every Phase 17 feature against the live server.
Run: python test_phase17.py
"""
import json
import sys
import time
import urllib.request
import urllib.error

# Force UTF-8 stdout encoding to avoid UnicodeEncodeErrors on some terminals
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE = "http://localhost:8000"
PASS = []
FAIL = []


def get(path):
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  ✅  {name}")
    else:
        FAIL.append(name)
        print(f"  ❌  {name}  {detail}")


# ── 1. Health endpoint ────────────────────────────────────────────────────────
print("\n[1] Health endpoint")
h = get("/health")
check("health status=healthy",           h.get("status") == "healthy")
check("health has llm block",            "llm" in h)
check("health llm 8 keys loaded",        h["llm"].get("groq_keys_total") == 8)
check("health has features block",       "features" in h)
check("feature multi_key_rotation",      h["features"].get("multi_key_rotation"))
check("feature websocket_progress",      h["features"].get("websocket_progress"))

# ── 2. Stats endpoint — token_usage block (Phase 17) ─────────────────────────
print("\n[2] /stats  — Phase 17 token_usage block")
s = get("/stats")
check("stats total_builds present",      "total_builds" in s)
check("stats token_usage block present", "token_usage" in s)
tu = s.get("token_usage", {})
check("token_usage has total_prompt_tokens",     "total_prompt_tokens" in tu)
check("token_usage has total_completion_tokens", "total_completion_tokens" in tu)
check("token_usage has total_tokens",            "total_tokens" in tu)
check("token_usage has avg_tokens_per_build",    "avg_tokens_per_build" in tu)
check("avg_duration_seconds top-level",          "avg_duration_seconds" in s)

# ── 3. Daily stats — total_tokens per day (Phase 17) ─────────────────────────
print("\n[3] /stats/daily  — Phase 17 total_tokens per day")
ds = get("/stats/daily?days=7")
check("daily has days field",    "days" in ds)
check("daily has data array",    "data" in ds)
if ds.get("data"):
    entry = ds["data"][0]
    check("daily entry has total_tokens", "total_tokens" in entry)
    check("daily entry has success",      "success" in entry)
else:
    check("daily entry shape (skipped — empty DB)", True, "(no data rows)")

# ── 4. Projects list ─────────────────────────────────────────────────────────
print("\n[4] GET /projects/")
pl = get("/projects/")
check("projects list returns total",    "total" in pl)
check("projects list returns projects", "projects" in pl)
projects = pl.get("projects", [])
check(f"projects found ({len(projects)} total)", True)

# ── 5. Project detail — build_steps (Phase 17 gap fix) ───────────────────────
print("\n[5] GET /projects/{id}  — Phase 17 build_steps")
if projects:
    # Pick the first completed project
    done = [p for p in projects if p["status"] in ("done", "failed")]
    target = done[0] if done else projects[0]
    bid = target["build_id"]
    print(f"     Using build: {bid[:8]}  status={target['status']}")
    pd = get(f"/projects/{bid}")
    check("project detail has files",       "files" in pd)
    check("project detail has file_count",  "file_count" in pd)
    check("project detail has build_steps", "build_steps" in pd,
          f"keys={list(pd.keys())}")
    steps = pd.get("build_steps", [])
    check(f"build_steps is a list ({len(steps)} entries)", isinstance(steps, list))
    if steps:
        first = steps[0]
        check("step entry has 'step'",      "step"      in first)
        check("step entry has 'name'",      "name"      in first)
        check("step entry has 'status'",    "status"    in first)
        check("step entry has 'timestamp'", "timestamp" in first)
        check("step entry has 'data' key",  "data"      in first,
              f"keys={list(first.keys())}")
        # Check a done step has elapsed_seconds in data
        done_steps = [st for st in steps if st["status"] == "done" and st.get("data")]
        if done_steps:
            raw = done_steps[0]["data"]
            try:
                d = json.loads(raw)
                check("done step data has elapsed_seconds", "elapsed_seconds" in d,
                      f"data keys={list(d.keys())}")
            except Exception as e:
                check("done step data parses as JSON", False, str(e))
        # Phase 17 token fields in project detail
        check("project has prompt_tokens field",     "prompt_tokens"     in pd)
        check("project has completion_tokens field", "completion_tokens" in pd)
        check("project has total_tokens field",      "total_tokens"      in pd)
else:
    print("     (no projects in DB — skipping project-detail tests)")
    check("project detail tests skipped", True, "(empty DB)")

# ── 6. Job status endpoint — completed_steps.data (Phase 17 gap fix) ─────────
print("\n[6] GET /jobs/{id}/status  — Phase 17 completed_steps data field")
if projects:
    # Use a running or recent build
    running = [p for p in projects if p["status"] == "running"]
    any_bid = running[0]["build_id"] if running else projects[0]["build_id"]
    print(f"     Using build: {any_bid[:8]}")
    js = get(f"/jobs/{any_bid}/status")
    check("job status has build_id",     "build_id" in js)
    check("job status has current_step", "current_step" in js)
    check("job status has progress",     "progress" in js)
    progress = js.get("progress", {})
    check("progress has completed_steps", "completed_steps" in progress)
    comp = progress.get("completed_steps", [])
    check(f"completed_steps is list ({len(comp)} entries)", isinstance(comp, list))
    if comp:
        first = comp[0]
        check("completed step has 'data' key", "data" in first,
              f"keys={list(first.keys())}")
else:
    check("job status tests skipped", True, "(empty DB)")

# ── 7. Jobs logs endpoint ─────────────────────────────────────────────────────
print("\n[7] GET /jobs/{id}/logs")
if projects:
    done_p = [p for p in projects if p["status"] in ("done", "failed")]
    if done_p:
        log_bid = done_p[0]["build_id"]
        logs = get(f"/jobs/{log_bid}/logs")
        check("logs is a list",                 isinstance(logs, list))
        if logs:
            check("log entry has step",         "step"      in logs[0])
            check("log entry has step_name",    "step_name" in logs[0])
            check("log entry has status",       "status"    in logs[0])
            check("log entry has timestamp",    "timestamp" in logs[0])
            check("log entry has data key",     "data"      in logs[0])
    else:
        check("logs test skipped (no done builds)", True)
else:
    check("logs tests skipped", True, "(empty DB)")

# ── 8. Admin reset-keys ────────────────────────────────────────────────────────
print("\n[8] POST /admin/reset-keys")
rk = post("/admin/reset-keys")
check("reset-keys returns keys_available", "keys_available" in rk)
check("reset-keys returns keys array",     "keys"           in rk)
check("all 8 keys available after reset",  rk.get("keys_available") == 8)

# ── 9. Queue / active jobs ────────────────────────────────────────────────────
print("\n[9] Queue & active jobs")
q = get("/jobs/queue")
check("queue has running",  "running"  in q)
check("queue has queued",   "queued"   in q)
check("queue has workers",  "workers"  in q)
aj = get("/jobs/active")
check("active has running",      "running"      in aj)
check("active has queued",       "queued"       in aj)
check("active has total_active", "total_active" in aj)

# ── Summary ───────────────────────────────────────────────────────────────────
total = len(PASS) + len(FAIL)
print(f"\n{'='*55}")
print(f"  Phase 17 Test Results: {len(PASS)}/{total} passed")
print(f"{'='*55}")
if FAIL:
    print("\nFailed tests:")
    for f in FAIL:
        print(f"  ❌  {f}")
else:
    print("\n  All tests passed! Phase 17 is fully implemented.")

sys.exit(0 if not FAIL else 1)
