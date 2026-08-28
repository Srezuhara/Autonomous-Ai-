"""
llm_client.py  v3.6.1  (Per-Model Exhaustion Tracking — UI counter fix)
========================================================================
Changes vs v3.6.0:

BUG FIX — Gap B: exhausted_keys counter in get_key_status() used set
  intersection (keys exhausted on BOTH models) instead of union (keys
  exhausted on AT LEAST ONE model).  The FloatingStatus component uses
  this number to decide whether to show the "Reset Keys" button.  If all
  keys were exhausted on the heavy model but none on the fast model, the
  counter read 0 and the reset button never appeared, leaving users
  unable to manually reset without knowing about the /admin/reset-keys
  endpoint directly.

  Fix: exhausted_keys now returns len(exhausted_heavy | exhausted_fast).
  Two additional breakdown fields are also returned so the UI can surface
  more informative messages when needed:
    "exhausted_70b": count of keys exhausted on heavy model only or both
    "exhausted_8b":  count of keys exhausted on fast model only or both

BUG FIX — Gap C: FrontendDebugger token budget was 1024 tokens, matching
  the fast-model agents.  However FrontendDebugger generates complete
  TypeScript file rewrites — identical to the code-generation agents —
  and 1024 tokens reliably truncates the output mid-function, producing
  broken JSX that fails the TypeScript compile check on the next run.
  Fix: budget raised to 1500 tokens (same as Documenter).

All v3.6.0 features retained unchanged:
  - Per-model exhaustion: _exhausted_by_model[model] = {key_indices}
  - _get_next_groq_key(model) — model-scoped key selection
  - _mark_groq_exhausted(key, model) — model-scoped exhaustion
  - _reset_exhausted() — clears ALL models for /admin/reset-keys
  - Dual-model routing (heavy agents → 70b, fast agents → 8b)
  - Per-agent token budgets
  - Per-minute vs daily-quota 429 classification
  - Multi-key round-robin rotation
  - Thread-safe per-build token accumulation
  - Ollama last-resort fallback
"""

import logging
import os
import threading
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

MAX_PER_MINUTE_WAIT = 60
MAX_DAILY_QUOTA_ROTATIONS_PER_CALL = int(
    os.getenv("GROQ_MAX_DAILY_QUOTA_ROTATIONS_PER_CALL", "2")
)
GROQ_RATE_LIMIT_MAX_WAIT_SECONDS = int(os.getenv("GROQ_RATE_LIMIT_MAX_WAIT_SECONDS", "900"))
GROQ_RATE_LIMIT_MAX_RETRIES = int(os.getenv("GROQ_RATE_LIMIT_MAX_RETRIES", "20"))
GROQ_TPM_SAFETY_TOKENS = int(os.getenv("GROQ_TPM_SAFETY_TOKENS", "800"))
# The tokens-per-minute ceiling, covering prompt AND completion together, used
# until a real `x-ratelimit-limit-tokens` header replaces it. Without a starting
# value `_fit_output_budget_to_model_limit` cannot clamp anything on the first
# call of a process, so an oversized request went out unchecked. 8000 is the
# free-tier figure this project actually runs against, observed in the header.
GROQ_TPM_LIMIT_DEFAULT = int(os.getenv("GROQ_TPM_LIMIT_DEFAULT", "8000"))
GROQ_CONTEXT_MAX_CHARS = int(os.getenv("GROQ_CONTEXT_MAX_CHARS", "2500"))
GROQ_FREE_TIER_CONSERVE = os.getenv("GROQ_FREE_TIER_CONSERVE", "true").lower() in {
    "1", "true", "yes", "on"
}
# Phase 23 (A3): test-only daily-quota simulation.
#
# Burning a real key to exercise the Phase 21 quota-handoff path costs a whole
# day of free-tier quota and is not repeatable. When this is > 0, `_call_groq`
# raises `_make_quota_error(model, "simulated")` after that many successful
# calls -- the same helper every real raise site uses, so the simulated error is
# byte-identical in type and payload to a genuine one. Default 0 = off.
GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS = int(
    os.getenv("GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS", "0")
)
_simulated_quota_lock = threading.Lock()
_simulated_call_count = 0

# Phase 23 (A5): recover from truncated completions.
#
# The gpt-oss models return `finish_reason="length"` when they run out of output
# budget mid-token, and the comment block above `_REASONING_MODEL_MARKERS`
# already spells out why that is the worst possible outcome: the result is a
# syntax error, and the Debugger burns all of its repair attempts on it because
# every repair truncates the same way. Nothing ever read `finish_reason`, so a
# half-written file was returned to the caller as if it were a complete answer.
#
# A truncated call has already been paid for, so retrying with a bigger budget
# costs one extra call to salvage work that was otherwise guaranteed to be
# thrown away — and it removes the 3 failed repair calls that followed.
GROQ_TRUNCATION_MAX_RETRIES = int(os.getenv("GROQ_TRUNCATION_MAX_RETRIES", "2"))
GROQ_TRUNCATION_BUDGET_MULTIPLIER = float(
    os.getenv("GROQ_TRUNCATION_BUDGET_MULTIPLIER", "2.0")
)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()
if LLM_PROVIDER not in {"groq", "ollama", "both"}:
    LLM_PROVIDER = "both"

_DAILY_QUOTA_KEYWORDS = (
    "daily", "quota", "exceeded", "limit reached",
    "rate_limit_exceeded", "tokens_exceeded",
)

_DAILY_LIMIT_PHRASES = (
    "tokens per day",
    "requests per day",
    "per day",
    "daily",
    "tpd",
    "rpd",
)

_TOKEN_LIMIT_PHRASES = (
    "tokens per minute",
    "token per minute",
    "tpm",
    "token rate",
)

_REQUEST_LIMIT_PHRASES = (
    "requests per minute",
    "request per minute",
    "rpm",
)


class GroqRateLimitError(RuntimeError):
    """Raised for Groq rate limits that should not fall back to Ollama."""


class GroqDailyQuotaError(GroqRateLimitError):
    """
    Raised when Groq reports a real daily request/token quota limit.

    Phase 21: carries structured diagnostics so the pipeline can write an
    accurate SESSION_CONTEXT.md without re-inspecting llm_client internals.
    All fields are optional — older raise sites that pass only a message
    still work unchanged.
    """

    def __init__(
        self,
        message:        str,
        model:          Optional[str] = None,
        keys_total:     Optional[int] = None,
        keys_exhausted: Optional[int] = None,
        reset_hint:     str = "",
        reason:         str = "",
    ):
        super().__init__(message)
        self.model          = model
        self.keys_total     = keys_total
        self.keys_exhausted = keys_exhausted
        self.reset_hint     = reset_hint
        self.reason         = reason

    def details(self) -> dict:
        """Serializable diagnostics for the session-context generator."""
        return {
            "message":        str(self),
            "model":          self.model,
            "keys_total":     self.keys_total,
            "keys_exhausted": self.keys_exhausted,
            "reset_hint":     self.reset_hint,
            "reason":         self.reason,
        }


@dataclass
class RateLimitInfo:
    kind: str
    wait_seconds: float = 0.0
    message: str = ""


@dataclass
class ModelRateState:
    # Seeded rather than None: an unknown ceiling is not the same as no ceiling,
    # and treating it as none let the first call of every process skip the fit.
    limit_tokens: Optional[int] = GROQ_TPM_LIMIT_DEFAULT
    remaining_tokens: Optional[int] = None
    reset_tokens_at: float = 0.0
    limit_requests: Optional[int] = None
    remaining_requests: Optional[int] = None
    reset_requests_at: float = 0.0
    cooldown_until: float = 0.0
    last_rate_limit_reason: str = ""
    last_wait_seconds: float = 0.0
    daily_limited: bool = False
    updated_at: float = field(default_factory=time.time)


def _get_config(attr: str, default):
    try:
        import config
        return getattr(config, attr, default)
    except ImportError:
        return default


# ── Dual-model configuration ──────────────────────────────────────────────────
# Defaults track what Groq currently serves. The llama-3.x models this project
# was originally built against were decommissioned — they now return HTTP 404 on
# every key, which surfaces as "all keys tried without success" rather than as a
# model error, so keep these current.
_HEAVY_MODEL = os.getenv("GROQ_MODEL_HEAVY", "openai/gpt-oss-120b")
_FAST_MODEL  = os.getenv("GROQ_MODEL_FAST",  "openai/gpt-oss-20b")

_legacy = os.getenv("GROQ_MODEL", "")
if _legacy:
    _HEAVY_MODEL = _legacy
    _FAST_MODEL  = _legacy
    logger.info(f"ℹ️  GROQ_MODEL override active — both models set to: {_legacy}")

# Phase 23: the code-producing agents run on the heavy model.
#
# This used to be "architect" alone, on the reasoning that heavy-model quota was
# the scarce one and should be spent only where it mattered most. That was true
# of the decommissioned llama pair (a small 70b allowance beside a large 8b one).
# It is **false** for the gpt-oss models that replaced them: each carries its own
# 200,000 tokens-per-day budget, so "keep everything on the fast model" did not
# conserve anything — it drained one 200K bucket daily while the other sat
# almost untouched. Measured live: 40 of a build's 41 calls went to the fast
# model, and the day died after two builds.
#
# Splitting the load is also the better choice on quality and on speed:
#   - gpt-oss-120b is the stronger model, and it is the one writing the code.
#   - It accepts `reasoning_effort=low`; gpt-oss-20b does not, and therefore
#     spends an uncontrolled private chain of thought on every call. See the
#     measurements above `_REASONING_MODEL_MARKERS`: 120b produced 3541 chars in
#     849 tokens where 20b needed a 1600-token floor for the same prompt.
#   - TPM (8000) is per-model too, so two buckets means roughly half the waiting.
_DEFAULT_HEAVY_AGENTS = (
    "architect,backend_developer,frontend_generator,frontend_debugger,documenter"
)


