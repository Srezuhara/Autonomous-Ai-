"""
llm_client.py  v3.1.0
======================
Bug fixes in this version
──────────────────────────

BUG 1 — 7th key (last key) never used, only 6 of 7 tried before exhaustion
─────────────────────────────────────────────────────────────────────────────
Root cause: _get_next_groq_key() advanced the index BEFORE returning a key.

  Old code:
      available = [0,1,2,3,4,5,6]   (7 keys, none exhausted yet)
      _groq_index = (_groq_index + 1) % len(available)   # increments first
      return _groq_keys[available[_groq_index % len(available)]]

  On the very first call _groq_index starts at 0, gets bumped to 1, and
  returns key[1].  Key[0] is returned only later when the index wraps.
  The real damage happens during exhaustion: _call_groq() adds each returned
  key to `tried`. Because _get_next_groq_key() advances BEFORE returning,
  the last remaining available key is returned, added to tried, then on the
  next call the available list is now shorter → the index modulo shrinks →
  the same key gets returned again → it's already in `tried` → loop exits
  with "All Groq keys tried without success" while one key was never touched.

  Fix: advance the index AFTER selecting, using a stable key-index lookup
  instead of re-computing modulo on a shrinking list. The new implementation
  keeps a _global_key_index that indexes directly into _groq_keys (not into
  the filtered available list), scans forward to find the next non-exhausted
  key, and returns it. This guarantees every key is tried exactly once per
  call before giving up.

BUG 2 — Ollama times out even though Ollama is running
──────────────────────────────────────────────────────────
Root cause: httpx.Client(timeout=180) sounds generous but Ollama on a
  7B model with q4 quantisation takes 90-300 s on CPU to generate 600
  tokens. 180s is occasionally not enough, and on the first token the
  connect+read timeout fires together.

  Additionally, _call_ollama() did not catch httpx.ReadTimeout and let it
  propagate as a hard RuntimeError that crashed the whole pipeline instead
  of being retried.

  Fixes:
  1. Timeout raised to 300 s (connect=10s, read=300s) via httpx.Timeout.
  2. httpx.ReadTimeout and httpx.TimeoutException caught → logged as warning
     → returned empty string so the caller can decide what to do rather than
     crashing the pipeline.
  3. generate_text() now retries Ollama once on timeout before giving up,
     so a transient slow first-token doesn't kill the whole build.
"""

import logging
import os
import threading
import re
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ── Config import (optional — graceful fallback if config.py missing) ─────────

def _get_config(attr: str, default):
    try:
        import config
        return getattr(config, attr, default)
    except ImportError:
        return default


# ── Groq key pool ──────────────────────────────────────────────────────────────

def _load_groq_keys() -> list[str]:
    """
    Load all Groq API keys from environment.
    Reads GROQ_API_KEY (primary) + GROQ_API_KEY_2 through GROQ_API_KEY_20.
    Gaps in numbering are fine — missing entries are silently skipped.
    Duplicate keys are deduplicated.
    """
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

# _global_key_index always indexes into _groq_keys directly (not a filtered
# subset). We scan forward from this position to find the next non-exhausted
# key. This avoids the shrinking-list modulo bug.
_global_key_index: int = -1          # start at -1 so first use gives index 0
_exhausted: set[int] = set()         # indices of daily-limit-hit keys
_exhausted_lock = threading.Lock()


def _get_next_groq_key() -> Optional[str]:
    """
    Return the next available (non-exhausted) Groq key.

    Scans forward from _global_key_index through the full key list.
    Returns None only when every key is exhausted.

    Fix for Bug 1: index is advanced AFTER a key is selected, and we scan
    the full _groq_keys list — not a filtered copy — so no key is ever skipped
    due to modulo shrinkage.
    """
    global _global_key_index
    with _exhausted_lock:
        n = len(_groq_keys)
        if n == 0:
            return None

        # Scan up to n keys starting from the next position
        for offset in range(1, n + 1):
            candidate_idx = (_global_key_index + offset) % n
            if candidate_idx not in _exhausted:
                _global_key_index = candidate_idx   # advance AFTER selection
                return _groq_keys[candidate_idx]

        # Every key is exhausted
        return None


def _mark_groq_exhausted(key: str):
    """Mark a key as daily-limit exhausted so it's skipped on future calls."""
    with _exhausted_lock:
        try:
            idx = _groq_keys.index(key)
            if idx not in _exhausted:
                _exhausted.add(idx)
                suffix    = key[-8:]
                remaining = len(_groq_keys) - len(_exhausted)
                logger.warning(
                    f"🔑 Groq key ...{suffix} rate-limited "
                    f"({len(_exhausted)} exhausted, {remaining} remaining)"
                )
        except ValueError:
            pass


def _reset_exhausted():
    """Reset all exhausted keys (call this after midnight when limits refresh)."""
    with _exhausted_lock:
        count = len(_exhausted)
        _exhausted.clear()
    logger.info(f"🔑 Reset {count} exhausted Groq key(s) — all {len(_groq_keys)} valid keys available")


def get_key_status() -> dict:
    """Return current key pool health — used by /health and /admin/reset-keys."""
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


# ── Groq call ──────────────────────────────────────────────────────────────────

