"""
llm_client.py  v3.2.0  (Phase 17 — token tracking)
====================================================
Changes vs v3.1:
  - Thread-safe per-build token accumulator (_token_store)
  - set_current_build_id(build_id) — call before pipeline starts
  - get_and_reset_token_usage(build_id) — call after pipeline ends
  - _add_tokens() — called inside _call_groq() after every successful response
  - All other behaviour identical to v3.1
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

_global_key_index: int = -1
_exhausted: set[int] = set()
_exhausted_lock = threading.Lock()

# ── Phase 17: Per-build token tracking ────────────────────────────────────────
# Maps build_id → {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
# Thread-safe: all reads/writes protected by _token_lock.
_token_store: dict[str, dict] = {}
_token_lock   = threading.Lock()
_current_build_id = threading.local()   # thread-local: which build is this thread serving


def set_current_build_id(build_id: str):
    """
    Register the build_id for the current thread so token usage is attributed correctly.
    Call this in runner._run_build() before creating the Pipeline.
    """
    _current_build_id.value = build_id
    with _token_lock:
        if build_id not in _token_store:
            _token_store[build_id] = {
                "prompt_tokens":     0,
                "completion_tokens": 0,
                "total_tokens":      0,
            }


def _add_tokens(prompt_tokens: int, completion_tokens: int):
    """
    Add token counts to the currently-running build's accumulator.
    Called after every successful Groq response inside _call_groq().
    No-op if no build_id is registered for this thread.
    """
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
    """
    Return the accumulated token usage for a build and remove it from the store.
    Call this in runner._run_build() after the pipeline completes.
    Returns zeros if no usage was recorded (e.g. Ollama-only builds).
    """
    with _token_lock:
        return _token_store.pop(
            build_id,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )


# ── Key helpers ────────────────────────────────────────────────────────────────

def _get_next_groq_key() -> Optional[str]:
    """
    Return the next available (non-exhausted) Groq key.
    Scans forward from _global_key_index through the full key list.
    Returns None only when every key is exhausted.
    Fix for Bug 1 (v3.1): index is advanced AFTER a key is selected.
    """
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
    logger.info(
        f"🔑 Reset {count} exhausted Groq key(s) — "
        f"all {len(_groq_keys)} valid keys available"
    )


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
    Phase 17: records token usage after every successful response.
    """
    import httpx

    groq_model = _get_config(
        "GROQ_MODEL", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    )
    tried: set[str] = set()

    while True:
        key = _get_next_groq_key()
        if key is None:
            raise RuntimeError(
                "All Groq keys are exhausted or invalid. "
                "Either wait for daily limits to reset or add more keys."
            )

        if key in tried:
            raise RuntimeError("All Groq keys tried without success")
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
                retry_after = resp.headers.get("retry-after", "")
                try:
                    wait_secs = float(retry_after)
                except (ValueError, TypeError):
                    wait_secs = None

                if wait_secs is not None and wait_secs <= 10:
                    import time
                    logger.info(
                        f"⏳ Key ...{key[-8:]} rate-limited for {wait_secs:.1f}s — waiting..."
                    )
                    time.sleep(wait_secs + 0.5)
                    tried.discard(key)
                    continue
                else:
                    _mark_groq_exhausted(key)
                    logger.info("🔁 Rotating to next Groq key...")
                    continue

            resp.raise_for_status()
            data = resp.json()

            # ── Phase 17: record token usage ──────────────────────────────────
            usage = data.get("usage", {})
            if usage:
                _add_tokens(
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )

            return data["choices"][0]["message"]["content"]

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                _mark_groq_exhausted(key)
                continue
            logger.warning(
                f"⚠️  Groq HTTP error ({e.response.status_code}) on key ...{key[-8:]}: {e}"
            )
            continue

        except httpx.TimeoutException:
            logger.warning(f"⚠️  Groq timeout on key ...{key[-8:]}, trying next")
            continue

        except Exception as e:
            logger.warning(f"⚠️  Groq unexpected error on key ...{key[-8:]}: {e}")
            continue


# ── Ollama call (last-resort fallback) ────────────────────────────────────────

def _call_ollama(prompt: str, system: str) -> str:
    """
    Call local Ollama instance.
    Timeout: connect=10s, read=300s (7B q4 on CPU can take 90-300s).
    """
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
    """
    if _groq_keys:
        try:
            return _call_groq(prompt, system, max_tokens)
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
                logger.warning(
                    f"🦙 Ollama timed out on attempt {attempt}, retrying once..."
                )
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