def _load_heavy_agent_names() -> set[str]:
    """
    Which agents run on `GROQ_MODEL_HEAVY` rather than `GROQ_MODEL_FAST`.

    The default spreads the load across both models' independent daily budgets
    (see the note above). The small, structured, high-frequency agents —
    intent_analyzer, planner, reviewer, tester, debugger — stay on the fast
    model, which keeps the split roughly even in tokens.

    Override with GROQ_HEAVY_AGENTS to rebalance, e.g. to put everything back on
    one model:  GROQ_HEAVY_AGENTS=architect
    """
    raw = os.getenv("GROQ_HEAVY_AGENTS", _DEFAULT_HEAVY_AGENTS)
    names: set[str] = set()
    for item in raw.split(","):
        name = item.strip().lower()
        if not name:
            continue
        names.add(name)
        names.add(name.replace("_", "").replace("-", "").replace(" ", ""))
    return names


_HEAVY_AGENT_NAMES = _load_heavy_agent_names()

# ── Per-agent token budgets ───────────────────────────────────────────────────
AGENT_TOKEN_BUDGETS: dict[str, int] = {
    # Fast-model agents — lightweight structured output
    "intentanalyzer":     512,
    "intent_analyzer":    512,
    "planner":            768,
    "reviewer":           600,
    "tester":            1024,
    "documenter":        1200,
    "debugger":          1024,
    # Heavy-model agents — need room for full code files
    "architect":         1024,
    "backenddeveloper":  1200,
    "backend_developer": 1200,
    "frontendgenerator": 1200,
    "frontend_generator":1200,
    # BUG FIX v3.6.1 (Gap C): FrontendDebugger rewrites complete TS/JSX files;
    # 1024 tokens truncates output mid-function → broken JSX → tsc still fails.
    # Raised to 1500 to match Documenter (same "full-file rewrite" pattern).
    "frontenddebugger":  1500,
    "frontend_debugger": 1500,
}

if GROQ_FREE_TIER_CONSERVE:
    # Phase 23: these are CAPS, not spend — `_apply_reasoning_budget` says so,
    # and a cap only costs tokens if the model actually reaches it. Setting them
    # too low is therefore not a saving; it is how a file gets truncated, and
    # since Fix 3 every truncation costs a whole extra call to recover from.
    #
    # Two things changed the right values here:
    #
    #  1. On the FAST model these numbers were largely inert anyway. gpt-oss-20b
    #     cannot be told to reason less, so `_apply_reasoning_budget` raises
    #     anything below `_REASONING_MIN_TOKENS` (1600) back up to it. A cap of
    #     850 for the debugger was never actually 850. They are written at the
    #     floor now so the table says what really happens.
    #
    #  2. The code-producing agents moved to the HEAVY model, where no floor
    #     applies and these caps bite for the first time. 950 is well under what
    #     a routes.py needs — that is precisely the budget that truncated live —
    #     so they are raised to a figure that lands in one call.
    AGENT_TOKEN_BUDGETS.update({
        # Fast model: at or above the reasoning floor, so these are honest.
        "reviewer":            600,
        "tester":             1600,
        "debugger":           1600,
        # Heavy model: real caps, sized so a full file finishes in one call.
        "documenter":         1200,
        "backenddeveloper":   2000,
        "backend_developer":  2000,
        "frontendgenerator":  2000,
        "frontend_generator": 2000,
        "frontenddebugger":   2000,
        "frontend_debugger":  2000,
    })

_DEFAULT_MAX_TOKENS = 1024


# ── Phase 22: reasoning-model support ─────────────────────────────────────────
#
# Groq decommissioned the llama-3.x models this project was built against. The
# replacements (openai/gpt-oss-*) are REASONING models: they spend part of the
# completion budget on a private chain of thought returned in a separate
# `reasoning` field, and only the remainder on `content`.
#
# Measured on the live API with max_tokens=950 and a 4-endpoint routes.py prompt:
#
#   gpt-oss-20b   no effort param   → finish_reason=length  (code TRUNCATED)
#   gpt-oss-120b  no effort param   → finish_reason=length  (code TRUNCATED)
#   gpt-oss-120b  reasoning_effort=low → finish_reason=stop, 3541 chars, 849 tokens
#
# Truncated code is worse than useless — it is a syntax error that the debugger
# then burns retries on. `reasoning_effort=low` fixes it outright and costs
# FEWER tokens, because the budget goes to code instead of deliberation.
#
# gpt-oss-20b USED to reject reasoning_effort with HTTP 400 ("Tool choice is none,
# but model called a tool"), so it was excluded and given a larger budget floor
# instead. Groq has since fixed it. Re-measured 2026-08-28, same prompt, same
# 600-token budget:
#
#   gpt-oss-20b  no effort param      → 1614 chars reasoning, 254 chars code, 442 tok
#   gpt-oss-20b  reasoning_effort=low →  578 chars reasoning, 582 chars code, 276 tok
#
# Twice the code for 38% fewer tokens. Keeping it excluded was costing whole
# calls: the matrix on 2026-08-28 logged THIRTEEN completions that finished with
# `finish_reason=length` and zero characters of content — the entire budget spent
# deliberating, nothing returned, then retried at double the budget and billed
# again. That is what this parameter prevents.

_REASONING_MODEL_MARKERS = ("gpt-oss", "qwen3", "deepseek-r1")

# Models verified to accept the `reasoning_effort` parameter on Groq.
_REASONING_EFFORT_SUPPORTED = ("gpt-oss-120b", "gpt-oss-20b")

_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")

# Floor applied to reasoning models that cannot be told to think less.
_REASONING_MIN_TOKENS = int(os.getenv("GROQ_REASONING_MIN_TOKENS", "1600"))


def _is_reasoning_model(model: str) -> bool:
    low = (model or "").lower()
    return any(marker in low for marker in _REASONING_MODEL_MARKERS)


def _supports_reasoning_effort(model: str) -> bool:
    low = (model or "").lower()
    return any(marker in low for marker in _REASONING_EFFORT_SUPPORTED)


def _apply_reasoning_budget(model: str, max_tokens: int) -> int:
    """
    Reasoning models that cannot be told to think less need a bigger cap, or the
    answer is cut off mid-statement.

    max_tokens is a CAP, not a spend — raising it costs nothing unless the model
    actually uses it, and a truncated file is discarded anyway.
    """
    if not _is_reasoning_model(model) or _supports_reasoning_effort(model):
        return max_tokens
    if max_tokens >= _REASONING_MIN_TOKENS:
        return max_tokens
    logger.debug(
        f"Raising [{model}] max_tokens {max_tokens} → {_REASONING_MIN_TOKENS} "
        f"(reasoning model without reasoning_effort support)"
    )
    return _REASONING_MIN_TOKENS


def _build_groq_payload(model: str, messages: list, max_tokens: int) -> dict:
    """Assemble the chat-completions body, adapting to reasoning models."""
    payload = {
        "model":       model,
        "messages":    messages,
        "max_tokens":  _apply_reasoning_budget(model, max_tokens),
        "temperature": 0.2,
    }
    if _supports_reasoning_effort(model) and _REASONING_EFFORT:
        payload["reasoning_effort"] = _REASONING_EFFORT
    return payload


def get_model_for_agent(agent_name: str) -> str:
    normalised = agent_name.lower().replace(" ", "").replace("-", "")
    if normalised in _HEAVY_AGENT_NAMES or agent_name.lower() in _HEAVY_AGENT_NAMES:
        return _HEAVY_MODEL
    return _FAST_MODEL


def get_agent_token_budget(agent_name: str) -> int:
    key = agent_name.lower().replace(" ", "").replace("-", "_")
    return AGENT_TOKEN_BUDGETS.get(key,
           AGENT_TOKEN_BUDGETS.get(agent_name.lower(), _DEFAULT_MAX_TOKENS))


# ── Groq key pool ──────────────────────────────────────────────────────────────

def _load_groq_keys() -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    primary = os.getenv("GROQ_API_KEY", "").strip()
    if primary:
        keys.append(primary)
        seen.add(primary)
    for i in range(2, 21):
        k = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if k and k not in seen:
            keys.append(k)
            seen.add(k)
    if keys:
        logger.info(f"🔑 Groq keys loaded: {len(keys)}")
    else:
        logger.warning("⚠️  No Groq API keys found — only Ollama available")
    return keys


_groq_keys: list[str] = _load_groq_keys()

_global_key_index: int = -1
_invalid_keys: set[int] = set()

# ── v3.6.0: Per-model exhaustion tracking ────────────────────────────────────
# dict[model_name, set[key_index]]
# A key is only blocked for the model it was exhausted on.
_exhausted_by_model: dict[str, set[int]] = {}
_exhausted_lock = threading.Lock()

# Per-minute wait is shared (transient, not quota-based)
_per_minute_wait: dict[int, float] = {}

_model_rate_states: dict[str, ModelRateState] = {}
_model_state_lock = threading.Lock()
_model_locks: dict[str, threading.Lock] = {}

# ── Per-build token tracking ──────────────────────────────────────────────────
_token_store:     dict[str, dict] = {}
_token_lock       = threading.Lock()
_current_build_id = threading.local()


def set_current_build_id(build_id: str):
    _current_build_id.value = build_id
    with _token_lock:
        if build_id not in _token_store:
            _token_store[build_id] = {
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                # Per-model split. Persisted with the build so the daily ledger
                # can be rebuilt exactly after a restart instead of estimated.
                "by_model": {},
            }


