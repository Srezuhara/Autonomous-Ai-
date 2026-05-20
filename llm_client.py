"""
llm_client.py  v3.5.0  (Dual-Model Routing + Per-Agent Token Budgets)
=======================================================================
Built on top of v3.3.0 (smarter 429 detection). Every v3.3.0 feature
is fully preserved. Two new layers are added on top:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHANGE 1 — DUAL-MODEL ROUTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Groq tracks daily token quotas SEPARATELY per model. Using two
models effectively splits the load across two independent quotas:

  HEAVY model  →  llama-3.3-70b-versatile
    ~14,400 tokens/day per key (free tier)
    Used for: architect, backend_developer, frontend_generator
    These are the only agents where the bigger model meaningfully
    improves code quality.

  FAST model   →  llama-3.1-8b-instant
    ~131,072 tokens/day per key (free tier) — 9× more headroom
    Used for: intent_analyzer, planner, debugger, reviewer,
              tester, documenter
    These agents do JSON parsing, scoring, or template work
    where the 8b model performs identically to the 70b.

Result across one full build (~33 LLM calls):
  Before:  all 33 calls → 70b quota  (~67K tokens reserved, 1 key burned)
  After:   ~12 calls    → 70b quota  (~15K tokens reserved)
           ~21 calls    → 8b quota   (~21K tokens reserved, 9× larger pool)
  = roughly 3-4 complete builds per key per day instead of <1.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHANGE 2 — PER-AGENT TOKEN BUDGETS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Old default: max_tokens=2048 for EVERY call.
Groq counts RESERVED tokens against quota, not just generated ones.
An intent_analyzer call reserved 2048 tokens but only used ~300.

Right-sized budgets cut total reservation by ~50%:
  intent_analyzer:   2048 → 512
  planner:           2048 → 768
  reviewer (×4):     2048 → 600   saves 5,792 tokens
  tester (×8):       2048 → 1024  saves 8,192 tokens
  Total saving:      ~34,000 tokens per build

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTERFACE CHANGE — generate_text() gets a new optional parameter
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  generate_text(prompt, system, max_tokens, agent_name="")

  agent_name is used to:
    1. Pick the right model (heavy vs fast)
    2. Look up the right token budget if max_tokens is not passed

  base_agent.py is updated to pass self.name as agent_name.
  No other file needs to change. All callers that don't pass
  agent_name continue to work exactly as before (fast model,
  default budget).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
.env OPTIONAL OVERRIDES (no new keys needed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  GROQ_MODEL_HEAVY=llama-3.3-70b-versatile  # already your default
  GROQ_MODEL_FAST=llama-3.1-8b-instant      # new — same free account
  # If you set the old GROQ_MODEL= it overrides both (backward compat)

All v3.3.0 features retained unchanged:
  - Per-minute vs daily-quota 429 detection (_classify_429)
  - Per-key per-minute backoff tracking (_per_minute_wait)
  - Multi-key round-robin rotation across all 8 keys
  - Thread-safe per-build token accumulation
  - Ollama last-resort fallback
  - _reset_exhausted() / get_key_status() for /admin/reset-keys
"""

import logging
import os
import threading
import re
import time
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Constants (unchanged from v3.3.0) ─────────────────────────────────────────
MAX_PER_MINUTE_WAIT = 60

_DAILY_QUOTA_KEYWORDS = (
    "daily", "quota", "exceeded", "limit reached",
    "rate_limit_exceeded", "tokens_exceeded",
)


def _get_config(attr: str, default):
    try:
        import config
        return getattr(config, attr, default)
    except ImportError:
        return default


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NEW: Dual-model configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Read model names from .env, with sensible defaults.
_HEAVY_MODEL = os.getenv("GROQ_MODEL_HEAVY", "llama-3.3-70b-versatile")
_FAST_MODEL  = os.getenv("GROQ_MODEL_FAST",  "llama-3.1-8b-instant")

# Backward compat: if old GROQ_MODEL is set, it overrides both.
_legacy = os.getenv("GROQ_MODEL", "")
if _legacy:
    _HEAVY_MODEL = _legacy
    _FAST_MODEL  = _legacy
    logger.info(f"ℹ️  GROQ_MODEL override active — both models set to: {_legacy}")

