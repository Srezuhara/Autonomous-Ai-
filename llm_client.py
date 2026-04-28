"""
llm_client.py  v3.0.0  (Phase 15 + 16-Groq-only)
==================================================
Multi-key Groq rotation only — no OpenAI/Anthropic.
Ollama remains as last-resort fallback.

Provider chain:  Groq key 1 → 2 → ... → N → Ollama

Phase 15.3: Ollama responses capped at config.OLLAMA_MAX_TOKENS (default 600)
            to prevent 30-120s truncated JSON on reviewer/tester calls.

.env setup (add as many keys as you have):
  GROQ_API_KEY=gsk_key1
  GROQ_API_KEY_2=gsk_key2
  GROQ_API_KEY_3=gsk_key3
  ...up to GROQ_API_KEY_20

  OLLAMA_URL=http://localhost:11434   (optional, default shown)
  OLLAMA_MODEL=llama3                 (optional, default shown)

Key rotation behaviour:
  - Keys are tried round-robin on every call
  - A key is marked exhausted on HTTP 429 (daily limit hit)
  - All other errors (network, 5xx) cause immediate retry on next key
  - POST /admin/reset-keys resets exhausted set after midnight
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
_groq_index: int = 0
_exhausted: set[int] = set()          # indices of daily-limit-hit keys
_exhausted_lock = threading.Lock()


def _get_next_groq_key() -> Optional[str]:
    """
    Return the next available (non-exhausted) Groq key via round-robin.
    Returns None if all keys are exhausted.
    """
    global _groq_index
    with _exhausted_lock:
        available = [i for i in range(len(_groq_keys)) if i not in _exhausted]
        if not available:
            return None
        # Advance index within the available subset
        _groq_index = (_groq_index + 1) % len(available)
        return _groq_keys[available[_groq_index % len(available)]]


def _mark_groq_exhausted(key: str):
    """Mark a key as daily-limit exhausted so it's skipped on future calls."""
    with _exhausted_lock:
        try:
            idx = _groq_keys.index(key)
            if idx not in _exhausted:
                _exhausted.add(idx)
                suffix = key[-8:]
                remaining = len(_groq_keys) - len(_exhausted)
                logger.warning(
                    f"🔑 Groq key ...{suffix} exhausted "
                    f"({len(_exhausted)}/{len(_groq_keys)} done, {remaining} remaining)"
                )
        except ValueError:
            pass


def _reset_exhausted():
    """Reset all exhausted keys (call this after midnight when limits refresh)."""
    with _exhausted_lock:
        count = len(_exhausted)
        _exhausted.clear()
    logger.info(f"🔑 Reset {count} exhausted Groq key(s) — all {len(_groq_keys)} available")


def get_key_status() -> dict:
    """Return current key pool health — used by /health and /admin/reset-keys."""
    with _exhausted_lock:
        exhausted_count = len(_exhausted)
        total = len(_groq_keys)
        available = total - exhausted_count
        keys_info = [
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

    groq_model = _get_config("GROQ_MODEL", os.getenv("GROQ_MODEL", "llama3-70b-8192"))

    tried: set[str] = set()

    while True:
        key = _get_next_groq_key()
        if key is None:
            raise RuntimeError("All Groq keys exhausted — falling back to Ollama")

        if key in tried:
            # We've cycled through all available keys without success
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
                        "model": groq_model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.2,
                    },
                )

            if resp.status_code == 429:
                _mark_groq_exhausted(key)
                logger.info(f"🔁 Key exhausted, rotating to next Groq key...")
                continue   # retry immediately with next key

            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                _mark_groq_exhausted(key)
                continue
            logger.warning(f"⚠️  Groq HTTP error ({e.response.status_code}) on key ...{key[-8:]}: {e}")
            # Non-rate-limit HTTP errors: try next key
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
    Phase 15.3: response capped at OLLAMA_MAX_TOKENS (default 600) to
    prevent 30-120s waits and truncated JSON from reviewer/tester.
    """
    import httpx

    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = _get_config("OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "llama3"))
    max_tokens   = _get_config("OLLAMA_MAX_TOKENS", 600)   # Phase 15.3

    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    logger.info(f"🦙 Calling Ollama ({ollama_model}, max_tokens={max_tokens})...")
    with httpx.Client(timeout=180) as client:
        resp = client.post(
            f"{ollama_url}/api/generate",
            json={
                "model":  ollama_model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"num_predict": max_tokens},   # Phase 15.3 cap
            },
        )
    resp.raise_for_status()
    return resp.json().get("response", "")


# ── Public interface ───────────────────────────────────────────────────────────

def generate_text(prompt: str, system: str = "", max_tokens: int = 2048) -> str:
    """
    Generate text via Groq (multi-key rotation) with Ollama as last resort.

    Chain:  Groq key 1 → 2 → ... → N  →  Ollama

    All agents call this function — nothing else needs to change for
    provider switching.
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

    # Last resort: Ollama
    logger.warning("🦙 Falling back to Ollama (expect slower responses)")
    return _call_ollama(prompt, system)


def _strip_fences(text: str) -> str:
    """
    Remove markdown code fences from LLM responses.
    Called by BaseAgent.think() after every generate_text() call.

    Handles:
      ```python ... ```
      ```json ... ```
      ``` ... ```
    """
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()