def _add_tokens(prompt_tokens: int, completion_tokens: int, model: str = ""):
    # The daily ledger is recorded first and unconditionally: it tracks the
    # organisation's quota, which is spent whether or not a build_id happens to
    # be set. Tying it to the per-build store is how CLI runs lost their token
    # count entirely (Phase 23, A1 finding 1).
    _ledger_record(model, int(prompt_tokens) + int(completion_tokens))

    bid = getattr(_current_build_id, "value", None)
    if not bid:
        return
    with _token_lock:
        rec = _token_store.setdefault(
            bid,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "by_model": {}},
        )
        rec["prompt_tokens"]     += prompt_tokens
        rec["completion_tokens"] += completion_tokens
        rec["total_tokens"]      += prompt_tokens + completion_tokens
        if model:
            by_model = rec.setdefault("by_model", {})
            by_model[model] = by_model.get(model, 0) + prompt_tokens + completion_tokens


def get_and_reset_token_usage(build_id: str) -> dict:
    with _token_lock:
        return _token_store.pop(
            build_id,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "by_model": {}},
        )


# ── Per-model daily token ledger (Phase 23) ───────────────────────────────────
#
# Groq enforces a tokens-per-day limit *per model* — the 429 names it:
#
#   rate limit reached for model `openai/gpt-oss-20b` … on tokens per day (tpd):
#   limit 200000, used 199306, requested 3187
#
# but it reports that number **nowhere else**. No response header carries a
# daily figure, `/health` cannot show one, and `get_quota_snapshot()` had no
# idea. The first indication that 190K of 200K was gone was the failure itself,
# which is why a four-build matrix run died after one build.
#
# So we keep the count ourselves.
#
# The shape of Groq's day, measured 2026-08-28. It is not a calendar reset and
# not a rolling window either — it is a LEAKY BUCKET that refills continuously.
# Two 429s, and the arithmetic matches both to within a second:
#
#   limit 200000, used 197225, requested 2885 -> "try again in 47.52s"
#     short by 110 tokens;  110 / (200000/86400) = 47.5s
#   limit 200000, used 196757, requested 4131 -> "try again in 6m23.616s"
#     short by 888 tokens;  888 / (200000/86400) = 6m23s
#
# So the budget comes back at GROQ_DAILY_TOKEN_LIMIT / 86400 ≈ 2.315 tokens per
# second, ≈ 8,333 per hour, per model. There is no midnight to wait for, and
# telling a user to wait for one — as this code used to — costs them a day.
#
# Summing the window instead of draining a bucket was the pessimistic version of
# the same idea: it only gave budget back when an individual call aged out, so
# after a matrix run it reported 0 remaining for six hours during which Groq
# would happily have accepted a build.
GROQ_DAILY_TOKEN_LIMIT = int(os.getenv("GROQ_DAILY_TOKEN_LIMIT", "200000"))
_LEDGER_WINDOW_SECONDS = 24 * 3600
_LEDGER_PATH = Path(os.getenv("OUTPUT_DIR", "generated_projects")) / "token_ledger.json"
_LEDGER_FORMAT = 2

# Build rows are written by another process with its own clock, and a build that
# has only just finished must not read as "the future".
_SEED_CLOCK_SKEW_SECONDS = 300

# Entries are [timestamp, model, total_tokens, source] where source is "live"
# (this or an earlier process watched the call happen) or "seeded"
# (reconstructed from a finished build's DB row — see `seed_ledger_from_history`).
# Legacy 3-element entries are read as "live". Pruned to the window on every touch.
_ledger: list[list] = []

# build_id -> the timestamp its spend is attributed to. This is what makes
# seeding idempotent: a build the ledger already accounts for, live or seeded,
# must never be added a second time. Pruned with the window.
_ledger_covered: dict[str, float] = {}
_ledger_lock = threading.Lock()


def _ledger_prune(now: Optional[float] = None) -> None:
    """Drop entries that have aged out of the window. Caller holds the lock."""
    global _ledger, _ledger_covered
    cutoff = (now if now is not None else time.time()) - _LEDGER_WINDOW_SECONDS
    _ledger = [e for e in _ledger if e[0] >= cutoff]
    _ledger_covered = {b: ts for b, ts in _ledger_covered.items() if ts >= cutoff}


def _ledger_load() -> None:
    """Restore the ledger across restarts — this workflow restarts a lot."""
    global _ledger, _ledger_covered
    _ledger, _ledger_covered = [], {}
    try:
        import json
        if not _LEDGER_PATH.is_file():
            return
        raw = json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
        # Format 1 was a bare list of entries with no build attribution.
        entries = raw if isinstance(raw, list) else raw.get("entries", [])
        _ledger = [
            list(e) for e in entries
            if isinstance(e, (list, tuple)) and len(e) in (3, 4)
        ]
        if isinstance(raw, dict) and isinstance(raw.get("covered_builds"), dict):
            _ledger_covered = {
                str(b): float(ts) for b, ts in raw["covered_builds"].items()
            }
        _ledger_prune()
    except Exception as e:
        # A corrupt ledger must never stop the app from making calls; the worst
        # case is that we under-count and hit the wall as blindly as before.
        logger.warning(f"Token ledger could not be read ({e}); starting empty.")
        _ledger, _ledger_covered = [], {}


