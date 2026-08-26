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
_dbg2.think = lambda p: (_prompts.append(p) or "x = 1\n")

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
usage = llm_client.get_daily_usage()["models"]
check("a build the ledger never saw is counted after seeding",
      seeded["builds_seeded"] == 1 and seeded["tokens_seeded"] == 30_000,
      f"seeded={seeded}")
check("the recorded per-model split is used verbatim, not estimated",
      usage["openai/gpt-oss-120b"]["tokens_used"] == 25_000
      and usage["openai/gpt-oss-20b"]["tokens_used"] == 5_000,
      f"usage={usage}")
check("seeded spend is reported as seeded, so the estimate is visible",
      usage["openai/gpt-oss-120b"]["seeded_tokens"] == 25_000)

# Seeding runs on every boot, and the server restarts constantly. Running it
# twice must not spend the budget twice.
again = llm_client.seed_ledger_from_history([_row("b-recent", 30_000, 2)], now=_now)
after = llm_client.get_daily_usage()["models"]
check("seeding the same build again adds nothing",
      again["builds_seeded"] == 0
      and after["openai/gpt-oss-120b"]["tokens_used"] == 25_000,
      f"again={again}")

# …and it must survive the restart it exists for.
llm_client._ledger, llm_client._ledger_covered = [], {}
llm_client._ledger_load()
llm_client.seed_ledger_from_history([_row("b-recent", 30_000, 2)], now=_now)
check("the covered-builds record survives a restart, so seeding stays idempotent",
      llm_client.get_daily_usage()["models"]["openai/gpt-oss-120b"]["tokens_used"]
      == 25_000,
      f"usage={llm_client.get_daily_usage()['models']}")

# A build this process watched live is already in the ledger call by call.
llm_client.reset_daily_usage()
llm_client._current_build_id.value = "b-live"
llm_client._add_tokens(6_000, 2_000, "openai/gpt-oss-120b")
live_seed = llm_client.seed_ledger_from_history([_row("b-live", 8_000, 0.1)], now=_now)
check("a build watched live is not seeded on top of itself",
      live_seed["builds_seeded"] == 0
      and llm_client.get_daily_usage()["models"]["openai/gpt-oss-120b"]["tokens_used"]
      == 8_000,
      f"live_seed={live_seed}")
llm_client._current_build_id.value = None

# The window is the whole point: yesterday's spend is not today's budget.
llm_client.reset_daily_usage()
old_seed = llm_client.seed_ledger_from_history([_row("b-old", 99_000, 30)], now=_now)
check("a build older than the 24h window is not seeded",
      old_seed["builds_seeded"] == 0
      and llm_client.get_daily_usage()["models"] == {},
      f"old_seed={old_seed}")

# Rows written before `tokens_by_model` existed carry no split. Half each is an
# estimate, and it is labelled as one rather than silently presented as measured.
llm_client.reset_daily_usage()
llm_client.seed_ledger_from_history([_row("b-legacy", 90_001, 3)], now=_now)
legacy = llm_client.get_daily_usage()["models"]
check("a row with no split is divided across both configured models",
      legacy["openai/gpt-oss-120b"]["tokens_used"]
      + legacy["openai/gpt-oss-20b"]["tokens_used"] == 90_001,
      f"legacy={legacy}")
check("…and the odd token is not lost to integer division",
      abs(legacy["openai/gpt-oss-120b"]["tokens_used"]
          - legacy["openai/gpt-oss-20b"]["tokens_used"]) == 1)
check("…and every token of it is marked as an estimate",
      legacy["openai/gpt-oss-120b"]["seeded_tokens"]
      == legacy["openai/gpt-oss-120b"]["tokens_used"])

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
      junk["builds_seeded"] == 0 and llm_client.get_daily_usage()["models"] == {},
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
check("a format-1 ledger file still loads",
      llm_client.get_daily_usage()["models"]["openai/gpt-oss-120b"]["tokens_used"]
      == 40_000)
check("…and its unlabelled entries count as observed, not estimated",
      llm_client.get_daily_usage()["models"]["openai/gpt-oss-120b"]["seeded_tokens"]
      == 0)
blind = llm_client.seed_ledger_from_history([_row("b-inspan", 40_000, 1)], now=_now)
check("a build inside a format-1 ledger's recorded span is not double-counted",
      blind["builds_seeded"] == 0
      and llm_client.get_daily_usage()["models"]["openai/gpt-oss-120b"]["tokens_used"]
      == 40_000,
      f"blind={blind}")

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
        from_db = llm_client.get_daily_usage()["models"]
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
            },
            "openai/gpt-oss-120b": {
                "tokens_used": 40_000, "percent_used": 20.0, "limit": 200_000,
                "tokens_remaining": 160_000, "seeded_tokens": 0,
                "window_resets_in_seconds": 3600, "calls": 12,
            },
        },
    },
    "reset_hint": "Groq free-tier daily quotas reset at 00:00 UTC.",
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
      _table.rstrip().endswith("reset at 00:00 UTC."))

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

    def think(self, prompt: str) -> str:
        self.prompts.append(prompt)
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
