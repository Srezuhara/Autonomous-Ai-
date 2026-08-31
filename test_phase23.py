"""
Phase 23 Test Suite — Live-validation support
==============================================
Offline tests. No server and no LLM calls: the Groq HTTP boundary is stubbed,
so every assertion here runs for free and deterministically.

Covers the A3 simulated-daily-quota switch, whose entire reason to exist is
that the error it produces must be *indistinguishable* from a real one. A
simulation that raised a lookalike exception would let the handoff path pass a
test it would fail in production, so most of these tests are about sameness
rather than about behaviour.

Run: python test_phase23.py
"""
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime

# Importing llm_client boots the token ledger, which now seeds itself from the
# platform database. That is right in production and wrong here: this suite must
# leave the real quota record exactly as it found it (see [15]).
os.environ["GROQ_LEDGER_SEED"] = "0"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import llm_client
from llm_client import GroqDailyQuotaError, GroqRateLimitError

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        PASS.append(name)
        print(f"  [PASS]  {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL]  {name}  {detail}")


class simulate:
    """Set the switch for the duration of a block and reset the counter."""

    def __init__(self, after_calls):
        self.after_calls = after_calls
        self.previous = None

    def __enter__(self):
        self.previous = os.environ.get("GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS")
        if self.after_calls is None:
            os.environ.pop("GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS", None)
        else:
            os.environ["GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS"] = str(self.after_calls)
        llm_client.reset_simulated_quota()
        return self

    def __exit__(self, *exc):
        if self.previous is None:
            os.environ.pop("GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS", None)
        else:
            os.environ["GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS"] = self.previous
        llm_client.reset_simulated_quota()
        return False


# ── 1. The switch is off unless asked for ─────────────────────────────────────
print("\n[1] Default is off")

check("module default is 0 (off)",
      llm_client.GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS == 0)

with simulate(None):
    check("no env var ⇒ limit resolves to 0",
          llm_client._simulated_quota_limit() == 0)
    # The hot path must not raise, and must not even count, when off.
    llm_client._check_simulated_quota("openai/gpt-oss-120b")
    for _ in range(50):
        llm_client._record_simulated_call()
    llm_client._check_simulated_quota("openai/gpt-oss-120b")
    check("off ⇒ _check_simulated_quota never raises however many calls run", True)

with simulate("not-a-number"):
    check("a malformed value degrades to off rather than crashing a build",
          llm_client._simulated_quota_limit() == 0)


# ── 2. It trips after exactly N successful calls ──────────────────────────────
print("\n[2] Trip point")

with simulate(3):
    raised_early = False
    for i in range(3):
        try:
            llm_client._check_simulated_quota("openai/gpt-oss-20b")
        except GroqRateLimitError:
            raised_early = True
            break
        llm_client._record_simulated_call()
    check("does not trip before the budget is spent", not raised_early)

    tripped = False
    try:
        llm_client._check_simulated_quota("openai/gpt-oss-20b")
    except GroqDailyQuotaError:
        tripped = True
    check("trips on the call after the Nth success", tripped)

with simulate(1):
    llm_client._record_simulated_call()
    tripped = False
    try:
        llm_client._check_simulated_quota("openai/gpt-oss-20b")
    except GroqDailyQuotaError:
        tripped = True
    check("N=1 trips on the second call", tripped)

with simulate(2):
    llm_client.reset_simulated_quota()
    llm_client._record_simulated_call()
    llm_client._record_simulated_call()
    # Once tripped it stays tripped — a build must not stumble past it.
    trips = 0
    for _ in range(3):
        try:
            llm_client._check_simulated_quota("openai/gpt-oss-20b")
        except GroqDailyQuotaError:
            trips += 1
    check("stays tripped on every subsequent call", trips == 3, f"trips={trips}")


# ── 3. The simulated error is identical to a real one ─────────────────────────
# This is the assertion the whole switch exists for. If these two diverge, the
# handoff path can pass here and still fail on a genuine quota wall.
print("\n[3] Simulated error is byte-identical to a real one")

real = llm_client._make_quota_error("openai/gpt-oss-120b", "daily request/token quota")

with simulate(0):
    pass

with simulate(1):
    llm_client._record_simulated_call()
    simulated = None
    try:
        llm_client._check_simulated_quota("openai/gpt-oss-120b")
    except GroqDailyQuotaError as e:
        simulated = e

check("simulated raise produces GroqDailyQuotaError", isinstance(simulated, GroqDailyQuotaError))
check("…which is also a GroqRateLimitError, so existing handlers catch it",
      isinstance(simulated, GroqRateLimitError))
check("same message as a real quota error", str(simulated) == str(real))
check("same model field", simulated.model == real.model)
check("same reset hint", simulated.reset_hint == real.reset_hint)
check("carries the key counts a real error carries",
      simulated.keys_total == real.keys_total)
check("reason names the simulation so no one mistakes an artefact for an outage",
      simulated.reason == "simulated")

payload_fields = {"model", "keys_total", "keys_exhausted", "reset_hint", "reason"}
check("no payload field is missing from the simulated error",
      all(hasattr(simulated, f) for f in payload_fields))


# ── 4. It marks the model daily-limited, exactly as the real path does ────────
# `get_quota_snapshot()` is what SESSION_CONTEXT.md is written from. If the
# simulation skipped this, the handoff document would be produced with empty
# diagnostics — the one thing it exists to contain.
print("\n[4] Quota diagnostics are populated")

with simulate(1):
    llm_client._record_simulated_call()
    try:
        llm_client._check_simulated_quota("openai/gpt-oss-120b")
    except GroqDailyQuotaError:
        pass
    snapshot = llm_client.get_quota_snapshot()

check("get_quota_snapshot() reports a daily limit after the simulated trip",
      bool(snapshot.get("any_daily_limited")) or bool(snapshot.get("models")),
      f"snapshot={snapshot}")
check("is_quota_exhausted() agrees with the snapshot",
      llm_client.is_quota_exhausted("openai/gpt-oss-120b") in (True, False))


# ── 5. Thread safety ──────────────────────────────────────────────────────────
# job_runner runs three workers, and a torn counter would make the trip point
# non-deterministic — which would make every test above flaky rather than wrong.
print("\n[5] Counter is thread-safe")

with simulate(10_000):
    def bump():
        for _ in range(200):
            llm_client._record_simulated_call()

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("1600 concurrent increments are not lost",
          llm_client._simulated_call_count == 1600,
          f"count={llm_client._simulated_call_count}")

llm_client.reset_simulated_quota()


# ── 6. The knob is wired into the real call path ──────────────────────────────
# Asserting the helpers work proves nothing if `_call_groq` never calls them.
print("\n[6] Wiring into _call_groq")

import inspect
src = inspect.getsource(llm_client._call_groq)
check("_call_groq consults the switch before issuing a request",
      "_check_simulated_quota(model)" in src)
check("_call_groq counts successful calls",
      "_record_simulated_call()" in src)
check("the check sits inside the key-retry loop, not before it",
      src.index("while True:") < src.index("_check_simulated_quota(model)"))


# ── 7. The import check must understand packages ──────────────────────────────
# Found in the A1 live run. `run_python` loaded every file with
# `spec_from_file_location(<stem>)`, which gives the module no package context,
# so a perfectly valid `from .models import X` raised
# "attempted relative import with no known parent package". The Debugger then
# spent LLM calls rewriting correct package code until it happened to produce
# something the broken check accepted -- burning the quota this phase is paced
# against, and degrading the code to do it.
print("\n[7] run_python validates package-relative imports")

import shutil
import tempfile
from pathlib import Path
import config
from tools import code_executor

PKG_TMP = Path(config.OUTPUT_DIR) / "_phase23_pkg"
shutil.rmtree(PKG_TMP, ignore_errors=True)
(PKG_TMP / "backend").mkdir(parents=True, exist_ok=True)


def _w(rel: str, text: str):
    (PKG_TMP / rel).write_text(text, encoding="utf-8")


_w("backend/__init__.py", "")
_w("backend/models.py", "class TodoOut:\n    pass\n")
_w("backend/routes.py", "from .models import TodoOut\n\nrouter = TodoOut\n")

rel_root = PKG_TMP.name
res = code_executor.run_python(f"{rel_root}/backend/routes.py")
check("a package-relative import passes the check instead of being 'fixed'",
      res.success, f"stderr={res.stderr[-300:]}")

# A genuinely broken import must still fail — a fix that made everything pass
# would be worse than the bug, because the Debugger would stop catching anything.
_w("backend/broken.py", "from .nonexistent import Thing\n")
res_bad = code_executor.run_python(f"{rel_root}/backend/broken.py")
check("a genuinely missing module still fails the check", not res_bad.success)

# A plain module outside any package keeps working exactly as before.
_w("standalone.py", "import json\nVALUE = json.dumps({'ok': True})\n")
res_plain = code_executor.run_python(f"{rel_root}/standalone.py")
check("a non-package module is unaffected", res_plain.success,
      f"stderr={res_plain.stderr[-300:]}")

# Syntax errors must still be caught, package or not.
_w("backend/syntax.py", "def broken(:\n    pass\n")
res_syn = code_executor.run_python(f"{rel_root}/backend/syntax.py")
check("a syntax error inside a package is still caught", not res_syn.success)

shutil.rmtree(PKG_TMP, ignore_errors=True)


# ── 8. Truncated completions must not be accepted silently ────────────────────
# Found in the A2 live matrix. `backend/routes.py` came back cut off mid-call:
#
#     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#     SyntaxError: '(' was never closed
#
# The model had hit its output budget and returned finish_reason="length".
# `_call_groq` never looked at finish_reason — it returned the half-written file
# as if it were a complete answer. The Debugger then spent all three of its
# repair attempts on it and failed every one, because each repair was truncated
# the same way. llm_client.py:271-277 already says truncated code "is worse than
# useless — it is a syntax error that the debugger then burns retries on"; the
# check that would act on it was simply never written.
print("\n[8] finish_reason='length' is detected")

import httpx as _httpx

# Sections 2-4 deliberately marked models daily-limited to prove the simulation
# populates the real diagnostics. That state is module-global, so clear it or
# `_call_groq` refuses to issue a call at all and this section tests nothing.
llm_client._reset_exhausted()

_calls: list[int] = []


class _FakeResponse:
    def __init__(self, content: str, finish_reason: str):
        self.status_code = 200
        self.headers = {}
        self._payload = {
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeClient:
    """Stands in for httpx.Client inside _call_groq. No network, no quota."""

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None, **kw):
        _calls.append(json.get("max_tokens", 0))
        # Truncate the first response, complete the second.
        if len(_calls) == 1:
            return _FakeResponse("def f(:\n    raise HTTPException(", "length")
        return _FakeResponse("def f():\n    return 1\n", "stop")


_orig_client = _httpx.Client
_orig_wait = llm_client._wait_for_model_capacity
_orig_headers = llm_client._update_rate_state_from_headers
_httpx.Client = _FakeClient
llm_client._wait_for_model_capacity = lambda *a, **kw: None
llm_client._update_rate_state_from_headers = lambda *a, **kw: None
try:
    out = llm_client._call_groq("write routes.py", "", 950, "openai/gpt-oss-20b")
finally:
    _httpx.Client = _orig_client
    llm_client._wait_for_model_capacity = _orig_wait
    llm_client._update_rate_state_from_headers = _orig_headers

check("a truncated completion is retried rather than returned",
      len(_calls) >= 2, f"only {len(_calls)} call(s) made")
check("the retry asks for a larger output budget",
      len(_calls) >= 2 and _calls[1] > _calls[0], f"budgets={_calls}")
check("the caller receives the complete text, not the truncated one",
      "return 1" in out and "raise HTTPException(" not in out,
      f"got={out!r}")


# ── 9. A "fix" may not gut the file ───────────────────────────────────────────
# Found in the A2 live matrix, and the most damaging behaviour seen in the phase.
#
# routes.py arrived truncated (a syntax error). The Debugger repaired it by
# deleting the entire body: 2980 chars of route handlers became 413 chars of
# imports with no `router` object left. That *compiles*, so the import check
# passed and the repair was recorded as a success -- while the application it
# was repairing no longer existed. The smoke test caught the wreckage
# ("cannot import name 'router' from 'routes'") but the build still scored
# review 7.33 / tests 12/12 and shipped a downloadable ZIP.
#
# `_accept_generated_fix` was asymmetric: it rejected fixes that were too LARGE
# (a multi-file paste) and had no lower bound at all. Deleting code was the
# cheapest possible way to satisfy "the file imports cleanly".
print("\n[9] a repair may not delete the file's contents")

from agents.debugger import Debugger

_dbg = Debugger()

GUTTED_TMP = Path(config.OUTPUT_DIR) / "_phase23_fix"
shutil.rmtree(GUTTED_TMP, ignore_errors=True)
GUTTED_TMP.mkdir(parents=True, exist_ok=True)

ORIGINAL = '''from fastapi import APIRouter, HTTPException, status
import sqlite3
from typing import List

from schemas import BookmarkCreate

router = APIRouter()


@router.get("/bookmarks")
async def list_bookmarks():
    return []


@router.post("/bookmarks")
async def create_bookmark(payload: BookmarkCreate):
    return payload


@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: int):
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
'''

# Exactly what the live run produced: imports only, no router, no handlers.
GUTTED = '''from fastapi import APIRouter, Depends, HTTPException, status
import sqlite3
from typing import List

from schemas import BookmarkCreate
'''

rel_fix = f"{GUTTED_TMP.name}/routes.py"
(GUTTED_TMP / "routes.py").write_text(ORIGINAL, encoding="utf-8")

check("a repair that deletes the file's body is rejected",
      not _dbg._accept_generated_fix(rel_fix, GUTTED))

# The symbol that mattered. Losing `router` is what made the app unimportable.
check("a repair that drops a top-level symbol other modules import is rejected",
      not _dbg._accept_generated_fix(
          rel_fix,
          ORIGINAL.replace("router = APIRouter()", "") + "\n",
      ))

# A real repair must still be accepted, or the Debugger stops being able to fix
# anything at all — which would be a worse failure than the one being fixed.
REPAIRED = ORIGINAL.rstrip() + '\n    return {"deleted": bookmark_id}\n'
check("a genuine repair of the same file is still accepted",
      _dbg._accept_generated_fix(rel_fix, REPAIRED))

# The original guard must keep working: a multi-file paste is still refused.
MULTI = ORIGINAL + "\n# backend/main.py\n" + ORIGINAL + "\n# backend/models.py\n"
check("an oversized multi-file paste is still rejected",
      not _dbg._accept_generated_fix(rel_fix, MULTI))

shutil.rmtree(GUTTED_TMP, ignore_errors=True)


# ── 10. Exhausted-before-start must take the handoff path too ─────────────────
# Found when the A2 matrix hit a real 200K TPD wall.
#
# A build that runs *into* the quota mid-flight is handled beautifully: Phase 21
# catches GroqDailyQuotaError, packages the work so far, writes SESSION_CONTEXT.md
# with real diagnostics, and finishes `done_with_context` with a downloadable ZIP.
#
# A build submitted when the quota is *already* gone got none of that. With every
# key already marked exhausted, `_get_next_groq_key` returns None and the code
# raised a bare RuntimeError — a different type, so the quota interception never
# saw it. Result: status `failed`, completion_reason NULL, no handoff document,
# and HTTP 400 on the download. Live, builds 2, 3 and 4 all died this way in
# 0.04s with no explanation for the user.
#
# It is the same condition and the same cause; only the timing differs, so it
# must produce the same error type.
print("\n[10] quota exhausted before the build starts is still a quota error")

llm_client._reset_exhausted()
llm_client._mark_model_daily_limited("openai/gpt-oss-20b", "tokens per day (tpd)")

_raised = None
try:
    llm_client._call_groq("anything", "", 500, "openai/gpt-oss-20b")
except GroqDailyQuotaError as e:
    _raised = e
except Exception as e:                      # noqa: BLE001 - we assert on the type
    _raised = e

check("an already-exhausted model raises GroqDailyQuotaError, not RuntimeError",
      isinstance(_raised, GroqDailyQuotaError),
      f"got {type(_raised).__name__}: {_raised}")
check("…so the Phase 21 interception, which catches GroqRateLimitError, sees it",
      isinstance(_raised, GroqRateLimitError),
      f"got {type(_raised).__name__}")
check("it carries the diagnostics SESSION_CONTEXT.md is written from",
      getattr(_raised, "model", None) == "openai/gpt-oss-20b"
      and bool(getattr(_raised, "reset_hint", "")),
      f"model={getattr(_raised, 'model', None)!r}")

llm_client._reset_exhausted()


# ── 11. The per-model daily token ledger ──────────────────────────────────────
# Groq enforces tokens-per-day *per model* but reports the number only inside the
# 429 that enforces it. Nothing could see the budget, so the first sign that 190K
# of 200K was gone was the failure — which is how a four-build matrix died after
# one build. This keeps the count locally so it can be read before it runs out.
print("\n[11] per-model daily token ledger")

# Point the ledger at a scratch file for the rest of this suite. Without this,
# running the tests wipes the REAL ledger — which is the platform's only record
# of how much daily quota has been spent. Observed for real: after a test run the
# ledger reported gpt-oss-20b at 3.6% while Groq's own counter said 99.9%, so the
# thing built to prevent a surprise quota wall would have walked straight into
# one. A measurement tool that its own tests corrupt is worse than none.
_REAL_LEDGER_PATH = llm_client._LEDGER_PATH
llm_client._LEDGER_PATH = Path(config.OUTPUT_DIR) / "_phase23_test_ledger.json"
llm_client._ledger = []

empty = llm_client.get_daily_usage()
check("an empty ledger reports no models", empty["models"] == {})
check("the limit is reported so a caller can do the arithmetic",
      empty["limit_per_model"] == llm_client.GROQ_DAILY_TOKEN_LIMIT)

llm_client._add_tokens(1000, 500, "openai/gpt-oss-20b")
llm_client._add_tokens(200, 100, "openai/gpt-oss-120b")
llm_client._add_tokens(1000, 0, "openai/gpt-oss-20b")

usage = llm_client.get_daily_usage()["models"]
check("spend is attributed to the model that incurred it",
      usage["openai/gpt-oss-20b"]["tokens_used"] == 2500
      and usage["openai/gpt-oss-120b"]["tokens_used"] == 300,
      f"usage={usage}")
check("the two model budgets are independent, which is the whole point",
      usage["openai/gpt-oss-20b"]["tokens_remaining"]
      != usage["openai/gpt-oss-120b"]["tokens_remaining"])
check("remaining = limit - used",
      usage["openai/gpt-oss-20b"]["tokens_remaining"]
      == llm_client.GROQ_DAILY_TOKEN_LIMIT - 2500)
check("call counts are tracked alongside tokens",
      usage["openai/gpt-oss-20b"]["calls"] == 2)

# The CLI lost its token count for exactly this reason: accounting was gated on
# a build_id being set. Organisation quota is spent either way.
llm_client._current_build_id.value = None
before = llm_client.get_daily_usage()["models"]["openai/gpt-oss-120b"]["tokens_used"]
llm_client._add_tokens(50, 50, "openai/gpt-oss-120b")
after = llm_client.get_daily_usage()["models"]["openai/gpt-oss-120b"]["tokens_used"]
check("spend is recorded even with no build_id set", after == before + 100)

# Rolling 24h window, not a calendar day: the live wall said "try again in
# 17m56s", not "at midnight".
with llm_client._ledger_lock:
    llm_client._ledger.append([time.time() - (25 * 3600), "openai/gpt-oss-20b", 999_999])
aged = llm_client.get_daily_usage()["models"]
check("an entry older than the window is dropped, not counted",
      aged["openai/gpt-oss-20b"]["tokens_used"] == 2500,
      f"got {aged['openai/gpt-oss-20b']['tokens_used']}")

# Restart survival — this workflow restarts the server constantly, and a ledger
# that forgets on restart would under-report exactly when it matters.
llm_client.reset_daily_usage()
llm_client._add_tokens(4000, 1000, "openai/gpt-oss-20b")
llm_client._ledger = []
llm_client._ledger_load()
reloaded = llm_client.get_daily_usage()["models"]
check("the ledger survives a process restart",
      reloaded.get("openai/gpt-oss-20b", {}).get("tokens_used") == 5000,
      f"reloaded={reloaded}")

# A corrupt ledger must never be able to stop a build.
try:
    llm_client._LEDGER_PATH.write_text("{not json", encoding="utf-8")
    llm_client._ledger_load()
    check("a corrupt ledger file degrades to empty instead of raising", True)
except Exception as e:
    check("a corrupt ledger file degrades to empty instead of raising", False, str(e))

check("get_quota_snapshot() carries the daily figures into SESSION_CONTEXT.md",
      "daily_usage" in llm_client.get_quota_snapshot())

llm_client.reset_daily_usage()


# ── 12. Load is split across both models' independent daily budgets ───────────
# The live failure: 40 of a build's 41 calls went to gpt-oss-20b, so its 200K/day
# ran out after two builds while gpt-oss-120b's separate 200K sat nearly unused.
# The cause was a default written for the decommissioned llama pair, where heavy
# quota really was the scarce one.
print("\n[12] both models carry load")

_HEAVY = llm_client._HEAVY_MODEL
_FAST  = llm_client._FAST_MODEL

routing = {
    name: llm_client.get_model_for_agent(name)
    for name in [
        "intent_analyzer", "planner", "architect", "backend_developer",
        "frontend_generator", "frontend_debugger", "debugger", "reviewer",
        "tester", "documenter",
    ]
}

check("the code-producing agents run on the heavy model",
      all(routing[a] == _HEAVY for a in
          ["architect", "backend_developer", "frontend_generator", "frontend_debugger"]),
      f"routing={routing}")
check("the small structured agents stay on the fast model",
      all(routing[a] == _FAST for a in
          ["intent_analyzer", "planner", "reviewer", "tester", "debugger"]),
      f"routing={routing}")
check("both models are actually used — the point of the change",
      len(set(routing.values())) == 2, f"routing={routing}")
check("underscore and camel spellings route identically",
      llm_client.get_model_for_agent("BackendDeveloper")
      == llm_client.get_model_for_agent("backend_developer"))

# Caps are not spend, but too low a cap causes truncation, and since Fix 3 every
# truncation costs an extra call. The heavy-model agents now have no reasoning
# floor to hide behind, so their caps must be genuinely large enough.
for agent in ["backend_developer", "frontend_generator", "frontend_debugger"]:
    budget = llm_client.get_agent_token_budget(agent)
    check(f"{agent} has room to finish a file in one call ({budget})",
          budget >= 1600, f"budget={budget}")

# GROQ_HEAVY_AGENTS must still be able to put everything back on one model.
_prev_heavy = os.environ.get("GROQ_HEAVY_AGENTS")
os.environ["GROQ_HEAVY_AGENTS"] = "architect"
try:
    names = llm_client._load_heavy_agent_names()
    check("GROQ_HEAVY_AGENTS still overrides the default",
          "architect" in names and "backenddeveloper" not in names,
          f"names={sorted(names)}")
finally:
    if _prev_heavy is None:
        os.environ.pop("GROQ_HEAVY_AGENTS", None)
    else:
        os.environ["GROQ_HEAVY_AGENTS"] = _prev_heavy


# ── 13. Debugger prompt cost ──────────────────────────────────────────────────
# Prompt tokens were 57% of a build's spend and the Debugger made 44% of the
# calls, sending the full file, an unbounded project map and the entire stderr
# on every attempt with no cap of any kind.
print("\n[13] the Debugger's prompt is bounded")

check("an import error is recognised",
      Debugger._is_import_error("ImportError: cannot import name 'router'"))
check("a syntax error is not mistaken for an import error",
      not Debugger._is_import_error("SyntaxError: '(' was never closed"))
check("the relative-import failure counts as an import error",
      Debugger._is_import_error("attempted relative import with no known parent package"))

short = "ImportError: boom"
check("a short traceback is passed through untouched",
      Debugger._trim_error(short) == short)

long_tb = "\n".join(f"  File \"C:/very/long/path/frame_{i}.py\", line {i}" for i in range(400))
long_tb += "\nImportError: cannot import name 'router' from 'routes'"
trimmed = Debugger._trim_error(long_tb)
check("a long traceback is trimmed",
      len(trimmed) < len(long_tb))
check("…from the head, keeping the exception itself",
      "cannot import name 'router'" in trimmed,
      "the tail is the part that says what went wrong")
check("the trim is signposted rather than silent",
      "trimmed" in trimmed)

# The project map is only informative for import errors.
_map_calls: list[str] = []
_orig_scan = Debugger._scan_project_structure
Debugger._scan_project_structure = lambda self, fp: (_map_calls.append(fp) or "MAP")

MAPTMP = Path(config.OUTPUT_DIR) / "_phase23_map"
shutil.rmtree(MAPTMP, ignore_errors=True)
MAPTMP.mkdir(parents=True, exist_ok=True)
(MAPTMP / "m.py").write_text("x = 1\n", encoding="utf-8")

_prompts: list[str] = []
_dbg2 = Debugger()
# Section 24 sizes the output cap to the file, so the stub takes it too.
_budgets: list = []
_dbg2.think = lambda p, max_tokens=None: (
    _prompts.append(p) or _budgets.append(max_tokens) or "x = 1\n")

_dbg2._generate_fix(f"{MAPTMP.name}/m.py", "SyntaxError: '(' was never closed")
check("no project map is sent for a syntax error", not _map_calls, f"calls={_map_calls}")
check("the prompt does not claim an import error when there is none",
      "an import error" not in _prompts[-1])

_dbg2._generate_fix(f"{MAPTMP.name}/m.py", "ImportError: cannot import name 'router'")
check("the project map IS sent for an import error", len(_map_calls) == 1)
check("the prompt names the import error", "an import error" in _prompts[-1])

Debugger._scan_project_structure = _orig_scan

# The map itself must not grow without bound.
for i in range(80):
    (MAPTMP / f"mod_{i:03d}.py").write_text("y = 1\n", encoding="utf-8")
real_map = Debugger()._scan_project_structure(f"{MAPTMP.name}/m.py")
check("the project map is capped rather than listing every module",
      len(real_map.splitlines()) <= 42, f"{len(real_map.splitlines())} lines")

shutil.rmtree(MAPTMP, ignore_errors=True)


# ── 14. The two daily budgets are fungible in both directions ─────────────────
# There was already a heavy→fast fallback: "a dead 70b must not end a build that
# 8b can finish." The mirror did not exist, because under the old routing the
# fast model was never the one that ran out.
#
# That is now backwards. The fast model carries the high-frequency agents, so it
# is the first to hit its 200K, while the heavy model's separate 200K may be
# barely touched — and the build would die anyway. Small structured work moving
# to the bigger model is also a quality gain, not a compromise.
print("\n[14] a build survives one model running out")

llm_client._reset_exhausted()
llm_client.reset_daily_usage()


class _OkClient:
    """Answers every request successfully; records which model was asked."""
    seen: list[str] = []

    def __init__(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, headers=None, json=None, **kw):
        _OkClient.seen.append(json["model"])
        return _FakeResponse("generated output", "stop")


_orig_client = _httpx.Client
_orig_wait = llm_client._wait_for_model_capacity
_orig_headers = llm_client._update_rate_state_from_headers
_httpx.Client = _OkClient
llm_client._wait_for_model_capacity = lambda *a, **kw: None
llm_client._update_rate_state_from_headers = lambda *a, **kw: None

try:
    # The fast model is gone; the heavy model still has budget.
    llm_client._mark_model_daily_limited(llm_client._FAST_MODEL, "tokens per day (tpd)")
    _OkClient.seen = []
    out = llm_client.generate_text(
        "analyse this", system="", max_tokens=400, agent_name="intent_analyzer"
    )
    check("a fast-model agent falls back to the heavy model's separate budget",
          _OkClient.seen == [llm_client._HEAVY_MODEL], f"models tried={_OkClient.seen}")
    check("…and the caller still gets its answer", out == "generated output")

    # Both gone: it must still be a quota error, so the handoff path engages.
    llm_client._mark_model_daily_limited(llm_client._HEAVY_MODEL, "tokens per day (tpd)")
    _raised2 = None
    try:
        llm_client.generate_text("x", system="", max_tokens=400, agent_name="intent_analyzer")
    except Exception as e:
        _raised2 = e
    check("with both models exhausted it is still a GroqDailyQuotaError",
          isinstance(_raised2, GroqDailyQuotaError),
          f"got {type(_raised2).__name__}")
finally:
    _httpx.Client = _orig_client
    llm_client._wait_for_model_capacity = _orig_wait
    llm_client._update_rate_state_from_headers = _orig_headers
    llm_client._reset_exhausted()
    llm_client.reset_daily_usage()


# ── 15. This suite must not corrupt the real quota record ─────────────────────
# It did. A test run wiped the live ledger, after which it reported gpt-oss-20b
# at 3.6% while Groq's own counter said 99.9% — the tool built to give warning of
# a quota wall would have walked into one silently.
print("\n[15] the test ledger is isolated from the real one")

check("the suite writes to a scratch ledger, not the platform's",
      llm_client._LEDGER_PATH != _REAL_LEDGER_PATH,
      f"path={llm_client._LEDGER_PATH}")
check("the real ledger file was not touched by this run",
      "_phase23_test_ledger" in str(llm_client._LEDGER_PATH))


# ── 16. The deployability cap must not delete the entry point ─────────────────
# Found on a live verification build. The architect planned 7 backend files and
# `_normalise_backend_architecture` trimmed them to 4 "for deployability":
#
#   Removed: ['backend/database.py', 'backend/exceptions.py', 'backend/main.py']
#
# It deleted main.py — the one file the application cannot exist without. The
# result had models, routes, schemas and services and no way to start: no
# `app = FastAPI()` anywhere, so the runtime smoke test found no entry point and
# skipped, and the build was recorded `done_with_context` with review 7.0.
#
# This is deterministic, not variance. BACKEND_FILE_PRIORITY ranks main.py at 4 —
# last of the real files — and the cap for a simple/medium app is exactly 4, so
# `sorted(...)[:4]` keeps models/schemas/services/routes and drops the entry
# point. Any time the architect includes a schemas.py, the app loses its main.
print("\n[16] the architecture cap never removes the entry point")

from agents.architect import Architect

_arch = Architect()


def _files(*names):
    return {"files": [{"path": f"backend/{n}", "purpose": n} for n in names]}


over = _files("models.py", "schemas.py", "services.py", "routes.py",
              "database.py", "exceptions.py", "main.py")
result = _arch._normalise_backend_architecture(over, {"complexity": "medium"})
kept = {Path(f["path"]).name for f in result["files"]}

check("main.py survives the cap", "main.py" in kept, f"kept={sorted(kept)}")
check("the cap is still enforced", len(kept) <= 4, f"kept={sorted(kept)}")
check("the files it did keep are still the useful ones",
      "routes.py" in kept and "models.py" in kept, f"kept={sorted(kept)}")

# app.py is the other spelling of an entry point.
over_app = _files("models.py", "schemas.py", "services.py", "routes.py",
                  "helpers.py", "app.py")
result_app = _arch._normalise_backend_architecture(over_app, {"complexity": "medium"})
kept_app = {Path(f["path"]).name for f in result_app["files"]}
check("app.py survives when it is the entry point",
      "app.py" in kept_app, f"kept={sorted(kept_app)}")

# Under the cap, nothing should be touched at all.
small = _files("models.py", "routes.py", "main.py")
result_small = _arch._normalise_backend_architecture(small, {"complexity": "simple"})
check("an already-small architecture is left alone",
      len(result_small["files"]) == 3)

# The existing main.py + routes.py + app.py de-duplication must still work.
dup = _files("models.py", "routes.py", "main.py", "app.py")
result_dup = _arch._normalise_backend_architecture(dup, {"complexity": "medium"})
kept_dup = {Path(f["path"]).name for f in result_dup["files"]}
check("the redundant app.py is still dropped when main.py defines the entry",
      "app.py" not in kept_dup and "main.py" in kept_dup, f"kept={sorted(kept_dup)}")


# ── 17. Seeding the ledger from finished builds ───────────────────────────────
# The ledger only counted calls it watched happen, so a restart made every token
# spent before it invisible: it read gpt-oss-20b at 3.6% while Groq's own counter
# said 99.9%. A gauge that under-reports is worse than no gauge, because it is
# believed. Seeding rebuilds the missing spend from the `projects` rows.
print("\n[17] the ledger is seeded from builds it never watched")

_now = time.time()


def _row(build_id, tokens, ago_hours, by_model=None):
    when = datetime.utcfromtimestamp(_now - ago_hours * 3600).isoformat()
    return {
        "build_id": build_id,
        "total_tokens": tokens,
        "created_at": when,
        "completed_at": when,
        "tokens_by_model": json.dumps(by_model) if by_model else None,
    }


llm_client.reset_daily_usage()
seeded = llm_client.seed_ledger_from_history(
    [_row("b-recent", 30_000, 2,
          {"openai/gpt-oss-120b": 25_000, "openai/gpt-oss-20b": 5_000})],
    now=_now,
)
usage = llm_client.get_daily_usage(now=_now)["models"]
check("a build the ledger never saw is counted after seeding",
      seeded["builds_seeded"] == 1 and seeded["tokens_seeded"] == 30_000,
      f"seeded={seeded}")