def _ledger_save() -> None:
    """Caller holds the lock."""
    try:
        import json
        _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LEDGER_PATH.write_text(
            json.dumps({
                "version": _LEDGER_FORMAT,
                "entries": _ledger,
                "covered_builds": _ledger_covered,
            }),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug(f"Token ledger could not be written: {e}")


def _ledger_record(model: str, total_tokens: int) -> None:
    if not model or total_tokens <= 0:
        return
    build_id = getattr(_current_build_id, "value", None)
    with _ledger_lock:
        now = time.time()
        _ledger.append([now, model, int(total_tokens), "live"])
        if build_id:
            # Watched live, so `seed_ledger_from_history` must leave this build
            # alone when its DB row shows up after a restart.
            _ledger_covered[str(build_id)] = now
        _ledger_prune(now)
        _ledger_save()


# ── Seeding the ledger from finished builds ───────────────────────────────────
#
# The ledger only ever knew about calls it watched happen. Spend from before it
# existed, from a process that wrote its DB row and exited, or from a run whose
# ledger file was cleared, was invisible: it read `gpt-oss-20b` at 3.6% while
# Groq's own counter said 99.9% — a gauge that errs in the one direction that
# matters. Seeding closes the gap by reconstructing spend from the `projects`
# rows inside the window.
#
# Attribution: a build row records totals, not a per-model split. Builds from
# here on store one (`tokens_by_model`) and it is used verbatim. Older rows have
# nothing to read, so the total is split evenly across the configured models and
# marked `seeded`; `get_daily_usage` reports how much of each model's figure
# came from an estimate rather than an observation.

def _ledger_history_rows() -> list[dict]:
    """Finished builds from the platform database. Read-only and best-effort."""
    try:
        import sqlite3 as _sqlite3
        db_path = Path(os.getenv("OUTPUT_DIR", "generated_projects")) / "platform.db"
        if not db_path.is_file():
            return []
        conn = _sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            conn.row_factory = _sqlite3.Row
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
            if not {"build_id", "total_tokens"} <= cols:
                return []
            selected = ["build_id", "total_tokens", "created_at", "completed_at"]
            if "tokens_by_model" in cols:
                selected.append("tokens_by_model")
            rows = conn.execute(
                f"SELECT {', '.join(selected)} FROM projects "
                f"WHERE total_tokens > 0 ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"Token ledger could not read build history: {e}")
        return []


def _row_timestamp(value) -> Optional[float]:
    """One DB timestamp as an epoch. They are naive UTC (`utcnow()`)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _row_epoch(row: dict) -> Optional[float]:
    """When a build's spend happened — its end, or its start if it has no end."""
    for field in ("completed_at", "created_at"):
        ts = _row_timestamp(row.get(field))
        if ts is not None:
            return ts
    return None


def _row_span(row: dict) -> tuple:
    """The interval a build's calls fall inside, as (start, end)."""
    start = _row_timestamp(row.get("created_at"))
    end = _row_timestamp(row.get("completed_at"))
    if start is None:
        start = end
    if end is None:
        end = start
    return start, end


def _row_split(row: dict, total: int) -> dict:
    """Per-model tokens for one build row."""
    raw = row.get("tokens_by_model")
    if raw:
        try:
            import json
            parsed = raw if isinstance(raw, dict) else json.loads(raw)
            split = {
                str(m): int(t) for m, t in parsed.items()
                if str(m) and int(t) > 0
            }
            if split:
                return split
        except Exception:
            pass  # unreadable split — fall through to the even estimate
    models = [_HEAVY_MODEL] if _FAST_MODEL == _HEAVY_MODEL else [_HEAVY_MODEL, _FAST_MODEL]
    share, remainder = divmod(total, len(models))
    split = {m: share for m in models}
    split[models[0]] += remainder
    return {m: t for m, t in split.items() if t > 0}


def seed_ledger_from_history(
    rows: Optional[list] = None, now: Optional[float] = None
) -> dict:
    """
    Add spend from builds the ledger never watched happen. Idempotent: a build
    already covered — live or previously seeded — is skipped.
    """
    if rows is None:
        rows = _ledger_history_rows()
    now = now if now is not None else time.time()
    cutoff = now - _LEDGER_WINDOW_SECONDS

    seeded_builds = 0
    seeded_tokens = 0
    with _ledger_lock:
        _ledger_prune(now)
        # A format-1 ledger carries entries with no build attribution, and every
        # checkout that ran the previous version has one on disk. Those entries
        # are spend already counted, so a build whose own run window contains
        # live entries was watched after all — seeding it would double-count.
        live_entries = sorted(e[0] for e in _ledger if len(e) < 4 or e[3] == "live")

        for row in rows:
            build_id = str(row.get("build_id") or "")
            total = int(row.get("total_tokens") or 0)
            if not build_id or total <= 0 or build_id in _ledger_covered:
                continue
            ts = _row_epoch(row)
            # A build that finished a moment ago reads as "the future" under any
            # clock skew between the writer and this process, so allow a margin
            # and attribute the spend to now rather than dropping it.
            if ts is None or ts < cutoff or ts > now + _SEED_CLOCK_SKEW_SECONDS:
                continue
            ts = min(ts, now)
            start, end = _row_span(row)
            start = (start if start is not None else ts) - _SEED_CLOCK_SKEW_SECONDS
            end = (end if end is not None else ts) + _SEED_CLOCK_SKEW_SECONDS
            if any(start <= e <= end for e in live_entries):
                _ledger_covered[build_id] = ts   # already counted, just unlabelled
                continue
            for model, tokens in _row_split(row, total).items():
                _ledger.append([ts, model, int(tokens), "seeded"])
            _ledger_covered[build_id] = ts
            seeded_builds += 1
            seeded_tokens += total

        if seeded_builds:
            _ledger.sort(key=lambda e: e[0])
            # Only when something changed: the file is shared with any other
            # process using this checkout, and each save rewrites the whole
            # thing, so a pointless write can drop a concurrent server's
            # freshly recorded calls.
            _ledger_save()

    if seeded_builds:
        logger.info(
            f"📒 Token ledger seeded from history: {seeded_builds} build(s), "
            f"{seeded_tokens:,} tokens inside the "
            f"{_LEDGER_WINDOW_SECONDS // 3600}h window"
        )
    return {"builds_seeded": seeded_builds, "tokens_seeded": seeded_tokens}


# Tokens returned per second. The same figure Groq's own retry-after is computed
# from — see the measurement above `_LEDGER_WINDOW_SECONDS`.
_REFILL_RATE = GROQ_DAILY_TOKEN_LIMIT / _LEDGER_WINDOW_SECONDS


def _bucket_level(entries: list, now: float) -> float:
    """
    How much of the daily budget is still owed, as a leaky bucket.

    Each call fills the bucket; time drains it at `_REFILL_RATE`. Decaying every
    entry independently would look similar and be wrong — it refunds the same
    elapsed seconds once per entry, so a build of 40 calls would appear to repay
    itself 40 times over. Draining the running total once, in call order, is the
    bucket Groq actually operates.
    """
    if not entries:
        return 0.0
    ordered = sorted(entries)
    level = 0.0
    prev = ordered[0][0]
    for ts, tokens in ordered:
        level = max(0.0, level - _REFILL_RATE * (ts - prev)) + tokens
        prev = ts
    return max(0.0, level - _REFILL_RATE * (now - prev))


def seconds_until_tokens(need: int, remaining: int) -> int:
    """
    How long until `need` tokens are available, given `remaining` now.

    This is Groq's own formula: the 429 that reports `used 197225, requested
    2885` says "try again in 47.52s", and 110 / 2.315 is 47.5.
    """
    if remaining >= need:
        return 0
    if _REFILL_RATE <= 0:
        return 0
    return int((need - remaining) / _REFILL_RATE)


def get_daily_usage(now: Optional[float] = None) -> dict:
    """
    Tokens spent per model inside the rolling 24h window, with what is left.

    This is the number there was previously no way to obtain. It is an estimate
    of Groq's own counter, not a reading of it: it counts what this process has
    spent plus what `seed_ledger_from_history` could reconstruct from finished
    builds, so anything else spending the same organisation's quota — another
    machine, another checkout — remains invisible to it.
    """
    # `now` is injectable for the same reason `seed_ledger_from_history` takes it:
    # the figures move with the clock, so a test that wants to assert what was
    # spent — rather than how much has since come back — must be able to stop it.
    now = now if now is not None else time.time()
    with _ledger_lock:
        _ledger_prune(now)
        entries = list(_ledger)

    per_model: dict = {}
    for entry in entries:
        ts, model, tokens = entry[0], entry[1], entry[2]
        source = entry[3] if len(entry) > 3 else "live"
        rec = per_model.setdefault(
            model, {"calls": 0, "seeded_tokens": 0, "_entries": []},
        )
        rec["_entries"].append((ts, tokens))
        rec["calls"] += 1
        if source == "seeded":
            rec["seeded_tokens"] += tokens

    for model, rec in per_model.items():
        used = _bucket_level(rec.pop("_entries"), now)
        # Round the spend and floor what is left: both err towards reporting
        # less budget than there is. Truncating `used` instead lost a token to
        # sub-second decay between two calls in the same build, which is the
        # one direction this number must never move.
        remaining = max(0, int(GROQ_DAILY_TOKEN_LIMIT - used))
        rec["tokens_used"] = int(round(used))
        rec["limit"] = GROQ_DAILY_TOKEN_LIMIT
        rec["tokens_remaining"] = remaining
        rec["percent_used"] = round(
            100.0 * used / GROQ_DAILY_TOKEN_LIMIT, 1
        ) if GROQ_DAILY_TOKEN_LIMIT else 0.0
        rec["refill_tokens_per_hour"] = int(_REFILL_RATE * 3600)
        # Seconds until the bucket is empty again, i.e. a full budget. Kept
        # under the old key because the documenter's table reads it.
        rec["window_resets_in_seconds"] = seconds_until_tokens(
            GROQ_DAILY_TOKEN_LIMIT, remaining
        )

    return {
        "window_hours": _LEDGER_WINDOW_SECONDS // 3600,
        "limit_per_model": GROQ_DAILY_TOKEN_LIMIT,
        "models": per_model,
    }


def reset_daily_usage() -> None:
    """Clear the ledger (tests, and the admin reset path)."""
    global _ledger, _ledger_covered
    with _ledger_lock:
        _ledger = []
        _ledger_covered = {}
        _ledger_save()


_ledger_load()
if os.getenv("GROQ_LEDGER_SEED", "1").lower() not in ("0", "false", "no"):
    seed_ledger_from_history()


# ── Key helpers (v3.6.0: model-scoped) ────────────────────────────────────────

def _get_model_lock(model: str) -> threading.Lock:
    with _model_state_lock:
        if model not in _model_locks:
            _model_locks[model] = threading.Lock()
        return _model_locks[model]


def _parse_header_int(value: str | None) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _parse_wait_seconds(value: str | None) -> Optional[float]:
    """Parse Groq reset headers such as '7.66s', '2m59.56s', or '1h2m3s'."""
    if not value:
        return None
    raw = str(value).strip().lower()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass

    total = 0.0
    matched = False
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", raw):
        matched = True
        val = float(amount)
        if unit == "ms":
            total += val / 1000.0
        elif unit == "s":
            total += val
        elif unit == "m":
            total += val * 60.0
        elif unit == "h":
            total += val * 3600.0
    return max(0.0, total) if matched else None


def _estimate_tokens(prompt: str, system: str, max_tokens: int) -> int:
    return int((len(prompt) + len(system)) / 4) + max_tokens


def _fit_output_budget_to_model_limit(
    model: str,
    prompt: str,
    system: str,
    max_tokens: int,
) -> int:
    prompt_tokens = int((len(prompt) + len(system)) / 4)
    with _model_state_lock:
        limit_tokens = _model_rate_states.get(model, ModelRateState()).limit_tokens

    if not limit_tokens:
        return max_tokens

    estimated = prompt_tokens + max_tokens
    if estimated + GROQ_TPM_SAFETY_TOKENS <= limit_tokens:
        return max_tokens

    available_output = limit_tokens - prompt_tokens - GROQ_TPM_SAFETY_TOKENS
    if available_output < 128:
        # Safety margin is helpful, but a tiny completion is better than
        # repeatedly submitting a request Groq has already told us cannot fit.
        available_output = limit_tokens - prompt_tokens - 100
    if available_output <= 0:
        raise GroqRateLimitError(
            f"Groq request for [{model}] is too large for the known TPM limit "
            f"({estimated} estimated tokens vs limit {limit_tokens}). "
            "The prompt/context must be compacted before retrying."
        )

    reduced = max(128, min(max_tokens, int(available_output)))
    if reduced < max_tokens:
        logger.warning(
            f"✂️  Reducing [{model}] max_tokens from {max_tokens} to {reduced} "
            f"to fit the known Groq TPM limit ({limit_tokens})."
        )
    return reduced


def _update_rate_state_from_headers(model: str, headers) -> None:
    now = time.time()
    limit_tokens = _parse_header_int(headers.get("x-ratelimit-limit-tokens"))
    remaining_tokens = _parse_header_int(headers.get("x-ratelimit-remaining-tokens"))
    reset_tokens = _parse_wait_seconds(headers.get("x-ratelimit-reset-tokens"))
    limit_requests = _parse_header_int(headers.get("x-ratelimit-limit-requests"))
    remaining_requests = _parse_header_int(headers.get("x-ratelimit-remaining-requests"))
    reset_requests = _parse_wait_seconds(headers.get("x-ratelimit-reset-requests"))

    with _model_state_lock:
        state = _model_rate_states.setdefault(model, ModelRateState())
        if limit_tokens is not None:
            state.limit_tokens = limit_tokens
        if remaining_tokens is not None:
            state.remaining_tokens = remaining_tokens
        if reset_tokens is not None:
            state.reset_tokens_at = now + reset_tokens
        if limit_requests is not None:
            state.limit_requests = limit_requests
        if remaining_requests is not None:
            state.remaining_requests = remaining_requests
        if reset_requests is not None:
            state.reset_requests_at = now + reset_requests
        state.updated_at = now


def _set_model_cooldown(model: str, reason: str, wait_seconds: float) -> None:
    wait = max(0.0, min(wait_seconds, GROQ_RATE_LIMIT_MAX_WAIT_SECONDS))
    with _model_state_lock:
        state = _model_rate_states.setdefault(model, ModelRateState())
        state.cooldown_until = max(state.cooldown_until, time.time() + wait)
        state.last_rate_limit_reason = reason
        state.last_wait_seconds = wait
        state.updated_at = time.time()


def _wait_for_model_capacity(model: str, estimated_tokens: int) -> None:
    while True:
        wait_seconds = 0.0
        reason = ""
        now = time.time()
        with _model_state_lock:
            state = _model_rate_states.setdefault(model, ModelRateState())
            if state.daily_limited:
                daily_reason = state.last_rate_limit_reason or "daily quota already marked"
            else:
                daily_reason = ""
        if daily_reason:
            raise _make_quota_error(model, daily_reason)
        with _model_state_lock:
            state = _model_rate_states.setdefault(model, ModelRateState())
            if state.cooldown_until > now:
                wait_seconds = state.cooldown_until - now
                reason = state.last_rate_limit_reason or "model cooldown"
            elif (
                state.remaining_tokens is not None
                and state.reset_tokens_at > now
                and estimated_tokens + GROQ_TPM_SAFETY_TOKENS > state.remaining_tokens
            ):
                wait_seconds = state.reset_tokens_at - now
                reason = "waiting for Groq token-per-minute budget"

        if wait_seconds <= 0:
            return
        if wait_seconds > GROQ_RATE_LIMIT_MAX_WAIT_SECONDS:
            raise GroqRateLimitError(
                f"Groq asked to wait {wait_seconds:.1f}s for [{model}], exceeding "
                f"GROQ_RATE_LIMIT_MAX_WAIT_SECONDS={GROQ_RATE_LIMIT_MAX_WAIT_SECONDS}."
            )
        logger.warning(
            f"⏳ Groq [{model}] {reason}; waiting {wait_seconds:.1f}s before retrying."
        )
        time.sleep(wait_seconds + 0.25)


def _get_next_groq_key(model: str) -> Optional[str]:
    """Return next available key for the given model (skips model-specific exhausted keys)."""
    global _global_key_index
    with _exhausted_lock:
        exhausted_for_model = _exhausted_by_model.get(model, set())
        n = len(_groq_keys)
        if n == 0:
            return None
        for offset in range(1, n + 1):
            candidate_idx = (_global_key_index + offset) % n
            if candidate_idx not in exhausted_for_model and candidate_idx not in _invalid_keys:
                _global_key_index = candidate_idx
                return _groq_keys[candidate_idx]
        return None


def _mark_key_invalid(key: str, reason: str = "auth failure"):
    with _exhausted_lock:
        try:
            idx = _groq_keys.index(key)
            _invalid_keys.add(idx)
            _per_minute_wait.pop(idx, None)
            logger.warning(f"🔑 Key ...{key[-8:]} disabled ({reason}).")
        except ValueError:
            pass


def _mark_groq_exhausted(key: str, model: str, reason: str = "daily quota"):
    """Mark a key exhausted FOR A SPECIFIC MODEL only. Other models unaffected."""
    with _exhausted_lock:
        try:
            idx = _groq_keys.index(key)
            if model not in _exhausted_by_model:
                _exhausted_by_model[model] = set()
            if idx not in _exhausted_by_model[model]:
                _exhausted_by_model[model].add(idx)
                _per_minute_wait.pop(idx, None)
                suffix          = key[-8:]
                exhausted_count = len(_exhausted_by_model[model])
                remaining       = len(_groq_keys) - exhausted_count
                logger.warning(
                    f"🔑 Key ...{suffix} exhausted on [{model}] ({reason}). "
                    f"{exhausted_count}/{len(_groq_keys)} keys exhausted for this model, "
                    f"{remaining} still available."
                )
                # Log if the OTHER model still has keys available
                other_model     = _FAST_MODEL if model == _HEAVY_MODEL else _HEAVY_MODEL
                other_exhausted = _exhausted_by_model.get(other_model, set())
                other_available = len(_groq_keys) - len(other_exhausted)
                if other_available > 0:
                    logger.info(
                        f"🔑 Note: {other_available} key(s) still available for "
                        f"[{other_model}] — fast-model calls unaffected."
                    )
        except ValueError:
            pass


def _mark_model_daily_limited(model: str, reason: str = "daily quota"):
    with _exhausted_lock:
        _exhausted_by_model[model] = set(range(len(_groq_keys)))
    with _model_state_lock:
        state = _model_rate_states.setdefault(model, ModelRateState())
        state.daily_limited = True
        state.last_rate_limit_reason = reason
        state.last_wait_seconds = 0.0
        state.updated_at = time.time()
    logger.error(
        f"🔒 Groq daily quota exhausted for [{model}] ({reason}). "
        "This is an organization/model limit; rotating keys will not help."
    )


_DEFAULT_RESET_HINT = (
    "Groq's free-tier budget refills continuously at about 8,333 tokens per "
    "hour per model — there is no daily reset to wait for. Re-run the same prompt "
    "after the reset, or add fresh GROQ_API_KEY values to .env and restart."
)


def _simulated_quota_limit() -> int:
    """
    Call count after which the simulated daily quota trips, or 0 when off.

    The env var is re-read on every call rather than frozen at import time so a
    test can flip the switch in-process without reloading the module.
    """
    try:
        return int(
            os.getenv(
                "GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS",
                str(GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS),
            )
        )
    except ValueError:
        return 0


def reset_simulated_quota() -> None:
    """Clear the simulated-call counter (tests, and between builds)."""
    global _simulated_call_count
    with _simulated_quota_lock:
        _simulated_call_count = 0


def _check_simulated_quota(model: str) -> None:
    """Raise a genuine GroqDailyQuotaError once the simulated budget is spent."""
    limit = _simulated_quota_limit()
    if limit <= 0:
        return
    with _simulated_quota_lock:
        spent = _simulated_call_count
    if spent < limit:
        return
    logger.warning(
        f"GROQ_SIMULATE_DAILY_QUOTA_AFTER_CALLS={limit} reached "
        f"({spent} successful calls); raising a simulated daily-quota error "
        f"for [{model}]."
    )
    _mark_model_daily_limited(model, "simulated")
    raise _make_quota_error(model, "simulated")


def _record_simulated_call() -> None:
    """Count one successful Groq call towards the simulated budget."""
    global _simulated_call_count
    if _simulated_quota_limit() <= 0:
        return
    with _simulated_quota_lock:
        _simulated_call_count += 1


def _make_quota_error(model: str, reason: str = "") -> GroqDailyQuotaError:
    """
    Build a fully-populated GroqDailyQuotaError for `model`.

    Phase 21: centralises the diagnostics so every raise site carries the same
    metadata (model, key counts, reset hint) for SESSION_CONTEXT.md.
    """
    with _exhausted_lock:
        total     = len(_groq_keys)
        exhausted = len(_exhausted_by_model.get(model, set()))
    message = (
        f"Groq daily quota exhausted for model [{model}]. "
        "Rotating API keys will not help because Groq rate limits apply at the "
        "organization/model level."
    )
    return GroqDailyQuotaError(
        message,
        model          = model,
        keys_total     = total,
        keys_exhausted = exhausted,
        reset_hint     = _DEFAULT_RESET_HINT,
        reason         = reason or "daily request/token quota",
    )


def is_quota_exhausted(model: Optional[str] = None) -> bool:
    """
    Phase 21: proactive quota check for the pipeline.

    model given  → True when that model is daily-limited or every key is
                   exhausted for it.
    model None   → True only when BOTH the heavy and fast models are dead,
                   i.e. no Groq call of any kind can succeed. This matches the
                   "fully_exhausted" semantics used by get_key_status().

    Returns False when no Groq keys are configured at all — in that case the
    provider routing in generate_text() decides, not the quota tracker.
    """
    if not _groq_keys:
        return False

    def _dead(m: str) -> bool:
        with _model_state_lock:
            state = _model_rate_states.get(m)
            if state is not None and state.daily_limited:
                return True
        with _exhausted_lock:
            exhausted = _exhausted_by_model.get(m, set())
            usable    = set(range(len(_groq_keys))) - exhausted - _invalid_keys
        return not usable

    if model:
        return _dead(model)
    return _dead(_HEAVY_MODEL) and _dead(_FAST_MODEL)


def get_quota_snapshot() -> dict:
    """
    Phase 21: serializable quota state embedded verbatim in SESSION_CONTEXT.md.

    Built from the existing get_key_status() / get_rate_limit_status() outputs
    so there is a single source of truth for these numbers.
    """
    keys  = get_key_status()
    rates = get_rate_limit_status()
    return {
        "captured_at":       datetime.now().isoformat(timespec="seconds"),
        "provider":          LLM_PROVIDER,
        "heavy_model":       _HEAVY_MODEL,
        "fast_model":        _FAST_MODEL,
        "total_keys":        keys["total_keys"],
        "available_keys":    keys["available_keys"],
        "exhausted_keys":    keys["exhausted_keys"],
        "exhausted_heavy":   keys["exhausted_70b"],
        "exhausted_fast":    keys["exhausted_8b"],
        "fully_exhausted":   keys["fully_exhausted"],
        "heavy_exhausted":   is_quota_exhausted(_HEAVY_MODEL),
        "fast_exhausted":    is_quota_exhausted(_FAST_MODEL),
        "all_exhausted":     is_quota_exhausted(),
        "any_daily_limited": rates["any_daily_limited"],
        "models":            rates["models"],
        # Phase 23: how much of the per-model daily budget this process has
        # spent. Groq reports the daily limit only in the 429 that enforces it,
        # so a handoff document that says "quota exhausted" could not previously
        # say how much had been used or when any of it comes back.
        "daily_usage":       get_daily_usage(),
        "reset_hint":        _DEFAULT_RESET_HINT,
    }


def _record_per_minute_wait(key: str, wait_secs: float):
    with _exhausted_lock:
        try:
            _per_minute_wait[_groq_keys.index(key)] = wait_secs
        except ValueError:
            pass


def _clear_per_minute_wait(key: str):
    with _exhausted_lock:
        try:
            _per_minute_wait.pop(_groq_keys.index(key), None)
        except ValueError:
            pass


def _reset_exhausted():
    """Reset ALL exhaustion across ALL models (called by /admin/reset-keys)."""
    with _exhausted_lock:
        total_cleared = sum(len(s) for s in _exhausted_by_model.values())
        _exhausted_by_model.clear()
        _per_minute_wait.clear()
        _invalid_keys.clear()
    with _model_state_lock:
        for state in _model_rate_states.values():
            state.cooldown_until = 0.0
            state.last_rate_limit_reason = ""
            state.last_wait_seconds = 0.0
            state.daily_limited = False
    logger.info(
        f"🔑 Reset {total_cleared} model-key exhaustion entries — "
        f"all {len(_groq_keys)} keys available for all models."
    )


def get_key_status() -> dict:
    """
    Return key exhaustion status for the FloatingStatus UI component and
    the /health + /admin/reset-keys endpoints.

    BUG FIX v3.6.1 (Gap B):
      Old: exhausted_keys = len(exhausted_heavy & exhausted_fast)
           → Only counted keys exhausted on BOTH models.
           → If all keys were exhausted on 70b but none on 8b, counter = 0
             → "Reset Keys" button never appeared even when builds were failing.

      New: exhausted_keys = len(exhausted_heavy | exhausted_fast)
           → Counts any key exhausted on AT LEAST ONE model.
           → Reset button appears as soon as any key hits any model limit.

      Additionally: two breakdown fields are now returned so the UI can
      distinguish "completely done" from "70b done, 8b still fine":
        "exhausted_70b": number of keys exhausted on the heavy model
        "exhausted_8b":  number of keys exhausted on the fast model
    """
    with _exhausted_lock:
        exhausted_heavy = _exhausted_by_model.get(_HEAVY_MODEL, set())
        exhausted_fast  = _exhausted_by_model.get(_FAST_MODEL,  set())

        # Union: any key exhausted on at least one model
        any_exhausted = exhausted_heavy | exhausted_fast
        # Intersection: keys exhausted on both (truly dead)
        fully_exhausted = exhausted_heavy & exhausted_fast

        total     = len(_groq_keys)
        # "available" = can be used on at least one model
        available = total - len(fully_exhausted)

        keys_info = []
        for i, k in enumerate(_groq_keys):
            h_ex = i in exhausted_heavy
            f_ex = i in exhausted_fast
            if i in _invalid_keys:
                status = "invalid"
            elif h_ex and f_ex:
                status = "exhausted"
            elif h_ex:
                status = "exhausted_70b_only"
            elif f_ex:
                status = "exhausted_8b_only"
            else:
                status = "available"
            keys_info.append({"suffix": f"...{k[-8:]}", "status": status})

    return {
        "total_keys":     total,
        "available_keys": available,
        # BUG FIX v3.6.1: union count so FloatingStatus reset button appears correctly
        "exhausted_keys": len(any_exhausted),
        # Breakdown fields for informative UI messages
        "exhausted_70b":  len(exhausted_heavy),
        "exhausted_8b":   len(exhausted_fast),
        "fully_exhausted": len(fully_exhausted),
        "keys":           keys_info,
    }


# ── 429 classification (unchanged from v3.5.0) ────────────────────────────────

def get_rate_limit_status() -> dict:
    """Expose Groq model cooldown/token state for /health and the UI."""
    now = time.time()
    with _model_state_lock:
        models = []
        for model, state in _model_rate_states.items():
            reset_tokens_seconds = max(0.0, state.reset_tokens_at - now)
            reset_requests_seconds = max(0.0, state.reset_requests_at - now)
            cooldown_seconds = max(0.0, state.cooldown_until - now)
            models.append({
                "model": model,
                "limit_tokens": state.limit_tokens,
                "remaining_tokens": state.remaining_tokens,
                "reset_tokens_seconds": round(reset_tokens_seconds, 1),
                "limit_requests": state.limit_requests,
                "remaining_requests": state.remaining_requests,
                "reset_requests_seconds": round(reset_requests_seconds, 1),
                "cooldown_seconds": round(cooldown_seconds, 1),
                "last_rate_limit_reason": state.last_rate_limit_reason,
                "last_wait_seconds": round(state.last_wait_seconds, 1),
                "daily_limited": state.daily_limited,
                "updated_at": state.updated_at,
            })
    return {
        "models": sorted(models, key=lambda item: item["model"]),
        "max_cooldown_seconds": max(
            (m["cooldown_seconds"] for m in models),
            default=0.0,
        ),
        "any_daily_limited": any(m["daily_limited"] for m in models),
    }


def _classify_429(resp) -> RateLimitInfo:
    retry_after = _parse_wait_seconds(resp.headers.get("retry-after"))
    reset_tokens = _parse_wait_seconds(resp.headers.get("x-ratelimit-reset-tokens"))
    reset_requests = _parse_wait_seconds(resp.headers.get("x-ratelimit-reset-requests"))

    body_text = ""
    try:
        body_json = resp.json()
        err = body_json.get("error", {})
        body_text = " ".join(
            str(err.get(key, ""))
            for key in ("message", "type", "code")
        ).lower()
    except Exception:
        try:
            body_text = resp.text.lower()
        except Exception:
            body_text = ""

    message = body_text[:300]
    if any(phrase in body_text for phrase in _DAILY_LIMIT_PHRASES):
        return RateLimitInfo("daily_limit", 0.0, message)

    if any(phrase in body_text for phrase in _TOKEN_LIMIT_PHRASES):
        wait = retry_after if retry_after is not None else reset_tokens
        return RateLimitInfo("tpm_wait", wait if wait is not None else 5.0, message)

    if any(phrase in body_text for phrase in _REQUEST_LIMIT_PHRASES):
        wait = retry_after if retry_after is not None else reset_requests
        return RateLimitInfo("rpm_wait", wait if wait is not None else 5.0, message)

    wait = retry_after
    if wait is None:
        wait = reset_tokens if reset_tokens is not None else reset_requests
    return RateLimitInfo("unknown_rate_limit", wait if wait is not None else 5.0, message)


# ── Groq call (v3.6.0: passes model to all helper functions) ──────────────────

def _call_groq_legacy_unused(prompt: str, system: str, max_tokens: int, model: str) -> str:
    """
    Try every available Groq key for the given model.
    Per-minute 429  → wait and retry SAME key.
    Daily quota 429 → mark exhausted FOR THIS MODEL ONLY, rotate to next key.
    """
    import httpx

    tried_keys: set[str] = set()
    daily_quota_rotations = 0

    while True:
        key = _get_next_groq_key(model)  # v3.6.0: model-scoped
        if key is None:
            raise RuntimeError(
                f"All Groq keys are exhausted for model [{model}]. "
                f"Other models may still have quota. "
                f"Call POST /admin/reset-keys after daily limits reset."
            )

        if key in tried_keys:
            raise RuntimeError(
                f"All {len(tried_keys)} available Groq keys tried for [{model}] without success."
            )
        tried_keys.add(key)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        per_minute_retries     = 0
        MAX_PER_MINUTE_RETRIES = 3

        while per_minute_retries <= MAX_PER_MINUTE_RETRIES:
            try:
                with httpx.Client(timeout=60) as client:
                    resp = client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type":  "application/json",
                        },
                        json={
                            "model":       model,
                            "messages":    messages,
                            "max_tokens":  max_tokens,
                            "temperature": 0.2,
                        },
                    )

                if resp.status_code == 429:
                    classification, wait_secs = _classify_429(resp)
                    if classification == "daily_quota":
                        _mark_groq_exhausted(key, model, reason="daily quota")  # v3.6.0
                        daily_quota_rotations += 1
                        if (
                            MAX_DAILY_QUOTA_ROTATIONS_PER_CALL > 0
                            and daily_quota_rotations >= MAX_DAILY_QUOTA_ROTATIONS_PER_CALL
                        ):
                            raise RuntimeError(
                                f"Daily quota hit on {daily_quota_rotations} key(s) for model "
                                f"[{model}] in one call. Stopping rotation early so remaining "
                                f"keys are preserved for later calls."
                            )
                        logger.info(f"🔁 Rotating to next key for [{model}]...")
                        break  # try next key
                    else:
                        _record_per_minute_wait(key, wait_secs)
                        actual_wait = min(wait_secs, MAX_PER_MINUTE_WAIT) + 0.5
                        logger.info(
                            f"⏳ Key ...{key[-8:]} rate-limited {actual_wait:.1f}s "
                            f"(per-minute on [{model}], retry {per_minute_retries+1}/"
                            f"{MAX_PER_MINUTE_RETRIES})"
                        )
                        time.sleep(actual_wait)
                        per_minute_retries += 1
                        tried_keys.discard(key)
                        continue

                resp.raise_for_status()

                _clear_per_minute_wait(key)
                data  = resp.json()
                usage = data.get("usage", {})
                if usage:
                    _add_tokens(
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                        model,
                    )
                return data["choices"][0]["message"]["content"]

            except RuntimeError:
                raise

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    classification, wait_secs = _classify_429(e.response)
                    if classification == "daily_quota":
                        _mark_groq_exhausted(key, model, reason="daily quota (HTTPStatusError)")
                        daily_quota_rotations += 1
                        if (
                            MAX_DAILY_QUOTA_ROTATIONS_PER_CALL > 0
                            and daily_quota_rotations >= MAX_DAILY_QUOTA_ROTATIONS_PER_CALL
                        ):
                            raise RuntimeError(
                                f"Daily quota hit on {daily_quota_rotations} key(s) for model "
                                f"[{model}] in one call. Stopping rotation early so remaining "
                                f"keys are preserved for later calls."
                            )
                        break
                    else:
                        actual_wait = min(wait_secs, MAX_PER_MINUTE_WAIT) + 0.5
                        logger.info(f"⏳ Key ...{key[-8:]} rate-limited {actual_wait:.1f}s")
                        time.sleep(actual_wait)
                        per_minute_retries += 1
                        tried_keys.discard(key)
                        continue
                logger.warning(
                    f"⚠️  Groq HTTP error ({e.response.status_code}) on key ...{key[-8:]}: {e}"
                )
                break

            except httpx.TimeoutException:
                logger.warning(f"⚠️  Groq timeout on key ...{key[-8:]}, trying next")
                break

            except Exception as e:
                logger.warning(f"⚠️  Groq unexpected error on key ...{key[-8:]}: {e}")
                break

        if per_minute_retries > MAX_PER_MINUTE_RETRIES:
            logger.warning(
                f"⚠️  Key ...{key[-8:]} exceeded {MAX_PER_MINUTE_RETRIES} per-minute retries "
                f"on [{model}] — rotating"
            )


