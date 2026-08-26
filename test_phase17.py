"""
Phase 17 Feature Test Suite
============================
Tests every Phase 17 feature against the live server.
Run: python test_phase17.py
"""
import json
import sys
import time
from datetime import datetime
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


# ── Fixture build ─────────────────────────────────────────────────────────────
# Sections 5-7 used to assert against "whichever project the API happened to
# return first", so the suite's own assertion count moved with the database
# (54 -> 53 when a build was added) and every branch could skip itself on an
# empty one. "53/53 passed" and "54/54 passed" looked equally green while
# covering different things. The fixture pins them: the same build, the same
# steps, the same count, on any database including an empty one.
FIXTURE_ID = "phase17-fixture-build"
FIXTURE_FILES = ("backend/main.py", "backend/models.py")


def install_fixture():
    from api_platform import database as db
    db.initialize_db()
    db.delete_project(FIXTURE_ID)          # cascades to files + steps
    db.create_project(FIXTURE_ID, "fixture: a todo API with SQLite")
    db.update_project(
        FIXTURE_ID,
        status            = "done",
        app_name          = "phase17_fixture_app",
        app_type          = "api",
        complexity        = "simple",
        debug_score       = 9.0,
        review_score      = 8.5,
        test_score        = 8.0,
        completed_at      = datetime.utcnow().isoformat(),
        duration_seconds  = 12.5,
        prompt_tokens     = 1000,
        completion_tokens = 500,
        total_tokens      = 1500,
        progress_percent  = 100.0,
    )
    for path in FIXTURE_FILES:
        db.add_project_file(FIXTURE_ID, path, len(path) * 10)
    db.add_build_step(FIXTURE_ID, 1, "architect", "done",
                      json.dumps({"elapsed_seconds": 4.2}))
    db.add_build_step(FIXTURE_ID, 2, "coder", "done",
                      json.dumps({"elapsed_seconds": 7.8}))


def remove_fixture():
    try:
        from api_platform import database as db
        db.delete_project(FIXTURE_ID)
    except Exception as e:
        print(f"     (fixture cleanup failed: {e})")


install_fixture()


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
print(f"     Using fixture build: {FIXTURE_ID}")
pd = get(f"/projects/{FIXTURE_ID}")
check("project detail has files",       "files" in pd)
check("project detail has file_count",  "file_count" in pd)
check("file_count matches the files recorded for the build",
      pd.get("file_count") == len(FIXTURE_FILES),
      f"got {pd.get('file_count')}")
check("project detail has build_steps", "build_steps" in pd,
      f"keys={list(pd.keys())}")
steps = pd.get("build_steps", [])
check("build_steps returns every step of the build",
      isinstance(steps, list) and len(steps) == 2, f"{len(steps)} entries")
first = steps[0] if steps else {}
check("step entry has 'step'",      "step"      in first)
check("step entry has 'name'",      "name"      in first)
check("step entry has 'status'",    "status"    in first)
check("step entry has 'timestamp'", "timestamp" in first)
check("step entry has 'data' key",  "data"      in first,
      f"keys={list(first.keys())}")
done_steps = [st for st in steps if st["status"] == "done" and st.get("data")]
check("the build's done steps carry their data payload",
      len(done_steps) == 2, f"{len(done_steps)} of {len(steps)}")
try:
    d = json.loads(done_steps[0]["data"]) if done_steps else {}
    check("done step data has elapsed_seconds", "elapsed_seconds" in d,
          f"data keys={list(d.keys())}")
except Exception as e:
    check("done step data parses as JSON", False, str(e))
# Phase 17 token fields in project detail
check("project has prompt_tokens field",     "prompt_tokens"     in pd)
check("project has completion_tokens field", "completion_tokens" in pd)
check("project has total_tokens field",      "total_tokens"      in pd)
check("token fields carry the build's real numbers",
      pd.get("total_tokens") == 1500
      and pd.get("prompt_tokens") == 1000
      and pd.get("completion_tokens") == 500,
      f"total={pd.get('total_tokens')}")

# ── 6. Job status endpoint — completed_steps.data (Phase 17 gap fix) ─────────
print("\n[6] GET /jobs/{id}/status  — Phase 17 completed_steps data field")
js = get(f"/jobs/{FIXTURE_ID}/status")
check("job status has build_id",     "build_id" in js)
check("job status has current_step", "current_step" in js)
check("job status has progress",     "progress" in js)
progress = js.get("progress", {})
check("progress has completed_steps", "completed_steps" in progress)
comp = progress.get("completed_steps", [])
check("completed_steps lists the steps that finished",
      isinstance(comp, list) and len(comp) == 2, f"{len(comp)} entries")
check("completed step has 'data' key", bool(comp) and "data" in comp[0],
      f"keys={list(comp[0].keys()) if comp else '[]'}")

# ── 7. Jobs logs endpoint ─────────────────────────────────────────────────────
print("\n[7] GET /jobs/{id}/logs")
logs = get(f"/jobs/{FIXTURE_ID}/logs")
check("logs is a list", isinstance(logs, list))
check("logs cover every step of the build",
      len(logs) == 2, f"{len(logs)} entries")
entry = logs[0] if logs else {}
check("log entry has step",         "step"      in entry)
check("log entry has step_name",    "step_name" in entry)
check("log entry has status",       "status"    in entry)
check("log entry has timestamp",    "timestamp" in entry)
check("log entry has data key",     "data"      in entry)

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

remove_fixture()

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