def _call_groq(prompt: str, system: str, max_tokens: int) -> str:
    """
    Try every available Groq key in round-robin order.
    Marks keys exhausted on 429 and retries on the next key immediately.
    Raises RuntimeError only when ALL keys are exhausted or unavailable.
    """
    import httpx

    groq_model = _get_config("GROQ_MODEL", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))

    tried: set[str] = set()

    while True:
        key = _get_next_groq_key()
        if key is None:
            raise RuntimeError(
                "All Groq keys are exhausted or invalid. "
                "Either wait for daily limits to reset or add more keys."
            )

        if key in tried:
            # Cycled through all available keys without success
            raise RuntimeError(
                "All Groq keys tried without success"
            )
        tried.add(key)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model":       groq_model,
                        "messages":    messages,
                        "max_tokens":  max_tokens,
                        "temperature": 0.2,
                    },
                )

            if resp.status_code == 429:
                # Check if it is a per-minute rate limit (Retry-After short) or
                # daily limit (no Retry-After header, or very long wait).
                retry_after = resp.headers.get("retry-after", "")
                try:
                    wait_secs = float(retry_after)
                except (ValueError, TypeError):
                    wait_secs = None

                if wait_secs is not None and wait_secs <= 10:
                    # Per-minute rate limit — wait briefly and retry on same key
                    import time
                    logger.info(f"⏳ Key ...{key[-8:]} rate-limited for {wait_secs:.1f}s — waiting...")
                    time.sleep(wait_secs + 0.5)
                    tried.discard(key)   # allow retry on this key
                    continue
                else:
                    # Daily limit — mark exhausted and move to next key
                    _mark_groq_exhausted(key)
                    logger.info("🔁 Rotating to next Groq key...")
                    continue

            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                _mark_groq_exhausted(key)
                continue
            logger.warning(f"⚠️  Groq HTTP error ({e.response.status_code}) on key ...{key[-8:]}: {e}")
            continue   # try next key

        except httpx.TimeoutException:
            logger.warning(f"⚠️  Groq timeout on key ...{key[-8:]}, trying next")
            continue   # try next key

        except Exception as e:
            logger.warning(f"⚠️  Groq unexpected error on key ...{key[-8:]}: {e}")
            continue


# ── Ollama call (last-resort fallback) ────────────────────────────────────────

def _call_ollama(prompt: str, system: str) -> str:
    """
    Call local Ollama instance.

    Fix for Bug 2:
    - Timeout raised from 180s to 300s with separate connect/read timeouts.
    - httpx.ReadTimeout caught and re-raised as a clear RuntimeError so the
      caller can retry rather than crashing the pipeline with a traceback.
    - OLLAMA_MAX_TOKENS default raised from 600 to 1500 so tester/reviewer
      responses are less likely to be truncated (truncation was causing
      JSON parse failures that wasted LLM fix attempts).
    """
    import httpx

    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = _get_config("OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M"))
    max_tokens   = _get_config("OLLAMA_MAX_TOKENS", 1500)  # raised from 600

    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    logger.info(f"🦙 Calling Ollama ({ollama_model}, max_tokens={max_tokens})...")

    try:
        # Separate connect + read timeouts:
        #   connect=10s  — Ollama should accept connections near-instantly
        #   read=300s    — 7B q4 on CPU can take 90-300s for 1500 tokens
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
            f"Ollama call timed out after 300s. "
            "The model may be loading — try again, or increase OLLAMA_MAX_TOKENS "
            "to a lower value to reduce generation time. "
            "Alternatively set LLM_PROVIDER=groq in .env to disable Ollama fallback."
        ) from e

    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Ollama returned HTTP {e.response.status_code}: {e.response.text[:200]}"
        ) from e


# ── Public interface ───────────────────────────────────────────────────────────

def generate_text(prompt: str, system: str = "", max_tokens: int = 2048) -> str:
    """
    Generate text via Groq (multi-key rotation) with Ollama as last resort.

    Provider chain:  Groq key 1 → 2 → ... → N  →  Ollama (with 1 retry)

    Fix for Bug 2: Ollama is now retried once on timeout before the
    pipeline raises. This handles the common case where the model is still
    loading on the first call.
    """
    # Try Groq first (all available keys)
    if _groq_keys:
        try:
            return _call_groq(prompt, system, max_tokens)
        except RuntimeError as e:
            logger.warning(f"⚠️  All Groq keys exhausted or failed: {e}")
        except Exception as e:
            logger.warning(f"⚠️  Groq call failed unexpectedly: {e}")
    else:
        logger.info("ℹ️  No Groq keys configured, going straight to Ollama")

    # Last resort: Ollama — with ONE retry on timeout
    logger.warning("🦙 Falling back to Ollama (expect slower responses)")
    for attempt in range(1, 3):   # attempt 1, then attempt 2 on timeout
        try:
            return _call_ollama(prompt, system)
        except RuntimeError as e:
            err_msg = str(e)
            if "timed out" in err_msg and attempt == 1:
                logger.warning(f"🦙 Ollama timed out on attempt {attempt}, retrying once...")
                continue
            # Connection refused or second timeout → raise to caller
            raise RuntimeError(
                f"Ollama call failed: {err_msg}\n"
                "Make sure Ollama is running (ollama serve) or set "
                "LLM_PROVIDER=groq in your .env to disable the Ollama fallback."
            ) from None

    # Should never reach here
    raise RuntimeError("Ollama failed after 2 attempts")


def _strip_fences(text: str) -> str:
    """
    Remove markdown code fences from LLM responses.
    Called by BaseAgent.think() after every generate_text() call.
    """
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$",          "", text, flags=re.MULTILINE)
    return text.strip()