# ── Ollama fallback (unchanged from v3.5.0) ───────────────────────────────────

def _call_groq(prompt: str, system: str, max_tokens: int, model: str) -> str:
    """
    Groq call path with organization/model-aware throttling.

    Temporary TPM/RPM 429s wait on a per-model cooldown and retry without
    marking keys exhausted. Keys are rotated only for real key failures such
    as 401/403. Daily TPD/RPD limits stop immediately because Groq applies
    those limits at the organization/model level.
    """
    import httpx

    tried_keys: set[str] = set()
    temporary_rate_retries = 0
    model_lock = _get_model_lock(model)
    retry_key: Optional[str] = None

    # Phase 23: the budget the *caller* asked for, kept separate from the
    # per-attempt figure. `_fit_output_budget_to_model_limit` used to assign
    # straight back into `max_tokens`, so every retry re-shrank an already
    # shrunken number and the budget ratcheted downwards across a single call.
    requested_max_tokens = max_tokens
    truncation_retries = 0
    best_content = ""

    with model_lock:
        while True:
            key = retry_key or _get_next_groq_key(model)
            retry_key = None
            if key is None:
                # Phase 23: the old message conflated two very different causes,
                # and the exception type followed the message rather than the
                # cause. When the reason is the daily quota, this must be a
                # GroqDailyQuotaError — otherwise a build submitted *after* the
                # quota is gone dies as a bare RuntimeError, the Phase 21
                # interception never sees it, and the user gets status `failed`
                # with a NULL reason, no SESSION_CONTEXT.md and a 400 on the
                # download. A build that hits the same wall mid-flight gets the
                # full graceful handoff. Same condition, same cause, only the
                # timing differs — so it gets the same error.
                with _model_state_lock:
                    state = _model_rate_states.get(model)
                    daily_limited = bool(state and state.daily_limited)
                    reason = (state.last_rate_limit_reason if state else "") or "daily quota"
                if daily_limited:
                    raise _make_quota_error(model, reason)
                raise RuntimeError(
                    f"No usable Groq keys remain for model [{model}]. "
                    "Every key failed authentication (401/403) for this model."
                )
            if key in tried_keys:
                raise RuntimeError(
                    f"All {len(tried_keys)} usable Groq keys tried for [{model}] without success."
                )
            tried_keys.add(key)

            _check_simulated_quota(model)

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            try:
                max_tokens = _fit_output_budget_to_model_limit(
                    model, prompt, system, requested_max_tokens
                )
                estimated_tokens = _estimate_tokens(prompt, system, max_tokens)
                _wait_for_model_capacity(model, estimated_tokens)

                with httpx.Client(timeout=60) as client:
                    resp = client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type":  "application/json",
                        },
                        json=_build_groq_payload(model, messages, max_tokens),
                    )
                _update_rate_state_from_headers(model, resp.headers)

                if resp.status_code == 429:
                    info = _classify_429(resp)
                    if info.kind == "daily_limit":
                        reason = info.message or "daily request/token quota"
                        _mark_model_daily_limited(model, reason)
                        raise _make_quota_error(model, reason)

                    temporary_rate_retries += 1
                    if temporary_rate_retries > GROQ_RATE_LIMIT_MAX_RETRIES:
                        raise GroqRateLimitError(
                            f"Groq [{model}] stayed rate-limited after "
                            f"{GROQ_RATE_LIMIT_MAX_RETRIES} retries."
                        )
                    wait_secs = max(0.5, info.wait_seconds)
                    _set_model_cooldown(model, info.kind, wait_secs)
                    logger.warning(
                        f"Groq [{model}] temporary {info.kind}; waiting "
                        f"{min(wait_secs, GROQ_RATE_LIMIT_MAX_WAIT_SECONDS):.1f}s "
                        "for token/request reset without marking keys exhausted."
                    )
                    retry_key = key
                    tried_keys.discard(key)
                    continue

                if resp.status_code in (401, 403):
                    _mark_key_invalid(key, reason=f"HTTP {resp.status_code}")
                    continue

                resp.raise_for_status()

                _clear_per_minute_wait(key)
                _record_simulated_call()
                data = resp.json()
                usage = data.get("usage", {})
                if usage:
                    _add_tokens(
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                        model,
                    )

                choice  = data["choices"][0]
                content = choice["message"]["content"] or ""
                if len(content) > len(best_content):
                    best_content = content

                # Phase 23: the model ran out of room mid-answer. Returning this
                # hands the caller a syntax error dressed up as a file.
                if choice.get("finish_reason") == "length":
                    if truncation_retries < GROQ_TRUNCATION_MAX_RETRIES:
                        truncation_retries += 1
                        # Double the EFFECTIVE cap, not the requested one. A
                        # reasoning model without `reasoning_effort` support has
                        # its cap raised to _REASONING_MIN_TOKENS on the way out,
                        # so doubling the request could leave the payload
                        # unchanged: the Reviewer asked for 600, the floor made it
                        # 1600, the retry asked for 1200 — and the floor made that
                        # 1600 too. A byte-identical call, billed in full. Seen
                        # twice in the 2026-08-28 matrix.
                        effective = _apply_reasoning_budget(model, requested_max_tokens)
                        bumped = max(
                            requested_max_tokens + 1,
                            int(effective * GROQ_TRUNCATION_BUDGET_MULTIPLIER),
                        )
                        # Zero content with finish_reason=length is not truncated
                        # code, it is no code at all — the whole budget went on
                        # hidden reasoning. Different cause, different fix.
                        shape = (
                            "spent its entire budget on reasoning and returned no "
                            "content" if not content.strip()
                            else f"returned {len(content)} chars before running out"
                        )
                        logger.warning(
                            f"✂️  Groq [{model}] hit its output budget "
                            f"(finish_reason=length): {shape}. "
                            f"Retrying with max_tokens {requested_max_tokens} → {bumped} "
                            f"(attempt {truncation_retries}/{GROQ_TRUNCATION_MAX_RETRIES}) "
                            "rather than returning truncated code."
                        )
                        requested_max_tokens = bumped
                        retry_key = key
                        tried_keys.discard(key)
                        continue

                    # Out of retries. The longest answer seen is the least-bad
                    # option, and saying so plainly beats a silent syntax error.
                    logger.error(
                        f"✂️  Groq [{model}] still truncating after "
                        f"{GROQ_TRUNCATION_MAX_RETRIES} budget increases "
                        f"(max_tokens={requested_max_tokens}). Returning the longest "
                        "response received; expect a syntax error downstream."
                    )
                    return best_content

                return content

            except GroqRateLimitError:
                raise
            except httpx.HTTPStatusError as e:
                _update_rate_state_from_headers(model, e.response.headers)
                if e.response.status_code == 429:
                    info = _classify_429(e.response)
                    if info.kind == "daily_limit":
                        reason = info.message or "daily request/token quota"
                        _mark_model_daily_limited(model, reason)
                        raise _make_quota_error(model, reason)
                    temporary_rate_retries += 1
                    if temporary_rate_retries > GROQ_RATE_LIMIT_MAX_RETRIES:
                        raise GroqRateLimitError(
                            f"Groq [{model}] stayed rate-limited after "
                            f"{GROQ_RATE_LIMIT_MAX_RETRIES} retries."
                        )
                    wait_secs = max(0.5, info.wait_seconds)
                    _set_model_cooldown(model, info.kind, wait_secs)
                    retry_key = key
                    tried_keys.discard(key)
                    continue
                if e.response.status_code in (401, 403):
                    _mark_key_invalid(key, reason=f"HTTP {e.response.status_code}")
                    continue
                logger.warning(
                    f"Groq HTTP error ({e.response.status_code}) on key ...{key[-8:]}: {e}"
                )
                continue
            except httpx.TimeoutException:
                logger.warning(f"Groq timeout on key ...{key[-8:]}, trying next")
                continue
            except Exception as e:
                logger.warning(f"Groq unexpected error on key ...{key[-8:]}: {e}")
                continue