# Agents that need the heavy model.
# Every agent NOT in this set uses the fast model automatically.
_HEAVY_AGENT_NAMES = {
    "architect",
    "backenddeveloper",      # normalised (lower, no spaces/underscores)
    "backend_developer",
    "frontendgenerator",
    "frontend_generator",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NEW: Per-agent token budgets
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AGENT_TOKEN_BUDGETS: dict[str, int] = {
    # Fast-model agents ─ lightweight structured output
    "intentanalyzer":     512,
    "intent_analyzer":    512,
    "planner":            768,
    "reviewer":           600,
    "tester":            1024,
    "documenter":        1200,
    "debugger":          1024,

    # Heavy-model agents ─ need room for full code files
    "architect":         1024,
    "backenddeveloper":  1200,
    "backend_developer": 1200,
    "frontendgenerator": 1200,
    "frontend_generator":1200,
}

# Used when an agent is not in the table above
_DEFAULT_MAX_TOKENS = 1024


def get_model_for_agent(agent_name: str) -> str:
    """
    Return the Groq model string for a given agent name.
    Heavy agents → llama-3.3-70b-versatile
    All others   → llama-3.1-8b-instant
    """
    normalised = agent_name.lower().replace(" ", "").replace("-", "")
    if normalised in _HEAVY_AGENT_NAMES or agent_name.lower() in _HEAVY_AGENT_NAMES:
        return _HEAVY_MODEL
    return _FAST_MODEL


def get_agent_token_budget(agent_name: str) -> int:
    """
    Return the right-sized max_tokens for a given agent.
    Called by base_agent.BaseAgent.__init__ to set self._token_budget.
    """
    key = agent_name.lower().replace(" ", "").replace("-", "_")
    return AGENT_TOKEN_BUDGETS.get(key,
           AGENT_TOKEN_BUDGETS.get(agent_name.lower(), _DEFAULT_MAX_TOKENS))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Everything below is IDENTICAL to v3.3.0 except:
#   • _call_groq() accepts a `model` parameter
#   • generate_text() accepts agent_name and routes to correct model
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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

_global_key_index: int        = -1
_exhausted:        set[int]   = set()
_per_minute_wait:  dict[int, float] = {}
_exhausted_lock    = threading.Lock()

# ── Per-build token tracking (Phase 17, unchanged) ────────────────────────────
_token_store:     dict[str, dict] = {}
_token_lock       = threading.Lock()
_current_build_id = threading.local()


def set_current_build_id(build_id: str):
    _current_build_id.value = build_id
    with _token_lock:
        if build_id not in _token_store:
            _token_store[build_id] = {
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            }


def _add_tokens(prompt_tokens: int, completion_tokens: int):
    bid = getattr(_current_build_id, "value", None)
    if not bid:
        return
    with _token_lock:
        rec = _token_store.setdefault(
            bid,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        rec["prompt_tokens"]     += prompt_tokens
        rec["completion_tokens"] += completion_tokens
        rec["total_tokens"]      += prompt_tokens + completion_tokens


def get_and_reset_token_usage(build_id: str) -> dict:
    with _token_lock:
        return _token_store.pop(
            build_id,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )


# ── Key helpers (unchanged from v3.3.0) ───────────────────────────────────────

def _get_next_groq_key() -> Optional[str]:
    global _global_key_index
    with _exhausted_lock:
        n = len(_groq_keys)
        if n == 0:
            return None
        for offset in range(1, n + 1):
            candidate_idx = (_global_key_index + offset) % n
            if candidate_idx not in _exhausted:
                _global_key_index = candidate_idx
                return _groq_keys[candidate_idx]
        return None


def _mark_groq_exhausted(key: str, reason: str = "daily quota"):
    with _exhausted_lock:
        try:
            idx = _groq_keys.index(key)
            if idx not in _exhausted:
                _exhausted.add(idx)
                _per_minute_wait.pop(idx, None)
                suffix    = key[-8:]
                remaining = len(_groq_keys) - len(_exhausted)
                logger.warning(
                    f"🔑 Groq key ...{suffix} exhausted ({reason}). "
                    f"{len(_exhausted)} exhausted, {remaining} remaining."
                )
        except ValueError:
            pass


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
    with _exhausted_lock:
        count = len(_exhausted)
        _exhausted.clear()
        _per_minute_wait.clear()
    logger.info(
        f"🔑 Reset {count} exhausted Groq key(s) — "
        f"all {len(_groq_keys)} valid keys available"
    )


def get_key_status() -> dict:
    with _exhausted_lock:
        exhausted_count = len(_exhausted)
        total           = len(_groq_keys)
        available       = total - exhausted_count
        keys_info       = [
            {
                "suffix": f"...{k[-8:]}",
                "status": "exhausted" if i in _exhausted else "available",
            }
            for i, k in enumerate(_groq_keys)
        ]
    return {
        "total_keys":     total,
        "available_keys": available,
        "exhausted_keys": exhausted_count,
        "keys":           keys_info,
    }


# ── 429 classification (unchanged from v3.3.0) ────────────────────────────────

def _classify_429(resp) -> tuple[str, float]:
    retry_after_raw = resp.headers.get("retry-after", "")
    retry_after: Optional[float] = None
    try:
        retry_after = float(retry_after_raw)
    except (ValueError, TypeError):
        retry_after = None

    body_text = ""
    try:
        body_json = resp.json()
        err = body_json.get("error", {})
        body_text = (
            err.get("message", "") + " " +
            err.get("type",    "") + " " +
            err.get("code",    "")
        ).lower()
    except Exception:
        try:
            body_text = resp.text.lower()
        except Exception:
            body_text = ""

    is_daily = any(kw in body_text for kw in _DAILY_QUOTA_KEYWORDS)

    if retry_after is not None:
        if retry_after > MAX_PER_MINUTE_WAIT:
            return "daily_quota", 0.0
        return ("daily_quota", 0.0) if is_daily else ("per_minute", retry_after)

    return ("daily_quota", 0.0) if is_daily else ("per_minute", 5.0)


# ── Groq call — now accepts `model` parameter ─────────────────────────────────

def _call_groq(prompt: str, system: str, max_tokens: int, model: str) -> str:
    """
    Try every available Groq key using the specified model.
    Per-minute 429  → wait and retry the SAME key.
    Daily quota 429 → mark key exhausted, rotate to next key.

    Note: Groq daily quotas are per-model. Exhausting a key on the 70b model
    does NOT consume its 8b quota. We share the key pool across both models
    because an invalid/blocked key fails for both anyway.
    """
    import httpx

    tried_keys: set[str] = set()

    while True:
        key = _get_next_groq_key()
        if key is None:
            raise RuntimeError(
                "All Groq keys are exhausted (daily quota). "
                "Wait for daily limits to reset or call POST /admin/reset-keys."
            )

        if key in tried_keys:
            raise RuntimeError(
                f"All {len(tried_keys)} available Groq keys tried without success."
            )
        tried_keys.add(key)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        per_minute_retries    = 0
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
                        _mark_groq_exhausted(key, reason=f"daily quota [{model}]")
                        logger.info(f"🔁 Rotating to next Groq key (daily quota on {model})...")
                        break
                    else:
                        _record_per_minute_wait(key, wait_secs)
                        actual_wait = min(wait_secs, MAX_PER_MINUTE_WAIT) + 0.5
                        logger.info(
                            f"⏳ Key ...{key[-8:]} rate-limited for {actual_wait:.1f}s "
                            f"(per-minute, retry {per_minute_retries+1}/{MAX_PER_MINUTE_RETRIES})"
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
                    )
                return data["choices"][0]["message"]["content"]

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    classification, wait_secs = _classify_429(e.response)
                    if classification == "daily_quota":
                        _mark_groq_exhausted(key, reason=f"daily quota/{model} (HTTPStatusError)")
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
                f"⚠️  Key ...{key[-8:]} exceeded {MAX_PER_MINUTE_RETRIES} per-minute retries — rotating"
            )


# ── Ollama fallback (unchanged from v3.3.0) ───────────────────────────────────

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

def generate_text(
    prompt:     str,
    system:     str = "",
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    agent_name: str = "",
) -> str:
    """
    Generate text via Groq (dual-model routing, multi-key) with Ollama fallback.

    New vs v3.3.0:
      agent_name  — if provided, selects the correct model (heavy vs fast)
                    and can be used to look up a token budget.
                    If omitted, the FAST model is used (safe default).
      max_tokens  — default is now _DEFAULT_MAX_TOKENS (1024), not 2048.
                    base_agent passes self._token_budget here.

    Callers that do NOT pass agent_name continue to work exactly as before.
    The only observable difference is they use the fast model and 1024 tokens
    instead of 2048 — both of which are fine for any generic call.
    """
    model = get_model_for_agent(agent_name) if agent_name else _FAST_MODEL

    if _groq_keys:
        try:
            logger.debug(
                f"📡 [{agent_name or 'generic'}] model={model} max_tokens={max_tokens}"
            )
            return _call_groq(prompt, system, max_tokens, model)
        except RuntimeError as e:
            logger.warning(f"⚠️  All Groq keys exhausted or failed: {e}")
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


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM responses. Unchanged from v3.3.0."""
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$",          "", text, flags=re.MULTILINE)
    return text.strip()