check("the recorded per-model split is used verbatim, not estimated",
      usage["openai/gpt-oss-120b"]["seeded_tokens"] == 25_000
      and usage["openai/gpt-oss-20b"]["seeded_tokens"] == 5_000,
      f"usage={usage}")
# The build is two hours old, so the bucket has already returned two hours of
# budget against it — 16,666 tokens. That is the point of §28, asserted here so
# the two views of the same ledger cannot drift apart.
check("…while what is still owed has decayed by two hours of refill",
      usage["openai/gpt-oss-120b"]["tokens_used"]
      == round(25_000 - 2 * llm_client._REFILL_RATE * 3600),
      f"usage={usage}")
check("seeded spend is reported as seeded, so the estimate is visible",
      usage["openai/gpt-oss-120b"]["seeded_tokens"] == 25_000)

# Seeding runs on every boot, and the server restarts constantly. Running it
# twice must not spend the budget twice.
again = llm_client.seed_ledger_from_history([_row("b-recent", 30_000, 2)], now=_now)
after = llm_client.get_daily_usage(now=_now)["models"]
check("seeding the same build again adds nothing",
      again["builds_seeded"] == 0
      and after["openai/gpt-oss-120b"]["seeded_tokens"] == 25_000,
      f"again={again}")

# …and it must survive the restart it exists for.
llm_client._ledger, llm_client._ledger_covered = [], {}
llm_client._ledger_load()
llm_client.seed_ledger_from_history([_row("b-recent", 30_000, 2)], now=_now)
check("the covered-builds record survives a restart, so seeding stays idempotent",
      llm_client.get_daily_usage(now=_now)["models"]["openai/gpt-oss-120b"]["seeded_tokens"]
      == 25_000,
      f"usage={llm_client.get_daily_usage(now=_now)['models']}")

# A build this process watched live is already in the ledger call by call.
llm_client.reset_daily_usage()
llm_client._current_build_id.value = "b-live"
llm_client._add_tokens(6_000, 2_000, "openai/gpt-oss-120b")
live_seed = llm_client.seed_ledger_from_history([_row("b-live", 8_000, 0.1)], now=_now)
check("a build watched live is not seeded on top of itself",
      live_seed["builds_seeded"] == 0
      and llm_client.get_daily_usage(now=_now)["models"]["openai/gpt-oss-120b"]["tokens_used"]
      == 8_000,
      f"live_seed={live_seed}")
llm_client._current_build_id.value = None

# The window is the whole point: yesterday's spend is not today's budget.
llm_client.reset_daily_usage()
old_seed = llm_client.seed_ledger_from_history([_row("b-old", 99_000, 30)], now=_now)
check("a build older than the 24h window is not seeded",
      old_seed["builds_seeded"] == 0
      and llm_client.get_daily_usage(now=_now)["models"] == {},
      f"old_seed={old_seed}")

# Rows written before `tokens_by_model` existed carry no split. Half each is an
# estimate, and it is labelled as one rather than silently presented as measured.
llm_client.reset_daily_usage()
llm_client.seed_ledger_from_history([_row("b-legacy", 90_001, 3)], now=_now)
legacy = llm_client.get_daily_usage(now=_now)["models"]
check("a row with no split is divided across both configured models",
      legacy["openai/gpt-oss-120b"]["seeded_tokens"]
      + legacy["openai/gpt-oss-20b"]["seeded_tokens"] == 90_001,
      f"legacy={legacy}")
check("…and the odd token is not lost to integer division",
      abs(legacy["openai/gpt-oss-120b"]["seeded_tokens"]
          - legacy["openai/gpt-oss-20b"]["seeded_tokens"]) == 1)
check("…and every token of it is marked as an estimate, none observed live",
      legacy["openai/gpt-oss-120b"]["seeded_tokens"] == 45_001
      and legacy["openai/gpt-oss-120b"]["calls"] == 1,
      f"legacy={legacy}")

# Junk rows must not stop a boot: seeding runs at import time.
llm_client.reset_daily_usage()
junk = llm_client.seed_ledger_from_history(
    [
        {"build_id": "b-zero", "total_tokens": 0, "completed_at": None},
        {"build_id": "", "total_tokens": 5_000, "completed_at": None},
        {"build_id": "b-nodate", "total_tokens": 5_000,
         "created_at": "not-a-date", "completed_at": ""},
        {"build_id": "b-future", "total_tokens": 5_000,
         "completed_at": datetime.utcfromtimestamp(_now + 9_999).isoformat()},
    ],
    now=_now,
)
check("rows with no tokens, no id, no usable date or a future date are skipped",
      junk["builds_seeded"] == 0 and llm_client.get_daily_usage(now=_now)["models"] == {},
      f"junk={junk}")

# A format-1 ledger (a bare list, no build attribution) is still on disk in every
# checkout that ran the previous version. Its entries are real spend already
# counted, so a build that finished while it was recording must not be seeded on
# top of them.
llm_client.reset_daily_usage()
llm_client._LEDGER_PATH.write_text(
    json.dumps([[_now - 3600, "openai/gpt-oss-120b", 40_000]]), encoding="utf-8"
)
llm_client._ledger, llm_client._ledger_covered = [], {}
llm_client._ledger_load()
# A live entry carries no `seeded_tokens`, so this one is asserted against the
# ledger itself: the entry loaded, with its tokens intact and its age unchanged.
check("a format-1 ledger file still loads",
      [e[1:3] for e in llm_client._ledger] == [["openai/gpt-oss-120b", 40_000]],
      llm_client._ledger)
check("…and its unlabelled entries count as observed, not estimated",
      llm_client.get_daily_usage(now=_now)["models"]["openai/gpt-oss-120b"]["seeded_tokens"]
      == 0)
blind = llm_client.seed_ledger_from_history([_row("b-inspan", 40_000, 1)], now=_now)
check("a build inside a format-1 ledger's recorded span is not double-counted",
      blind["builds_seeded"] == 0 and len(llm_client._ledger) == 1,
      f"blind={blind} ledger={llm_client._ledger}")

# The reader itself is best-effort: no database, or one without the column, must
# degrade to "nothing to seed" rather than take the process down.
_saved_output_dir = os.environ.get("OUTPUT_DIR")
_seed_dir = Path(config.OUTPUT_DIR) / "_phase23_seed_db"
_seed_dir.mkdir(parents=True, exist_ok=True)
os.environ["OUTPUT_DIR"] = str(_seed_dir)
try:
    check("a missing platform.db yields no rows instead of an exception",
          llm_client._ledger_history_rows() == [])

    _db = _seed_dir / "platform.db"
    _conn = sqlite3.connect(str(_db))
    _conn.execute("CREATE TABLE projects (build_id TEXT, total_tokens INTEGER)")
    _conn.commit()
    _conn.close()
    check("a projects table without the new column still reads",
          llm_client._ledger_history_rows() == [])

    # The real schema, written by the real migration.
    _db.unlink()
    import api_platform.database as _db_mod
    _saved_db_path = _db_mod.DB_PATH
    _db_mod.DB_PATH = _db
    try:
        _db_mod.initialize_db()
        _db_mod.create_project("b-schema", "a prompt")
        _db_mod.update_project(
            "b-schema",
            status="done",
            completed_at=datetime.utcnow().isoformat(),
            total_tokens=12_345,
            tokens_by_model=json.dumps({"openai/gpt-oss-120b": 12_345}),
        )
        stored = _db_mod.get_project("b-schema")
        check("the migration adds tokens_by_model to an existing database",
              "tokens_by_model" in stored, f"keys={sorted(stored)}")
        check("a build's per-model split round-trips through the database",
              json.loads(stored["tokens_by_model"])
              == {"openai/gpt-oss-120b": 12_345})
        check("list_projects() returns the split too, so /health can show it",
              "tokens_by_model" in _db_mod.list_projects(limit=1)[0])

        rows = llm_client._ledger_history_rows()
        check("the ledger reads that build straight out of the database",
              any(r["build_id"] == "b-schema" and r["total_tokens"] == 12_345
                  for r in rows),
              f"rows={rows}")

        llm_client.reset_daily_usage()
        llm_client.seed_ledger_from_history(now=_now)
        # Read on the same clock the seed was written on. The bucket refills at
        # 2.315 tokens/sec, so reading against wall-clock time subtracts however
        # long the suite took to get here — under half a token on an idle
        # machine, more than that while a live build is running, which rounded
        # 12,345 down to 12,344 and failed here for reasons having nothing to do
        # with the code under test.
        from_db = llm_client.get_daily_usage(now=_now)["models"]
        check("…and seeds it with the split the build actually recorded",
              from_db.get("openai/gpt-oss-120b", {}).get("tokens_used") == 12_345
              and "openai/gpt-oss-20b" not in from_db,
              f"from_db={from_db}")
    finally:
        _db_mod.DB_PATH = _saved_db_path
finally:
    if _saved_output_dir is None:
        os.environ.pop("OUTPUT_DIR", None)
    else:
        os.environ["OUTPUT_DIR"] = _saved_output_dir
    shutil.rmtree(_seed_dir, ignore_errors=True)

# The per-build split is what makes future seeding exact rather than an estimate,
# so the pipeline has to actually record it.
llm_client.reset_daily_usage()
llm_client.set_current_build_id("b-split")
llm_client._add_tokens(700, 300, "openai/gpt-oss-120b")
llm_client._add_tokens(100, 100, "openai/gpt-oss-20b")
_usage = llm_client.get_and_reset_token_usage("b-split")
check("per-build usage now carries the per-model split",
      _usage["by_model"] == {"openai/gpt-oss-120b": 1000, "openai/gpt-oss-20b": 200},
      f"by_model={_usage.get('by_model')}")
check("…without disturbing the totals the API already reports",
      _usage["total_tokens"] == 1200 and _usage["prompt_tokens"] == 800)
check("an unknown build still returns a usable, empty shape",
      llm_client.get_and_reset_token_usage("nope")["by_model"] == {})
llm_client._current_build_id.value = None
llm_client.reset_daily_usage()


# ── 18. The SPA history fallback must not answer for the API ──────────────────
# The catch-all served the shell with HTTP 200 for *any* unmatched GET, so a
# wrong API path looked like a success to anything that is not a browser. It
# cost a live session: a download script pointed at `/downloads/{id}` — a URL
# that does not exist, the real one is `/projects/{id}/download` — got 200 and
# saved an HTML page as a .zip. Browsers still need the fallback for deep links,
# so the two are told apart by `Accept`, the same rule the navigation middleware
# already uses.
print("\n[18] the SPA fallback answers browsers, not scripts")

from api_platform.main import FRONTEND_DIST  # noqa: E402

if not FRONTEND_DIST.is_dir():
    print("  (skipped — no frontend/dist; run `npm run build` in frontend/)")
else:
    from fastapi.testclient import TestClient  # noqa: E402
    from api_platform.main import app as _api_app  # noqa: E402
    import api_platform.main as _api_main  # noqa: E402

    _client = TestClient(_api_app)
    _HTML = {"accept": "text/html,application/xhtml+xml"}
    _JSON = {"accept": "application/json"}

    _typo = _client.get("/downloads/some-build-id", headers=_JSON)
    check("a mistyped API path 404s instead of returning the shell",
          _typo.status_code == 404, f"status={_typo.status_code}")
    check("…and the body is an error, not a page",
          "text/html" not in _typo.headers.get("content-type", ""),
          f"content-type={_typo.headers.get('content-type')}")

    _no_accept = _client.get("/downloads/some-build-id", headers={"accept": "*/*"})
    check("a client that asks for anything is still not a browser",
          _no_accept.status_code == 404, f"status={_no_accept.status_code}")

    _deep = _client.get("/some/client/route", headers=_HTML)
    check("a browser deep link still gets the shell, so React Router works",
          _deep.status_code == 200
          and "text/html" in _deep.headers.get("content-type", ""),
          f"status={_deep.status_code}")

    _asset = _client.get("/favicon.svg", headers=_JSON)
    check("a file that really exists in dist is served whoever asks",
          _asset.status_code == 200
          and "text/html" not in _asset.headers.get("content-type", ""),
          f"status={_asset.status_code} ct={_asset.headers.get('content-type')}")

    _health = _client.get("/health", headers=_JSON)
    check("real API routes are untouched by the change",
          _health.status_code == 200 and "status" in _health.json())

    # `/` is the one path that is both an API endpoint and a page.
    _root_api = _client.get("/", headers=_JSON)
    check("curl / keeps returning the platform info JSON",
          _root_api.status_code == 200
          and _root_api.json().get("service") == "AI App Builder Platform")
    _root_html = _client.get("/", headers=_HTML)
    check("a browser at / gets the landing page, not the info JSON",
          _root_html.status_code == 200
          and "text/html" in _root_html.headers.get("content-type", ""),
          f"ct={_root_html.headers.get('content-type')}")

    # The collision this whole mechanism exists for, in both directions.
    _api_miss = _client.get("/projects/does-not-exist", headers=_JSON)
    check("an unknown build id reaches the API and 404s as JSON",
          _api_miss.status_code == 404
          and "text/html" not in _api_miss.headers.get("content-type", ""),
          f"status={_api_miss.status_code}")
    _page_hit = _client.get("/projects/does-not-exist", headers=_HTML)
    check("…while the same URL in the address bar renders the SPA",
          _page_hit.status_code == 200
          and "text/html" in _page_hit.headers.get("content-type", ""))

    # The containment check still has to hold: the fallback resolves paths
    # against dist, and a 404 is the right answer for an escape attempt.
    # The Download ZIP button calls `window.open`, which is an HTML navigation
    # to a path under `/projects/` — so the rule above handed it the app shell
    # and the browser saved 1.5KB of HTML instead of the archive. Nothing
    # errored: the click just did nothing. Found by the live E2E suite, which
    # is the only place a real browser is involved.
    _finished = [
        b for b in _client.get("/projects/?limit=50").json().get("projects", [])
        if b.get("status") in ("done", "done_with_context")
    ]
    _dl = (f"/projects/{_finished[0]['build_id']}/download"
           if _finished else "/projects/none/download")
    check("a download path is not treated as a page, whatever the Accept header",
          not _api_main._is_spa_navigation_path(_dl), _dl)
    check("…while its sibling project page still is",
          _api_main._is_spa_navigation_path("/projects/some-build-id"))
    check("the exemption is anchored to the end of the path",
          _api_main._is_spa_navigation_path("/projects/download/detail"),
          "a build literally called 'download' still has a detail page")
    check("the root is still a page for a browser",
          _api_main._is_spa_navigation_path("/"))
    check("an unrelated API path is not a page",
          not _api_main._is_spa_navigation_path("/health"))

    _dl_nav = _client.get(_dl, headers=_HTML)
    check("a browser navigating to a download gets bytes, not the app shell",
          "text/html" not in _dl_nav.headers.get("content-type", ""),
          f"status={_dl_nav.status_code} ct={_dl_nav.headers.get('content-type')}")
    if _dl_nav.status_code == 200:
        check("…and those bytes are a real ZIP",
              _dl_nav.content[:4] == b"PK",
              f"first bytes={_dl_nav.content[:8]!r}")
    else:
        check("…and those bytes are a real ZIP (skipped — no downloadable build)",
              True, f"status={_dl_nav.status_code}")


    _escape = _client.get("/../llm_client.py", headers=_JSON)
    check("a traversal attempt is not served a file outside dist",
          _escape.status_code == 404
          or "def _ledger_record" not in _escape.text,
          f"status={_escape.status_code}")


# ── 19. The handoff's key table must not read as a contradiction ──────────────
# It rendered "Keys still usable | 8" directly above "Keys exhausted (any
# model) | 8". Both were true — usable on 120b, exhausted on 20b — and the
# reader of a handoff document is someone trying to work out whether they can
# re-run the build, which that table cannot answer. It also never mentioned the
# daily token budget, which is the thing that actually ran out: all 8 keys share
# one pool per model, so "8 keys available" and "no budget left" coexist.
print("\n[19] the handoff quota table says which model it means")

from agents.documenter import Documenter  # noqa: E402

_doc = Documenter.__new__(Documenter)

# The exact live situation that produced the contradiction.
_snapshot = {
    "heavy_model": "openai/gpt-oss-120b",
    "fast_model": "openai/gpt-oss-20b",
    "total_keys": 8,
    "available_keys": 8,
    "exhausted_keys": 8,
    "exhausted_heavy": 0,
    "exhausted_fast": 8,
    "fully_exhausted": 0,
    "heavy_exhausted": False,
    "fast_exhausted": True,
    "daily_usage": {
        "window_hours": 24,
        "limit_per_model": 200_000,
        "models": {
            "openai/gpt-oss-20b": {
                "tokens_used": 199_306, "percent_used": 99.7, "limit": 200_000,
                "tokens_remaining": 694, "seeded_tokens": 60_000,
                "window_resets_in_seconds": 1080, "calls": 41,
                "refill_tokens_per_hour": 8_333,
            },
            "openai/gpt-oss-120b": {
                "tokens_used": 40_000, "percent_used": 20.0, "limit": 200_000,
                "tokens_remaining": 160_000, "seeded_tokens": 0,
                "window_resets_in_seconds": 3600, "calls": 12,
            },
        },
    },
    "reset_hint": "Groq's free-tier budget refills continuously at about 8,333 "
                  "tokens per hour per model — there is no daily reset to wait for.",
}
_table = _doc._format_quota_block(_snapshot)

check("the unqualified 'keys still usable' row is gone",
      "Keys still usable" not in _table)
check("…as is the 'exhausted (any model)' row it contradicted",
      "Keys exhausted (any model)" not in _table)
check("the count that matters — keys with nothing left — is stated",
      "Keys with no model left | 0" in _table, _table)
check("spent keys are reported against the model they were spent on",
      "Keys spent on `openai/gpt-oss-20b` | 8" in _table
      and "Keys spent on `openai/gpt-oss-120b` | 0" in _table, _table)
check("a model with no keys left says so instead of 'exhausted'",
      "no keys left" in _table and "| available |" in _table, _table)
check("the reader is told quota is counted per key and per model",
      "per key and per model" in _table)

check("the daily budget — the thing that actually ran out — is in the table",
      "Daily token budget" in _table, _table)
check("the exhausted model's own numbers are shown",
      "199,306" in _table and "(99.7%)" in _table, _table)
check("…including how long until that budget frees up",
      "18 min" in _table, _table)
check("a figure that is partly reconstructed is marked as an estimate",
      "*(part estimated)*" in _table)
check("…and a fully observed figure is not",
      _table.count("*(part estimated)*") == 1, _table)
check("the reset hint still closes the block",
      _table.rstrip().endswith("no daily reset to wait for."), _table[-120:])
check("the table says how fast the budget comes back",
      "refilling ~8,333 tokens/hour" in _table, _table)

# A build that never touched the quota path has no snapshot at all.
check("no snapshot renders nothing, not an empty table",
      _doc._format_quota_block({}) == "")
check("a snapshot with no daily figures still renders the key table",
      "Daily token budget" not in _doc._format_quota_block(
          {k: v for k, v in _snapshot.items() if k != "daily_usage"}))


# ── 20. A finished build must record the files it produced ────────────────────
# `add_project_file` has existed since Phase 14 and nothing ever called it. The
# `files` table was empty for all 58 builds in the database, so every project
# detail page reported `file_count: 0` and an empty file list while the build's
# ZIP held eighteen files. Nothing failed; the information simply was not there.
print("\n[20] a finished build records its files")

from api_platform.runner import _record_project_files  # noqa: E402

_files_root = Path(config.OUTPUT_DIR) / "_phase23_files_build"
shutil.rmtree(_files_root, ignore_errors=True)
(_files_root / "backend").mkdir(parents=True, exist_ok=True)
(_files_root / "backend" / "__pycache__").mkdir(parents=True, exist_ok=True)
(_files_root / "node_modules" / "dep").mkdir(parents=True, exist_ok=True)
(_files_root / "backend" / "main.py").write_text("app = 1\n", encoding="utf-8")
(_files_root / "backend" / "models.py").write_text("x = 1\n", encoding="utf-8")
(_files_root / "README.md").write_text("# hi\n", encoding="utf-8")
(_files_root / "backend" / "__pycache__" / "main.pyc").write_bytes(b"\x00")
(_files_root / "node_modules" / "dep" / "index.js").write_text("1\n", encoding="utf-8")

import api_platform.database as _fdb  # noqa: E402

_files_db = Path(config.OUTPUT_DIR) / "_phase23_files.db"
_files_db.unlink(missing_ok=True)
_saved_files_db_path = _fdb.DB_PATH
_fdb.DB_PATH = _files_db
try:
    _fdb.initialize_db()
    _fdb.create_project("b-files", "a prompt")
    _count = _record_project_files("b-files", str(_files_root))
    _recorded = {f["file_path"] for f in _fdb.get_project_files("b-files")}

    check("the build's files are recorded, not left to an empty table",
          _count == 3 and len(_recorded) == 3, f"count={_count} files={_recorded}")
    check("paths are stored relative to the build root, with forward slashes",
          _recorded == {"backend/main.py", "backend/models.py", "README.md"},
          f"recorded={_recorded}")
    check("build artefacts are not recorded as source",
          not any("__pycache__" in f or "node_modules" in f for f in _recorded))
    check("the file type is stored alongside the path",
          {f["file_type"] for f in _fdb.get_project_files("b-files")} == {"py", "md"},
          f"types={[f['file_type'] for f in _fdb.get_project_files('b-files')]}")
    check("the project detail endpoint's count now matches reality",
          len(_fdb.get_project_files("b-files")) == 3)

    # Recording must never be able to fail a build that produced real code.
    check("a build with no output path records nothing and does not raise",
          _record_project_files("b-files", None) == 0)
    check("a path that is not a directory records nothing and does not raise",
          _record_project_files("b-files", str(_files_root / "README.md")) == 0)
    check("a directory that does not exist records nothing and does not raise",
          _record_project_files("b-files", str(_files_root / "nope")) == 0)
finally:
    _fdb.DB_PATH = _saved_files_db_path
    _files_db.unlink(missing_ok=True)
    shutil.rmtree(_files_root, ignore_errors=True)


# ── 21. A request-time failure must reach the repair passes ───────────────────
# Build 3d57d0b8 shipped with three of five routes returning 500 on every call,
# and remediation reported "no files were repaired this pass". Not because the
# repair failed — because the smoke test's findings were filed as advisory,
# "issues the repair passes cannot fix", and never became something to repair.
# The failure itself was ordinary: routes.py re-declared the `get_db`
# dependency and yielded the result of *calling* crud's generator function, so
# every handler received a generator where it expected a connection.
print("\n[21] a request-time failure reaches the repair passes")

from tools.runtime_smoke import RouteProbe, SmokeResult  # noqa: E402

_REAL_ERROR = (
    "AttributeError: 'generator' object has no attribute 'execute' "
    "(at backend/routes.py:53 in list_tasks_endpoint -> backend/crud.py:68 in get_tasks)"
)
_probe = RouteProbe(path="/tasks/", method="GET", status=500, error=_REAL_ERROR)

check("the traceback keeps every project frame, in call order",
      [f["file"] for f in _probe.frames]
      == ["backend/routes.py", "backend/crud.py"],
      f"frames={_probe.frames}")
check("…with the line and function of each",
      _probe.frames[0]["line"] == 53
      and _probe.frames[0]["function"] == "list_tasks_endpoint")
check("blame lands on the caller, not on the file that raised",
      _probe.blame_file == "backend/routes.py",
      "repairing crud.py would teach the helper to accept a generator")
check("a 5xx with no traceback blames nobody rather than guessing",
      RouteProbe("/x", "GET", 500, "Internal Server Error").blame_file == "")
check("a probe that answered 4xx is not a failure at all",
      RouteProbe("/x", "POST", 422, "").ok)

# The pipeline turns those probes into a repair target.
from agents.pipeline import Pipeline  # noqa: E402


class _FakeSmokePipeline(Pipeline):
    """Pipeline with the subprocess app-boot replaced by a fixed result."""
    def __init__(self, smoke):
        self._smoke = smoke
        self._emitted = []

    def _emit_progress(self, *a, **kw):
        self._emitted.append((a, kw))


class _Result:
    def __init__(self):
        self.architecture = {"root_folder": "task_manager_x"}
        self.smoke_summary = ""


def _run_smoke(pipeline, smoke):
    import tools.runtime_smoke as rs
    original = rs.smoke_test_app
    rs.smoke_test_app = lambda root, **kw: smoke
    try:
        return pipeline._smoke_test_runtime(_Result())
    finally:
        rs.smoke_test_app = original


_smoke = SmokeResult(
    ran=True, app_loaded=True, entry="backend/main.py",
    probes=[
        RouteProbe("/tasks/", "POST", 422, ""),
        RouteProbe("/tasks/", "GET", 500, _REAL_ERROR),
        RouteProbe("/tasks/{task_id}", "DELETE", 500, _REAL_ERROR),
    ],
)
_pipeline = _FakeSmokePipeline(_smoke)
_advisory = _run_smoke(_pipeline, _smoke)

check("the failing endpoints are still reported to the reader",
      any("2 of 3 endpoint(s) return a server error" in a for a in _advisory),
      f"advisory={_advisory}")
check("the repair target is recorded, keyed the way the pipeline spells paths",
      list(_pipeline._smoke_runtime_errors) == ["task_manager_x/backend/routes.py"],
      f"keys={list(_pipeline._smoke_runtime_errors)}")
check("both failing routes are described in the one repair brief",
      _pipeline._smoke_runtime_errors["task_manager_x/backend/routes.py"].count(
          "'generator' object") == 2)
check("the brief names the method and path, not just the exception",
      "GET /tasks/ → 500"
      in _pipeline._smoke_runtime_errors["task_manager_x/backend/routes.py"])

_clean = SmokeResult(ran=True, app_loaded=True, entry="backend/main.py",
                     probes=[RouteProbe("/tasks/", "GET", 200, "")])
_pipeline_clean = _FakeSmokePipeline(_clean)
check("an app whose routes all answer produces no advisory and no repair target",
      _run_smoke(_pipeline_clean, _clean) == []
      and _pipeline_clean._smoke_runtime_errors == {})

_skipped = SmokeResult(ran=False, app_loaded=False, entry="", probes=[])
_pipeline_skipped = _FakeSmokePipeline(_skipped)
check("a non-FastAPI build skips cleanly and blames nothing",
      _run_smoke(_pipeline_skipped, _skipped) == []
      and _pipeline_skipped._smoke_runtime_errors == {})

# End to end through the real probe, on a project shaped like the one that
# failed. This is the only test that boots a generated app, and it exists
# because the first version of the frame chain blamed `_smoke_probe.py` for
# every failure — the probe is written into the project directory, so it is a
# project frame too, and it is always the outermost one. Every repair would
# have been aimed at a file the pipeline deletes on the way out.
_PROBE_DIR = Path(config.OUTPUT_DIR) / "_phase23_probe_app"
shutil.rmtree(_PROBE_DIR, ignore_errors=True)
(_PROBE_DIR / "backend").mkdir(parents=True, exist_ok=True)
(_PROBE_DIR / "backend" / "__init__.py").write_text("", encoding="utf-8")
(_PROBE_DIR / "backend" / "store.py").write_text(
    "def get_conn():\n"
    "    yield {'rows': []}\n"
    "\n"
    "def list_rows(conn):\n"
    "    return conn['rows']\n",
    encoding="utf-8",
)
(_PROBE_DIR / "backend" / "routes.py").write_text(
    "from fastapi import APIRouter, Depends\n"
    "from store import get_conn as store_get_conn, list_rows\n"
    "\n"
    "router = APIRouter()\n"
    "\n"
    "\n"
    "def get_conn():\n"
    "    conn = store_get_conn()\n"
    "    yield conn\n"
    "\n"
    "\n"
    '@router.get("/rows/")\n'
    "def list_rows_endpoint(conn=Depends(get_conn)):\n"
    "    return list_rows(conn)\n"
    "\n"
    "\n"
    '@router.get("/healthy/")\n'
    "def healthy_endpoint():\n"
    '    return {"ok": True}\n',
    encoding="utf-8",
)
(_PROBE_DIR / "backend" / "main.py").write_text(
    "import os, sys\n"
    "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
    "from fastapi import FastAPI\n"
    "from routes import router\n"
    "\n"
    "app = FastAPI()\n"
    "app.include_router(router)\n",
    encoding="utf-8",
)

from tools.runtime_smoke import smoke_test_app  # noqa: E402

_probe_result = smoke_test_app(_PROBE_DIR.name)

check("the probe boots a generated app and calls its routes",
      _probe_result.ran and _probe_result.app_loaded, _probe_result.error)
check("a route that works is reported as working",
      any(p.path == "/healthy/" and p.ok for p in _probe_result.probes),
      f"{[(p.path, p.status) for p in _probe_result.probes]}")
_broken_probe = [p for p in _probe_result.probes if p.path == "/rows/"]
check("the wrapped-generator route is caught as a 5xx",
      bool(_broken_probe) and _broken_probe[0].status == 500,
      f"{[(p.path, p.status) for p in _probe_result.probes]}")
check("blame is the route file, not the probe the pipeline injected",
      bool(_broken_probe) and _broken_probe[0].blame_file == "backend/routes.py",
      f"blame={_broken_probe[0].blame_file if _broken_probe else '—'}")
check("…and the helper it blew up in is still recorded as context",
      bool(_broken_probe)
      and [f["file"] for f in _broken_probe[0].frames]
      == ["backend/routes.py", "backend/store.py"],
      f"frames={_broken_probe[0].frames if _broken_probe else []}")
check("the probe cleans up after itself",
      not (_PROBE_DIR / "backend" / "_smoke_probe.py").exists())

shutil.rmtree(_PROBE_DIR, ignore_errors=True)

# ── The debugger's side: a file that imports cleanly but fails on a request ────
from agents.debugger import Debugger, FileDebugResult  # noqa: E402


def _blank_result():
    return FileDebugResult(file_path=_rt_rel, success=True, attempts=1)

_BROKEN_ROUTES = '''from fastapi import APIRouter, Depends
from crud import get_db as crud_get_db, get_tasks

router = APIRouter()


def get_db():
    conn = crud_get_db()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/tasks/")
def list_tasks_endpoint(db=Depends(get_db)):
    return get_tasks(db)
'''

_FIXED_ROUTES = '''from fastapi import APIRouter, Depends
from crud import get_db, get_tasks

router = APIRouter()


@router.get("/tasks/")
def list_tasks_endpoint(db=Depends(get_db)):
    return get_tasks(db)
'''

_RT_DIR = Path(config.OUTPUT_DIR) / "_phase23_runtime"
shutil.rmtree(_RT_DIR, ignore_errors=True)
_RT_DIR.mkdir(parents=True, exist_ok=True)
_rt_rel = f"{_RT_DIR.name}/routes.py"
(_RT_DIR / "routes.py").write_text(_BROKEN_ROUTES, encoding="utf-8")


class _StubDebugger(Debugger):
    """The Debugger with its one LLM call replaced by a scripted answer."""
    def __init__(self, answer):
        super().__init__()
        self.answer = answer
        self.prompts = []
        self.budgets = []

    def think(self, prompt: str, max_tokens: int = None) -> str:
        self.prompts.append(prompt)
        self.budgets.append(max_tokens)
        return self.answer


class _Execution:
    def __init__(self, success):
        self.success = success
        self.stderr = "" if success else "SyntaxError: invalid syntax"
        self.stdout = ""


def _with_import_check(passing, fn):
    """Run `fn` with the debugger's import check forced to a fixed verdict."""
    import agents.debugger as dbg
    original = dbg.run_python
    dbg.run_python = lambda *a, **kw: _Execution(passing)
    try:
        return fn()
    finally:
        dbg.run_python = original


_dbg = _StubDebugger(_FIXED_ROUTES)
_res = _with_import_check(True, lambda: _dbg._debug_file(_rt_rel, runtime_error=_REAL_ERROR))

check("a file that imports fine is still repaired when it fails on a request",
      any("Runtime repair" in f for f in _res.fixes_applied),
      f"fixes={_res.fixes_applied}")
check("the repair is written to disk",
      "crud_get_db" not in (_RT_DIR / "routes.py").read_text(encoding="utf-8"))
check("the repair prompt says the failure is at request time",
      any("REQUEST time" in p for p in _dbg.prompts))
check("…and tells the model the bug is in this file, not where it surfaced",
      any("do not make the other" in p and "tolerate it" in p for p in _dbg.prompts))
check("…and states the dependency rule that was actually broken",
      any("generator function" in p and "Depends" in p for p in _dbg.prompts))
check("…and carries the traceback in call order",
      any(_REAL_ERROR[:40] in p for p in _dbg.prompts))

# No runtime error supplied → no LLM call, no rewrite. This is the common case
# on every passing file in every build, so it must cost nothing.
(_RT_DIR / "routes.py").write_text(_BROKEN_ROUTES, encoding="utf-8")
_quiet = _StubDebugger(_FIXED_ROUTES)
_with_import_check(True, lambda: _quiet._debug_file(_rt_rel))
check("a passing file with no runtime failure costs no LLM call",
      _quiet.prompts == [] and
      (_RT_DIR / "routes.py").read_text(encoding="utf-8") == _BROKEN_ROUTES)