def _call_ollama(prompt: str, system: str) -> str:
    import httpx

    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = _get_config(
        "OLLAMA_MODEL",
        os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M"),
    )
    max_tokens = _get_config("OLLAMA_MAX_TOKENS", 1500)

    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    logger.info(f"🦙 Calling Ollama ({ollama_model}, max_tokens={max_tokens})...")

    try:
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=5.0)
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{ollama_url}/api/generate",
                json={
                    "model":   ollama_model,
                    "prompt":  full_prompt,
                    "stream":  False,
                    "options": {"num_predict": max_tokens},
                },
            )
        resp.raise_for_status()
        return resp.json().get("response", "")

    except httpx.ConnectError as e:
        raise RuntimeError(
            f"Ollama connection refused at {ollama_url}. "
            "Make sure Ollama is running: `ollama serve`"
        ) from e

    except (httpx.ReadTimeout, httpx.TimeoutException) as e:
        raise RuntimeError(
            "Ollama call timed out after 300s. "
            "The model may be loading — try again, or set "
            "LLM_PROVIDER=groq in .env to disable the Ollama fallback."
        ) from e

    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Ollama returned HTTP {e.response.status_code}: {e.response.text[:200]}"
        ) from e


# ── Public interface ───────────────────────────────────────────────────────────