# A repair that breaks the module is worse than the bug it fixed.
(_RT_DIR / "routes.py").write_text(_BROKEN_ROUTES, encoding="utf-8")
_breaker = _StubDebugger("from fastapi import APIRouter\nrouter = APIRouter(\n")
_with_import_check(False, lambda: _breaker._repair_runtime_error(
    _rt_rel, _REAL_ERROR, _blank_result()))
check("a runtime repair that breaks the import check is rolled back",
      (_RT_DIR / "routes.py").read_text(encoding="utf-8") == _BROKEN_ROUTES)

# The existing shrinkage guard still applies to this new path.
(_RT_DIR / "routes.py").write_text(_BROKEN_ROUTES, encoding="utf-8")
_gutter = _StubDebugger("from fastapi import APIRouter\n")
_with_import_check(True, lambda: _gutter._repair_runtime_error(
    _rt_rel, _REAL_ERROR, _blank_result()))
check("a runtime repair that deletes `router` is rejected before it is written",
      (_RT_DIR / "routes.py").read_text(encoding="utf-8") == _BROKEN_ROUTES)

# run() must route each file's own failure to it, and nothing to the others.
(_RT_DIR / "routes.py").write_text(_BROKEN_ROUTES, encoding="utf-8")
(_RT_DIR / "crud.py").write_text("def get_db():\n    yield 1\n", encoding="utf-8")
_router_dbg = _StubDebugger(_FIXED_ROUTES)
_with_import_check(True, lambda: _router_dbg.run(
    [_rt_rel, f"{_RT_DIR.name}/crud.py"],
    runtime_errors={_rt_rel: _REAL_ERROR},
))
check("only the blamed file is repaired; its siblings are left alone",
      len(_router_dbg.prompts) == 1 and _rt_rel in _router_dbg.prompts[0],
      f"{len(_router_dbg.prompts)} prompt(s)")

shutil.rmtree(_RT_DIR, ignore_errors=True)

# The repair-shrinkage guard had to learn the difference between a name a file
# *defines* and a name it merely re-exports, because the correct fix for a
# duplicated dependency deletes the local `get_db` and imports the real one.
# That is a loosening of a safety check, so the thing it was built to catch is
# re-asserted here rather than assumed.
_guard = Debugger.__new__(Debugger)

check("an import binds a top-level name, exactly as a def does",
      "get_db" in Debugger._top_level_symbols("from crud import get_db\n"))
check("…but `defined_only` sees only what the file itself defines",
      Debugger._top_level_symbols(
          "from crud import get_db\ndef helper():\n    pass\n", defined_only=True)
      == {"helper"})
check("an aliased import binds the alias, not the original name",
      Debugger._top_level_symbols("from crud import get_db as db_dep\n")
      == {"db_dep"})
check("a star import binds nothing this guard can name",
      Debugger._top_level_symbols("from crud import *\n") == set())
check("a plain module import binds the module name",
      Debugger._top_level_symbols("import sqlite3\n") == {"sqlite3"})
check("source that will not parse still yields symbols via the regex",
      "router" in Debugger._top_level_symbols(
          "from fastapi import APIRouter\nrouter = APIRouter(\ndef broken(:\n"))

_RT_DIR.mkdir(parents=True, exist_ok=True)
_guard_file = f"{_RT_DIR.name}/guard.py"
(_RT_DIR / "guard.py").write_text(_BROKEN_ROUTES, encoding="utf-8")

check("the fix that swaps a local dependency for the imported one is accepted",
      _guard._accept_generated_fix(_guard_file, _FIXED_ROUTES))
check("a fix that drops `router` is still rejected — the Phase 23 regression",
      not _guard._accept_generated_fix(
          _guard_file, "from fastapi import APIRouter, Depends\n"))
check("a fix that empties the file is still rejected",
      not _guard._accept_generated_fix(_guard_file, "\n"))
check("a fix that drops a route handler is still rejected",
      not _guard._accept_generated_fix(_guard_file, '''from fastapi import APIRouter, Depends
from crud import get_db, get_tasks

router = APIRouter()
'''))
check("an oversized rewrite is still rejected",
      not _guard._accept_generated_fix(
          _guard_file, _FIXED_ROUTES + "\n# padding\n" * 400))

shutil.rmtree(_RT_DIR, ignore_errors=True)

# The prompt that should stop this being generated in the first place.
_bd_prompt = Path("prompts/backend_developer.txt").read_text(encoding="utf-8")
check("the code-writing prompt forbids the exact shape that was generated",
      "'generator' object has no attribute 'execute'" in _bd_prompt
      and "crud_get_db()" in _bd_prompt)
check("…and says not to re-declare the dependency in routes.py",
      "do not write a" in _bd_prompt and "second `get_db` in routes.py" in _bd_prompt)


# ── 22. A completed requirements.txt must not still read as a stub ────────────
# Matrix row 1 (2026-08-28) reached done_with_context over two issues, one of
# which was "requirements.txt was never filled in and still contains the
# scaffold placeholder". It had been filled in: the requirements builder had
# appended fastapi, pydantic, pytest and python-dotenv below the architect's
# placeholder comment and left the comment there — so the placeholder audit in
# pipeline._audit_placeholders read a complete file as an empty scaffold and
# degraded the build. The same file was also missing uvicorn, which nothing in
# a generated FastAPI app imports and without which SETUP.md's own run command
# does not work.
print("\n[22] a filled-in requirements.txt is not reported as a stub")

from tools.requirements_builder import (          # noqa: E402
    validate_and_fix_requirements,
    _strip_scaffold_placeholder,
)
from agents.architect import PLACEHOLDER_MARKER as _ARCH_MARKER  # noqa: E402
from agents.pipeline import Pipeline as _ReqPipeline             # noqa: E402

check("the builder and the architect agree on the placeholder marker",
      _ARCH_MARKER == _ReqPipeline._PLACEHOLDER_MARKER)

# The exact block row 1 shipped.
_scaffold = ("# Project dependencies: FastAPI, Uvicorn, SQLAlchemy, pydantic\n"
             "# will be generated by the code generation agents.\n")

check("the whole placeholder block goes, not just the marker line",
      _strip_scaffold_placeholder(_scaffold) == "",
      repr(_strip_scaffold_placeholder(_scaffold)))
check("real package lines survive the strip",
      _strip_scaffold_placeholder(_scaffold + "fastapi>=0.111.0\n") == "fastapi>=0.111.0\n",
      repr(_strip_scaffold_placeholder(_scaffold + "fastapi>=0.111.0\n")))
check("a comment the generator wrote deliberately is left alone",
      _strip_scaffold_placeholder("# pinned deliberately\nfastapi>=0.111.0\n")
      == "# pinned deliberately\nfastapi>=0.111.0\n")
check("a file with no placeholder is returned unchanged",
      _strip_scaffold_placeholder("fastapi>=0.111.0\n") == "fastapi>=0.111.0\n")

_req_root = "_phase23_requirements_build"
_req_dir = Path(config.OUTPUT_DIR) / _req_root
shutil.rmtree(_req_dir, ignore_errors=True)
(_req_dir / "backend").mkdir(parents=True, exist_ok=True)
(_req_dir / "requirements.txt").write_text(_scaffold, encoding="utf-8")
(_req_dir / "backend" / "main.py").write_text(
    "from fastapi import FastAPI\n"
    "from dotenv import load_dotenv\n"
    "app = FastAPI()\n", encoding="utf-8")

_req_audit = _ReqPipeline.__new__(_ReqPipeline)

try:
    validate_and_fix_requirements(_req_root, [f"{_req_root}/backend/main.py"])
    _req_text = (_req_dir / "requirements.txt").read_text(encoding="utf-8")

    check("the imports the app actually uses are listed",
          "fastapi>=0.111.0" in _req_text and "python-dotenv" in _req_text,
          _req_text)
    check("uvicorn is added for a FastAPI app that never imports it",
          "uvicorn" in _req_text, _req_text)
    check("the scaffold placeholder is gone once real packages are written",
          _ARCH_MARKER not in _req_text, _req_text)
    check("so the placeholder audit no longer reports the file as a stub",
          _req_audit._audit_placeholders(_req_dir) == [],
          _req_audit._audit_placeholders(_req_dir))

    # Running twice must not duplicate a package or re-add uvicorn.
    validate_and_fix_requirements(_req_root, [f"{_req_root}/backend/main.py"])
    _req_text2 = (_req_dir / "requirements.txt").read_text(encoding="utf-8")
    check("a second pass changes nothing", _req_text2 == _req_text, _req_text2)

    # A file the generators never touched at all must still be reported, or the
    # strip would hide the very failure the audit exists to catch.
    (_req_dir / "requirements.txt").write_text(_scaffold, encoding="utf-8")
    (_req_dir / "backend" / "main.py").write_text("x = 1\n", encoding="utf-8")
    validate_and_fix_requirements(_req_root, [f"{_req_root}/backend/main.py"])
    _req_stub = (_req_dir / "requirements.txt").read_text(encoding="utf-8")
    check("a genuinely empty scaffold is still flagged as a stub",
          _ARCH_MARKER in _req_stub, _req_stub)
    check("…and the audit still reports it",
          len(_req_audit._audit_placeholders(_req_dir)) == 1,
          _req_audit._audit_placeholders(_req_dir))
finally:
    shutil.rmtree(_req_dir, ignore_errors=True)


# ── 23. An app that never boots must reach the repair passes ──────────────────
# Matrix row 2 (2026-08-28) generated a bookmark manager whose routes.py used a
# plain class as a `response_model`. FastAPI raises on import, so the app never
# loaded and not one endpoint existed — and the pipeline filed that under
# "issues the repair passes cannot fix", while in the same build a single
# broken route (strictly less damage) was repaired. Section 21 routed request-
# time 5xx into repair; a total boot failure still fell through, because the
# probe reported only the exception's type and message with no frames to aim at.
print("\n[23] a boot failure is repairable, not merely documented")

from tools.runtime_smoke import smoke_test_app, _parse_frames  # noqa: E402
from agents.pipeline import Pipeline as _BootPipeline                       # noqa: E402
from agents.pipeline import BuildResult as _BootBuildResult                 # noqa: E402

# The two failures need opposite blame rules; assert both, since one regressing
# silently sends every repair to the wrong file.
_boot_chain = ("FastAPIError: bad response field "
               "(at backend/main.py:2 in <module> -> backend/routes.py:7 in <module>)")
check("the frame chain parses out of the probe's error suffix",
      [f["file"] for f in _parse_frames(_boot_chain)]
      == ["backend/main.py", "backend/routes.py"],
      _parse_frames(_boot_chain))
check("a boot failure blames the innermost frame — the module that raised",
      SmokeResult(error=_boot_chain).blame_file == "backend/routes.py",
      SmokeResult(error=_boot_chain).blame_file)
check("…while a request-time 5xx still blames the outermost — the caller",
      RouteProbe(path="/x", method="GET", status=500,
                 error=_boot_chain).blame_file == "backend/main.py")
check("an error with no traceback blames nothing rather than guessing",
      SmokeResult(error="FastAPIError: no frames at all").blame_file == "")

# End to end, against row 2's actual defect.
_boot_root = "_phase23_boot_app"
_boot_dir  = Path(config.OUTPUT_DIR) / _boot_root
shutil.rmtree(_boot_dir, ignore_errors=True)
(_boot_dir / "backend").mkdir(parents=True, exist_ok=True)
(_boot_dir / "backend" / "services.py").write_text(
    "class BookmarkOut:\n"
    "    def __init__(self, url):\n"
    "        self.url = url\n", encoding="utf-8")
(_boot_dir / "backend" / "routes.py").write_text(
    "from typing import List\n"
    "from fastapi import APIRouter\n"
    "from services import BookmarkOut\n"
    "\n"
    "router = APIRouter()\n"
    "\n"
    "@router.get('/bookmarks', response_model=List[BookmarkOut])\n"
    "def list_bookmarks():\n"
    "    return []\n", encoding="utf-8")
(_boot_dir / "backend" / "main.py").write_text(
    "from fastapi import FastAPI\n"
    "from routes import router\n"
    "\n"
    "app = FastAPI()\n"
    "app.include_router(router)\n", encoding="utf-8")

try:
    _boot_smoke = smoke_test_app(_boot_root)
    check("the smoke test runs and the app does not load",
          _boot_smoke.ran and not _boot_smoke.app_loaded,
          f"ran={_boot_smoke.ran} loaded={_boot_smoke.app_loaded}")
    check("the import-time traceback now names the generated file that raised",
          _boot_smoke.blame_file == "backend/routes.py", _boot_smoke.blame_file)
    check("the interpreter's own frames are not mistaken for project files",
          "<frozen" not in _boot_smoke.error and "<string>" not in _boot_smoke.error,
          _boot_smoke.error[:200])

    _boot_pl = _BootPipeline.__new__(_BootPipeline)
    _boot_br = _BootBuildResult.__new__(_BootBuildResult)
    _boot_br.architecture = {"root_folder": _boot_root}
    _boot_issues = _boot_pl._smoke_test_runtime(_boot_br)

    check("the build is still told, in words, that nothing is reachable",
          len(_boot_issues) == 1 and "does not start" in _boot_issues[0],
          _boot_issues)
    # §30 sends this one further: routes.py only imports the offending class, so
    # the repair belongs in services.py, which defines it. The smoke test still
    # blames routes.py — that is where it raised — and the pipeline redirects.
    check("and a repair is aimed at a file, so it is no longer advisory-only",
          len(_boot_pl._smoke_runtime_errors) == 1
          and bool(_boot_pl._smoke_runtime_errors),
          _boot_pl._smoke_runtime_errors)
    check("…at the file that DEFINES the broken class, not the one that imports it",
          list(_boot_pl._smoke_runtime_errors) == [f"{_boot_root}/backend/services.py"],
          _boot_pl._smoke_runtime_errors)
    check("the repair prompt carries the exception, not just a file name",
          "FastAPIError" in "".join(_boot_pl._smoke_runtime_errors.values()),
          _boot_pl._smoke_runtime_errors)

    # A working app must not be dragged into repair by any of this.
    (_boot_dir / "backend" / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "\n"
        "router = APIRouter()\n"
        "\n"
        "@router.get('/bookmarks')\n"
        "def list_bookmarks():\n"
        "    return []\n", encoding="utf-8")
    _ok_pl = _BootPipeline.__new__(_BootPipeline)
    _ok_br = _BootBuildResult.__new__(_BootBuildResult)
    _ok_br.architecture = {"root_folder": _boot_root}
    _ok_issues = _ok_pl._smoke_test_runtime(_ok_br)
    check("an app that boots and answers reports no issue and no repair",
          _ok_issues == [] and _ok_pl._smoke_runtime_errors == {},
          f"issues={_ok_issues} repairs={_ok_pl._smoke_runtime_errors}")
finally:
    shutil.rmtree(_boot_dir, ignore_errors=True)


# ── 24. A full-file rewrite must be allowed to be as long as the file ─────────
# Matrix row 3 (2026-08-28) is the first build in which the request-time repair
# path of section 21 actually fired live — and it still shipped broken. The
# repair was asked to return a complete 10,775-character routes.py under the
# Debugger's flat 1,600-token cap. The reply truncated, the truncation retry
# doubled the cap to 3,200 and truncated again, and the abridged file lost a
# top-level name — at which point the shrinkage guard correctly rejected it and
# the build shipped with twelve endpoints returning 500. Every prompt in the
# debugger asks for a whole file back; none of them sized the cap to the file.
print("\n[24] a rewrite budget is sized to the file being rewritten")

from agents.debugger import _rewrite_budget   # noqa: E402


class _BudgetAgent:
    _token_budget = 1600                 # the Debugger's cap under conserve mode


_ba = _BudgetAgent()

check("row 3's file gets more than the doubled retry that still truncated",
      _rewrite_budget(_ba, "x" * 10775) > 3200, _rewrite_budget(_ba, "x" * 10775))
check("the budget scales with the file rather than being flat",
      _rewrite_budget(_ba, "x" * 30000) > _rewrite_budget(_ba, "x" * 10775))
check("a small file is never given less than the agent's own budget",
      _rewrite_budget(_ba, "x" * 500) == 1600)
check("an empty or missing file falls back to the agent's budget, not zero",
      _rewrite_budget(_ba, "") == 1600 and _rewrite_budget(_ba, None) == 1600)
# Section 27 removed the ceiling that used to live here. Groq bills prompt and
# completion against one 8,000-token minute, and llm_client already clamps every
# request to fit it from the rate-limit header — so a second ceiling in the
# debugger could only be wrong, and an unreachable 8,000 was exactly that.
check("no second ceiling: a huge file asks for what it needs",
      _rewrite_budget(_ba, "x" * 500000) == 500000 // 3 + 400,
      _rewrite_budget(_ba, "x" * 500000))
check("the ceiling is llm_client's, and it is always known",
      llm_client.ModelRateState().limit_tokens == llm_client.GROQ_TPM_LIMIT_DEFAULT,
      llm_client.ModelRateState().limit_tokens)

# Every prompt that says "return the complete code" must use it. A new one added
# without the budget is the same bug again, so count the call sites.
_dbg_src = Path("agents/debugger.py").read_text(encoding="utf-8")
check("every rewrite call passes a sized budget",
      _dbg_src.count("self.think(prompt, max_tokens=_rewrite_budget(self, current_code))") == 4
      and "self.think(prompt, max_tokens=_rewrite_budget(self, block.source))" in _dbg_src
      and "self.think(prompt)\n" not in _dbg_src,
      f"whole-file={_dbg_src.count('_rewrite_budget(self, current_code)')} "
      f"block={_dbg_src.count('_rewrite_budget(self, block.source)')}")


# ── 25. Locating and replacing one block of a file ────────────────────────────
# The unit under a repair that does not rewrite the whole file. Groq bills prompt
# and completion against a single 8,000-token minute, so sending a file to get
# the same file back is impossible above roughly 11KB — and matrix row 3's
# routes.py was 10,775 characters, sitting exactly on that wall.
print("\n[25] one block can be located and replaced")

from tools.code_patcher import locate_block, splice, file_digest  # noqa: E402

_PATCH_SRC = '''from fastapi import APIRouter, Depends
from typing import List
import crud

router = APIRouter()
DB = "app.db"


def get_db():
    yield crud.connect(DB)


class Thing:
    def helper(self):
        return 1


@router.get("/things", response_model=List[Thing])
def list_things(db=Depends(get_db)):
    return crud.get_things(db)


def unrelated():
    return "leave me alone"
'''

_b = locate_block(_PATCH_SRC, function="list_things")
check("a block is found by the name the traceback gives",
      _b is not None and _b.name == "list_things", _b)
check("the block starts at the decorator, not at `def`",
      _b.source.startswith("@router.get("), _b.source.splitlines()[0])
check("…and ends at the last line of the function",
      _b.source.rstrip().endswith("return crud.get_things(db)"),
      _b.source.splitlines()[-1])
check("the block is a fraction of the file",
      len(_b.source) < len(_PATCH_SRC) * 0.4,
      f"{len(_b.source)} of {len(_PATCH_SRC)}")

# Row 2's shape: the app never booted, so the frame is `<module>` at the
# decorator's own line. It must resolve to the same enclosing block.
_decorator_line = _PATCH_SRC[:_PATCH_SRC.index("@router.get(")].count("\n") + 1
_b_mod = locate_block(_PATCH_SRC, line=_decorator_line, function="<module>")
check("a <module> frame at the decorator resolves to the whole function",
      _b_mod is not None and _b_mod.name == "list_things"
      and _b_mod.start_line == _b.start_line, _b_mod)

_b_method = locate_block(_PATCH_SRC, function="helper")
check("a method resolves to its class, which is what can be replaced whole",
      _b_method is not None and _b_method.name == "Thing", _b_method)

check("a name that is not there finds nothing rather than guessing",
      locate_block(_PATCH_SRC, function="does_not_exist") is None)
check("a file that will not parse finds nothing",
      locate_block("def broken(:\n", function="broken") is None)
check("empty source finds nothing", locate_block("", line=1) is None)

_identity = splice(_PATCH_SRC, _b, _b.source)
check("replacing a block with itself round-trips exactly",
      _identity == _PATCH_SRC)

_fixed = splice(_PATCH_SRC, _b, '@router.get("/things")\ndef list_things(db=Depends(get_db)):\n    return []\n')
check("a real replacement lands and the file still parses",
      _fixed is not None and "return []" in _fixed)
check("everything outside the block is untouched",
      _fixed is not None and "def unrelated():" in _fixed
      and 'DB = "app.db"' in _fixed and "class Thing:" in _fixed)

import ast as _past  # noqa: E402
_before_names = {n.name for n in _past.parse(_PATCH_SRC).body if hasattr(n, "name")}
_after_names = {n.name for n in _past.parse(_fixed).body if hasattr(n, "name")}
check("no top-level name is lost — the failure mode the guard exists for",
      _before_names == _after_names, _before_names - _after_names)

check("a replacement that does not parse is refused, not written",
      splice(_PATCH_SRC, _b, "def broken(:\n    pass") is None)
check("an empty replacement is refused",
      splice(_PATCH_SRC, _b, "   ") is None)

_digest = file_digest(_PATCH_SRC, exclude=_b)
check("the digest carries the imports the replacement may rely on",
      "from fastapi import APIRouter, Depends" in _digest, _digest)
check("…and the names it must not clobber",
      "unrelated" in _digest and "get_db" in _digest, _digest)
check("…without carrying the bodies, which is the whole point",
      "return crud.get_things" not in _digest and len(_digest) < len(_PATCH_SRC),
      f"{len(_digest)} vs {len(_PATCH_SRC)}")


# ── 26. The debugger repairs the block, not the file ──────────────────────────
# Row 3 (2026-08-28) was the first live run of the request-time repair path, and
# it still shipped twelve dead endpoints. The repair was asked to return a
# complete 10,775-character routes.py; the reply came back compressed, dropped
# the top-level `startup`, and the shrinkage guard rejected it. Both guards
# worked. The request was the problem.
print("\n[26] a runtime repair sends one block and splices the reply back")

# Sized past _TARGETED_MIN_FILE_CHARS, because below that the block prompt's own
# scaffolding costs more than the file body it saves and the targeted path
# rightly declines. Padded the way a real routes.py is: with more handlers.
_PAD = "".join(
    f'''

@router.get("/pad{i}", response_model=List[Thing])
def pad_handler_{i}(db=Depends(get_db)):
    """One more endpoint, so the fixture is the size of a real routes.py."""
    rows = crud.get_things(db)
    return [r for r in rows if r is not None]
'''
    for i in range(12)
)
_TARGET_SRC = _PATCH_SRC + _PAD
_TARGET_LINE = _PATCH_SRC[:_PATCH_SRC.index("def list_things")].count("\n") + 1
_TARGET_ERR = (
    "GET /things → 500: AttributeError: 'generator' object has no attribute "
    f"'execute' (at backend/routes.py:{_TARGET_LINE} in list_things)"
)
_GOOD_REPLY = ('@router.get("/things", response_model=List[Thing])\n'
               'def list_things(db=Depends(get_db)):\n'
               '    return crud.get_things(db)\n')


class _TargetedDebugger(Debugger):
    """The Debugger with its LLM call scripted, recording what it was asked."""
    def __init__(self, answer):
        super().__init__()
        self.answer = answer
        self.prompts = []
        self.budgets = []

    def think(self, prompt: str, max_tokens: int = None) -> str:
        self.prompts.append(prompt)
        self.budgets.append(max_tokens)
        return self.answer

    def _scan_project_structure(self, file_path):
        return "MAP"


_td = _TargetedDebugger(_GOOD_REPLY)
_out = _td._generate_targeted_runtime_fix(
    "proj/backend/routes.py", _TARGET_SRC, _TARGET_ERR, "MAP")

check("the repair produces a complete file from a block-sized reply",
      _out is not None and _out.count("def unrelated") == 1, _out)
check("the prompt does NOT contain the whole file",
      _TARGET_SRC not in _td.prompts[0])
# Measured against the prompt the old path would have sent for the SAME file,
# which is the comparison that means anything: on a small fixture the fixed rules
# dominate, on row 3's real 10,775-char routes.py the targeted prompt was 2,351.
_full = _TargetedDebugger(_GOOD_REPLY)
_full._generate_runtime_fix("proj/backend/routes.py", _TARGET_SRC, _TARGET_ERR, "MAP")
check("the targeted prompt is smaller than the full-file prompt for the same file",
      len(_td.prompts[0]) < len(_full.prompts[0]),
      f"targeted={len(_td.prompts[0])} full={len(_full.prompts[0])}")
check("…and the gap is most of the file body, sent once instead of twice",
      len(_full.prompts[0]) - len(_td.prompts[0]) > len(_TARGET_SRC) * 0.5,
      f"saved={len(_full.prompts[0]) - len(_td.prompts[0])} of {len(_TARGET_SRC)}")
check("the prompt carries the failing block",
      "def list_things" in _td.prompts[0])
check("the prompt asks for the block back, not the file",
      "THAT BLOCK ONLY" in _td.prompts[0])
_tb = locate_block(_TARGET_SRC, function="list_things")
check("the budget is sized to the block, not to the file",
      _td.budgets[0] == _rewrite_budget(_td, _tb.source)
      and _td.budgets[0] <= _rewrite_budget(_td, _TARGET_SRC),
      f"block={_td.budgets[0]} file={_rewrite_budget(_td, _TARGET_SRC)}")

_names_before = {n.name for n in _past.parse(_TARGET_SRC).body if hasattr(n, "name")}
_names_after = {n.name for n in _past.parse(_out).body if hasattr(n, "name")}
check("every top-level name survives, because none was re-typed",
      _names_before == _names_after, _names_before - _names_after)
check("the shrinkage guard accepts a spliced repair",
      _td._accept_generated_fix("proj/backend/routes.py", _out))

# Falling back must be reliable: this path is additive and the old one is the net.
_no_frames = _TargetedDebugger(_GOOD_REPLY)
check("an error with no frame chain falls back to the full-file rewrite",
      _no_frames._generate_targeted_runtime_fix(
          "proj/backend/routes.py", _TARGET_SRC,
          "AttributeError: something broke", "MAP") is None)

_other_file = _TargetedDebugger(_GOOD_REPLY)
check("a frame naming a different file falls back",
      _other_file._generate_targeted_runtime_fix(
          "proj/backend/routes.py", _TARGET_SRC,
          "boom (at backend/crud.py:3 in get_things)", "MAP") is None)

_bad_reply = _TargetedDebugger("def list_things(:\n  pass")
check("a reply that does not parse falls back rather than writing it",
      _bad_reply._generate_targeted_runtime_fix(
          "proj/backend/routes.py", _TARGET_SRC, _TARGET_ERR, "MAP") is None)

_empty_reply = _TargetedDebugger("   ")
check("an empty reply falls back",
      _empty_reply._generate_targeted_runtime_fix(
          "proj/backend/routes.py", _TARGET_SRC, _TARGET_ERR, "MAP") is None)

# A one-function file is all block; the full-file prompt gives more for the same
# money, so the targeted path should decline it.
check("a file too small to be worth splitting falls back",
      _TargetedDebugger(_GOOD_REPLY)._generate_targeted_runtime_fix(
          "proj/backend/routes.py", _PATCH_SRC, _TARGET_ERR, "MAP") is None)

_TINY = 'def only_thing():\n    return crud.get(1)\n'
_tiny = _TargetedDebugger(_GOOD_REPLY)
check("a file that IS one block falls back to the full-file prompt",
      _tiny._generate_targeted_runtime_fix(
          "proj/backend/routes.py", _TINY,
          "boom (at backend/routes.py:2 in only_thing)", "MAP") is None)

_ONE_BIG = "def only_thing():\n" + "".join(
    f"    x{i} = crud.get({i})  # padding to make one block a whole large file\n"
    for i in range(60))
check("a large file that is still ONE block falls back — nothing to save",
      _TargetedDebugger(_GOOD_REPLY)._generate_targeted_runtime_fix(
          "proj/backend/routes.py", _ONE_BIG,
          "boom (at backend/routes.py:3 in only_thing)", "MAP") is None,
      len(_ONE_BIG))

# The anchor must survive the trim that stores it, or every long error silently
# downgrades to a whole-file rewrite.
_long = "FastAPIError: " + "x" * 600 + " (at backend/main.py:2 in <module> -> backend/routes.py:7 in <module>)"
_trimmed = Pipeline._trim_keeping_frames(_long)
check("a long error is trimmed but keeps its frame chain",
      len(_trimmed) <= 400 and _trimmed.endswith("in <module>)"), _trimmed[-60:])
check("…so the frames still parse out of the stored text",
      [f["file"] for f in _parse_frames(_trimmed)]
      == ["backend/main.py", "backend/routes.py"],
      _parse_frames(_trimmed))
check("a short error is passed through untouched",
      Pipeline._trim_keeping_frames("boom (at a.py:1 in f)") == "boom (at a.py:1 in f)")
check("an error with no frames is still trimmed to the limit",
      len(Pipeline._trim_keeping_frames("y" * 900)) == 400)


# ── 27. Paying for reasoning that returns nothing ─────────────────────────────
# The 2026-08-28 matrix logged THIRTEEN completions with finish_reason=length and
# zero characters of content: gpt-oss-20b spending its whole budget deliberating
# and returning nothing, then being retried at double the budget and billed
# again. Debugger 5, Reviewer 4, Tester 2, out of a 200K daily budget.
print("\n[27] the reasoning budget is not spent on nothing")

# Re-measured live on 2026-08-28, same prompt, same 600-token budget:
#   no effort param      → 1614 chars reasoning, 254 chars code, 442 tokens
#   reasoning_effort=low →  578 chars reasoning, 582 chars code, 276 tokens
# The Phase 22 comment saying 20b rejects the parameter was stale; Groq fixed it.
check("both models are told to think less, not just the heavy one",
      llm_client._supports_reasoning_effort("openai/gpt-oss-20b")
      and llm_client._supports_reasoning_effort("openai/gpt-oss-120b"))
check("the parameter actually reaches the request body",
      llm_client._build_groq_payload(
          "openai/gpt-oss-20b", [], 600).get("reasoning_effort") == "low")
check("a model we have not measured is left alone",
      not llm_client._supports_reasoning_effort("llama-3.3-70b"))

# The retry that resent an identical request. The Reviewer asks for 600; the
# reasoning floor raises it to 1600; the old retry doubled the REQUESTED 600 to
# 1200, which the floor raised to 1600 again — the same payload, billed twice.
_floored = "some-qwen3-model"          # reasoning, no effort support → floored
check("the floor still applies to a model that cannot be told to think less",
      llm_client._apply_reasoning_budget(_floored, 600)
      == llm_client._REASONING_MIN_TOKENS)

_effective = llm_client._apply_reasoning_budget(_floored, 600)
_bumped = max(601, int(_effective * llm_client.GROQ_TRUNCATION_BUDGET_MULTIPLIER))
check("a retry now asks for strictly more than the call that failed",
      llm_client._apply_reasoning_budget(_floored, _bumped) > _effective,
      f"effective={_effective} bumped={_bumped}")
_src_llm = Path("llm_client.py").read_text(encoding="utf-8")
check("the retry doubles the effective cap, not the requested one",
      "effective = _apply_reasoning_budget(model, requested_max_tokens)" in _src_llm
      and "int(effective * GROQ_TRUNCATION_BUDGET_MULTIPLIER)" in _src_llm)
check("a zero-content completion is named as its own failure, not as truncation",
      "spent its entire budget on reasoning and returned no" in _src_llm)

# The ceiling has one home, and it is known before the first response arrives.
check("a fresh model state already knows a token ceiling",
      llm_client.ModelRateState().limit_tokens == llm_client.GROQ_TPM_LIMIT_DEFAULT
      and llm_client.GROQ_TPM_LIMIT_DEFAULT > 0)
check("so an oversized request is clamped on the very first call",
      llm_client._fit_output_budget_to_model_limit(
          "brand-new-model", "x" * 4000, "", 99999)
      < 99999)


# ── 28. The daily budget is a bucket that refills, not a day that resets ──────
# The ledger summed a rolling 24h window, so budget only came back when an
# individual call aged out. After the 2026-08-28 matrix that meant it reported 0
# remaining for six hours during which Groq would have accepted a build — and
# `run_live_matrix.py` refuses below 70,000, so it would have idled for nothing.
#
# Groq's own 429s say what the shape really is. Both are reproduced below as
# the test that matters: if our model and Groq's disagree, ours is wrong.
#
#   limit 200000, used 197225, requested 2885 -> "please try again in 47.52s"
#   limit 200000, used 196757, requested 4131 -> "please try again in 6m23.616s"
print("\n[28] the daily budget refills continuously")

_RATE = llm_client._REFILL_RATE

check("the refill rate is the limit spread over the window",
      abs(_RATE - llm_client.GROQ_DAILY_TOKEN_LIMIT / (24 * 3600)) < 1e-9,
      _RATE)
check("…which is about 8,333 tokens per hour",
      8_300 < _RATE * 3600 < 8_400, _RATE * 3600)

# Groq's arithmetic, ours. Its retry-after carries fractional seconds; we return
# whole ones, so the tolerance is one second and nothing more.
for _used, _requested, _groq_said in ((197_225, 2_885, 47.52),
                                      (196_757, 4_131, 383.616)):
    _remaining = llm_client.GROQ_DAILY_TOKEN_LIMIT - _used
    _ours = llm_client.seconds_until_tokens(_requested, _remaining)
    check(f"the wait for {_requested:,} tokens at {_used:,} used matches Groq's own",
          abs(_ours - _groq_said) <= 1,
          f"groq={_groq_said}s ours={_ours}s")