def _generate_text_legacy_unused(
    prompt:     str,
    system:     str = "",
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    agent_name: str = "",
) -> str:
    """
    Generate text via Groq (per-model exhaustion, multi-key) with Ollama fallback.

    v3.6.0: Groq call uses model-scoped exhaustion so exhausting a key on
    llama-3.3-70b does NOT block subsequent fast-model (llama-3.1-8b) calls.

    agent_name  — selects model (heavy vs fast) and token budget.
    max_tokens  — defaults to per-agent budget from AGENT_TOKEN_BUDGETS.
    """
    model = get_model_for_agent(agent_name) if agent_name else _FAST_MODEL

    if _groq_keys:
        try:
            logger.debug(
                f"📡 [{agent_name or 'generic'}] model={model} max_tokens={max_tokens}"
            )
            return _call_groq(prompt, system, max_tokens, model)
        except RuntimeError as e:
            err_msg = str(e)
            if model == _HEAVY_MODEL and _FAST_MODEL != _HEAVY_MODEL:
                logger.warning(
                    f"⚠️  Heavy model [{_HEAVY_MODEL}] unavailable for "
                    f"[{agent_name or 'generic'}]: {err_msg}"
                )
                try:
                    logger.warning(
                        f"↘️  Retrying [{agent_name or 'generic'}] on fast model "
                        f"[{_FAST_MODEL}] before using Ollama."
                    )
                    return _call_groq(prompt, system, max_tokens, _FAST_MODEL)
                except Exception as fast_exc:
                    logger.warning(f"⚠️  Fast-model retry also failed: {fast_exc}")
            else:
                logger.warning(f"⚠️  All Groq keys exhausted or failed: {err_msg}")
        except Exception as e:
            logger.warning(f"⚠️  Groq call failed unexpectedly: {e}")
    else:
        logger.info("ℹ️  No Groq keys configured, going straight to Ollama")

    logger.warning("🦙 Falling back to Ollama (expect slower responses)")
    for attempt in range(1, 3):
        try:
            return _call_ollama(prompt, system)
        except RuntimeError as e:
            err_msg = str(e)
            if "timed out" in err_msg and attempt == 1:
                logger.warning(f"🦙 Ollama timed out on attempt {attempt}, retrying once...")
                continue
            raise RuntimeError(
                f"Ollama call failed: {err_msg}\n"
                "Make sure Ollama is running (ollama serve) or set "
                "LLM_PROVIDER=groq in your .env to disable the Ollama fallback."
            ) from None

    raise RuntimeError("Ollama failed after 2 attempts")


def generate_text(
    prompt:     str,
    system:     str = "",
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    agent_name: str = "",
) -> str:
    """
    Generate text with explicit provider semantics.

    LLM_PROVIDER=groq is Groq-only: no Ollama fallback, and temporary Groq
    rate limits are surfaced as waits/retries rather than fake key exhaustion.
    LLM_PROVIDER=both may use Ollama only after non-rate-limit Groq failures.
    """
    model = get_model_for_agent(agent_name) if agent_name else _FAST_MODEL

    if LLM_PROVIDER == "ollama":
        logger.info("LLM_PROVIDER=ollama; using Ollama directly")
        return _call_ollama(prompt, system)

    if not _groq_keys:
        if LLM_PROVIDER == "groq":
            raise RuntimeError(
                "LLM_PROVIDER=groq but no Groq API keys are configured. "
                "Add GROQ_API_KEY values to .env and restart the server."
            )
        logger.info("No Groq keys configured, going straight to Ollama")
        return _call_ollama(prompt, system)

    try:
        logger.debug(f"[{agent_name or 'generic'}] model={model} max_tokens={max_tokens}")
        return _call_groq(prompt, system, max_tokens, model)

    # ── Phase 21: preserve the quota exception TYPE ───────────────────────────
    # Previously this branch was folded into the generic GroqRateLimitError
    # handler below, which re-raised a plain RuntimeError(...) from None. That
    # destroyed the GroqDailyQuotaError type at the boundary, so the pipeline
    # could not tell "daily quota dead, hand off gracefully" apart from "this
    # step failed, retry it". GroqDailyQuotaError already subclasses
    # RuntimeError, so every existing `except RuntimeError` caller is unaffected.
    #
    # When the heavy model is quota-dead but the fast model still has budget we
    # retry there first — a dead 70b must not end a build that 8b can finish.
    except GroqDailyQuotaError as quota_exc:
        if model == _HEAVY_MODEL and _FAST_MODEL != _HEAVY_MODEL and not is_quota_exhausted(_FAST_MODEL):
            logger.warning(
                f"Heavy model [{_HEAVY_MODEL}] is quota-exhausted for "
                f"[{agent_name or 'generic'}]; retrying on fast model [{_FAST_MODEL}]."
            )
            try:
                return _call_groq(prompt, system, max_tokens, _FAST_MODEL)
            except GroqDailyQuotaError as fast_quota_exc:
                logger.error(f"Fast model also quota-exhausted: {fast_quota_exc}")
                raise
            except Exception as fast_exc:
                # Heavy is quota-dead but fast failed for an unrelated reason.
                # Surfacing the quota error here would tell the pipeline that
                # ALL models are dead, which is not true — report the real cause.
                logger.warning(f"Fast-model retry after heavy quota failure: {fast_exc}")
                raise RuntimeError(
                    f"Heavy model [{_HEAVY_MODEL}] quota-exhausted; fast-model "
                    f"retry failed with: {fast_exc}"
                ) from None
        # Phase 23: the mirror of the branch above, and now the one that fires.
        #
        # Each model has its OWN 200K tokens-per-day allowance. Under the split
        # routing the fast model carries the high-frequency agents and is the
        # first to run out, while the heavy model's separate budget may be
        # largely unspent — and without this the build would die anyway, with
        # half the day's tokens still on the table. Small structured work moving
        # to the bigger model costs nothing in quality.
        if model == _FAST_MODEL and _HEAVY_MODEL != _FAST_MODEL and not is_quota_exhausted(_HEAVY_MODEL):
            logger.warning(
                f"Fast model [{_FAST_MODEL}] is quota-exhausted for "
                f"[{agent_name or 'generic'}]; retrying on heavy model "
                f"[{_HEAVY_MODEL}], which has its own daily budget."
            )
            try:
                return _call_groq(prompt, system, max_tokens, _HEAVY_MODEL)
            except GroqDailyQuotaError as heavy_quota_exc:
                logger.error(f"Heavy model also quota-exhausted: {heavy_quota_exc}")
                raise
            except Exception as heavy_exc:
                logger.warning(f"Heavy-model retry after fast quota failure: {heavy_exc}")
                raise RuntimeError(
                    f"Fast model [{_FAST_MODEL}] quota-exhausted; heavy-model "
                    f"retry failed with: {heavy_exc}"
                ) from None

        logger.error(f"Groq daily quota exhausted for [{model}]: {quota_exc}")
        raise

    except GroqRateLimitError as e:
        logger.error(f"Groq rate limit for [{model}]: {e}")
        raise RuntimeError(
            f"Groq-only rate limit for model [{model}]: {e}"
        ) from None
    except Exception as groq_exc:
        err_msg = str(groq_exc)
        if model == _HEAVY_MODEL and _FAST_MODEL != _HEAVY_MODEL:
            logger.warning(
                f"Heavy model [{_HEAVY_MODEL}] failed for "
                f"[{agent_name or 'generic'}]: {err_msg}"
            )
            try:
                logger.warning(
                    f"Retrying [{agent_name or 'generic'}] on Groq fast model "
                    f"[{_FAST_MODEL}] before any fallback."
                )
                return _call_groq(prompt, system, max_tokens, _FAST_MODEL)
            except GroqDailyQuotaError:
                # Phase 21: keep the type — both models are now quota-dead.
                raise
            except GroqRateLimitError as fast_rate_exc:
                logger.error(f"Groq fast model rate limit: {fast_rate_exc}")
                raise RuntimeError(
                    f"Groq-only rate limit for fast model [{_FAST_MODEL}]: {fast_rate_exc}"
                ) from None
            except Exception as fast_exc:
                logger.warning(f"Groq fast-model retry also failed: {fast_exc}")
                err_msg = f"{err_msg}; fast retry failed: {fast_exc}"

        if LLM_PROVIDER == "groq":
            raise RuntimeError(
                "LLM_PROVIDER=groq is enabled, so Ollama fallback is disabled. "
                f"Groq failed with: {err_msg}"
            ) from None

    logger.warning("Falling back to Ollama after non-rate-limit Groq failure")
    for attempt in range(1, 3):
        try:
            return _call_ollama(prompt, system)
        except RuntimeError as e:
            err_msg = str(e)
            if "timed out" in err_msg and attempt == 1:
                logger.warning(f"Ollama timed out on attempt {attempt}, retrying once...")
                continue
            raise RuntimeError(
                f"Ollama call failed: {err_msg}\n"
                "Make sure Ollama is running (ollama serve) or set "
                "LLM_PROVIDER=groq in your .env to disable the Ollama fallback."
            ) from None

    raise RuntimeError("Ollama failed after 2 attempts")


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM responses."""
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$",          "", text, flags=re.MULTILINE)
    return text.strip()