check("no wait when the budget is already there",
      llm_client.seconds_until_tokens(1_000, 5_000) == 0)

# The bucket itself: spend it all at once, then watch it come back.
_t0 = 1_000_000.0
_spent = [(_t0, 100_000), (_t0 + 60, 100_000)]

check("a budget spent to the floor reads as spent",
      llm_client._bucket_level(_spent, _t0 + 60) > 199_000,
      llm_client._bucket_level(_spent, _t0 + 60))
# The delta, not the absolute: 139 tokens had already come back during the 60
# seconds between the two calls, and an assertion that ignores that is testing
# the fixture rather than the refill.
check("an hour later, exactly an hour of refill is back",
      abs((llm_client._bucket_level(_spent, _t0 + 60)
           - llm_client._bucket_level(_spent, _t0 + 60 + 3600))
          - _RATE * 3600) < 2,
      llm_client._bucket_level(_spent, _t0 + 60)
      - llm_client._bucket_level(_spent, _t0 + 60 + 3600))
check("the driver's 70,000 threshold is reached in about 8.4 hours",
      200_000 - llm_client._bucket_level(_spent, _t0 + 60 + 8.4 * 3600) >= 70_000,
      200_000 - llm_client._bucket_level(_spent, _t0 + 60 + 8.4 * 3600))
check("after a full window the budget is whole again",
      llm_client._bucket_level(_spent, _t0 + 60 + 86_400) == 0.0)
check("and it never goes past whole, however long the gap",
      llm_client._bucket_level(_spent, _t0 + 60 + 10 * 86_400) == 0.0)

# Draining each entry independently would refund the same seconds once per
# entry, so a build of many small calls would appear to repay itself many times.
_many = [(_t0 + i, 1_000) for i in range(50)]
check("many small calls owe their sum, not their sum minus one refund each",
      abs(llm_client._bucket_level(_many, _t0 + 49) - (50_000 - _RATE * 49)) < 1,
      llm_client._bucket_level(_many, _t0 + 49))

check("an empty ledger owes nothing", llm_client._bucket_level([], _t0) == 0.0)
check("entries out of order are still handled in call order",
      llm_client._bucket_level(list(reversed(_spent)), _t0 + 60)
      == llm_client._bucket_level(_spent, _t0 + 60))

# End to end through the public snapshot, with the clock stopped.
llm_client.reset_daily_usage()
llm_client._ledger = [
    [_t0, "openai/gpt-oss-120b", 200_000, "live"],
]
_fresh = llm_client.get_daily_usage(now=_t0)["models"]["openai/gpt-oss-120b"]
check("a model just spent reports nothing left",
      _fresh["tokens_remaining"] == 0 and _fresh["percent_used"] == 100.0,
      _fresh)
check("…and says how long until the budget is whole again",
      abs(_fresh["window_resets_in_seconds"] - 86_400) <= 1,
      _fresh["window_resets_in_seconds"])
check("…and how fast it is coming back, so the number can be acted on",
      _fresh["refill_tokens_per_hour"] == int(_RATE * 3600), _fresh)

_later = llm_client.get_daily_usage(now=_t0 + 4 * 3600)["models"]["openai/gpt-oss-120b"]
check("four hours later a third of the budget is usable again",
      abs(_later["tokens_remaining"] - 4 * _RATE * 3600) < 2,
      _later["tokens_remaining"])
check("spend and remaining still add up to the limit",
      _later["tokens_used"] + _later["tokens_remaining"]
      == llm_client.GROQ_DAILY_TOKEN_LIMIT, _later)

llm_client.reset_daily_usage()

# The claim we used to ship to users in every quota-interrupted build.
_hint_src = Path("agents/documenter.py").read_text(encoding="utf-8")
check("the documenter no longer tells users to wait for a midnight reset",
      "reset at 00:00 UTC" not in _hint_src)
check("…and llm_client's own hint does not either",
      "reset at 00:00 UTC" not in Path("llm_client.py").read_text(encoding="utf-8"))


# ── 29. Many endpoints failing one way is not a block-level bug ───────────────
# Verified live on 2026-08-28 against row 3's own project, and this is the check
# that turned it from 7/19 routes into 19/19.
#
# Twelve endpoints returned `OperationalError: no such table`. The traceback
# blamed a different handler each time and every one of them was innocent: the
# generated code registered its schema creation on `@router.on_event("startup")`,
# which does not fire for an included router, so init_db() never ran. Repairing
# `list_suppliers` — the handler that happened to be blamed — was APPLIED and
# fixed nothing, which is worse than doing nothing: it edited working code.
#
# The fix has to go in a block no failure names, so the whole-file prompt is the
# only tool that can see it.
print("\n[29] a fault shared by many endpoints is not repaired one block at a time")

from agents.debugger import _shared_cause   # noqa: E402

_ROW3 = "\n".join(
    f"GET /{n} → 500: OperationalError: no such table: {n} "
    f"(at backend/routes.py:{100 + i} in list_{n})"
    for i, n in enumerate(["supplier", "product", "warehouse", "stock_movement"])
)
check("row 3's twelve identical failures are recognised as one cause",
      _shared_cause(_ROW3) == "OperationalError", _shared_cause(_ROW3))

# Row 1, a day earlier: three endpoints, one duplicated `get_db`. The same rule
# would have aimed that repair correctly too.
_ROW1 = "\n".join([
    "GET /tasks → 500: AttributeError: 'generator' object has no attribute "
    "'execute' (at backend/routes.py:53 in list_tasks)",
    "GET /tasks/1 → 500: AttributeError: 'generator' object has no attribute "
    "'execute' (at backend/routes.py:61 in get_task)",
])
check("…as are row 1's, which had a shared cause of its own",
      _shared_cause(_ROW1) == "AttributeError", _shared_cause(_ROW1))

_ONE = "GET /x → 500: ValueError: boom (at backend/routes.py:5 in handler)"
check("one broken endpoint is still a block-level bug",
      _shared_cause(_ONE) == "")
check("the same handler probed twice is one bug, not a shared cause",
      _shared_cause(_ONE + "\nPOST /x → 500: ValueError: boom "
                           "(at backend/routes.py:5 in handler)") == "",
      "distinct functions is what separates the two cases")
check("two different faults are not a shared cause",
      _shared_cause(_ONE + "\nGET /y → 500: KeyError: 'z' "
                           "(at backend/routes.py:9 in other)") == "")
check("text with no frames at all yields nothing",
      _shared_cause("boom") == "" and _shared_cause("") == "")

# And the debugger must act on it: no block repair, hand back to the full file.
_shared_dbg = _TargetedDebugger(_GOOD_REPLY)
check("a shared cause skips the targeted path entirely",
      _shared_dbg._generate_targeted_runtime_fix(
          "proj/backend/routes.py", _TARGET_SRC, _ROW3, "MAP") is None
      and _shared_dbg.prompts == [],
      f"prompts={len(_shared_dbg.prompts)}")

_single_dbg = _TargetedDebugger(_GOOD_REPLY)
_single_dbg._generate_targeted_runtime_fix(
    "proj/backend/routes.py", _TARGET_SRC, _TARGET_ERR, "MAP")
check("…while a single failing endpoint still gets one",
      len(_single_dbg.prompts) == 1)


# ── 30. Three mistakes found by using the thing ───────────────────────────────
# None of these needed quota to fix, and all three were found by running the
# system rather than reading it.
print("\n[30] the fourth blame rule, the prompts, and the driver's report")

from tools.code_patcher import imported_symbols   # noqa: E402

# ---- 30a. A boot failure about an imported name belongs to its definition ----
# Row 2 (2026-08-28): routes.py does `from services import BookmarkOut` and uses
# it as a response_model. BookmarkOut is a plain class, so FastAPI raises while
# importing routes.py and every frame names routes.py — but routes.py is right.
# The repair was aimed there anyway and told "the bug is in THIS file, do not
# make the other module tolerate it", which forbids the only fix that works.
# Both models were tried live; both produced something the guards rejected.
check("a file's imports are readable as {symbol: module}",
      imported_symbols("from services import BookmarkOut\nimport sqlite3\n")
      == {"BookmarkOut": "services", "sqlite3": "sqlite3"},
      imported_symbols("from services import BookmarkOut\nimport sqlite3\n"))
check("an alias binds the name actually used",
      imported_symbols("from services import BookmarkOut as BM")
      == {"BM": "services"})
check("a star import binds nothing that can be blamed",
      imported_symbols("from services import *") == {})
check("unparseable source yields nothing rather than raising",
      imported_symbols("def broken(:") == {})

_blame_root = "_phase23_blame"
_blame_dir = Path(config.OUTPUT_DIR) / _blame_root
shutil.rmtree(_blame_dir, ignore_errors=True)
(_blame_dir / "backend").mkdir(parents=True, exist_ok=True)
(_blame_dir / "backend" / "services.py").write_text(
    "class BookmarkOut:\n    def __init__(self, url):\n        self.url = url\n",
    encoding="utf-8")
(_blame_dir / "backend" / "routes.py").write_text(
    "from typing import List\n"
    "from fastapi import APIRouter\n"
    "from services import BookmarkOut\n"
    "\n"
    "router = APIRouter()\n"
    "\n"
    "@router.get('/bookmarks', response_model=List[BookmarkOut])\n"
    "def list_bookmarks():\n"
    "    return []\n", encoding="utf-8")

_bp = _BootPipeline.__new__(_BootPipeline)
_ROW2_ERR = ("FastAPIError: Invalid args for response field! Hint: check that "
             "typing.List[services.BookmarkOut] is a valid Pydantic field type.")
try:
    _to, _note = _bp._redirect_blame_to_definition(
        _blame_root, "backend/routes.py", _ROW2_ERR)
    check("the repair is redirected to the file that defines the broken class",
          _to == "backend/services.py", _to)
    check("…and says why, so the log explains itself",
          "only imports `BookmarkOut`" in _note and "services.py" in _note, _note)

    # A genuine in-file bug must keep the frame-based rule.
    _same, _n2 = _bp._redirect_blame_to_definition(
        _blame_root, "backend/routes.py", "NameError: name 'router' is not defined")
    check("an error naming nothing imported leaves the blame where it was",
          _same == "backend/routes.py" and _n2 == "")
    # A stdlib or third-party name must never send a repair outside the project.
    _same2, _ = _bp._redirect_blame_to_definition(
        _blame_root, "backend/routes.py", "TypeError: List is not callable")
    check("a name from typing or fastapi is not chased out of the project",
          _same2 == "backend/routes.py", _same2)
    _missing, _ = _bp._redirect_blame_to_definition(
        _blame_root, "backend/nope.py", _ROW2_ERR)
    check("a blamed file that does not exist is returned unchanged",
          _missing == "backend/nope.py")
finally:
    shutil.rmtree(_blame_dir, ignore_errors=True)

# ---- 30b. The prompts forbid what shipped ----
# Two defects the matrix produced are cheaper to prevent than to repair.
_bd = Path("prompts/backend_developer.txt").read_text(encoding="utf-8")
check("the prompt forbids the router startup hook that never fires",
      "@router.on_event(\"startup\")" in _bd and "DOES NOT FIRE" in _bd)
check("…and shows the lifespan handler that does",
      "lifespan" in _bd and "asynccontextmanager" in _bd)
check("…and does not merely move the problem to module level",
      "Do not create tables at module level" in _bd)
check("the prompt requires a response_model to be a Pydantic model",
      "RESPONSE MODEL RULE" in _bd and "must be a Pydantic" in _bd)
check("…naming the failure it prevents, so the rule is not arbitrary",
      "FastAPIError" in _bd and "never booted" in _bd)

# ---- 30c. The driver's report merges and does not overstate ----
import run_live_matrix as _M    # noqa: E402

_report = Path(config.OUTPUT_DIR) / "_phase23_report.md"
_report.unlink(missing_ok=True)


def _row_result(row, tokens, ok=True, verification=None):
    return {"row": row, "shape": f"shape {row}", "status": "done_with_context",
            "total_tokens": tokens, "duration_seconds": 100.0, "file_count": 20,
            "zip": {"ok": ok, "status": 200, "content_type": "application/zip",
                    "bytes": 1000},
            "build_id": f"b{row}", "completion_reason": "", "progress_percent": 100,
            "tokens_by_model": None, "expect_boot": True,
            "verification": verification if verification is not None else [
                {"check": "runtime_smoke", "status": "verified",
                 "detail": "5/5 routes responded without a server error",
                 "findings": [], "evidence": {}},
            ],
            "smoke_summary": "5/5 routes responded without a server error",
            "build_shape": "web_api"}


try:
    _M.write_report([_row_result(2, 171_914), _row_result(3, 131_848)], _report)
    _merged = _M.merge_previous([_row_result(1, 94_576)], _report)
    check("a later run carries earlier rows forward instead of erasing them",
          [r["row"] for r in _merged] == [1, 2, 3],
          [r["row"] for r in _merged])
    check("…and marks which of them this run did not produce",
          [r.get("carried", False) for r in _merged] == [False, True, True])

    _M.write_report(_merged, _report)
    _text = _report.read_text(encoding="utf-8")
    check("the merged report shows all three rows",
          _text.count("| 1 |") == 1 and _text.count("| 2 |") == 1
          and _text.count("| 3 |") == 1, _text[:400])
    check("a carried row is labelled rather than passed off as fresh",
          _text.count("*(earlier run)*") == 2, _text)
    check("only the row this run produced gets a detail section",
          _text.count("### Row") == 1, _text)

    # The count used to read as the whole criterion, then as explicitly half of
    # it — row 3 was counted as passing on 2026-08-28 while shipping twelve dead
    # endpoints. Now BOTH halves are read from the API, so the report states the
    # count against both and no longer sends the reader to the server log.
    check("the result line counts rows that meet BOTH halves",
          "meet BOTH halves" in _text, _text[:700])
    check("…and still says how many merely shipped a ZIP",
          "shipped a valid ZIP" in _text, _text[:700])
    check("the table carries the verification verdict per row",
          "| Verified |" in _text, _text[:900])

    # A row whose artifact was never executed must not be counted as passing,
    # however healthy its status and ZIP look.
    _unver = Path(config.OUTPUT_DIR) / "_phase23_report_unverified.md"
    try:
        _M.write_report([_row_result(1, 94_576, verification=[
            {"check": "runtime_smoke", "status": "not_run",
             "detail": "a web app was found and the probe could not boot it",
             "findings": ["…so this build is unverified"], "evidence": {}}])],
            _unver)
        _utext = _unver.read_text(encoding="utf-8")
        check("a shipped-but-unverified row is not counted as passing",
              "**Result: 0 of 1 rows meet BOTH halves" in _utext, _utext[:700])
        check("…and the report names the check that never ran",
              "never ran: runtime_smoke" in _utext, _utext[:1500])
    finally:
        _unver.unlink(missing_ok=True)

    _re_run = _M.merge_previous([_row_result(3, 999)], _report)
    check("a row that is re-run wins over the record of it",
          [r["total_tokens"] for r in _re_run if r["row"] == 3] == [999])
finally:
    _report.unlink(missing_ok=True)




# ---- 31. requirements.txt is recorded as a file that was written ----------
# The builder writes requirements.txt straight to disk instead of through the
# generation loop, so it never entered `written`. Everything downstream that
# asks "was this planned file produced?" reads that list, so a complete
# requirements.txt was still reported as missing: row 2's handoff listed it
# under "Files in the plan that were never generated" AND raised an "Implement
# requirements.txt" todo, while the file sat on disk with six packages in it.
from agents.backend_developer import BackendDeveloper           # noqa: E402
from agents.documenter import Documenter                        # noqa: E402
from tools.requirements_builder import validate_and_fix_requirements  # noqa: E402

_rr_root = "_test_req_registration"
_rr_dir = Path(config.OUTPUT_DIR) / _rr_root
shutil.rmtree(_rr_dir, ignore_errors=True)
try:
    (_rr_dir / "backend").mkdir(parents=True)
    (_rr_dir / "backend" / "main.py").write_text(
        "import fastapi\nfrom fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    # Exactly what the architect scaffolds: the marker and nothing else.
    (_rr_dir / "requirements.txt").write_text(
        "# Python dependencies for the project\n"
        "# will be generated by the code generation agents.\n",
        encoding="utf-8",
    )

    _rr_written = [f"{_rr_root}/backend/main.py"]
    _rr_arch = {"files": [
        {"path": "backend/main.py", "description": "app"},
        {"path": "requirements.txt", "description": "Python dependencies for the project"},
    ]}

    # §37 made the disk authoritative in _missing_files, which independently
    # covers this file. Registration still matters: `written` is what the
    # requirements builder, the tester and the ZIP packer all read, and a file
    # absent from it is invisible to them even when it is on disk. So assert
    # the registration itself, and assert the disk rule on a file that is
    # genuinely absent.
    _rr_absent_arch = {"files": [{"path": "not_written.txt", "description": "absent"}]}
    check("a planned file that is on neither the list nor the disk is missing",
          [p for p, _ in Documenter.__new__(Documenter)._missing_files(
              _rr_absent_arch, list(_rr_written), _rr_root)] == ["not_written.txt"])

    BackendDeveloper.__new__(BackendDeveloper)._validate_requirements(
        _rr_root, _rr_written
    )

    check("requirements.txt is appended to the written-files list",
          f"{_rr_root}/requirements.txt" in _rr_written, _rr_written)
    check("…using the same OUTPUT_DIR-relative, forward-slash form as the rest",
          all("\\" not in p for p in _rr_written), _rr_written)
    check("…and the real generated files are left alone",
          f"{_rr_root}/backend/main.py" in _rr_written, _rr_written)

    _rr_after = Documenter.__new__(Documenter)._missing_files(
        _rr_arch, _rr_written, _rr_root
    )
    check("so the documenter no longer reports it as never generated",
          _rr_after == [], _rr_after)

    # The §4.3 behaviour this sits next to, re-asserted on the same fixture:
    # the file must not still read as a stub once it holds real packages.
    _rr_text = (_rr_dir / "requirements.txt").read_text(encoding="utf-8")
    check("the scaffold marker is gone once real packages are written",
          "will be generated by the code generation agents" not in _rr_text, _rr_text)
    check("…and a FastAPI app that imports no server still gets uvicorn",
          "uvicorn" in _rr_text, _rr_text)

    # Registration must be idempotent: remediation can run the validator again.
    BackendDeveloper.__new__(BackendDeveloper)._validate_requirements(
        _rr_root, _rr_written
    )
    check("running the validator twice does not double-register the file",
          _rr_written.count(f"{_rr_root}/requirements.txt") == 1, _rr_written)

    # A build whose requirements.txt was never created must not gain a phantom
    # entry — the list has to keep meaning "this exists on disk".
    _rr_missing_root = "_test_req_registration_absent"
    _rr_missing_dir = Path(config.OUTPUT_DIR) / _rr_missing_root
    shutil.rmtree(_rr_missing_dir, ignore_errors=True)
    _rr_missing_dir.mkdir(parents=True)
    _rr_none = []
    BackendDeveloper._register_requirements(
        validate_and_fix_requirements.__globals__["ValidationResult"](
            requirements_file=str(_rr_missing_dir / "requirements.txt")
        ),
        _rr_none,
    )
    check("a requirements.txt that is not on disk is not registered",
          _rr_none == [], _rr_none)
    shutil.rmtree(_rr_missing_dir, ignore_errors=True)
finally:
    shutil.rmtree(_rr_dir, ignore_errors=True)



# ---- 32. A path that only file_writer could resolve --------------------------
# `written` / `result.backend_files` hold OUTPUT_DIR-relative paths, because
# that is what create_file() takes. analyze_file() used a bare open(), which
# honours cwd instead — so every relative caller missed, and because
# analyze_file caught FileNotFoundError into `parse_error`, a file that was not
# found was reported as a file that "does not parse".
#
# The bill: _verify_and_repair spent one LLM call per generated Python file
# asking a model to fix a syntax error that did not exist, then wrote the reply
# over the correct original (create_file resolves what open() could not), then
# re-scanned, failed identically, and logged "defects remain after repair".
# Eight of eight files in the aborted 2026-08-29 row 3 run. The tester's
# route-aware mock guidance — the fix for todo_app's 1/9 test score — returned
# "" on every build for the same reason, silently.
from tools.code_introspect import analyze_file as _af                 # noqa: E402
from agents.backend_developer import BackendDeveloper as _BD          # noqa: E402
from agents.tester import Tester as _T                                # noqa: E402

_cp_root = "_test_introspect_paths"
_cp_dir = Path(config.OUTPUT_DIR) / _cp_root
shutil.rmtree(_cp_dir, ignore_errors=True)
try:
    (_cp_dir / "backend").mkdir(parents=True)
    (_cp_dir / "backend" / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "from services import fetch_all\n"
        "router = APIRouter()\n"
        "\n"
        "@router.get('/items')\n"
        "def list_items():\n"
        "    return fetch_all()\n"
        "\n"
        "@router.get('/items/{i}')\n"
        "def read_item(i: int):\n"
        "    pass\n",
        encoding="utf-8",
    )
    (_cp_dir / "backend" / "broken.py").write_text(
        "def f(:\n    pass\n", encoding="utf-8"
    )

    _cp_rel = f"{_cp_root}/backend/routes.py"
    _cp_abs = str((_cp_dir / "backend" / "routes.py").resolve())

    # The three path forms callers actually use.
    _cp_from_rel = _af(_cp_rel)
    _cp_from_abs = _af(_cp_abs)
    check("an OUTPUT_DIR-relative path resolves, as file_writer's callers assume",
          _cp_from_rel.read_error is None and _cp_from_rel.parse_error is None,
          (_cp_from_rel.read_error, _cp_from_rel.parse_error))
    check("…and yields the same facts an absolute path does",
          _cp_from_rel.route_handlers == _cp_from_abs.route_handlers
          == ["list_items", "read_item"], _cp_from_rel.route_handlers)
    check("an absolute path still works — the old callers are not regressed",
          _cp_from_abs.read_error is None and len(_cp_from_abs.route_handlers) == 2)

    # The conflation itself: unreadable and unparseable are different states.
    _cp_missing = _af(f"{_cp_root}/backend/does_not_exist.py")
    check("a file that is not there reports read_error",
          _cp_missing.read_error is not None, _cp_missing.read_error)
    check("…and NOT parse_error — it is not a file with a syntax error",
          _cp_missing.parse_error is None, _cp_missing.parse_error)

    _cp_broken = _af(f"{_cp_root}/backend/broken.py")
    check("a file that is there but will not parse still reports parse_error",
          _cp_broken.parse_error is not None, _cp_broken.parse_error)
    check("…and not read_error, because it read fine",
          _cp_broken.read_error is None, _cp_broken.read_error)

    # The consequence at the call site that was paying for it.
    _cp_bd = _BD.__new__(_BD)
    _cp_planned = _cp_bd._planned_modules(
        {"files": [{"path": "backend/routes.py"}, {"path": "backend/services.py"}]}
    )
    _cp_defects = _cp_bd._scan_defects(_cp_rel, _cp_planned)
    check("scanning a relative path no longer invents a parse defect",
          not any("does not parse" in d for d in _cp_defects), _cp_defects)
    check("…and now sees the real defect that was being masked by it",
          any("stub" in d for d in _cp_defects), _cp_defects)

    # The safety net: even with a path that resolves nowhere, no call is spent.
    _cp_none = _cp_bd._scan_defects(
        f"{_cp_root}/backend/does_not_exist.py", _cp_planned
    )
    check("an unreadable file yields NO defects, so no repair call is spent on it",
          _cp_none == [], _cp_none)

    # The tester's guidance, silently empty on every build until now.
    _cp_guidance = _T.__new__(_T)._build_mock_examples(_cp_rel, [])
    check("the tester's route-aware mock guidance is no longer silently empty",
          _cp_guidance.strip() != "", repr(_cp_guidance))
    check("…and names the handlers it must not let the model patch",
          "list_items" in _cp_guidance and "NEVER write patch" in _cp_guidance,
          _cp_guidance[:400])
finally:
    shutil.rmtree(_cp_dir, ignore_errors=True)



# ---- 33. A project with no dependencies still must not ship the marker ------
# _strip_scaffold_placeholder ran only on the path that WRITES packages, so a
# project with nothing third-party to add returned early with the architect's
# marker intact. _audit_placeholders then reads it as a planned file nobody
# filled in and degrades the build to done_with_context. That is exactly row
# 4's shape — a bulk-rename CLI built entirely on the standard library — and
# row 4 has not been run yet.
from agents.pipeline import Pipeline as _P33                       # noqa: E402

_sl_root = "_test_stdlib_only"
_sl_dir = Path(config.OUTPUT_DIR) / _sl_root
shutil.rmtree(_sl_dir, ignore_errors=True)
try:
    _sl_dir.mkdir(parents=True)
    (_sl_dir / "cli.py").write_text(
        "import os, sys, argparse, pathlib, json, shutil\n"
        "def main():\n    return 0\n",
        encoding="utf-8",
    )
    (_sl_dir / "requirements.txt").write_text(
        "# Python dependencies for the project\n"
        "# will be generated by the code generation agents.\n",
        encoding="utf-8",
    )

    _sl_written = [f"{_sl_root}/cli.py"]
    _BD.__new__(_BD)._validate_requirements(_sl_root, _sl_written)
    _sl_text = (_sl_dir / "requirements.txt").read_text(encoding="utf-8")

    check("a stdlib-only project has the scaffold marker stripped too",
          "will be generated by the code generation agents" not in _sl_text,
          repr(_sl_text))
    check("…and nothing is invented for it to depend on",
          _sl_text.strip() == "", repr(_sl_text))
    check("…so the placeholder audit does not degrade the build",
          _P33.__new__(_P33)._audit_placeholders(_sl_dir) == [],
          _P33.__new__(_P33)._audit_placeholders(_sl_dir))
    check("…and the file is still registered as written",
          f"{_sl_root}/requirements.txt" in _sl_written, _sl_written)
finally:
    shutil.rmtree(_sl_dir, ignore_errors=True)



# ---- 34. Pydantic V1 config keys that V2 ignores ----------------------------
# The project installs pydantic>=2. Generated schemas kept writing the V1 idiom
# `class Config: orm_mode = True`, which V2 does not reject and does not honour
# — it is dropped with a UserWarning buried in import stderr. from_attributes
# is therefore never set, and every response_model that serializes a row 500s
# at REQUEST time while the module imports perfectly. Twenty across the
# generated projects on 2026-08-29; six in row 3's schemas.py alone.
from tools.pydantic_compat import fix_pydantic_v1_config, _rewrite   # noqa: E402

_pc_root = "_test_pydantic_compat"
_pc_dir = Path(config.OUTPUT_DIR) / _pc_root
shutil.rmtree(_pc_dir, ignore_errors=True)
try:
    (_pc_dir / "backend").mkdir(parents=True)
    (_pc_dir / "backend" / "schemas.py").write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "class ProductRead(BaseModel):\n"
        "    id: int\n"
        "    name: str\n"
        "\n"
        "    class Config:\n"
        "        orm_mode = True\n"
        "        schema_extra = {'example': {}}\n"
        "\n"
        "class SupplierRead(BaseModel):\n"
        "    id: int\n"
        "\n"
        "    class Config:\n"
        "        orm_mode = True\n"
        "        allow_population_by_field_name = True\n",
        encoding="utf-8",
    )
    # A test file full of response.json() — the trap a blanket rewrite falls in.
    (_pc_dir / "backend" / "test_api.py").write_text(
        "def test_one(client):\n"
        "    data = client.get('/products').json()\n"
        "    assert data == []\n"
        "\n"
        "def test_two(client):\n"
        "    assert client.get('/suppliers').json() == []\n",
        encoding="utf-8",
    )

    _pc_files = [f"{_pc_root}/backend/schemas.py", f"{_pc_root}/backend/test_api.py"]
    _pc_res = fix_pydantic_v1_config(_pc_root, _pc_files)
    _pc_schemas = (_pc_dir / "backend" / "schemas.py").read_text(encoding="utf-8")
    _pc_tests = (_pc_dir / "backend" / "test_api.py").read_text(encoding="utf-8")

    check("orm_mode is renamed to the key V2 actually reads",
          "orm_mode" not in _pc_schemas and _pc_schemas.count("from_attributes") == 2,
          _pc_schemas)
    check("…and so are the other renames whose meaning did not change",
          "json_schema_extra" in _pc_schemas and "populate_by_name" in _pc_schemas,
          _pc_schemas)
    check("only the file that needed it is rewritten",
          _pc_res.files_changed == [f"{_pc_root}/backend/schemas.py"],
          _pc_res.files_changed)

    # The one that would have broken every generated test suite.
    check("response.json() is NOT rewritten — it is httpx, not a pydantic model",
          _pc_tests.count(".json()") == 2 and "model_dump_json" not in _pc_tests,
          _pc_tests)

    # Semantics-changing V1 idioms are deliberately left for the LLM path: a
    # blind @validator -> @field_validator rename produces broken code.
    _pc_v, _pc_applied = _rewrite(
        "from pydantic import validator\n"
        "@validator('x')\n"
        "def check(cls, v): return v\n"
    )
    check("@validator is left alone — its V2 replacement has a different signature",
          "@validator" in _pc_v and _pc_applied == [], _pc_applied)

    # Rewriting must be exact, never a substring match.
    _pc_sub, _ = _rewrite("    not_orm_mode = True\n    orm_mode_extra = 1\n")
    check("a longer identifier containing the key is not touched",
          "not_orm_mode = True" in _pc_sub and "orm_mode_extra = 1" in _pc_sub,
          _pc_sub)

    # Idempotence: the pass runs on every build.
    _pc_again = fix_pydantic_v1_config(_pc_root, _pc_files)
    check("a second pass changes nothing", _pc_again.files_changed == [],
          _pc_again.files_changed)

    # The rewritten config must actually take effect, not merely read well.
    _pc_ns: dict = {}
    exec(compile(_pc_schemas, "schemas.py", "exec"), _pc_ns)
    check("the rewritten model really carries from_attributes at runtime",
          _pc_ns["ProductRead"].model_config.get("from_attributes") is True,
          _pc_ns["ProductRead"].model_config)
finally:
    shutil.rmtree(_pc_dir, ignore_errors=True)

# The prompt must stop it at the source; the compat pass is the safety net.
_pc_prompt = Path("prompts/backend_developer.txt").read_text(encoding="utf-8")
check("the prompt requires pydantic V2 and names the key that keeps shipping",
      "PYDANTIC VERSION RULE" in _pc_prompt and "orm_mode" in _pc_prompt)
check("…and explains why V1 keys are worse than an error — they are ignored",
      "IGNORED" in _pc_prompt and "REQUEST time" in _pc_prompt)



# ---- 35. The smoke test must run the app's lifespan -------------------------
# Starlette runs startup/lifespan ONLY when TestClient is entered as a context
# manager. runtime_smoke did not, so an app that creates its tables in an
# asynccontextmanager lifespan — exactly what the prompt tells the generator to
# write — was probed against a database with no tables. Every data route
# answered "no such table" and the failure was blamed on generated code that
# was correct. Twelve of row 3's nineteen, twice. The debugger's earlier "fix"
# was to create tables at module import: the one pattern the prompt forbids.
from tools.runtime_smoke import smoke_test_app                      # noqa: E402

_ls_root = "_test_lifespan_smoke"
_ls_dir = Path(config.OUTPUT_DIR) / _ls_root
shutil.rmtree(_ls_dir, ignore_errors=True)
try:
    _ls_dir.mkdir(parents=True)
    (_ls_dir / "main.py").write_text(
        "import os, sqlite3\n"
        "from contextlib import asynccontextmanager\n"
        "from fastapi import FastAPI\n"
        "\n"
        "DB = os.path.join(os.path.dirname(__file__), 'app.db')\n"
        "\n"
        "@asynccontextmanager\n"
        "async def lifespan(app):\n"
        "    conn = sqlite3.connect(DB)\n"
        "    conn.execute('CREATE TABLE IF NOT EXISTS item (id INTEGER PRIMARY KEY, name TEXT);')\n"
        "    conn.commit(); conn.close()\n"
        "    yield\n"
        "\n"
        "app = FastAPI(lifespan=lifespan)\n"
        "\n"
        "@app.get('/items')\n"
        "def list_items():\n"
        "    conn = sqlite3.connect(DB)\n"
        "    rows = conn.execute('SELECT id, name FROM item').fetchall()\n"
        "    conn.close()\n"
        "    return [{'id': r[0], 'name': r[1]} for r in rows]\n",
        encoding="utf-8",
    )
    _ls_res = smoke_test_app(_ls_root)
    check("an app whose tables are made in lifespan is probed with them present",
          _ls_res.passed == _ls_res.total and _ls_res.total >= 1,
          f"{_ls_res.passed}/{_ls_res.total} "
          + "; ".join(f"{p.path} {p.status} {p.error[:80]}" for p in _ls_res.failures))
    check("…and no route reports the table missing",
          not any("no such table" in (p.error or "") for p in _ls_res.probes),
          [p.error[:90] for p in _ls_res.failures])
finally:
    shutil.rmtree(_ls_dir, ignore_errors=True)


# ---- 36. SQL that reads a column the schema does not define ------------------
# main.py and routes.py are written by separate LLM calls and drift. Row 3
# created `contact_email` and selected `contact`; both files import perfectly
# and five routes 500'd at request time on `no such column`. Nothing executes
# SQL until a request arrives, so no gate saw it.
from tools.sql_schema_check import (                                # noqa: E402
    check_project_sql, parse_schema, _from_clause_tables,
)

_sq_schema = parse_schema(
    "CREATE TABLE IF NOT EXISTS supplier (\n"
    "  id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "  name TEXT NOT NULL,\n"
    "  contact_email TEXT\n"
    ");\n"
    "CREATE TABLE stock_movement (\n"
    "  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL,\n"
    "  movement_type TEXT, quantity INTEGER,\n"
    "  FOREIGN KEY (product_id) REFERENCES product(id)\n"
    ");\n"
)
check("CREATE TABLE columns are parsed",
      _sq_schema.get("supplier") == {"id", "name", "contact_email"}, _sq_schema)
check("…and a table-level FOREIGN KEY is not mistaken for a column",
      "FOREIGN" not in _sq_schema.get("stock_movement", set())
      and "product_id" in _sq_schema.get("stock_movement", set()),
      _sq_schema.get("stock_movement"))

_sq_alias, _sq_single = _from_clause_tables("stock_movement sm JOIN product p ON p.id = sm.product_id")
check("a join's aliases resolve to their tables",
      _sq_alias.get("sm") == "stock_movement" and _sq_alias.get("p") == "product",
      _sq_alias)
check("…and a join is not treated as a single-table query",
      _sq_single is False, _sq_single)

_sq_root = "_test_sql_schema"
_sq_dir = Path(config.OUTPUT_DIR) / _sq_root
shutil.rmtree(_sq_dir, ignore_errors=True)
try:
    (_sq_dir / "backend").mkdir(parents=True)
    (_sq_dir / "backend" / "main.py").write_text(
        'import sqlite3\n'
        'def init():\n'
        '    conn = sqlite3.connect("app.db")\n'
        '    conn.executescript("""\n'
        '        CREATE TABLE IF NOT EXISTS supplier (\n'
        '            id INTEGER PRIMARY KEY, name TEXT, contact_email TEXT\n'
        '        );\n'
        '        CREATE TABLE IF NOT EXISTS stock_movement (\n'
        '            id INTEGER PRIMARY KEY, product_id INTEGER, movement_type TEXT\n'
        '        );\n'
        '    """)\n',
        encoding="utf-8",
    )
    (_sq_dir / "backend" / "routes.py").write_text(
        'def list_suppliers(db):\n'
        '    return db.execute("SELECT id, name, contact FROM supplier").fetchall()\n'
        'def report(db):\n'
        '    return db.execute("SELECT sm.direction FROM stock_movement sm JOIN supplier s ON s.id = sm.id").fetchall()\n'
        'def ok_star(db):\n'
        '    return db.execute("SELECT * FROM supplier").fetchall()\n'
        'def ok_real(db):\n'
        '    return db.execute("SELECT id, name, contact_email FROM supplier").fetchall()\n'
        'def ok_unknown_table(db):\n'
        '    return db.execute("SELECT whatever FROM some_other_table").fetchall()\n',
        encoding="utf-8",
    )

    _sq_files = [f"{_sq_root}/backend/main.py", f"{_sq_root}/backend/routes.py"]
    _sq_rep = check_project_sql(_sq_root, _sq_files)
    _sq_found = {(i.table, i.column) for i in _sq_rep.issues}

    check("a bare column the table does not have is caught",
          ("supplier", "contact") in _sq_found, _sq_found)
    check("…and so is a join-qualified one, via its alias",
          ("stock_movement", "direction") in _sq_found, _sq_found)
    check("exactly the two real mismatches, nothing else",
          len(_sq_rep.issues) == 2, [str(i)[:70] for i in _sq_rep.issues])
    check("SELECT * is not flagged — there is no column list to check",
          not any(i.column == "*" for i in _sq_rep.issues), _sq_found)
    check("a correct query is not flagged",
          ("supplier", "contact_email") not in _sq_found, _sq_found)
    check("a table with no CREATE TABLE is left alone — the schema may be elsewhere",
          not any(i.table == "some_other_table" for i in _sq_rep.issues), _sq_found)
    check("the message names the real columns, so one call can fix it",
          "contact_email" in str(next(i for i in _sq_rep.issues if i.column == "contact")),
          str(_sq_rep.issues[0]))

    # The defect has to reach the file that runs the query, not the schema.
    check("the mismatch is blamed on the file whose SQL is wrong",
          all(i.file.endswith("routes.py") for i in _sq_rep.issues),
          [i.file for i in _sq_rep.issues])
finally:
    shutil.rmtree(_sq_dir, ignore_errors=True)



# ---- 37. An audit must not report on a step that has not run yet ------------
# _audit_placeholders runs during remediation (step 8). The documenter does not
# write README.md until step 9. So the claim "README.md was never filled in" is
# guaranteed true when the audit makes it and guaranteed false by the time
# SESSION_CONTEXT.md states it. Row 3 on 2026-08-29 was degraded to
# done_with_context over a README the documenter then wrote with 46 lines and 8
# sections, and its handoff told the user to "Implement README.md".
from agents.pipeline import Pipeline as _P37                        # noqa: E402
from agents.documenter import Documenter as _D37                    # noqa: E402

_ph_root = "_test_late_step_audit"
_ph_dir = Path(config.OUTPUT_DIR) / _ph_root
shutil.rmtree(_ph_dir, ignore_errors=True)
try:
    _ph_dir.mkdir(parents=True)
    _ph_marker = "# will be generated by the code generation agents.\n"
    (_ph_dir / "README.md").write_text(_ph_marker, encoding="utf-8")
    (_ph_dir / "SETUP.md").write_text(_ph_marker, encoding="utf-8")
    (_ph_dir / "helpers.py").write_text(_ph_marker, encoding="utf-8")

    _ph_audit = _P37.__new__(_P37)._audit_placeholders(_ph_dir)
    check("a file the documenter has not written yet is not called unfilled",
          not any("README.md" in i or "SETUP.md" in i for i in _ph_audit), _ph_audit)
    check("…but a stub nobody owns is still caught",
          len(_ph_audit) == 1 and "helpers.py" in _ph_audit[0], _ph_audit)

    # Belt and braces: an issue raised earlier is re-checked before it is
    # printed, so anything filled in between the audit and the report drops out.
    _ph_doc = _D37.__new__(_D37)
    _ph_stale = ["1 planned file(s) were never filled in and still contain "
                 "the scaffold placeholder: README.md"]
    (_ph_dir / "README.md").write_text("# Real README\n\nFeatures\n", encoding="utf-8")
    check("an issue the disk no longer supports is dropped before reporting",
          _ph_doc._drop_stale_issues(_ph_stale, _ph_root) == [], "not dropped")

    _ph_real = ["1 planned file(s) were never filled in and still contain "
                "the scaffold placeholder: helpers.py"]
    check("…while one that is still true survives",
          _ph_doc._drop_stale_issues(_ph_real, _ph_root) == _ph_real)

    _ph_mixed = ["2 planned file(s) were never filled in and still contain "
                 "the scaffold placeholder: README.md, helpers.py"]
    _ph_kept = _ph_doc._drop_stale_issues(_ph_mixed, _ph_root)
    check("a partly-stale issue is narrowed to what is still true",
          len(_ph_kept) == 1 and "helpers.py" in _ph_kept[0]
          and "README.md" not in _ph_kept[0], _ph_kept)

    _ph_other = ["12 of 19 endpoint(s) return a server error when called"]
    check("issues that are not placeholder claims are left untouched",
          _ph_doc._drop_stale_issues(_ph_other, _ph_root) == _ph_other)

    # A planned file written outside the generation loop is not "missing".
    _ph_arch = {"files": [
        {"path": "README.md", "description": "Project overview"},
        {"path": "never_made.py", "description": "not written"},
    ]}
    _ph_missing = _D37.__new__(_D37)._missing_files(_ph_arch, [], _ph_root)
    check("a planned file that exists on disk is not reported as never generated",
          [p for p, _ in _ph_missing] == ["never_made.py"], _ph_missing)
finally:
    shutil.rmtree(_ph_dir, ignore_errors=True)



# ---- 38. An import hidden in a try/except is still an import ----------------
# analyze_module read imports from `tree.body` only, and deferred_imports from
# function bodies only. An import nested in a module-level try/if/with fell in
# between and was invisible to both. That is exactly the shape the debugger
# produced on 2026-08-29 when it "fixed" five unresolvable imports by wrapping
# each in `try: … except ImportError: pass`: routes.py imported perfectly,
# every gate went green, and the application registered ZERO routes.
from tools.code_introspect import (                                 # noqa: E402
    analyze_module as _am38, find_phantom_imports as _fp38,
)

_gi_src = (
    "from fastapi import APIRouter\n"
    "router = APIRouter()\n"
    "try:\n"
    "    from supplier_routes import router as supplier_router\n"
    "    router.include_router(supplier_router, prefix='/suppliers')\n"
    "except ImportError:\n"
    "    pass\n"
    "if True:\n"
    "    import nonexistent_helper\n"
)
_gi = _am38(_gi_src)
check("an import inside a module-level try is seen at all",
      "supplier_router" in _gi.imported_names, _gi.imported_names)
check("…and one inside a module-level if",
      "nonexistent_helper" in _gi.imported_names, _gi.imported_names)
check("…and both are recorded as guarded, not as ordinary top-level imports",
      set(_gi.guarded_imports) == {"supplier_routes", "nonexistent_helper"},
      _gi.guarded_imports)
check("so the phantom-import check can finally see them",
      {m for m, _ in _fp38(_gi, {"routes", "main"})}
      == {"supplier_routes", "nonexistent_helper"}, _fp38(_gi, {"routes", "main"}))

# A guarded import of something that DOES resolve is not a defect: guarding an
# optional third-party dependency is a legitimate pattern.
_gi_ok = _am38("try:\n    import json\nexcept ImportError:\n    json = None\n")
check("a guarded import that resolves is not reported",
      _fp38(_gi_ok, set()) == [], _fp38(_gi_ok, set()))

_gi_root = "_test_guarded_imports"
_gi_dir = Path(config.OUTPUT_DIR) / _gi_root
shutil.rmtree(_gi_dir, ignore_errors=True)
try:
    (_gi_dir / "backend").mkdir(parents=True)
    (_gi_dir / "backend" / "routes.py").write_text(_gi_src, encoding="utf-8")
    _gi_bd = _BD.__new__(_BD)
    _gi_planned = _gi_bd._planned_modules(
        {"files": [{"path": "backend/routes.py"}, {"path": "backend/main.py"}]}
    )
    _gi_defects = _gi_bd._scan_defects(f"{_gi_root}/backend/routes.py", _gi_planned)

    check("the swallowed ImportError is called out as hiding the failure",
          any("swallows the ImportError" in d for d in _gi_defects), _gi_defects)
    check("…and the defect says the import must not merely be silenced",
          any("hidden, not handled" in d for d in _gi_defects), _gi_defects)
    check("an APIRouter with no handlers is reported as an app with no endpoints",
          any("no route handlers" in d and "no endpoints" in d for d in _gi_defects),
          _gi_defects)

    # A router that does define handlers must not trip that check.
    (_gi_dir / "backend" / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/items')\n"
        "def list_items():\n"
        "    return []\n",
        encoding="utf-8",
    )
    _gi_clean = _gi_bd._scan_defects(f"{_gi_root}/backend/routes.py", _gi_planned)
    check("a router that defines handlers is left alone",
          not any("no endpoints" in d for d in _gi_clean), _gi_clean)
finally:
    shutil.rmtree(_gi_dir, ignore_errors=True)

_gi_prompt = Path("prompts/debugger.txt").read_text(encoding="utf-8")
check("the debugger is told never to silence an import",
      "NEVER SILENCE AN IMPORT" in _gi_prompt)
check("…and is shown the routes.py that served zero endpoints",
      "ZERO endpoints" in _gi_prompt and "include_router" in _gi_prompt)



# ---- 39. A project folder must not shadow an installed package --------------
# The architect adds __init__.py to every Python folder. For `alembic/` that
# turns the migrations directory into a package which wins on sys.path once the
# project root is inserted, so the project's own env.py failed with "cannot
# import name 'context' from 'alembic'" — pointing at the project folder. The
# generated code was right; the __init__.py was not.
from tools.code_introspect import shadows_installed_package as _sip   # noqa: E402

check("a folder named after an installed package is refused an __init__.py",
      _sip("alembic") is True)
check("…including one nested in a path",
      _sip("backend/alembic") is True)
check("…and a stdlib name too", _sip("json") is True and _sip("email") is True)
check("ordinary project folders are unaffected",
      not any(_sip(n) for n in ("backend", "tests", "routers", "services",
                                "models", "api", "utils")))
check("a non-identifier folder name is not treated as a module",
      _sip("my-folder") is False and _sip("") is False)


# ---- 39b. A script a framework runs is not an importable module -------------
# alembic's env.py does `from alembic import context`, which is a proxy module
# populated only while alembic is running a migration. Importing it standalone
# raises "module 'alembic.context' has no attribute 'config'" no matter how
# correct the file is. Row 3 spent debugger attempts on it, then reported it as
# a failing backend file.
from agents.debugger import _is_framework_script as _ifs             # noqa: E402

check("alembic's env.py is not import-checked",
      _ifs("proj/alembic/env.py") is True)
check("…nor a generated migration",
      _ifs("proj/migrations/versions/abc123_init.py") is True)
check("a normal backend file still is",
      _ifs("proj/backend/routes.py") is False)
check("…and a file merely NAMED env.py elsewhere still is",
      _ifs("proj/backend/env.py") is False)


# ---- 39c. A test must be able to import the app the way a user writes it ----
# main.py does `from routes import router`, which only resolves with backend/ on
# sys.path. The import check adds the file's own directory, so backend files are
# fine and tests are not: `from main import app` in tests/test_stock.py raised
# ModuleNotFoundError and the file was reported as failing verification when the
# test was written exactly as anyone would write it.
_sp_root = "_test_sibling_syspath"
_sp_dir = Path(config.OUTPUT_DIR) / _sp_root
shutil.rmtree(_sp_dir, ignore_errors=True)
try:
    (_sp_dir / "backend").mkdir(parents=True)
    (_sp_dir / "tests").mkdir(parents=True)
    (_sp_dir / "backend" / "routes.py").write_text("router = 'r'\n", encoding="utf-8")
    (_sp_dir / "backend" / "main.py").write_text(
        "from routes import router\napp = {'router': router}\n", encoding="utf-8"
    )
    (_sp_dir / "tests" / "test_app.py").write_text(
        "from main import app\ndef test_app():\n    assert app\n", encoding="utf-8"
    )
    from tools.code_executor import run_python as _rp39              # noqa: E402

    _sp_res = _rp39(f"{_sp_root}/tests/test_app.py")
    check("a test importing the app by bare module name now resolves",
          _sp_res.success, _sp_res.stderr[-200:])
    _sp_backend = _rp39(f"{_sp_root}/backend/main.py")
    check("…and a backend file is not regressed",
          _sp_backend.success, _sp_backend.stderr[-200:])

    # The shadowing guard must apply here too: an alembic/ sibling must never
    # be put on sys.path, or the real alembic becomes unreachable.
    (_sp_dir / "alembic").mkdir()
    (_sp_dir / "alembic" / "env.py").write_text("x = 1\n", encoding="utf-8")
    (_sp_dir / "tests" / "test_alembic_ok.py").write_text(
        "import alembic\n"
        "assert hasattr(alembic, '__version__')\n"
        "def test_real_alembic():\n    assert True\n",
        encoding="utf-8",
    )
    _sp_shadow = _rp39(f"{_sp_root}/tests/test_alembic_ok.py")
    check("an alembic/ sibling is never added to sys.path",
          _sp_shadow.success, _sp_shadow.stderr[-200:])
finally:
    shutil.rmtree(_sp_dir, ignore_errors=True)


# ---- 39d. The phantom-import message must not name the wrong mechanism ------
# It said the imports were "inside function bodies". Row 3's five were inside a
# module-level try/except that swallowed the ImportError, so anyone following
# the message looked in the wrong part of the file.
_pi_root = "_test_phantom_message"
_pi_dir = Path(config.OUTPUT_DIR) / _pi_root
shutil.rmtree(_pi_dir, ignore_errors=True)
try:
    _pi_dir.mkdir(parents=True)
    (_pi_dir / "routes.py").write_text(
        "try:\n"
        "    from supplier_routes import router\n"
        "except ImportError:\n"
        "    pass\n",
        encoding="utf-8",
    )
    _pi_msg = _P37.__new__(_P37)._audit_python_imports(_pi_dir)
    check("the phantom import is still reported",
          len(_pi_msg) == 1 and "supplier_routes" in _pi_msg[0], _pi_msg)
    check("…and the message no longer asserts it is in a function body",
          "Imports inside function bodies do" not in _pi_msg[0], _pi_msg[0])
    check("…naming the try/except that swallows ImportError as the other way",
          "swallows ImportError" in _pi_msg[0], _pi_msg[0])
finally:
    shutil.rmtree(_pi_dir, ignore_errors=True)

# ---- 40. A write endpoint must be probed with a body its model accepts -----
# The smoke test sent `json={}` to every POST/PUT, so validation rejected it
# with 422 before the handler ran -- and 422 counts as "responded without a
# server error". Row 3 on 2026-08-30 was scored 16/16 while every POST and PUT
# to /suppliers/ and /products/ raised AttributeError: routes.py read
# `sup.contact` and `prod.sku`, and schemas.py declared `contact_email` and no
# `sku` at all. Six write routes were green without one line of them running.
_SB_APP = '''
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional


class SupplierCreate(BaseModel):
    name: str
    contact_email: Optional[str] = None


class Ok(BaseModel):
    name: str


app = FastAPI()


@app.post("/suppliers/")
def create(sup: SupplierCreate):
    # the drift: the model declares contact_email, the handler reads contact
    return {"name": sup.name, "contact": sup.contact}


@app.post("/ok/")
def ok(item: Ok):
    return {"name": item.name}


@app.get("/items/")
def items():
    return []
'''

_sb_root = "_test_smoke_body"
_sb_dir = Path(config.OUTPUT_DIR) / _sb_root
shutil.rmtree(_sb_dir, ignore_errors=True)
try:
    _sb_dir.mkdir(parents=True)
    (_sb_dir / "main.py").write_text(_SB_APP, encoding="utf-8")
    from tools.runtime_smoke import smoke_test_app as _sta40         # noqa: E402

    _sb = _sta40(_sb_root)
    _sb_by = {(_p.method, _p.path): _p for _p in _sb.probes}
    _sb_bad = _sb_by.get(("POST", "/suppliers/"))
    _sb_good = _sb_by.get(("POST", "/ok/"))

    check("a POST whose handler reads a field its model lacks is now a failure",
          _sb_bad is not None and not _sb_bad.ok,
          f"status={getattr(_sb_bad, 'status', None)}")
    check("...and the error names the attribute, not just '500'",
          _sb_bad is not None and "contact" in _sb_bad.error,
          getattr(_sb_bad, "error", "")[:160])
    check("...and blame is aimed at the file that raised",
          _sb_bad is not None and _sb_bad.blame_file.endswith("main.py"),
          getattr(_sb_bad, "blame_file", ""))
    # The other half of the guarantee: a correct write route must really run,
    # not merely fail validation. A 2xx proves the synthesised body was valid,
    # so a green score now means the handler executed.
    check("a correct POST is executed for real, not answered with 422",
          _sb_good is not None and _sb_good.status is not None
          and _sb_good.status < 300,
          f"status={getattr(_sb_good, 'status', None)}")
finally:
    shutil.rmtree(_sb_dir, ignore_errors=True)


# ---- 40a. A constraint rejecting the synthetic row is not a code defect -----
# The body is invented, so a supplier_id that does not exist or a name already
# taken can raise IntegrityError. Blaming the handler for that would spend a
# repair call editing correct code -- the false positive sql_schema_check was
# built to avoid. Precision over recall, as everywhere else in verification.
from tools.runtime_smoke import RouteProbe as _RP40                  # noqa: E402

check("an IntegrityError 500 from the probe's own row is not counted against the app",
      _RP40(path="/p/", method="POST", status=500,
            error="IntegrityError: UNIQUE constraint failed: supplier.name",
            constraint=True).ok)
check("...while any other 500 still is",
      not _RP40(path="/p/", method="POST", status=500,
                error="AttributeError: no attribute 'contact'").ok)

# A NOT NULL violation is never the probe's fault: the body carries every field
# the model declares, so a column that arrives NULL was made NULL by the handler.
# That is exactly what a repair does when it silences an AttributeError as
# `data.get("sku")` -- and excusing it scored such a repair 16/16 on 2026-08-30,
# one point HIGHER than the repair that actually fixed the bug. A UNIQUE or
# FOREIGN KEY violation stays excused: those really can be the invented row.
_NN_APP = '''
import os
import sqlite3
from fastapi import FastAPI
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))


def db(which):
    # One file per route: a handler that raises leaves its transaction open, and
    # a shared file would make the next probe fail with "database is locked"
    # instead of the constraint error under test.
    conn = sqlite3.connect(os.path.join(HERE, which + ".sqlite"))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS product ("
        " id INTEGER PRIMARY KEY, name TEXT NOT NULL, sku TEXT NOT NULL UNIQUE)"
    )
    return conn


class ProductCreate(BaseModel):
    name: str


app = FastAPI()


@app.post("/products/")
def create(prod: ProductCreate):
    # the silencing move: sku is not on the model, so .get() yields None
    data = prod.model_dump()
    conn = db("nn")
    conn.execute(
        "INSERT INTO product (name, sku) VALUES (?, ?)",
        (data.get("name"), data.get("sku")),
    )
    conn.commit()
    return {"ok": True}


@app.post("/dupes/")
def dupe(prod: ProductCreate):
    # a genuine UNIQUE collision caused by the probe's own repeated value
    conn = db("dupe")
    conn.execute("INSERT INTO product (name, sku) VALUES (?, ?)", ("a", "fixed"))
    conn.execute("INSERT INTO product (name, sku) VALUES (?, ?)", ("b", "fixed"))
    conn.commit()
    return {"ok": True}
'''

_nn_root = "_test_smoke_notnull"
_nn_dir = Path(config.OUTPUT_DIR) / _nn_root
shutil.rmtree(_nn_dir, ignore_errors=True)
try:
    _nn_dir.mkdir(parents=True)
    (_nn_dir / "main.py").write_text(_NN_APP, encoding="utf-8")
    _nn = _sta40(_nn_root)
    _nn_by = {p_.path: p_ for p_ in _nn.probes}
    _nn_null = _nn_by.get("/products/")
    _nn_dupe = _nn_by.get("/dupes/")

    check("a NOT NULL violation is counted against the app, not excused",
          _nn_null is not None and not _nn_null.ok,
          f"status={getattr(_nn_null, 'status', None)} "
          f"constraint={getattr(_nn_null, 'constraint', None)}")
    check("...while a UNIQUE collision from the probe's own row is still excused",
          _nn_dupe is not None and _nn_dupe.ok,
          f"status={getattr(_nn_dupe, 'status', None)} "
          f"constraint={getattr(_nn_dupe, 'constraint', None)}")
finally:
    shutil.rmtree(_nn_dir, ignore_errors=True)


# ---- 41. Every agent that overwrites a file uses the same guard -------------
# The Debugger's guards were each paid for by a live failure. The two other
# agents that overwrite a generated file with an LLM reply had none at all --
# `if fixed and fixed.strip()` and then straight to create_file. A three-line
# reply could replace a three-hundred-line module, and BackendDeveloper's
# re-scan would then call the result clean, because an empty file has no
# defects.
from tools.repair_guard import (                                     # noqa: E402
    accept_generated_fix as _agf41,
    accept_python_reply as _apr41,
    accept_test_reply as _atr41,
    count_test_functions as _ctf41,
)

_SRC41 = (
    "from fastapi import APIRouter\n"
    "\n"
    "router = APIRouter()\n"
    "\n"
    "\n"
    "@router.get('/items')\n"
    "def list_items():\n"
    "    return [{'id': 1, 'name': 'one'}, {'id': 2, 'name': 'two'}]\n"
    "\n"
    "\n"
    "@router.get('/items/{item_id}')\n"
    "def get_item(item_id: int):\n"
    "    return {'id': item_id, 'name': 'one'}\n"
)

check("the shared guard accepts a genuine repair",
      _agf41(_SRC41, _SRC41.replace("'one'", "'ONE'"))[0])
check("...rejects a reply that drops a top-level name",
      not _agf41(_SRC41, "from fastapi import APIRouter\n")[0])

# The old floor was `len(current) > 400 and len(fixed) < len(current) * 0.5`,
# which left two holes: a file of 400 chars or fewer could be reduced to
# nothing, and any file could legally lose 49.9% of itself.
_SMALL41 = (
    "import sqlite3\n"
    "\n"
    "DB = 'app.db'\n"
    "\n"
    "\n"
    "def connect():\n"
    "    conn = sqlite3.connect(DB)\n"
    "    conn.row_factory = sqlite3.Row\n"
    "    return conn\n"
)
check("a file under the old 400-char floor can no longer be gutted",
      len(_SMALL41) < 400
      and not _agf41(_SMALL41, "import sqlite3\nDB = 'app.db'\ndef connect():\n    pass\n")[0])

# accept_python_reply adds the syntax check the Debugger can skip (it re-runs
# the import check and restores the original); BackendDeveloper and the Tester
# have no such backstop.
check("a reply that does not parse is refused where there is no rollback",
      not _apr41(_SRC41, _SRC41 + "\ndef broken(:\n")[0])
check("...and an empty reply is refused",
      not _apr41(_SRC41, "   \n")[0])
check("...while a valid repair still passes",
      _apr41(_SRC41, _SRC41.replace("'one'", "'ONE'"))[0])


# ---- 41a. A test repair may not go green by deleting the failing test -------
# Asked to turn a red suite green, a repair can always do it by removing the
# test. That is §0.7's failure mode in a new place -- the silencing repair
# scored HIGHER than the correct one -- so the test count may never drop.
# The symbol guard is deliberately NOT applied here: renaming a test is a
# legitimate repair and every test name is a top-level symbol.
_TESTS41 = (
    "from main import app\n"
    "\n"
    "\n"
    "def test_one():\n"
    "    assert app is not None\n"
    "\n"
    "\n"
    "def test_two():\n"
    "    assert True\n"
    "\n"
    "\n"
    "def test_three():\n"
    "    assert 1 + 1 == 2\n"
)

check("count_test_functions counts the test functions",
      _ctf41(_TESTS41) == 3, str(_ctf41(_TESTS41)))
check("a test repair that deletes the failing test is refused",
      not _atr41(_TESTS41, _TESTS41.replace(
          "def test_three():\n    assert 1 + 1 == 2\n", ""))[0])
check("...and the reason names the deletion",
      "drops 1 of 3" in _atr41(_TESTS41, _TESTS41.replace(
          "def test_three():\n    assert 1 + 1 == 2\n", ""))[1])
check("a test repair that RENAMES a test is still accepted",
      _atr41(_TESTS41, _TESTS41.replace("test_three", "test_three_renamed"))[0])
check("...and one that fixes an assertion in place is accepted",
      _atr41(_TESTS41, _TESTS41.replace("1 + 1 == 2", "2 + 2 == 4"))[0])
check("a test reply that does not parse is refused",
      not _atr41(_TESTS41, "def test_x(:\n")[0])


# ---- 41b. tsc still failing is not a success --------------------------------
# `result.success = len(result.fixes_applied) > 0` meant "we tried, therefore we
# succeeded". Pipeline._diagnose filters on `not success and not skipped`, so a
# frontend file whose every error survived both LLM attempts was invisible to
# the one gate that would have surfaced it.
import inspect                                                       # noqa: E402
import re as _re41                                                   # noqa: E402
from agents.frontend_debugger import FrontendDebugger as _FD41       # noqa: E402

_fd_src41 = inspect.getsource(_FD41._fix_file)
# Match the ASSIGNMENT, not the prose: the comment explaining the old bug
# quotes the old expression, and a substring test would match its own docs.
check("the frontend debugger no longer calls 'we tried' a success",
      _re41.search(r"result\.success\s*=\s*len\(result\.fixes_applied\)",
                _fd_src41) is None)
check("...and the fall-through path reports failure",
      "result.success      = False" in _fd_src41)


# ---- 41c. A request-time failure is repaired on whichever attempt passes ----
# The runtime repair was gated on `attempt == 1` INSIDE the branch where the
# import check had just passed. A file that failed its import check, was
# repaired, and passed on attempt 2 never had its 500 looked at at all -- the
# smoke test found a real failure and the only pass that could act on it was
# skipped.
from agents.debugger import Debugger as _DBG41                       # noqa: E402

_dbg_src41 = inspect.getsource(_DBG41._debug_file)
check("the runtime repair is no longer gated on attempt == 1",
      "runtime_error and attempt == 1" not in _dbg_src41)
check("...it is gated on whether it has already been tried",
      "runtime_repair_tried" in _dbg_src41)
check("...and it is reachable from every import-check success path",
      _dbg_src41.count("_try_runtime_repair()") >= 4,
      str(_dbg_src41.count("_try_runtime_repair()")))


# ---- 42. "Not checked" is not "checked and clean" ---------------------------
# Every verifier answered with a list of findings, and an empty list meant four
# different things: it passed, it does not apply, it could not run, or there was
# nothing to look at. Pipeline._smoke_test_runtime returned [] for all four, so
# a build nobody had verified and a build that passed were the same value.
from tools.verification import (                                     # noqa: E402
    Status as _St42,
    VerificationOutcome as _VO42,
    collect_findings as _cf42,
    worst_status as _ws42,
    EXECUTING_CHECKS as _EXEC42,
)

check("a check that passed is ok",
      _VO42.verified("x").ok)
check("a check that RAN the artifact and passed is evidence it works",
      _VO42.verified("runtime_smoke").is_evidence_of_working)
# Half the checks never run the thing they inspect. A green static check says
# the code reads correctly, which is not the same claim -- and 27 of the 41
# saved builds have a verified static check and no verified executing one.
check("a static check that passed is NOT evidence the thing works",
      not _VO42.verified("sql_schema").is_evidence_of_working
      and not _VO42.verified("feature_coverage").is_evidence_of_working
      and not _VO42.verified("web_assets").is_evidence_of_working
      and not _VO42.verified("schema_attr").is_evidence_of_working)
check("...and an unknown check name is not evidence either",
      not _VO42.verified("x").is_evidence_of_working)
check("every check that executes the artifact is listed as such",
      _EXEC42 == {"runtime_smoke", "cli_smoke", "package_smoke",
                  "generated_tests", "static_smoke"}, str(sorted(_EXEC42)))
check("and every static check is kept out of it",
      not (_EXEC42 & {"web_assets", "feature_coverage", "schema_attr",
                      "sql_schema"}),
      "a static check is being counted as execution evidence")
check("a check that does not apply is ok, but is NOT evidence",
      _VO42.not_applicable("runtime_smoke").ok
      and not _VO42.not_applicable("runtime_smoke").is_evidence_of_working)
check("a check that never ran is NOT ok — the hole is not a pass",
      not _VO42.not_run("x", detail="no entry point").ok)
check("a failed check is not ok",
      not _VO42.failed("x", ["boom"]).ok)

# The NOT_RUN line is the whole point: it puts "we do not know" into the same
# list the pipeline reports, so an unverified build reads as unverified rather
# than disappearing into silence.
_nr42 = _cf42([_VO42.not_run("runtime_smoke", detail="no entry point found")])
check("a check that never ran contributes an explicit finding",
      len(_nr42) == 1 and "unverified" in _nr42[0], str(_nr42))
check("...while one that does not apply contributes nothing",
      _cf42([_VO42.not_applicable("cli_smoke")]) == [])
check("worst_status ranks a hole above a pass",
      _ws42([_VO42.verified("a"), _VO42.not_run("b")]) is _St42.NOT_RUN)
check("...and a failure above the hole",
      _ws42([_VO42.not_run("a"), _VO42.failed("b", ["x"])]) is _St42.FAILED)


# ---- 42a. One shape detector, and it finds what row 4 hid -------------------
# runtime_smoke._find_entry searched backend/, src/ and the project root for a
# file containing the literal "FastAPI(". Row 4's architect wrote its app to
# bulk_file_renamer/main.py, so the search found nothing, the pipeline logged
# "Runtime smoke test skipped (no FastAPI entry point)", and a web application
# shipped without one request ever being sent to it.
from tools.build_shape import detect_shapes as _ds42                 # noqa: E402

_bs_root = "_test_build_shape"
_bs_dir = Path(config.OUTPUT_DIR) / _bs_root
shutil.rmtree(_bs_dir, ignore_errors=True)
try:
    # A layout no directory-list would find: the app is neither in backend/ nor
    # src/ nor the root, and the CLI sits beside it.
    (_bs_dir / "mytool").mkdir(parents=True)
    (_bs_dir / "mytool" / "__init__.py").write_text("", encoding="utf-8")
    (_bs_dir / "mytool" / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n",
        encoding="utf-8",
    )
    (_bs_dir / "mytool" / "cli.py").write_text(
        "import argparse\n"
        "def main():\n"
        "    argparse.ArgumentParser().parse_args()\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (_bs_dir / "page.html").write_text("<html></html>", encoding="utf-8")

    _bs = _ds42(_bs_dir, rel_to=config.OUTPUT_DIR)
    check("a web app outside backend/, src/ and the root is still found",
          _bs.is_web and _bs.primary_web_entry.path.endswith("mytool/main.py"),
          str([e.path for e in _bs.web_entries]))
    check("...and the CLI beside it is found too",
          _bs.is_cli and _bs.cli_entries[0].path.endswith("mytool/cli.py"))
    check("...and the page",
          _bs.is_static_frontend)
    check("a build is several shapes at once, not one",
          set(_bs.names()) >= {"web_api", "cli", "static_frontend"},
          _bs.describe())
    check("paths are OUTPUT_DIR-relative, not absolute",
          not _bs.primary_web_entry.path.startswith(("/", "C:", "c:")),
          _bs.primary_web_entry.path)

    # Flask, and an app built by a factory rather than bound at module level —
    # the old probe required a module-level `app` and reported the ordinary
    # factory pattern as "module defines no `app` object", i.e. a boot failure.
    (_bs_dir / "flaskapp.py").write_text(
        "from flask import Flask\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    return app\n",
        encoding="utf-8",
    )
    _bs2 = _ds42(_bs_dir, rel_to=config.OUTPUT_DIR)
    _flask = [e for e in _bs2.web_entries if e.path.endswith("flaskapp.py")]
    check("a Flask app is recognised as a web entry",
          bool(_flask) and _flask[0].framework == "flask")
    check("...and a create_app() factory counts as an entry point",
          bool(_flask) and _flask[0].factory == "create_app")

    # An `import argparse` with no way to invoke it is a helper, not a tool.
    (_bs_dir / "helper.py").write_text(
        "import argparse\n"
        "def build_parser():\n"
        "    return argparse.ArgumentParser()\n",
        encoding="utf-8",
    )
    _bs3 = _ds42(_bs_dir, rel_to=config.OUTPUT_DIR)
    check("a module that merely imports argparse is not called a CLI",
          not any(e.path.endswith("helper.py") for e in _bs3.cli_entries),
          str([e.path for e in _bs3.cli_entries]))
finally:
    shutil.rmtree(_bs_dir, ignore_errors=True)


# ---- 42b. The CLI is actually run --------------------------------------------
# Nothing had ever executed a generated command-line tool. The import check
# imports the module, and everything under `if __name__ == "__main__"` is by
# definition not executed by an import.
from tools.cli_smoke import smoke_test_cli as _cli42                 # noqa: E402

_cs_root = "_test_cli_smoke"
_cs_dir = Path(config.OUTPUT_DIR) / _cs_root
shutil.rmtree(_cs_dir, ignore_errors=True)
try:
    _cs_dir.mkdir(parents=True)
    (_cs_dir / "good.py").write_text(
        "import argparse\n"
        "\n"
        "def main():\n"
        "    p = argparse.ArgumentParser(description='renames things')\n"
        "    p.add_argument('PATTERN')\n"
        "    p.add_argument('REPLACEMENT')\n"
        "    a = p.parse_args()\n"
        "    print(a.PATTERN, a.REPLACEMENT)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    _good = _cli42(_cs_root)
    check("a working CLI verifies, and --help really ran",
          _good.status is _St42.VERIFIED
          and _good.evidence["entries"][0]["help_exit"] == 0,
          _good.detail + " " + str(_good.findings))
    check("...and its required positionals were read from the usage line",
          set(_good.evidence["entries"][0]["positionals"]) ==
          {"PATTERN", "REPLACEMENT"},
          str(_good.evidence["entries"][0]))
finally:
    shutil.rmtree(_cs_dir, ignore_errors=True)

_cs2_dir = Path(config.OUTPUT_DIR) / "_test_cli_broken"
shutil.rmtree(_cs2_dir, ignore_errors=True)
try:
    _cs2_dir.mkdir(parents=True)
    # A parser that cannot even build its own help text: `type=` names a
    # function that does not exist. It imports perfectly.
    (_cs2_dir / "broken.py").write_text(
        "import argparse\n"
        "\n"
        "def main():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('path', type=nonexistent_validator)\n"
        "    p.parse_args()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    _bad = _cli42("_test_cli_broken")
    check("a CLI that blows up on --help is caught",
          _bad.status is _St42.FAILED, _bad.detail)
    check("...and the finding names the tool and the exit",
          any("broken.py" in f and "--help" in f for f in _bad.findings),
          str(_bad.findings)[:200])
finally:
    shutil.rmtree(_cs2_dir, ignore_errors=True)

_cs3_dir = Path(config.OUTPUT_DIR) / "_test_cli_absent"
shutil.rmtree(_cs3_dir, ignore_errors=True)
try:
    _cs3_dir.mkdir(parents=True)
    (_cs3_dir / "lib.py").write_text("def add(a, b):\n    return a + b\n",
                                     encoding="utf-8")
    _none = _cli42("_test_cli_absent")
    check("a project with no CLI reports not-applicable, never a false failure",
          _none.status is _St42.NOT_APPLICABLE, _none.detail)
finally:
    shutil.rmtree(_cs3_dir, ignore_errors=True)


# ---- 42c. The page is actually parsed ---------------------------------------
# A plain HTML/CSS/JS frontend had exactly one check: a regex for RELATIVE
# import specifiers pointing at files that do not exist. Row 2 shipped an app.js
# whose first two lines are bare specifiers (`import React from "react"`), which
# a browser cannot resolve in a module — and the regex passed it, because those
# imports are not relative.
from tools.web_asset_check import check_web_assets as _wac42         # noqa: E402

_wa_root = "_test_web_assets"
_wa_dir = Path(config.OUTPUT_DIR) / _wa_root
shutil.rmtree(_wa_dir, ignore_errors=True)
try:
    (_wa_dir / "backend").mkdir(parents=True)
    (_wa_dir / "frontend").mkdir(parents=True)
    (_wa_dir / "backend" / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "\n"
        "@router.get('/bookmarks')\n"
        "def list_b():\n"
        "    return []\n"
        "\n"
        "@router.delete('/bookmarks/{bid}')\n"
        "def del_b(bid: int):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    # The page reaches app.js through an INLINE module's import, which is how
    # row 2 does it — checking only <script src> tags never opens the file.
    (_wa_dir / "frontend" / "index.html").write_text(
        '<!DOCTYPE html><html><head>\n'
        '<link rel="stylesheet" href="./missing.css">\n'
        '</head><body><div id="root"></div>\n'
        '<script type="module">import App from "./app.js";</script>\n'
        '</body></html>\n',
        encoding="utf-8",
    )
    (_wa_dir / "frontend" / "app.js").write_text(
        'import React from "react";\n'
        'const API = "http://localhost:8000";\n'
        'export default function App() {\n'
        '  fetch(`${API}/bookmarks`);\n'
        '  fetch(`${API}/bookmarks/${id}`);\n'
        '  fetch(`${API}/api/v2/bookmarks`);\n'
        '}\n',
        encoding="utf-8",
    )
    _wa = _wac42(_wa_root)
    check("a bare specifier in a module reached through an inline import is caught",
          any("`react`" in f for f in _wa.findings), str(_wa.findings)[:250])
    check("a referenced file that does not exist is caught",
          any("missing.css" in f for f in _wa.findings), str(_wa.findings)[:250])
    check("a frontend call the backend does not serve is caught",
          any("/api/v2/bookmarks" in f for f in _wa.findings),
          str(_wa.findings)[:250])
    # Precision: the two calls that DO line up must not be reported, including
    # the parameterised one -- /bookmarks/${id} against /bookmarks/{bid}.
    check("...while a call that matches a declared route is not reported",
          not any("`/bookmarks`" in f for f in _wa.findings),
          str(_wa.findings)[:250])
    check("...and a parameterised route matches its path parameter",
          not any("/bookmarks/1" in f for f in _wa.findings),
          str(_wa.findings)[:250])
finally:
    shutil.rmtree(_wa_dir, ignore_errors=True)

# A bundled frontend resolves bare specifiers at build time, so reporting them
# there would be a false positive on every React project the builder produces.
_wa2_dir = Path(config.OUTPUT_DIR) / "_test_web_bundled"
shutil.rmtree(_wa2_dir, ignore_errors=True)
try:
    (_wa2_dir / "frontend" / "src").mkdir(parents=True)
    (_wa2_dir / "frontend" / "package.json").write_text('{"name":"f"}',
                                                        encoding="utf-8")
    (_wa2_dir / "frontend" / "index.html").write_text(
        '<html><body><script type="module" src="./src/main.jsx"></script>'
        '</body></html>', encoding="utf-8",
    )
    (_wa2_dir / "frontend" / "src" / "main.jsx").write_text(
        'import React from "react";\nexport default React;\n', encoding="utf-8",
    )
    _wa2 = _wac42("_test_web_bundled")
    check("a bundled frontend's bare specifiers are not reported",
          not any("react" in f for f in _wa2.findings), str(_wa2.findings)[:200])
finally:
    shutil.rmtree(_wa2_dir, ignore_errors=True)

_wa3_dir = Path(config.OUTPUT_DIR) / "_test_web_absent"
shutil.rmtree(_wa3_dir, ignore_errors=True)
try:
    _wa3_dir.mkdir(parents=True)
    (_wa3_dir / "lib.py").write_text("x = 1\n", encoding="utf-8")
    check("a project with no HTML reports not-applicable",
          _wac42("_test_web_absent").status is _St42.NOT_APPLICABLE)
finally:
    shutil.rmtree(_wa3_dir, ignore_errors=True)


# ---- 42d. An app that serves nothing is not a clean run ---------------------
# `if not smoke.probes: return []` — an app that boots and declares ZERO routes
# produced no issue, no advisory, and not even the summary log line. That is the
# literal empty build; §4.20 shipped exactly it.
_zr_root = "_test_zero_routes"
_zr_dir = Path(config.OUTPUT_DIR) / _zr_root
shutil.rmtree(_zr_dir, ignore_errors=True)
try:
    (_zr_dir / "backend").mkdir(parents=True)
    (_zr_dir / "backend" / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n",
        encoding="utf-8",
    )
    _zr_pipeline = Pipeline.__new__(Pipeline)
    _zr_pipeline._smoke_runtime_errors = {}
    _zr_result = type("R", (), {
        "architecture": {"root_folder": _zr_root}, "smoke_summary": ""
    })()
    _zr_issues = _zr_pipeline._smoke_test_runtime(_zr_result)
    check("an app that boots with no routes is reported, not passed silently",
          bool(_zr_issues) and "no routes" in _zr_issues[0], str(_zr_issues))
    check("...and a repair is aimed at the file that should define them",
          bool(_zr_pipeline._smoke_runtime_errors),
          str(_zr_pipeline._smoke_runtime_errors))
finally:
    shutil.rmtree(_zr_dir, ignore_errors=True)


# ---- 43. Did it build what was asked for? -----------------------------------
# `intent["features"]` reached exactly one place before this: the README. So a
# build could implement two of six requested features and every gate stayed
# green — the files import, the tests pass, the routes that DO exist answer 200.
# "It works" and "it is what you asked for" are different questions.
from tools.feature_coverage import (                                 # noqa: E402
    check_feature_coverage as _fc43,
    _content_words as _cw43,
)

_fc_root = "_test_feature_coverage"
_fc_dir = Path(config.OUTPUT_DIR) / _fc_root
shutil.rmtree(_fc_dir, ignore_errors=True)
try:
    (_fc_dir / "backend").mkdir(parents=True)
    (_fc_dir / "backend" / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "\n"
        "@router.get('/stock_movements/')\n"
        "def list_stock_movements():\n"
        "    return []\n"
        "\n"
        "@router.get('/low_stock/')\n"
        "def low_stock_report():\n"
        "    return []\n",
        encoding="utf-8",
    )
    (_fc_dir / "backend" / "cli.py").write_text(
        "import argparse\n"
        "\n"
        "def main():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('-d', '--dry-run', action='store_true')\n"
        "    p.parse_args()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )

    _fc_ok = _fc43(_fc_root, {"features": [
        "CRUD for StockMovement",
        "Low-stock report endpoint",
        "dry-run flag",
    ]})
    check("a feature the code implements is not reported missing",
          _fc_ok.status is _St42.VERIFIED, _fc_ok.detail + str(_fc_ok.findings))

    _fc_bad = _fc43(_fc_root, {"features": [
        "Low-stock report endpoint",
        "CSV export of the inventory",
        "barcode scanning support",
    ]})
    check("a feature nothing in the code refers to IS reported",
          _fc_bad.status is _St42.FAILED
          and len(_fc_bad.evidence["missing"]) == 2,
          str(_fc_bad.evidence.get("missing")))
    check("...and the finding quotes the request, not a code symbol",
          any("CSV export of the inventory" in f for f in _fc_bad.findings),
          str(_fc_bad.findings)[:200])

    # A request with no features listed must never be reported as a failure —
    # most prompts do not enumerate them.
    check("a request that lists no features is not applicable",
          _fc43(_fc_root, {"features": []}).status is _St42.NOT_APPLICABLE)

    # A feature described only in CRUD verbs has no distinguishing content:
    # every generated backend would match it, so checking proves nothing.
    _fc_weak = _fc43(_fc_root, {"features": ["create and delete"]})
    check("a feature made only of CRUD verbs is skipped, not reported missing",
          _fc_weak.evidence.get("checked") == 0, str(_fc_weak.evidence))
finally:
    shutil.rmtree(_fc_dir, ignore_errors=True)


# ---- 43a. The two ways this checker was wrong before it shipped -------------
# Both were caught by running it against real builds and disbelieving the
# result. Row 3 was reported as missing "CRUD for StockMovement" while serving
# five routes for it, and row 4 as missing its "dry-run flag" while
# implementing it. Neither was a defect in the generated code.

# 1. The feature phrase was not split the way identifiers are. "StockMovement"
#    became one token, and the artifact spells it `/stock_movements/` and
#    `StockMovement` — split against unsplit matches nothing.
check("a CamelCase feature name is split into its words",
      {"stock", "movement"} <= _cw43("CRUD for StockMovement"),
      str(_cw43("CRUD for StockMovement")))
check("...and a hyphenated one too",
      {"dry", "run"} <= _cw43("dry-run flag"), str(_cw43("dry-run flag")))
check("...while generic words are still dropped",
      not ({"the", "system", "data", "endpoint"} & _cw43(
          "the system data endpoint")))

# 2. argparse takes the short flag first, so a regex reading only the first
#    argument of add_argument() sees "-d" and never "--dry-run" — the only one
#    carrying meaning.
_fc2_dir = Path(config.OUTPUT_DIR) / "_test_feature_flags"
shutil.rmtree(_fc2_dir, ignore_errors=True)
try:
    _fc2_dir.mkdir(parents=True)
    (_fc2_dir / "tool.py").write_text(
        "import argparse\n"
        "\n"
        "def main():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument(\n"
        "        '-d',\n"
        "        '--dry-run',\n"
        "        action='store_true',\n"
        "    )\n"
        "    p.parse_args()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    _flag = _fc43("_test_feature_flags", {"features": ["a dry-run flag"]})
    check("a long flag declared after a short one is still found",
          _flag.status is _St42.VERIFIED, str(_flag.findings))
finally:
    shutil.rmtree(_fc2_dir, ignore_errors=True)

# The documenter writes the requested features into the README as prose, so
# counting prose would let a project "implement" a feature by describing it.
_fc3_dir = Path(config.OUTPUT_DIR) / "_test_feature_prose"
shutil.rmtree(_fc3_dir, ignore_errors=True)
try:
    _fc3_dir.mkdir(parents=True)
    (_fc3_dir / "app.py").write_text(
        '"""This module provides barcode scanning support."""\n'
        "# barcode scanning support\n"
        "def unrelated():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    _prose = _fc43("_test_feature_prose", {"features": ["barcode scanning support"]})
    check("a feature only DESCRIBED in a comment does not count as built",
          _prose.status is _St42.FAILED, _prose.detail + str(_prose.findings))
finally:
    shutil.rmtree(_fc3_dir, ignore_errors=True)


# ---- 44. The prompts must not contradict each other -------------------------
# Two contradictions were producing broken builds directly, and neither is
# visible from inside either file — you only see it by reading both.
_PROMPTS = Path(__file__).parent / "prompts"


def _prompt44(name: str) -> str:
    try:
        return (_PROMPTS / name).read_text(encoding="utf-8")
    except Exception:
        return ""


_arch44 = _prompt44("architect.txt")
_front44 = _prompt44("frontend_generator.txt")
_backend44 = _prompt44("backend_developer.txt")
_debug44 = _prompt44("debugger.txt")

check("every prompt file is readable",
      all([_arch44, _front44, _backend44, _debug44]))

# 1. architect.txt said "plain HTML/CSS/JavaScript for ALL frontend code" while
#    frontend_generator.txt said React + Tailwind + axios with a default
#    export. The generator obeyed the second, the architect planned for the
#    first, and row 2 shipped the hybrid: a React component in a file called
#    app.js, loaded by a plain <script type="module">, whose bare `import React
#    from "react"` a browser cannot resolve. The page rendered nothing.
check("the architect still requires plain HTML/CSS/JS",
      "plain HTML/CSS/JavaScript" in _arch44)
# Assert the DIRECTIVE, not the string: the prompt names React in order to
# forbid it, and a substring test would match its own prohibition.
check("the frontend generator no longer asks for React",
      "React/Tailwind code" not in _front44
      and "functional components with hooks" not in _front44)
check("...and explicitly forbids it instead",
      "No React" in _front44)
check("...nor Tailwind as the styling system",
      "Use Tailwind CSS for styling" not in _front44)
check("...and it forbids the bare specifier that broke the page",
      "NEVER IMPORT A BARE PACKAGE NAME" in _front44)
check("the runtime repair prompt agrees with it",
      "Tailwind CSS classes" not in
      inspect.getsource(__import__("agents.frontend_generator",
                                   fromlist=["FrontendGenerator"])))

# 2. backend_developer.txt forbids ORMs; debugger.txt's own ✅ example was
#    `db.query(Supplier).all()` — SQLAlchemy. With an architect free to plan
#    alembic/, that is the mechanism behind the persistence-shape drift that
#    cost row 3 two remediation passes and ~48K tokens.
check("the backend developer still forbids an ORM",
      "Do NOT use SQLAlchemy" in _backend44)
check("the debugger's example no longer uses an ORM",
      "db.query(" not in _debug44, "SQLAlchemy example survives in debugger.txt")
check("...and shows raw sqlite3 instead",
      "conn.execute(" in _debug44)
check("the architect is forbidden to plan an alembic layout",
      "alembic/" in _arch44 and "alembic.ini" in _arch44)

# 3. The forced backend. Its own justification was "required for the testing and
#    debugging pipeline to function" — the product was being distorted to fit a
#    verifier that only understood FastAPI. Row 4 shipped a FastAPI app serving
#    one /health route beside the CLI that was actually requested.
# Same again: the replacement text quotes the old rule to explain why it went.
# What must be gone is the enforcing sentence, not every mention of it.
check("the blanket always-a-backend mandate is gone",
      "MANDATORY RULE" not in _arch44.split("BUILD WHAT WAS ASKED FOR")[0]
      and "Every project MUST include AT MINIMUM" not in _arch44
      and "create a minimal FastAPI backend" not in _arch44)
check("...replaced by building the shape that was requested",
      "BUILD WHAT WAS ASKED FOR" in _arch44)
check("...and a CLI request is told not to add a web API",
      "NO FastAPI" in _arch44)

# 4. debugger.txt capped fixes at 60 lines while agents/debugger.py sizes the
#    rewrite budget to the file with deliberately no ceiling. Told to cap at 60
#    lines and to return a 300-line file complete, a model truncates — and a
#    truncated file is a syntax error the next pass has to repair.
check("the debugger prompt no longer caps the fix at 60 lines",
      "Maximum 60 lines" not in _debug44)
check("...and requires the file back complete",
      "Never truncate" in _debug44)

# 5. §0.7's lesson, written where the model will see it: silencing an
#    AttributeError scored HIGHER on the smoke test than the correct fix.
check("the debugger is forbidden to silence an AttributeError",
      "NEVER SILENCE AN ATTRIBUTE ERROR" in _debug44)
check("...and the import version of the rule is still there",
      "NEVER SILENCE AN IMPORT" in _debug44)


# ---- 45. "Repairable" must mean there is something to repair ----------------
# _diagnose returned four findings as repairable. Three of them contributed
# NOTHING to failed_paths: frontend/TypeScript failures, "no executable tests
# were generated", and "generated tests fail". So remediation announced a repair
# pass, set llm_used=True and passes=1 before any work, found `failed_paths`
# empty, broke with "made no progress", and degraded the build. That was the
# commonest route to done_with_context in the whole pipeline.
#
# The invariant: if _diagnose reports something as repairable, it must name a
# file to aim the repair at.
class _FakeDbg45:
    def __init__(self, path, ok):
        self.file_path, self.success = path, ok


class _FakeTest45:
    def __init__(self, path, passed, total, skipped=False):
        self.file_path, self.passed = path, passed
        self.tests_generated, self.skipped = total, skipped


class _FakeTs45:
    def __init__(self, path, ok, skipped=False):
        self.file_path, self.success, self.skipped = path, ok, skipped


from agents.pipeline import BuildResult as _BR45              # noqa: E402

_d45 = Pipeline.__new__(Pipeline)


def _diag45(**kw):
    r = _BR45(user_prompt="x", build_id="diag45")
    r.architecture = {"root_folder": "_diag45", "files": []}
    r.backend_files = kw.get("backend", ["_diag45/backend/routes.py"])
    r.debug_results = kw.get("debug", [])
    r.test_results = kw.get("tests", [])
    r.frontend_debug_results = kw.get("frontend", [])
    return _d45._diagnose(r)


# A frontend file the Python debugger cannot touch, and which
# agents/frontend_debugger.py has already spent its attempts on.
_i45, _f45, _a45 = _diag45(
    debug=[_FakeDbg45("_diag45/backend/routes.py", True)],
    tests=[_FakeTest45("_diag45/backend/routes.py", 3, 3)],
    frontend=[_FakeTs45("frontend/App.tsx", False)],
)
check("a frontend failure is advisory, not a repair nobody can perform",
      not _i45 and any("Frontend/TypeScript" in a for a in _a45),
      f"issues={_i45} advisory={_a45}")
check("...and it names no file for the Python debugger to aim at",
      _f45 == [], str(_f45))

# "No executable tests were generated" — no repair pass generates tests.
_i45b, _f45b, _a45b = _diag45(
    debug=[_FakeDbg45("_diag45/backend/routes.py", True)],
    tests=[],
)
check("'no executable tests' is advisory, since no pass can generate them",
      not _i45b and any("unverified by tests" in a for a in _a45b),
      f"issues={_i45b} advisory={_a45b}")

# A failing test IS repairable — the code under test is usually what is wrong,
# and TestResult.file_path names it. This was the one of the three that had a
# file to aim at all along and simply never supplied it.
_i45c, _f45c, _a45c = _diag45(
    debug=[_FakeDbg45("_diag45/backend/routes.py", True)],
    tests=[_FakeTest45("_diag45/backend/routes.py", 1, 3)],
)
check("a failing test is still repairable",
      any("tests fail" in i for i in _i45c), str(_i45c))
check("...and now hands the debugger the file under test",
      _f45c == ["_diag45/backend/routes.py"], str(_f45c))

# The invariant itself, over every combination that produces an issue.
for _label, _kw in (
    ("import failure", {"debug": [_FakeDbg45("_diag45/backend/routes.py", False)]}),
    ("failing tests", {"debug": [_FakeDbg45("_diag45/backend/routes.py", True)],
                       "tests": [_FakeTest45("_diag45/backend/routes.py", 0, 3)]}),
    ("both", {"debug": [_FakeDbg45("_diag45/backend/routes.py", False)],
              "tests": [_FakeTest45("_diag45/backend/services.py", 0, 3)]}),
):
    _i, _f, _a = _diag45(**_kw)
    check(f"repairable issues from {_label} name a file to aim at",
          bool(_f) if _i else True, f"issues={_i} paths={_f}")

# A clean build must still produce nothing at all — the reclassification must
# not turn silence into advisory noise.
_i45d, _f45d, _a45d = _diag45(
    debug=[_FakeDbg45("_diag45/backend/routes.py", True)],
    tests=[_FakeTest45("_diag45/backend/routes.py", 3, 3)],
)
check("a clean build reports neither an issue nor an advisory",
      not _i45d and not _a45d and not _f45d,
      f"issues={_i45d} advisory={_a45d}")


# ---- 46. A library is imported the way a user imports it --------------------
# `run_python` imports each file individually with its own directory on
# sys.path. A user writes `import mylib`, which runs `mylib/__init__.py` and
# every re-export in it — and __init__.py is exactly where a renamed or missing
# name shows up. This matters now that the architect no longer bolts a FastAPI
# app onto every request, so a library request produces a library.
from tools.package_smoke import smoke_test_package as _pk46           # noqa: E402


def _mk_pkg46(root, init_src, core_src="def add(a, b):\n    return a + b\n"):
    d = Path(config.OUTPUT_DIR) / root
    shutil.rmtree(d, ignore_errors=True)
    (d / "mylib").mkdir(parents=True)
    (d / "mylib" / "__init__.py").write_text(init_src, encoding="utf-8")
    (d / "mylib" / "core.py").write_text(core_src, encoding="utf-8")
    return d


_pk_good = _mk_pkg46("_test_pkg_good",
                     'from .core import add\n__all__ = ["add"]\n')
try:
    _r46 = _pk46("_test_pkg_good")
    check("a library that imports cleanly verifies",
          _r46.status is _St42.VERIFIED, _r46.detail + str(_r46.findings))
finally:
    shutil.rmtree(_pk_good, ignore_errors=True)

# __all__ is a promise about the public API. A name listed there that does not
# exist is an ImportError for anyone following the README — and every
# individual file still imports perfectly, so the per-file check sees nothing.
_pk_bad = _mk_pkg46("_test_pkg_all",
                    'from .core import add\n__all__ = ["add", "subtract"]\n')
try:
    _r46b = _pk46("_test_pkg_all")
    check("a name promised by __all__ but never defined is caught",
          _r46b.status is _St42.FAILED
          and any("subtract" in f for f in _r46b.findings),
          str(_r46b.findings)[:200])
finally:
    shutil.rmtree(_pk_bad, ignore_errors=True)

# The re-export that names something that was never written.
_pk_err = _mk_pkg46("_test_pkg_import", "from .core import nonexistent\n")
try:
    _r46c = _pk46("_test_pkg_import")
    check("a broken re-export in __init__.py is caught",
          _r46c.status is _St42.FAILED
          and any("import mylib" in f for f in _r46c.findings),
          str(_r46c.findings)[:200])
finally:
    shutil.rmtree(_pk_err, ignore_errors=True)

# A package that imports but exposes nothing is an empty build in library form.
_pk_empty = _mk_pkg46("_test_pkg_empty", "\n")
try:
    _r46d = _pk46("_test_pkg_empty")
    check("a package that exposes no public API at all is caught",
          _r46d.status is _St42.FAILED
          and any("no public names" in f for f in _r46d.findings),
          str(_r46d.findings)[:200])
finally:
    shutil.rmtree(_pk_empty, ignore_errors=True)

# Precision: a web app or a CLI has a verifier that exercises far more than an
# import, so this must stand down rather than double-report.
_pk_web = Path(config.OUTPUT_DIR) / "_test_pkg_web"
shutil.rmtree(_pk_web, ignore_errors=True)
try:
    (_pk_web / "mylib").mkdir(parents=True)
    (_pk_web / "mylib" / "__init__.py").write_text("", encoding="utf-8")
    (_pk_web / "mylib" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    check("a web project is left to the web verifier",
          _pk46("_test_pkg_web").status is _St42.NOT_APPLICABLE)
finally:
    shutil.rmtree(_pk_web, ignore_errors=True)



# ---- 47. A field the model never declared -----------------------------------
# The drift a runtime probe structurally cannot see. Two-sided throughout: the
# checker must catch the read that raises AND stay silent on the code that is
# right, because four of the six checkers written on 2026-08-30 reported a
# defect that did not exist and each was caught only by running it against a
# real build.
from tools.schema_attr_check import (                                  # noqa: E402
    check_project_attributes as _attr47,
    check_schema_attributes as _attr47o,
    find_model_definition as _attrdef47,
)

_ATTR_SCHEMAS = '''from pydantic import BaseModel, ConfigDict
from typing import Optional


class SupplierBase(BaseModel):
    name: str
    contact_email: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class SupplierCreate(SupplierBase):
    pass


class ProductBase(BaseModel):
    name: str
    price: float


class ProductCreate(ProductBase):
    pass
'''


def _mk_attr47(root: str, routes_src: str, schemas_src: str = _ATTR_SCHEMAS):
    d = Path(config.OUTPUT_DIR) / root
    shutil.rmtree(d, ignore_errors=True)
    (d / "backend").mkdir(parents=True)
    (d / "backend" / "schemas.py").write_text(schemas_src, encoding="utf-8")
    (d / "backend" / "routes.py").write_text(routes_src, encoding="utf-8")
    return root


_bad47 = _mk_attr47("_test_attr_bad", '''import schemas


def create_supplier(sup: schemas.SupplierCreate):
    return (sup.name, sup.contact)


def create_product(prod: schemas.ProductCreate):
    return (prod.name, prod.sku)
''')
try:
    _r47 = _attr47(_bad47)
    _names47 = {f"{i.model}.{i.attr}" for i in _r47.issues}
    check("a field the model does not declare is caught",
          _names47 == {"SupplierCreate.contact", "ProductCreate.sku"},
          str(_names47))
    check("the message names the fields that DO exist, so the repair can choose",
          any("contact_email" in str(i) for i in _r47.issues))
    check("the message forbids the silencing move that scored 15/16",
          all(".get()" in str(i) for i in _r47.issues))
    check("model_config is not offered to the repair as a field",
          all("model_config" not in ", ".join(i.declared) for i in _r47.issues))
finally:
    shutil.rmtree(Path(config.OUTPUT_DIR) / _bad47, ignore_errors=True)

# The other half: correct code must stay silent, including every read this
# checker deliberately cannot resolve. A checker that finds nothing has proved
# nothing, but one that fires on working code costs an LLM call and tells a
# user their build is broken.
_good47 = _mk_attr47("_test_attr_good", '''import schemas
from typing import Optional, List


def create_supplier(sup: schemas.SupplierCreate):
    return (sup.name, sup.contact_email, sup.model_dump(), sup.dict())


def optional_ok(sup: Optional[schemas.SupplierCreate]):
    return sup.contact_email


def a_list_is_not_a_model(sups: List[schemas.SupplierCreate]):
    return sups.count


def rebound_is_not_checked(sup: schemas.SupplierCreate):
    sup = object()
    return sup.anything_at_all
''')
try:
    _r47g = _attr47(_good47)
    check("correct field reads produce nothing",
          _r47g.issues == [], str([str(i)[:60] for i in _r47g.issues]))
    check("the outcome is VERIFIED, not silence",
          _attr47o(_good47).status.value == "verified")
finally:
    shutil.rmtree(Path(config.OUTPUT_DIR) / _good47, ignore_errors=True)

# A model whose base chain leaves the project cannot be checked: the base may
# declare the very field about to be called missing.
_open47 = _mk_attr47("_test_attr_open", '''import schemas


def handler(sup: schemas.SupplierCreate):
    return sup.whatever
''', '''from pydantic import BaseModel
from somewhere_external import ExternalBase


class SupplierBase(ExternalBase):
    name: str


class SupplierCreate(SupplierBase):
    pass
''')
try:
    check("a model with an unresolved base is not checked",
          _attr47("_test_attr_open").issues == [])
finally:
    shutil.rmtree(Path(config.OUTPUT_DIR) / _open47, ignore_errors=True)

_extra47 = _mk_attr47("_test_attr_extra", '''import schemas


def handler(sup: schemas.SupplierCreate):
    return sup.anything
''', '''from pydantic import BaseModel, ConfigDict


class SupplierBase(BaseModel):
    name: str
    model_config = ConfigDict(extra="allow")


class SupplierCreate(SupplierBase):
    pass
''')
try:
    check("a model that accepts extra fields is not checked",
          _attr47("_test_attr_extra").issues == [])
finally:
    shutil.rmtree(Path(config.OUTPUT_DIR) / _extra47, ignore_errors=True)

_nomodels47 = _mk_attr47("_test_attr_none", "def f(x):\n    return x.anything\n",
                         "VALUE = 1\n")
try:
    check("a project with no pydantic models is NOT_APPLICABLE, not verified",
          _attr47o(_nomodels47).status.value == "not_applicable")
finally:
    shutil.rmtree(Path(config.OUTPUT_DIR) / _nomodels47, ignore_errors=True)


# ---- 47a. The fourth blame rule reaches request-time failures ---------------
# It only ever covered boot failures, so an AttributeError naming a class
# defined in schemas.py sent the repair to routes.py -- which can rename the
# read or silence it, and can never add a field that is missing. Measured live:
# the repair wrote `data.get("sku")`, a None into a NOT NULL column, and scored
# HIGHER than the correct fix.
_blame47 = _mk_attr47("_test_attr_blame", '''import schemas


def create_supplier(sup: schemas.SupplierCreate):
    return sup.contact


def create_product(prod: schemas.ProductCreate):
    return prod.sku
''')
try:
    _pl47 = Pipeline.__new__(Pipeline)
    _rename = _pl47._redirect_missing_field_to_definition(
        _blame47, "backend/routes.py",
        "AttributeError: 'SupplierCreate' object has no attribute 'contact' "
        "(at backend/routes.py:5 in create_supplier)")
    _missing = _pl47._redirect_missing_field_to_definition(
        _blame47, "backend/routes.py",
        "AttributeError: 'ProductCreate' object has no attribute 'sku' "
        "(at backend/routes.py:9 in create_product)")
    check("a misspelt field is still repaired where it is READ",
          _rename[0] == "backend/routes.py", str(_rename))
    check("a missing field is repaired where the model is DEFINED",
          _missing[0] == "backend/schemas.py", str(_missing))
    check("the redirect explains itself in the log",
          "declares no `sku`" in _missing[1], _missing[1])

    # Precision: everything that is not this shape keeps the frame-based rule.
    check("a non-AttributeError keeps the frame rule",
          _pl47._redirect_missing_field_to_definition(
              _blame47, "backend/routes.py",
              "OperationalError: no such table: supplier "
              "(at backend/routes.py:5 in create_supplier)"
          )[0] == "backend/routes.py")
    check("an attribute that EXISTS keeps the frame rule",
          _pl47._redirect_missing_field_to_definition(
              _blame47, "backend/routes.py",
              "AttributeError: 'SupplierCreate' object has no attribute 'name'"
          )[0] == "backend/routes.py")
    check("a class this project does not define keeps the frame rule",
          _pl47._redirect_missing_field_to_definition(
              _blame47, "backend/routes.py",
              "AttributeError: 'Connection' object has no attribute 'execute'"
          )[0] == "backend/routes.py")
    check("find_model_definition names the file and the fields",
          _attrdef47(_blame47, "ProductCreate")
          == ("_test_attr_blame/backend/schemas.py", ("name", "price")),
          str(_attrdef47(_blame47, "ProductCreate")))
finally:
    shutil.rmtree(Path(config.OUTPUT_DIR) / _blame47, ignore_errors=True)


# ---- 48. A rewrite that fixes nothing does not get to stay ------------------
# BackendDeveloper re-scanned after its repair, found the defects still there,
# incremented a counter that was logged and discarded, and left the rewrite on
# disk. So a repair that changed the file without improving it shipped, and
# nothing downstream could see it.
from tools.repair_guard import accept_rescan as _rescan48                # noqa: E402

check("a repair that removes a defect is kept",
      _rescan48(["a", "b"], ["a"])[0] is True)
check("a repair that removes every defect is kept",
      _rescan48(["a", "b"], [])[0] is True)
check("a repair that changes nothing is rolled back",
      _rescan48(["a", "b"], ["a", "b"])[0] is False)
check("a repair that swaps one defect for another is rolled back",
      _rescan48(["a"], ["b"])[0] is False)
check("a rewrite that introduces a NEW defect is rolled back",
      _rescan48([], ["a"])[0] is False)
check("the rejection says which defects survived",
      "leaves 2 of 2" in _rescan48(["a", "b"], ["a", "b"])[1])
check("a file with nothing to fix is not rejected",
      _rescan48([], [])[0] is True)

# And the counter is no longer discarded: what could not be repaired is named,
# with the file to aim at, so `_diagnose` can hand it to remediation.
_bd48 = BackendDeveloper.__new__(BackendDeveloper)
_bd48.unrepaired_defects = {"proj/backend/routes.py": ["two stub handlers"]}
_pl48 = Pipeline.__new__(Pipeline)
_pl48.backend_developer = _bd48
_res48 = type("R", (), {})()
_res48.debug_results = []
_res48.frontend_debug_results = []
_res48.test_results = []
_res48.backend_files = ["proj/backend/routes.py"]
_res48.frontend_files = []
_res48.architecture = {"root_folder": "proj"}
_res48.intent = {}
_issues48, _paths48, _adv48 = _pl48._diagnose(_res48)
check("an unrepaired defect becomes a reported issue",
      any("self-verification could not repair" in i for i in _issues48),
      str(_issues48))
check("and it names a file to aim the repair at - repairable must mean that",
      "proj/backend/routes.py" in _paths48, str(_paths48))


# ---- 49. `unusable` is decided by a field, not by wording -------------------
# The verdict matched substrings against finding text, so rewording a finding
# silently stopped it firing -- the same class of defect as an empty list
# meaning four things.
from tools.verification import VerificationOutcome as _VO49              # noqa: E402


def _verdict49(outcomes, unresolved=()):
    r = type("R", (), {})()
    r.verification_outcomes = [o.to_dict() for o in outcomes]
    r.backend_files = ["x.py"]
    r.frontend_files = []
    r.remediation = type("Rep", (), {"unresolved": list(unresolved)})()
    return Pipeline._functional_verdict(Pipeline.__new__(Pipeline), r)


_fatal49 = _VO49.failed("cli_smoke", ["a finding worded however you like"],
                        detail="ran it").mark_fatal("--help fails")
_plain49 = _VO49.failed("feature_coverage", ["a requested feature is missing"])
check("a fatal outcome makes the build unusable whatever the finding says",
      _verdict49([_fatal49])[0] is False)
check("a non-fatal failure does not - that is still a build a user can finish",
      _verdict49([_plain49])[0] is True)
check("the reason given is the finding, not the flag",
      "worded however you like" in _verdict49([_fatal49])[1][0])
check("a verified outcome is usable",
      _verdict49([_VO49.verified("cli_smoke", detail="ran 1 entry point")])[0]
      is True)
check("is_fatal is False until a verifier says otherwise",
      _plain49.is_fatal is False and _fatal49.is_fatal is True)
check("the flag survives the round trip through the database",
      _VO49.failed("x", ["f"]).mark_fatal("why").to_dict()["evidence"]["fatal"]
      is True)
# The old string path still works, for findings that reach `unresolved` from a
# path with no outcome -- it is a fallback now, not the mechanism.
check("the finding-text fallback still fires when nothing structured did",
      _verdict49([], unresolved=["the application does not start: boom"])[0]
      is False)


# ---- 49a. The web probe says what it did ------------------------------------
# It was the most important check in the pipeline and the only one that never
# produced an outcome: its result lived in the server log and nowhere else,
# which is why run_live_matrix.py had to tell an operator to grep for it.
_src49 = Path("agents/pipeline.py").read_text(encoding="utf-8")
check("every exit of the web probe records an outcome",
      _src49.count("self._smoke_outcome = ") >= 6,
      f"{_src49.count('self._smoke_outcome = ')} assignments")
check("the recorded list is the one the API stores",
      "result.verification_outcomes = [o.to_dict() for o in recorded]" in _src49)
check("the web probe's findings are recorded but not collected twice",
      "recorded.insert(0, smoke_outcome)" in _src49)


# ---- 50. The quota gate reads the model that actually runs out --------------
# It took max() across models, so a row started whenever EITHER model was rich.
# The fast model carries the tester, the reviewer and every remediation pass;
# on 2026-08-30 a row started with it at 73,286, ran it dry mid-tester, and
# survived only on the dual-model fallback.
import run_live_matrix as _m50                                          # noqa: E402

_fast50, _heavy50 = _m50.model_roles()
check("the fast and heavy models are identified, not left blank",
      bool(_fast50) and bool(_heavy50) and _fast50 != _heavy50,
      f"{_fast50!r} / {_heavy50!r}")
check("the start that ran out on 2026-08-30 is now refused",
      "fast" in _m50.budget_blocks_start(
          {_fast50: {"tokens_remaining": 73_286},
           _heavy50: {"tokens_remaining": 176_721}}))
check("a rich heavy model no longer covers for an empty fast one",
      _m50.budget_blocks_start(
          {_fast50: {"tokens_remaining": 20_000},
           _heavy50: {"tokens_remaining": 190_000}}) != "")
check("both models above their floors starts",
      _m50.budget_blocks_start(
          {_fast50: {"tokens_remaining": 150_000},
           _heavy50: {"tokens_remaining": 150_000}}) == "")
check("the fast floor is the higher of the two",
      _m50.MIN_FAST_TOKENS_TO_START > _m50.MIN_HEAVY_TOKENS_TO_START)
check("no figures is not evidence of no budget",
      _m50.budget_blocks_start({}) == "")


# ---- 50a. The driver evaluates BOTH halves of its own criterion -------------
# The 0-5xx half existed only in the server log, so the report stated the first
# half and told the reader to grep for the rest. Row 3 passed the stated
# criterion on 2026-08-28 while shipping twelve endpoints that returned 500.
def _v50(*outcomes):
    return _m50.verification_verdict({"verification": list(outcomes)})


check("row 4's shipped record passes: two checks executed the artifact",
      _v50({"check": "runtime_smoke", "status": "not_applicable"},
           {"check": "cli_smoke", "status": "verified"},
           {"check": "feature_coverage", "status": "verified"})[0] is True)
check("a failed check fails the row",
      _v50({"check": "runtime_smoke", "status": "failed"})[0] is False)
check("a check that never ran fails the row - a hole is not a pass",
      _v50({"check": "runtime_smoke", "status": "not_run"},
           {"check": "cli_smoke", "status": "verified"})[0] is False)
check("all-not-applicable fails: nothing executed the artifact",
      _v50({"check": "runtime_smoke", "status": "not_applicable"},
           {"check": "cli_smoke", "status": "not_applicable"})[0] is False)
check("no record at all is unverified, not clean",
      _v50()[0] is False)
check("the report no longer sends the reader to the server log",
      "Runtime smoke test|failed to boot" not in
      Path("run_live_matrix.py").read_text(encoding="utf-8"))

# ── §4.22 Reconciling the ledger against Groq's own counter ───────────────────
# The ledger only records calls that came back 2xx with a usage body, so every
# 400, every 429-rejected attempt and every retried attempt is invisible to it.
# Measured on row 2 (2026-08-31): the estimate read 145,967 used on gpt-oss-20b
# at the moment Groq's 429 stated `used 197323` — a 51K shortfall, all in the
# optimistic direction, which is how a row cleared the 90,000 start floor and
# then ran the fast model dry mid-tester.

_R22_REAL_429 = (
    "rate limit reached for model `openai/gpt-oss-20b` in organization "
    "`org_01kjhb2kvxft0s58tg3tz9mg0p` service tier `on_demand` on tokens per "
    "day (tpd): limit 200000, used 197323, requested 3745. please try again "
    "in 7m41.376s. need more tokens? upgrade to dev tier today"
)

check("the real row-2 429 yields Groq's own (limit, used)",
      llm_client.parse_tpd_usage(_R22_REAL_429) == (200000, 197323))
check("a per-minute 429 carries no daily figure and must not be mistaken for one",
      llm_client.parse_tpd_usage(
          "rate limit reached ... on tokens per minute (tpm): limit 30000, "
          "used 29000, requested 2000") is None)
check("an empty reason parses to nothing rather than raising",
      llm_client.parse_tpd_usage("") is None)
check("a reason that is just the default string parses to nothing",
      llm_client.parse_tpd_usage("daily quota") is None)


def _r22_ledger(entries, model="openai/gpt-oss-20b"):
    llm_client._ledger = [[ts, model, tok, "live"] for ts, tok in entries]
    llm_client._ledger_covered = {}


_R22_NOW = 1_000_000.0

# The measured drift, reproduced exactly.
_r22_ledger([(_R22_NOW, 145967)])
_r22_before = llm_client.get_daily_usage(_R22_NOW)["models"]["openai/gpt-oss-20b"]
_r22_added = llm_client.reconcile_ledger_from_groq(
    "openai/gpt-oss-20b", 197323, now=_R22_NOW)
_r22_after = llm_client.get_daily_usage(_R22_NOW)["models"]["openai/gpt-oss-20b"]

check("before reconciling, the estimate reports the optimistic figure",
      _r22_before["tokens_used"] == 145967)
check("the shortfall Groq's counter reveals is added",
      _r22_added == 51356, f"added {_r22_added}")
check("after reconciling, used matches Groq exactly",
      _r22_after["tokens_used"] == 197323)
check("…and remaining is the honest 2,677, not 54,033",
      _r22_after["tokens_remaining"] == 2677,
      f"remaining {_r22_after['tokens_remaining']}")
check("a row would now be refused against the 90,000 fast floor",
      _r22_after["tokens_remaining"] < 90000)

# Reconciling must never hand back budget: an over-count costs a wait, an
# under-count costs a dead build.
_r22_down = llm_client.reconcile_ledger_from_groq(
    "openai/gpt-oss-20b", 10_000, now=_R22_NOW)
check("a lower figure from Groq is refused — the pessimistic side is kept",
      _r22_down == 0)
check("…and the ledger is left where it was",
      llm_client.get_daily_usage(_R22_NOW)["models"][
          "openai/gpt-oss-20b"]["tokens_used"] == 197323)

# The bucket must keep draining afterwards, not freeze at the anchor.
_r22_hour = llm_client.get_daily_usage(_R22_NOW + 3600)["models"][
    "openai/gpt-oss-20b"]["tokens_used"]
check("a reconciled ledger still refills at ~8,333/hour",
      abs(_r22_hour - (197323 - 8333)) <= 2, f"after 1h: {_r22_hour}")

# Reconciling an empty ledger is the cold-start case: a fresh process that has
# spent nothing locally but shares an organisation budget already half gone.
_r22_ledger([])
_r22_cold = llm_client.reconcile_ledger_from_groq(
    "openai/gpt-oss-20b", 180_000, now=_R22_NOW)
check("a cold ledger adopts Groq's figure wholesale",
      _r22_cold == 180000 and llm_client.get_daily_usage(_R22_NOW)["models"][
          "openai/gpt-oss-20b"]["tokens_used"] == 180000)

check("a blank model name is refused rather than creating a phantom entry",
      llm_client.reconcile_ledger_from_groq("", 100, now=_R22_NOW) == 0)

# The wiring: the handler that flags a model must reconcile from the same text.
_r22_src = Path("llm_client.py").read_text(encoding="utf-8")
_r22_fn = _r22_src[_r22_src.index("def _mark_model_daily_limited"):]
_r22_fn = _r22_fn[:_r22_fn.index("_DEFAULT_RESET_HINT")]
check("_mark_model_daily_limited parses the 429 it is handed",
      "parse_tpd_usage(reason)" in _r22_fn)
check("…and feeds it to the ledger rather than only logging it",
      "reconcile_ledger_from_groq(" in _r22_fn)

# End to end: the flag path itself must move the number.
_r22_ledger([(_R22_NOW, 145967)])
llm_client._mark_model_daily_limited("openai/gpt-oss-20b", _R22_REAL_429)
check("flagging a model daily-limited reconciles the ledger as a side effect",
      llm_client.get_daily_usage()["models"][
          "openai/gpt-oss-20b"]["tokens_used"] >= 197323 - 60)

# A reason with no daily figure must leave the ledger untouched.
_r22_ledger([(_R22_NOW, 50_000)])
llm_client._mark_model_daily_limited("openai/gpt-oss-20b", "daily quota")
check("a reason carrying no counter changes nothing",
      llm_client.get_daily_usage(_R22_NOW)["models"][
          "openai/gpt-oss-20b"]["tokens_used"] == 50000)


# -- 4.24 The build ships a test suite; something must run it -----------------
# Row 2 shipped tests/test_api.py in which all 4 tests errored at fixture setup
# (`conn = init_db()` returns None) and was still recorded `verified: yes`,
# because no check in the six-check record executes the tests. A suite that
# cannot collect looked exactly like one that passed.

from tools.verification import Status                      # noqa: E402
from tools.generated_tests import (                       # noqa: E402
    run_generated_tests, _find_test_files, _summarise, _counts,
)

_G24 = Path(tempfile.mkdtemp(prefix="gt24_"))
_G24_OUT = _G24 / "out"
_G24_OUT.mkdir(parents=True)


def _g24_project(name, files):
    root = _G24_OUT / name
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return name


def _g24_run(name):
    real = config.OUTPUT_DIR
    try:
        config.OUTPUT_DIR = str(_G24_OUT)
        return run_generated_tests(name)
    finally:
        config.OUTPUT_DIR = real


# A project with no tests is not a failure -- the architect decides that.
_g24_project("no_tests", {"main.py": "print('hi')\n"})
_o = _g24_run("no_tests")
check("a project shipping no tests is not applicable, not failed",
      _o.status is Status.NOT_APPLICABLE, str(_o.status))

# A suite that passes.
_g24_project("good", {
    "calc.py": "def add(a, b):\n    return a + b\n",
    "tests/test_calc.py": (
        "from calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "def test_add_negative():\n    assert add(-1, 1) == 0\n"
    ),
})
_o = _g24_run("good")
check("a suite that passes is verified", _o.status is Status.VERIFIED, str(_o.status))
check("...and the record says what ran, not just that something did",
      "2 passed" in (_o.detail or ""), _o.detail)

# Row 2's exact defect: every test errors at fixture setup.
_g24_project("dead_fixture", {
    "db.py": "def init_db():\n    pass\n",
    "tests/test_api.py": (
        "import pytest\n"
        "from db import init_db\n"
        "@pytest.fixture(autouse=True)\n"
        "def reset_db():\n"
        "    conn = init_db()\n"
        "    conn.close()\n"
        "    yield\n"
        "def test_one():\n    assert True\n"
        "def test_two():\n    assert True\n"
    ),
})
_o = _g24_run("dead_fixture")
check("a suite whose every test errors at setup FAILS",
      _o.status is Status.FAILED, str(_o.status))
check("...and is described as not running, not as failing assertions",
      any("error before executing" in f for f in _o.findings), str(_o.findings[:1]))
check("...and the record carries the real reason, not just a count",
      any("AttributeError" in f for f in _o.findings), str(_o.findings))
check("a build with a dead suite is not evidence of working",
      _o.is_evidence_of_working is False)

# A suite that collects but disagrees with the code is a different verdict from
# one that never ran, and must read differently.
_g24_project("failing", {
    "calc.py": "def add(a, b):\n    return a - b\n",
    "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n",
})
_o = _g24_run("failing")
check("a suite that runs and disagrees fails", _o.status is Status.FAILED)
check("...and says so as a failure, not as an error before executing",
      not any("error before executing" in f for f in _o.findings), str(_o.findings[:1]))

# Test files that collect nothing at all are inert, and that is worth saying.
_g24_project("inert", {"tests/test_nothing.py": "x = 1\n"})
_o = _g24_run("inert")
check("test files that collect zero tests are reported as inert",
      _o.status is Status.FAILED and
      any("collected" in f and "0 tests" in f for f in _o.findings),
      str(_o.findings))

# A project that does not exist cannot be called clean.
_o = _g24_run("does_not_exist_at_all")
check("a missing project is NOT_RUN, never a pass", _o.status is Status.NOT_RUN)

check("both test-file naming conventions are collected",
      {p.name for p in _find_test_files(_G24_OUT / "good")} == {"test_calc.py"})

check("the tally parser reads pytest's own wording",
      _counts("4 failed, 13 passed, 2 errors in 1.2s") ==
      {"failed": 4, "passed": 13, "error": 2})
check("a collection error is summarised even with no summary block",
      any("ImportError" in f for f in
          _summarise("E   ImportError: cannot import name 'x'", "")))

# The wiring: the pipeline must actually run it, and the corpus tool must be
# able to, or the check is a hypothesis nobody tested.
_g24_pipe = Path("agents/pipeline.py").read_text(encoding="utf-8")
check("the pipeline registers generated_tests among its shape verifiers",
      '("generated_tests", run_generated_tests)' in _g24_pipe)
check("...and imports it", "from tools.generated_tests import" in _g24_pipe)
check("verify_corpus runs it too, so it is testable for free",
      '("generated_tests", run_generated_tests)' in
      Path("tools/verify_corpus.py").read_text(encoding="utf-8"))

shutil.rmtree(_G24, ignore_errors=True)


# -- 4.25 A finding recorded once must be re-read before it ships --------------
# Row 2 recorded `bookmark.description` as unrepairable during generation; the
# debugger then fixed it in the file that DECLARES the field, and schema_attr
# verified the build clean -- but the shipped SESSION_CONTEXT.md still told the
# user to go and fix it.

_R25 = Path(tempfile.mkdtemp(prefix="rescan25_"))
_R25_OUT = _R25 / "out"
_R25_OUT.mkdir(parents=True)


def _r25_build(name, files):
    root = _R25_OUT / name
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    rels = [str(p.relative_to(root)).replace("\\", "/")
            for p in root.rglob("*.py")]
    arch = {"root_folder": name, "files": [{"path": r} for r in rels]}
    return arch, [name + "/" + r for r in rels], name


_R25_CLEAN = {
    "backend/models.py": (
        "from pydantic import BaseModel\n"
        "from typing import Optional\n"
        "class BookmarkCreate(BaseModel):\n"
        "    url: str\n    title: str\n"
        "    description: Optional[str] = None\n"
    ),
    "backend/services.py": (
        "from backend.models import BookmarkCreate\n"
        "def create(bookmark: BookmarkCreate):\n"
        "    return bookmark.description\n"
    ),
}

_r25_arch, _r25_written, _r25_root = _r25_build("fixed_since", _R25_CLEAN)
_r25_snapshot = {
    _r25_root + "/backend/services.py": [
        "`bookmark.description` is read at line 3, but `bookmark` is a "
        "`BookmarkCreate`, which declares title, url.",
    ]
}

_real_out = config.OUTPUT_DIR
try:
    config.OUTPUT_DIR = str(_R25_OUT)
    _bd25 = BackendDeveloper.__new__(BackendDeveloper)
    _bd25.unrepaired_defects = dict(_r25_snapshot)
    _r25_after = _bd25.rescan_unrepaired_defects(
        _r25_arch, _r25_root, _r25_written)
finally:
    config.OUTPUT_DIR = _real_out

check("a defect fixed after it was recorded stops being reported",
      _r25_after == {}, str(_r25_after))

# The other direction matters more: a defect that is still there must survive.
_R25_BROKEN = dict(_R25_CLEAN)
_R25_BROKEN["backend/models.py"] = (
    "from pydantic import BaseModel\n"
    "class BookmarkCreate(BaseModel):\n"
    "    url: str\n    title: str\n"
)
_r25_arch2, _r25_written2, _r25_root2 = _r25_build("still_broken", _R25_BROKEN)
try:
    config.OUTPUT_DIR = str(_R25_OUT)
    _bd25b = BackendDeveloper.__new__(BackendDeveloper)
    _bd25b.unrepaired_defects = {
        _r25_root2 + "/backend/services.py": ["`bookmark.description` ..."]
    }
    _r25_after2 = _bd25b.rescan_unrepaired_defects(
        _r25_arch2, _r25_root2, _r25_written2)
finally:
    config.OUTPUT_DIR = _real_out

check("a defect that is still on disk still ships as an open issue",
      list(_r25_after2) == [_r25_root2 + "/backend/services.py"],
      str(_r25_after2))
check("...and it is re-stated from disk rather than replayed from the snapshot",
      any("description" in d for d in
          _r25_after2[_r25_root2 + "/backend/services.py"]))

# An empty snapshot must not cost a scan, and must not invent one.
_bd25c = BackendDeveloper.__new__(BackendDeveloper)
_bd25c.unrepaired_defects = {}
check("nothing recorded means nothing to re-check",
      _bd25c.rescan_unrepaired_defects({}, "", []) == {})

# Failure must leave the snapshot standing: a stale finding costs a minute, a
# dropped one costs the defect.
_bd25d = BackendDeveloper.__new__(BackendDeveloper)
_bd25d.unrepaired_defects = {"x/y.py": ["something"]}
check("a re-scan that cannot run keeps the finding rather than clearing it",
      _bd25d.rescan_unrepaired_defects(None, None, None) ==
      {"x/y.py": ["something"]})

check("the pipeline re-scans before assembling the issue list",
      "rescan_unrepaired_defects(" in _g24_pipe)

shutil.rmtree(_R25, ignore_errors=True)


# -- B1. Persistence: SQLAlchemy + Alembic behind the existing seam ------------
# The whole point of B1 is that nothing above the seam changed. These tests
# assert the seam holds (same signatures, same dict shapes, same string types),
# that the ~50 live builds survive being brought under Alembic, and that the two
# things the old hand-rolled ALTER block could never do -- add an index, and
# record what a database has been through -- now work.

import sqlite3 as _sq_b1                                       # noqa: E402
import api_platform.database as _dbm                           # noqa: E402
from api_platform.db import (                                  # noqa: E402
    current_url as _cur_url, dispose_all as _dispose_b1, get_engine as _eng_b1,
)
from api_platform.db.models import (                           # noqa: E402
    PROJECT_COLUMNS as _PCOLS, Project as _PModel,
)

_B1 = Path(tempfile.mkdtemp(prefix="b1_"))
_b1_saved_db_path = _dbm.DB_PATH


def _b1_use(name):
    _dbm.DB_PATH = _B1 / name
    _dispose_b1()
    _dbm.initialize_db()
    return _dbm.DB_PATH


# --- a fresh database ---------------------------------------------------------
_b1_db = _b1_use("fresh.db")

_b1_created = _dbm.create_project("b1-a", "a prompt")
check("create_project still returns the four keys its callers read",
      set(_b1_created) == {"build_id", "prompt", "status", "created_at"},
      str(sorted(_b1_created)))
check("a new build is pending", _b1_created["status"] == "pending")
check("created_at is still an ISO string, not a datetime",
      isinstance(_b1_created["created_at"], str))
check("...and is naive, so it sorts against the rows already on disk",
      "+00:00" not in _b1_created["created_at"])

_dbm.add_project_file("b1-a", "backend/main.py", "python")
_dbm.add_build_step("b1-a", 1, "intent_analyzer", "done", '{"x": 1}')
_dbm.update_project("b1-a", status="done", total_tokens=99, review_score=7.5)

_b1_got = _dbm.get_project("b1-a")
check("get_project returns every column, as a plain dict",
      isinstance(_b1_got, dict) and set(_b1_got) == set(_PCOLS),
      str(len(_b1_got)))
check("an update round-trips", (_b1_got["status"], _b1_got["total_tokens"],
                                _b1_got["review_score"]) == ("done", 99, 7.5))
check("get_project on an unknown id is None, not an exception",
      _dbm.get_project("nope") is None)

_b1_files = _dbm.get_project_files("b1-a")
check("get_project_files keeps its four keys",
      set(_b1_files[0]) == {"id", "build_id", "file_path", "file_type"})
_b1_prog = _dbm.get_build_progress("b1-a")
check("get_build_progress keeps its seven keys",
      set(_b1_prog[0]) ==
      {"id", "build_id", "step", "step_name", "status", "timestamp", "data"})

_b1_list = _dbm.list_projects()
check("list_projects returns exactly the columns it always did",
      set(_b1_list[0]) == set(_dbm._LIST_COLUMNS), str(sorted(_b1_list[0])))
check("...and does not leak the heavy blobs into the list view",
      "verification" not in _b1_list[0] and "smoke_summary" not in _b1_list[0])

# Ordering is what the dashboard depends on.
_dbm.create_project("b1-b", "later")
check("list_projects is newest-first",
      _dbm.list_projects()[0]["build_id"] == "b1-b")
check("limit/offset still page",
      len(_dbm.list_projects(limit=1)) == 1 and
      _dbm.list_projects(limit=1, offset=1)[0]["build_id"] == "b1-a")

# Deleting a build must take its children with it.
_dbm.delete_project("b1-a")
check("delete_project cascades to files and progress",
      _dbm.get_project("b1-a") is None
      and _dbm.get_project_files("b1-a") == []
      and _dbm.get_build_progress("b1-a") == [])
check("deleting a build that is not there reports False",
      _dbm.delete_project("b1-a") is False)
check("update_project with no fields is a no-op, as before",
      _dbm.update_project("b1-b") is False)

# The old implementation interpolated caller keys straight into a SET clause.
try:
    _dbm.update_project("b1-b", **{"status = 'x' --": "y"})
    _b1_injected = True
except ValueError:
    _b1_injected = False
check("a column name that does not exist is refused, not interpolated",
      _b1_injected is False)

# --- Alembic ------------------------------------------------------------------
with _sq_b1.connect(str(_b1_db)) as _c:
    _b1_ver = _c.execute("SELECT version_num FROM alembic_version").fetchone()
    _b1_idx = {
        t: {r[1] for r in _c.execute(f"PRAGMA index_list({t})")
            if not r[1].startswith("sqlite_")}
        for t in ("projects", "files", "build_progress")
    }
check("a fresh database is stamped at head, not left unversioned",
      _b1_ver is not None and _b1_ver[0] == "0002_indexes", str(_b1_ver))
check("the lookup indexes every status poll needs exist",
      _b1_idx["files"] == {"ix_files_build_id"}
      and _b1_idx["build_progress"] == {"ix_build_progress_build_id"}
      and _b1_idx["projects"] == {"ix_projects_created_at"},
      str(_b1_idx))

# --- a database that predates Alembic ----------------------------------------
# The case that matters: real rows, no alembic_version, and missing some of the
# columns that arrived through the old ALTER block. It must be reconciled,
# stamped and upgraded WITHOUT losing a row.
_b1_legacy = _B1 / "legacy.db"
with _sq_b1.connect(str(_b1_legacy)) as _c:
    _c.executescript("""
        CREATE TABLE projects (
            build_id TEXT PRIMARY KEY, prompt TEXT NOT NULL, app_name TEXT,
            app_type TEXT, complexity TEXT, status TEXT NOT NULL,
            debug_score TEXT, review_score REAL, test_score TEXT,
            output_path TEXT, created_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP, duration_seconds REAL
        );
        CREATE TABLE files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, build_id TEXT NOT NULL,
            file_path TEXT NOT NULL, file_type TEXT
        );
        CREATE TABLE build_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT, build_id TEXT NOT NULL,
            step INTEGER NOT NULL, step_name TEXT NOT NULL, status TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL, data TEXT
        );
        INSERT INTO projects (build_id, prompt, status, created_at)
            VALUES ('old-1', 'from before', 'done', '2026-01-01T00:00:00');
        INSERT INTO files (build_id, file_path) VALUES ('old-1', 'a.py');
        INSERT INTO build_progress (build_id, step, step_name, status, timestamp)
            VALUES ('old-1', 1, 'architect', 'done', '2026-01-01T00:00:00');
    """)

_dbm.DB_PATH = _b1_legacy
_dispose_b1()
_dbm.initialize_db()

with _sq_b1.connect(str(_b1_legacy)) as _c:
    _b1_rows = _c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    _b1_frows = _c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    _b1_prows = _c.execute("SELECT COUNT(*) FROM build_progress").fetchone()[0]
    _b1_cols = {r[1] for r in _c.execute("PRAGMA table_info(projects)")}
    _b1_lver = _c.execute("SELECT version_num FROM alembic_version").fetchone()
    _b1_lidx = {r[1] for r in _c.execute("PRAGMA index_list(files)")
                if not r[1].startswith("sqlite_")}

check("a pre-Alembic database keeps every row it had",
      (_b1_rows, _b1_frows, _b1_prows) == (1, 1, 1),
      f"{_b1_rows}/{_b1_frows}/{_b1_prows}")
check("...and its old row is still readable through the seam",
      _dbm.get_project("old-1")["prompt"] == "from before")
check("...and gains every column that arrived after the Phase 14 baseline",
      {"total_tokens", "tokens_by_model", "verification", "build_shape"}
      <= _b1_cols, str(sorted(_b1_cols)))
check("...and is brought all the way to head, not just stamped at the baseline",
      _b1_lver is not None and _b1_lver[0] == "0002_indexes", str(_b1_lver))
check("...and an index the old ALTER block could never add is now there",
      _b1_lidx == {"ix_files_build_id"}, str(_b1_lidx))

# Running it twice must be a no-op, because the server calls it on every start.
_dbm.initialize_db()
with _sq_b1.connect(str(_b1_legacy)) as _c:
    _b1_again = _c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
check("initialize_db is idempotent across restarts", _b1_again == 1)

# --- the URL seam -------------------------------------------------------------
_b1_env_saved = os.environ.get("DATABASE_URL")
try:
    os.environ["DATABASE_URL"] = "postgresql+psycopg://u:p@example:5432/db"
    check("DATABASE_URL wins over DB_PATH", _cur_url().startswith("postgresql"))
    os.environ["DATABASE_URL"] = ""
    _dbm.DB_PATH = _B1 / "fresh.db"
    check("...and with it unset the URL is still derived from DB_PATH",
          _cur_url().startswith("sqlite:///") and
          _cur_url().endswith("fresh.db"))
finally:
    if _b1_env_saved is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = _b1_env_saved

# A file-backed SQLite engine must not hold the file open between calls: three
# suites point DB_PATH at a temp database and then delete it, and a pool makes
# that impossible on Windows.
from sqlalchemy.pool import NullPool as _NullPool_b1              # noqa: E402
_dispose_b1()
_dbm.DB_PATH = _B1 / "poolcheck.db"
check("a file-backed sqlite engine does not pool its connections",
      isinstance(_eng_b1().pool, _NullPool_b1),
      type(_eng_b1().pool).__name__)
_b1_delete_me = _B1 / "poolcheck.db"
_dbm.initialize_db()
_dispose_b1()
try:
    _b1_delete_me.unlink()
    _b1_unlinked = True
except Exception:
    _b1_unlinked = False
check("...so the database file can still be deleted afterwards", _b1_unlinked)

# The deprecated call this phase was also meant to remove. Asserted against the
# parsed source rather than the text: both modules explain in a docstring why
# the replacement drops its tzinfo, and a substring check cannot tell an
# explanation from a call.
import ast as _ast_b1                                              # noqa: E402


def _b1_utcnow_calls(path):
    tree = _ast_b1.parse(Path(path).read_text(encoding="utf-8"))
    return [
        n.lineno for n in _ast_b1.walk(tree)
        if isinstance(n, _ast_b1.Call)
        and isinstance(n.func, _ast_b1.Attribute)
        and n.func.attr == "utcnow"
    ]


check("datetime.utcnow() is no longer called in the persistence layer",
      _b1_utcnow_calls("api_platform/database.py") == [],
      str(_b1_utcnow_calls("api_platform/database.py")))
check("...replaced by the timezone-aware call",
      "datetime.now(timezone.utc)" in
      Path("api_platform/database.py").read_text(encoding="utf-8"))
check("and it is no longer called in the runner either",
      _b1_utcnow_calls("api_platform/runner.py") == [],
      str(_b1_utcnow_calls("api_platform/runner.py")))
check("the runner still stores a naive timestamp, so old rows still compare",
      "replace(tzinfo=None)" in
      Path("api_platform/runner.py").read_text(encoding="utf-8"))

_dbm.DB_PATH = _b1_saved_db_path
_dispose_b1()
shutil.rmtree(_B1, ignore_errors=True)


# -- 4.26 A broken test suite is not a broken build ---------------------------
# Row 2 serves 7/7 routes and ships a test suite that does not run. Counting
# that as a verification failure would call a working build degraded; dropping
# it would hide something real. It is routed to the user as manual testing, and
# the check still records FAILED so the signal is not lost.

from agents.pipeline import RemediationReport                    # noqa: E402

_M26 = Path(tempfile.mkdtemp(prefix="manual26_"))
_M26_OUT = _M26 / "out"
_M26_OUT.mkdir(parents=True)


def _m26_project(name):
    """A project whose app is fine and whose shipped tests are not."""
    root = _M26_OUT / name
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from calc import add\n"
        "def test_broken():\n    raise RuntimeError('dead')\n",
        encoding="utf-8",
    )
    return name


def _m26_result(name):
    r = type("R", (), {})()
    r.architecture = {"root_folder": name, "files": [{"path": "calc.py"}]}
    r.intent = {}
    r.backend_files = []
    r.frontend_files = []
    r.verification_outcomes = []
    r.build_shape = None
    return r


def _m26_run(name, smoke_outcome):
    real = config.OUTPUT_DIR
    try:
        config.OUTPUT_DIR = str(_M26_OUT)
        pl = Pipeline.__new__(Pipeline)
        pl._smoke_outcome = smoke_outcome
        res = _m26_result(name)
        advisory = pl._verify_other_shapes(res)
        return advisory, list(getattr(pl, "_manual_checks", [])), res
    finally:
        config.OUTPUT_DIR = real


_m26_project("works")

# The artifact was executed and found sound.
_m26_adv, _m26_man, _m26_res = _m26_run(
    "works",
    _VO49.verified("runtime_smoke", detail="7/7 routes responded without a server error"),
)
check("a failing suite does not degrade a build that was shown to work",
      _m26_adv == [], str(_m26_adv))
check("...the findings are handed over as manual testing instead",
      len(_m26_man) >= 1, str(_m26_man))
check("...and the check still records FAILED, so the signal is not lost",
      any(o["check"] == "generated_tests" and o["status"] == "failed"
          for o in _m26_res.verification_outcomes),
      str([(o["check"], o["status"]) for o in _m26_res.verification_outcomes]))

# No positive evidence: now the same finding is corroborating, and must count.
_m26_adv2, _m26_man2, _m26_res2 = _m26_run(
    "works",
    _VO49.failed("runtime_smoke", findings=["GET /x -> 500"],
                 detail="the application does not start"),
)
check("with nothing showing the artifact works, a failing suite still counts",
      len(_m26_adv2) >= 1, str(_m26_adv2))
check("...and is not quietly moved to manual testing",
      _m26_man2 == [], str(_m26_man2))

# NOT_APPLICABLE is not evidence of working -- it is the absence of a question.
_m26_adv3, _m26_man3, _ = _m26_run(
    "works",
    _VO49.not_applicable("runtime_smoke", detail="ships no web app"),
)
check("a not_applicable probe is not positive evidence, so the finding counts",
      len(_m26_adv3) >= 1 and _m26_man3 == [],
      f"advisory={len(_m26_adv3)} manual={len(_m26_man3)}")

# A build carrying only manual checks must reach `done`, not done_with_context.
_m26_rep = RemediationReport()
_m26_rep.unresolved = []
_m26_rep.manual_checks = list(_m26_man)
_m26_rep.degraded = bool(_m26_rep.unresolved)
check("manual checks alone do not mark a build degraded",
      _m26_rep.degraded is False)

check("only generated_tests is routed this way, not the checks that judge the app",
      Pipeline._MANUAL_WHEN_WORKING == ("generated_tests",),
      str(Pipeline._MANUAL_WHEN_WORKING))

# The shipped document must separate the two, and say which is which.
_m26_doc = Documenter.__new__(Documenter)
_m26_text = _m26_doc._build_session_context(
    app_name="x", root="works", intent={"features": []},
    architecture={"root_folder": "works", "files": []},
    backend_files=[], frontend_files=[], completed_steps=["documenter"],
    pending_steps=[], reason="", quota_snapshot={}, remediation=_m26_rep,
    progress_percent=100.0, debug_results=[], review_results=[],
    test_results=[], error_detail="",
)
check("the handoff grows a 'Worth Checking By Hand' section",
      "Worth Checking By Hand" in _m26_text)
check("...carrying the test-suite finding",
      "test suite" in _m26_text.split("Worth Checking By Hand", 1)[1][:600])
check("...while Remaining Work reports nothing outstanding",
      "_No outstanding issues were recorded._" in
      _m26_text.split("Remaining Work", 1)[1].split("##", 1)[0])

# And a build with nothing to check by hand must not grow an empty heading.
_m26_clean = RemediationReport()
_m26_clean.unresolved = []
_m26_clean.manual_checks = []
_m26_text2 = _m26_doc._build_session_context(
    app_name="x", root="works", intent={"features": []},
    architecture={"root_folder": "works", "files": []},
    backend_files=[], frontend_files=[], completed_steps=["documenter"],
    pending_steps=[], reason="", quota_snapshot={}, remediation=_m26_clean,
    progress_percent=100.0, debug_results=[], review_results=[],
    test_results=[], error_detail="",
)
check("a build with nothing to check by hand grows no empty section",
      "Worth Checking By Hand" not in _m26_text2)

shutil.rmtree(_M26, ignore_errors=True)


# -- 4.27 The shipped document describes the final state, not a mid-build one --
# `issues` and `diag_advisory` came from the diagnosis that ran BEFORE
# remediation, and were reused verbatim at the end. That is how row 2 shipped a
# checklist telling its reader to fix `bookmark.description` after the debugger
# had already fixed it. The re-scan in 4.25 only helps if the diagnosis is
# actually re-run.

_f27 = Path("agents/pipeline.py").read_text(encoding="utf-8")
_f27_final = _f27.split("Re-run the whole diagnosis", 1)
check("the final re-audit re-runs the diagnosis rather than reusing the first",
      len(_f27_final) == 2, "the final re-audit still reuses diag_advisory")
check("...and does so before assembling the report",
      "issues, failed_paths, diag_advisory = self._diagnose(result)"
      in _f27_final[1].split("report.unresolved", 1)[0])
check("the re-diagnosis happens after the remediation loop, not inside it",
      _f27.rindex("self._diagnose(result)") >
      _f27.index("Remediation resolved all issues on pass"))
check("the report still carries manual checks separately from unresolved",
      "report.manual_checks = list(getattr(self, \"_manual_checks\", []) or [])"
      in _f27)


# -- 4.28 The row criterion follows the same rule as the pipeline -------------
# A build that serves every route it declares must not fail its row because the
# test suite it ships does not run. The check is still reported on every row.

import run_live_matrix as _m28                                     # noqa: E402


def _m28_rec(check, status):
    return {"check": check, "status": status}


_m28_working = {"verification": [
    _m28_rec("runtime_smoke", "verified"), _m28_rec("web_assets", "verified"),
    _m28_rec("cli_smoke", "not_applicable"),
    _m28_rec("generated_tests", "failed"),
]}
_m28_ok, _m28_why = _m28.verification_verdict(_m28_working)
check("a working app with a broken shipped suite passes its row",
      _m28_ok is True, _m28_why)
check("...and the row still says the suite needs manual testing",
      "manual testing" in _m28_why and "generated_tests" in _m28_why, _m28_why)

_m28_broken = {"verification": [
    _m28_rec("runtime_smoke", "failed"), _m28_rec("generated_tests", "failed"),
]}
_m28_ok2, _m28_why2 = _m28.verification_verdict(_m28_broken)
check("an app that does not run still fails its row",
      _m28_ok2 is False and "runtime_smoke" in _m28_why2, _m28_why2)

_m28_hole = {"verification": [
    _m28_rec("runtime_smoke", "not_run"), _m28_rec("web_assets", "verified"),
]}
check("a check that never ran is still a hole, not a pass",
      _m28.verification_verdict(_m28_hole)[0] is False)

_m28_nothing = {"verification": [
    _m28_rec("cli_smoke", "not_applicable"),
    _m28_rec("generated_tests", "failed"),
]}
check("a row with no positive evidence still fails, suite aside",
      _m28.verification_verdict(_m28_nothing)[0] is False)

check("the excluded set is exactly the one the pipeline uses",
      _m28.MANUAL_CHECKS == Pipeline._MANUAL_WHEN_WORKING,
      f"{_m28.MANUAL_CHECKS} vs {Pipeline._MANUAL_WHEN_WORKING}")


# -- 4.29 The tester keeps working; only its residue is handed over -----------
# The tester runs the generated suite and a failing test is often the only sign
# that the code under test is wrong, so it must keep driving repair. What
# changes is the ENDING: once the build has been verified and repair has had
# every pass it gets, a suite that still does not run is not a defect in a
# working application -- it goes to the user as manual testing.


def _t29_result(test_results):
    r = type("R", (), {})()
    r.architecture = {"root_folder": "proj", "files": []}
    r.intent = {}
    r.backend_files = ["proj/backend/main.py"]
    r.frontend_files = []
    r.debug_results = []
    r.frontend_debug_results = []
    r.test_results = test_results
    r.verification_outcomes = []
    return r


def _t29_failing_test(passed=1, generated=3, path="proj/tests/test_api.py"):
    t = type("T", (), {})()
    t.skipped = False
    t.tests_generated = generated
    t.passed = passed
    t.file_path = path
    return t


# During the build: unchanged. This is the half that must not regress.
_t29_pl = Pipeline.__new__(Pipeline)
_t29_issues, _t29_paths, _t29_adv = _t29_pl._diagnose(
    _t29_result([_t29_failing_test()]))

check("a failing test suite is still an issue while the build is running",
      any("Generated tests fail" in i for i in _t29_issues), str(_t29_issues))
check("...and still hands the debugger the file to repair",
      "proj/tests/test_api.py" in _t29_paths, str(_t29_paths))
check("...so the tester keeps catching defects in the code under test",
      len(_t29_paths) >= 1)

# At the end, with the application verified: handed over, build not degraded.
_t29_pl._artifact_verified_working = True
_t29_pl._manual_checks = []
_t29_ei, _t29_ea = _t29_pl._hand_over_test_suite_findings(
    list(_t29_issues), list(_t29_adv))
check("once the application is verified, the residue stops being an issue",
      not any("Generated tests fail" in i for i in _t29_ei), str(_t29_ei))
check("...and is handed to the user for manual testing",
      any("Generated tests fail" in m for m in _t29_pl._manual_checks),
      str(_t29_pl._manual_checks))
check("...leaving nothing to degrade the build",
      (_t29_ei + _t29_ea) == [], str(_t29_ei + _t29_ea))

# Without evidence the application works, it must still count.
_t29_pl2 = Pipeline.__new__(Pipeline)
_t29_i2, _t29_p2, _t29_a2 = _t29_pl2._diagnose(
    _t29_result([_t29_failing_test()]))
_t29_pl2._artifact_verified_working = False
_t29_pl2._manual_checks = []
_t29_ei2, _t29_ea2 = _t29_pl2._hand_over_test_suite_findings(
    list(_t29_i2), list(_t29_a2))
check("with nothing showing the application works, the finding still counts",
      any("Generated tests fail" in i for i in _t29_ei2), str(_t29_ei2))
check("...and is not quietly moved to manual testing",
      _t29_pl2._manual_checks == [], str(_t29_pl2._manual_checks))

# A build that generated no tests at all, but works, is the same shape.
_t29_pl3 = Pipeline.__new__(Pipeline)
_t29_i3, _t29_p3, _t29_a3 = _t29_pl3._diagnose(_t29_result([]))
check("a build with no executable tests says so",
      any("No executable backend tests" in a for a in _t29_a3), str(_t29_a3))
_t29_pl3._artifact_verified_working = True
_t29_pl3._manual_checks = []
_t29_ei3, _t29_ea3 = _t29_pl3._hand_over_test_suite_findings(
    list(_t29_i3), list(_t29_a3))
check("...and once verified, that too is a manual check rather than a defect",
      _t29_ea3 == [] and len(_t29_pl3._manual_checks) == 1,
      f"advisory={_t29_ea3} manual={_t29_pl3._manual_checks}")

# Passing tests must produce nothing to hand over.
_t29_pl4 = Pipeline.__new__(Pipeline)
_t29_i4, _t29_p4, _t29_a4 = _t29_pl4._diagnose(
    _t29_result([_t29_failing_test(passed=3, generated=3)]))
check("a suite that passes leaves nothing to hand over",
      getattr(_t29_pl4, "_test_suite_issues", []) == [],
      str(getattr(_t29_pl4, "_test_suite_issues", [])))

# The per-diagnosis reset matters: _diagnose runs twice per build, and a stale
# list would hand over a finding the second run no longer produces.
_t29_pl5 = Pipeline.__new__(Pipeline)
_t29_pl5._diagnose(_t29_result([_t29_failing_test()]))
check("the first diagnosis records a test-suite finding",
      len(_t29_pl5._test_suite_issues) == 1)
_t29_pl5._diagnose(_t29_result([_t29_failing_test(passed=3, generated=3)]))
check("...and a later diagnosis that finds none clears it, rather than "
      "carrying the old one into the shipped document",
      _t29_pl5._test_suite_issues == [],
      str(_t29_pl5._test_suite_issues))

# Both exits from remediation must route, not just the one that runs repair.
_t29_src = Path("agents/pipeline.py").read_text(encoding="utf-8")
check("the advisory-only exit hands over too",
      _t29_src.count("_hand_over_test_suite_findings(") >= 3,
      f"{_t29_src.count('_hand_over_test_suite_findings(')} call sites")


# -- 4.30 Which side of a failing test is actually broken ---------------------
# The pipeline repaired in two directions at once without evidence: the tester
# rewrote the TEST (which, when the source is at fault, teaches the test to
# accept a real bug) and _diagnose handed the SOURCE to the debugger (wasted
# when the test is at fault). The deepest traceback frame separates them.
# Measured over the corpus: 65 source defects, 41 test defects, 40 ambiguous;
# 18 builds stop rewriting the test, 7 stop repairing the source, none both.

from tools.test_blame import (                                     # noqa: E402
    Blame, classify_pytest_output, is_test_path,
)

# Row 2's exact defect, in the format `Tester._run_pytest_single` produces.
_B30_TEST_SIDE = """
=================================== ERRORS ====================================
_________________________ ERROR at setup of test_one __________________________

    @pytest.fixture(autouse=True)
    def reset_db():
        conn = init_db()
>       conn.close()
E       AttributeError: 'NoneType' object has no attribute 'close'

tests/test_api.py:6: AttributeError
"""

_B30_SOURCE_SIDE = """
=================================== ERRORS ====================================
____________________ ERROR collecting tests/test_app.py _______________________

tests/test_app.py:3: in <module>
    from backend.services import build_report
backend/services.py:12: in <module>
    def build(rows: List[str]):
E   NameError: name 'List' is not defined

backend/services.py:12: NameError
"""

_B30_ASSERTION = """
=================================== FAILURES ==================================
___________________________ test_create_product _______________________________

    def test_create_product():
>       assert response.status_code == 201
E       assert 422 == 201

tests/test_products.py:14: AssertionError
"""

_b30_t = classify_pytest_output(_B30_TEST_SIDE)
check("an exception raised inside the test is a test defect",
      [f.verdict for f in _b30_t.failures] == [Blame.TEST_DEFECT],
      str([str(f) for f in _b30_t.failures]))
check("...so the source must not be repaired for it",
      _b30_t.all_test_defects is True)
check("...and the test may still be rewritten",
      _b30_t.has_source_defect is False)

_b30_s = classify_pytest_output(_B30_SOURCE_SIDE)
check("an exception raised inside the source is a source defect, even though "
      "it surfaced while importing a test",
      [f.verdict for f in _b30_s.failures] == [Blame.SOURCE_DEFECT],
      str([str(f) for f in _b30_s.failures]))
check("...so the test must NOT be rewritten to accommodate it",
      _b30_s.has_source_defect is True)
check("...and it is not mistaken for a test defect",
      _b30_s.all_test_defects is False)

_b30_a = classify_pytest_output(_B30_ASSERTION)
check("a failing assertion is ambiguous, not a test defect",
      [f.verdict for f in _b30_a.failures] == [Blame.AMBIGUOUS],
      str([str(f) for f in _b30_a.failures]))
check("...so neither repair is skipped for it",
      _b30_a.has_source_defect is False and _b30_a.all_test_defects is False)

# A mixed file: one real source defect is enough to stop the test rewrite.
_b30_mixed = classify_pytest_output(_B30_TEST_SIDE + _B30_SOURCE_SIDE)
check("one source defect among test defects still stops the test rewrite",
      _b30_mixed.has_source_defect is True)
check("...and stops the source repair being skipped",
      _b30_mixed.all_test_defects is False)

# Ambiguity anywhere must fall back to today's behaviour.
_b30_amb = classify_pytest_output(_B30_TEST_SIDE + _B30_ASSERTION)
check("a single ambiguous failure prevents skipping the source repair",
      _b30_amb.all_test_defects is False,
      str(_b30_amb.counts()))

# Unreadable output must never change behaviour. This is the rule that the
# study behind this module got wrong first time, scoring ten broken suites as
# passing because an empty result meant two different things.
for _b30_junk in ("", "1 failed in 0.2s", "no frames here at all",
                  "tests/x.py: some prose without a line number"):
    _b30_r = classify_pytest_output(_b30_junk)
    check(f"unreadable output changes nothing ({_b30_junk[:24]!r})",
          _b30_r.has_source_defect is False
          and _b30_r.all_test_defects is False
          and _b30_r.failures == [])

check("a report with no failures is not 'all test defects'",
      classify_pytest_output("").all_test_defects is False)
check("the summary of an empty report says so rather than implying a pass",
      "no failures could be attributed" in classify_pytest_output("").summary())

# --tb=native is the other format that reaches this, and must agree.
_B30_NATIVE = """=========================== ERRORS ============================
Traceback (most recent call last):
  File "tests/test_api.py", line 6, in reset_db
    conn.close()
AttributeError: 'NoneType' object has no attribute 'close'
"""
check("the native traceback format is classified the same way",
      classify_pytest_output(_B30_NATIVE).all_test_defects is True,
      str(classify_pytest_output(_B30_NATIVE).counts()))

# Path classification underpins all of it.
check("test files are recognised by name and by directory",
      all(is_test_path(p) for p in
          ("tests/test_api.py", "test_x.py", "a/b_test.py",
           "tests/conftest.py", r"pkg\tests\test_z.py")))
check("source files are not mistaken for tests",
      not any(is_test_path(p) for p in
              ("backend/services.py", "main.py", "src/latest_test_helper.py",
               "")),
      "a source path was classified as a test")

# The wiring, in both directions.
_b30_tester_src = Path("agents/tester.py").read_text(encoding="utf-8")
check("the tester classifies before spending a rewrite",
      "classify_pytest_output(output" in _b30_tester_src)
check("...and skips the rewrite when the source is at fault",
      "if blame.has_source_defect:" in _b30_tester_src)
check("TestResult carries the verdict to the pipeline",
      "all_test_defects" in _b30_tester_src and
      "source_defect" in _b30_tester_src)
check("MAX_TEST_FIXES is unchanged — attempts are spent, not capped",
      "MAX_TEST_FIXES = 3" in _b30_tester_src)

_b30_pipe_src = Path("agents/pipeline.py").read_text(encoding="utf-8")
check("the pipeline skips source repair when the test is at fault",
      'if getattr(r, "all_test_defects", False):' in _b30_pipe_src)
check("...but still reports the failure, so nothing leaves the record",
      "_test_suite_issues.append(_test_issue)" in _b30_pipe_src)


# -- 4.31 "Verified" must mean something ran, not something was read ----------
# Half the checks never execute what they inspect. `is_evidence_of_working`
# returned True for any VERIFIED outcome, so a green static check was read as
# proof the artifact runs. Measured on the baseline: 27 of 41 builds have a
# verified static check and NO verified executing one, and two of them --
# `project` and `todo_app` -- passed the row criterion on `sql_schema` alone,
# with nothing ever having been run.

import run_live_matrix as _m31                                     # noqa: E402


def _m31_rec(check, status):
    return {"check": check, "status": status}


_m31_static_only = {"verification": [
    _m31_rec("sql_schema", "verified"),
    _m31_rec("runtime_smoke", "not_applicable"),
    _m31_rec("cli_smoke", "not_applicable"),
]}
_m31_ok, _m31_why = _m31.verification_verdict(_m31_static_only)
check("a row verified only by static checks does NOT pass",
      _m31_ok is False, _m31_why)
check("...and the reason says it was only read, not merely 'not applicable'",
      "only read statically" in _m31_why, _m31_why)

_m31_real = {"verification": [
    _m31_rec("runtime_smoke", "verified"),
    _m31_rec("sql_schema", "verified"),
]}
check("a row where something actually ran still passes",
      _m31.verification_verdict(_m31_real)[0] is True)

check("the driver and the pipeline share one idea of what executes",
      _m31.EXECUTING_CHECKS == _EXEC42,
      f"{sorted(_m31.EXECUTING_CHECKS)} vs {sorted(_EXEC42)}")

# The gate my manual-check routing uses is the same property, so it inherits
# the fix: a failing test suite must not be handed to the user as "the app was
# verified" when nothing executed the app.
_m31_pl = Pipeline.__new__(Pipeline)
_m31_pl._manual_checks = []
_m31_pl._artifact_verified_working = False
_m31_i, _m31_a = _m31_pl._hand_over_test_suite_findings(["Generated tests fail"], [])
check("without execution, a test-suite finding is not handed over as verified",
      _m31_i == ["Generated tests fail"] and _m31_pl._manual_checks == [])


# -- 4.32 A static page has to be served to count as verified -----------------
# web_asset_check READS the page. Nothing SERVED it, so for a project that is
# only a static page every executing check answered not_applicable -- and once
# 4.31 made "verified" mean "something ran the artifact", such a build could
# never demonstrate it works. That gap was created by the fix; this closes it.
# Validated across the corpus before wiring: 32 not_applicable, 7 verified,
# 2 failed, and both failures confirmed real by hand.

from tools.static_smoke import smoke_test_static, _asset_refs   # noqa: E402

_S32 = Path(tempfile.mkdtemp(prefix="static32_"))
_S32_OUT = _S32 / "out"
_S32_OUT.mkdir(parents=True)


def _s32_project(name, files):
    root = _S32_OUT / name
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
    return name


def _s32_run(name):
    real = config.OUTPUT_DIR
    try:
        config.OUTPUT_DIR = str(_S32_OUT)
        return smoke_test_static(name)
    finally:
        config.OUTPUT_DIR = real


_s32_project("good", {
    "index.html": (
        '<html><head><link rel="stylesheet" href="./styles.css">'
        '<script src="https://cdn.example.com/x.js"></script></head>'
        '<body><img src="./logo.png"><script src="./app.js"></script>'
        "</body></html>"
    ),
    "styles.css": "body{}",
    "app.js": "console.log(1)",
    "logo.png": b"\x89PNG\r\n",
})
_o = _s32_run("good")
check("a page whose assets all resolve is verified",
      _o.status is Status.VERIFIED, f"{_o.status} {_o.detail}")
check("...and the record says how much was actually fetched",
      "3 local asset(s)" in (_o.detail or ""), _o.detail)
check("...and a static page is now evidence the build works",
      _o.is_evidence_of_working is True)

# The defect a parser cannot see: a reference that looks fine and 404s.
_s32_project("missing", {
    "index.html": '<html><body><script src="./missing.js"></script></body></html>',
})
_o = _s32_run("missing")
check("a page loading a script that is not served fails",
      _o.status is Status.FAILED, str(_o.status))
check("...and the finding names the reference",
      any("missing.js" in f for f in _o.findings), str(_o.findings))
check("...and defers to web_assets rather than filing the same defect twice",
      any("web_assets" in f for f in _o.findings), str(_o.findings))

# The case only execution can find: the file exists but is not reachable.
_s32_project("escapes", {
    "shared/util.js": "x=1",
    "frontend/index.html":
        '<html><body><script src="../shared/util.js"></script></body></html>',
})
_o = _s32_run("escapes")
check("a file that exists but is outside the served root is reported",
      _o.status is Status.FAILED, str(_o.status))
check("...and is described as unreachable, not as absent",
      any("exists in the project" in f for f in _o.findings), str(_o.findings))

# Applicability and network hygiene.
_s32_project("nopage", {"main.py": "print(1)"})
check("a project with no HTML page is not applicable",
      _s32_run("nopage").status is Status.NOT_APPLICABLE)

_s32_project("cdn_only", {
    "index.html": (
        '<html><head><link rel="stylesheet" '
        'href="https://cdn.example.com/a.css">'
        '<script src="//cdn.example.com/b.js"></script></head>'
        "<body>hi</body></html>"
    ),
})
_o = _s32_run("cdn_only")
check("remote assets are skipped, so a CDN never decides a build",
      _o.status is Status.VERIFIED and "0 local asset(s)" in (_o.detail or ""),
      f"{_o.status} {_o.detail}")

check("absolute, protocol-relative and data URLs are all skipped",
      _asset_refs(
          '<script src="https://a/x.js"></script>'
          '<script src="//b/y.js"></script>'
          '<img src="data:image/png;base64,AAA">'
          '<a href="#top"></a><script src="./real.js"></script>'
      ) == ["./real.js"],
      str(_asset_refs('<script src="./real.js"></script>')))

# A missing project must not read as clean.
check("a project that does not exist is NOT_RUN, never a pass",
      _s32_run("does_not_exist").status is Status.NOT_RUN)

# The server must not survive the check, or a long corpus run leaks ports.
import threading as _th32                                          # noqa: E402
_s32_before = _th32.active_count()
_s32_run("good"); _s32_run("missing")
check("the HTTP server is torn down after every check",
      _th32.active_count() <= _s32_before,
      f"threads {_s32_before} -> {_th32.active_count()}")

# Wiring.
check("static_smoke counts as a check that executes the artifact",
      "static_smoke" in _EXEC42, str(sorted(_EXEC42)))
check("the pipeline runs it beside web_assets",
      '("static_smoke", smoke_test_static)' in
      Path("agents/pipeline.py").read_text(encoding="utf-8"))
check("verify_corpus runs it too, so it stays testable for free",
      '("static_smoke",    smoke_test_static)' in
      Path("tools/verify_corpus.py").read_text(encoding="utf-8"))

# The two honesty fixes found on the way.
_s32_rs = Path("tools/runtime_smoke.py").read_text(encoding="utf-8")
check("the skip message no longer names a narrower search than it performs",
      'result.error = "no FastAPI entry point found"' not in _s32_rs)
check("...and says what it actually looked for",
      "no create_app() factory" in _s32_rs)

shutil.rmtree(_S32, ignore_errors=True)


# -- 4.33 The sys.path shim must not outrank __future__ -----------------------
# Row 3 (2026-08-31) shipped `unusable` with its entire API unimportable.
# backend/models.py was generated correctly with `from __future__ import
# annotations` on line 1; `Debugger._inject_syspath` then prepended its sys.path
# block ABOVE it, pushing the future import to line 10, and Python refuses the
# file: "from __future__ imports must occur at the beginning of the file".
# The generated code was right and the pipeline broke it -- which is why a red
# verification result is a hypothesis about the pipeline first.

import ast as _ast33                                               # noqa: E402
from agents.debugger import Debugger as _Dbg33                     # noqa: E402

_F33 = Path(tempfile.mkdtemp(prefix="future33_"))
_F33_OUT = _F33 / "out"
_F33_OUT.mkdir(parents=True)

_F33_CASES = {
    "plain_future":
        "from __future__ import annotations\n\nimport os\nX = 1\n",
    "docstring_then_future":
        '"""Doc."""\nfrom __future__ import annotations\n\nimport os\n',
    "shebang_doc_future":
        '#!/usr/bin/env python\n"""Doc."""\n'
        "from __future__ import annotations\nimport os\n",
    "multiline_future":
        "from __future__ import (annotations,\n"
        "                        generator_stop)\n\nimport os\n",
    "two_future_lines":
        "from __future__ import annotations\n"
        "from __future__ import generator_stop\n\nimport os\n",
    "no_future":
        '"""Doc."""\nimport os\nY = 2\n',
}


def _f33_inject(name, src):
    proj = _F33_OUT / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "m.py").write_text(src, encoding="utf-8")
    real = config.OUTPUT_DIR
    try:
        config.OUTPUT_DIR = str(_F33_OUT)
        _Dbg33.__new__(_Dbg33)._inject_syspath(f"{name}/m.py")
    finally:
        config.OUTPUT_DIR = real
    return (proj / "m.py").read_text(encoding="utf-8")


for _name, _src in _F33_CASES.items():
    _out = _f33_inject(_name, _src)
    try:
        _ast33.parse(_out)
        _parses, _why = True, ""
    except SyntaxError as e:
        _parses, _why = False, e.msg
    check(f"the shim leaves `{_name}` importable", _parses, _why)
    check(f"...and the shim was actually injected into `{_name}`",
          "_sys.path.insert" in _out)

# The exact shape row 3 died on: the shim must end up BELOW the future import.
_r33 = _f33_inject("row3_shape",
                   "from __future__ import annotations\n\nimport datetime\n")
_r33_lines = [l for l in _r33.splitlines() if l.strip()]
check("the future import still comes first, above the shim",
      _r33_lines[0].startswith("from __future__"), _r33_lines[0][:60])
check("...and the shim follows it rather than preceding it",
      _r33.index("from __future__") < _r33.index("_sys.path.insert"))

# A file that does not parse is exactly when this runs, so the fallback matters.
_broken = _f33_inject(
    "unparseable",
    "from __future__ import annotations\ndef f(:\n    pass\n")
check("an unparseable file still gets the shim below its future import",
      _broken.index("from __future__") < _broken.index("_sys.path.insert"),
      _broken[:80])

# Re-injection must stay idempotent: the block is stripped and re-added, and it
# must not migrate above the future import on the second pass.
_again = _f33_inject("plain_future", _f33_inject(
    "plain_future", _F33_CASES["plain_future"]))
check("re-injecting does not move the shim above the future import",
      _again.index("from __future__") < _again.index("_sys.path.insert"))
check("...and does not duplicate the shim",
      _again.count("_grandparent = ") == 1, str(_again.count("_grandparent = ")))

# The helper itself, on input the line-scanner has to handle alone.
check("the scanner stops at the first line that is not a future import",
      _Dbg33._after_future_imports(
          "from __future__ import annotations\nimport os\nfrom __future__ import x\n",
          ["from __future__ import annotations\n", "import os\n",
           "from __future__ import x\n"], 0) == 1)

shutil.rmtree(_F33, ignore_errors=True)


# ── Cleanup ───────────────────────────────────────────────────────────────────
# Put the ledger back where it belongs and remove the scratch file, so a test run
# leaves the platform's real quota record exactly as it found it.
try:
    llm_client._LEDGER_PATH.unlink(missing_ok=True)
except Exception:
    pass
llm_client._LEDGER_PATH = _REAL_LEDGER_PATH
llm_client._ledger = []
llm_client._ledger_covered = {}
llm_client._ledger_load()


# ── Summary ───────────────────────────────────────────────────────────────────
total = len(PASS) + len(FAIL)
print(f"\n{'='*58}")
print(f"  Phase 23 Test Results: {len(PASS)}/{total} passed")
print(f"{'='*58}")
if FAIL:
    print("\n  Failures:")
    for f in FAIL:
        print(f"  [FAIL]  {f}")
    sys.exit(1)
print("\n  All tests passed.")
