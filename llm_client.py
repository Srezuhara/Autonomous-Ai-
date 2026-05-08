"""
llm_client.py  v3.2.0
======================
Phase 15.4 addition
────────────────────
_validate_keys_on_startup() — probes each key with max_tokens=1 in a background
thread at import time. 401 keys are marked exhausted before any build runs,
saving 30–60 s of wasted retries on the first build.

Bug fixes from v3.1.0 retained:
  BUG 1 — last key skipped (index advanced before selection)
  BUG 2 — Ollama 180s timeout, ReadTimeout not caught
"""

import logging
import os
import threading
import re
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ── Config import (optional) ──────────────────────────────────────────────────

def _get_config(attr: str, default):
    try:
        import config
        return getattr(config, attr, default)
    except ImportError:
        return default


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
_exhausted: set[int] = set()
_exhausted_lock = threading.Lock()


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


def _mark_groq_exhausted(key: str):
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
    with _exhausted_lock:
        count = len(_exhausted)
        _exhausted.clear()
    logger.info(f"🔑 Reset {count} exhausted Groq key(s) — all {len(_groq_keys)} valid keys available")


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


# ── Phase 15.4 — Startup key validation ──────────────────────────────────────

def _validate_keys_on_startup() -> None:
    """
    Fire a minimal (max_tokens=1) request against each Groq key in a
    background daemon thread. Keys returning 401 are marked exhausted
    immediately so the first real build doesn't waste time on them.

    Does NOT block startup — runs completely in the background.
    Network failures are silently ignored (key stays valid by default).
    """
    def _probe():
        groq_model = _get_config(
            "GROQ_MODEL",
            os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        )
        for i, key in enumerate(_groq_keys):
            try:
                import httpx
                with httpx.Client(timeout=10) as c:
                    r = c.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": groq_model,
                            "messages": [{"role": "user", "content": "hi"}],
                            "max_tokens": 1,
                        },
                    )
                if r.status_code == 401:
                    with _exhausted_lock:
                        _exhausted.add(i)
                    logger.warning(
                        f"🔑 Key ...{key[-8:]} is INVALID (401) — marked exhausted at startup"
                    )
                elif r.status_code in (200, 429):
                    # 429 means valid key, just rate-limited (don't mark exhausted here)
                    logger.info(f"🔑 Key ...{key[-8:]} validated (HTTP {r.status_code})")
                # Other status codes (500 etc.) — leave key as valid
            except Exception:
                # Network issues at startup — don't penalise valid keys
                pass

    threading.Thread(target=_probe, daemon=True, name="groq-key-validator").start()


# ── Groq call ──────────────────────────────────────────────────────────────────

def _call_groq(prompt: str, system: str, max_tokens: int) -> str:
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
                    logger.info(f"⏳ Key ...{key[-8:]} rate-limited for {wait_secs:.1f}s — waiting...")
                    time.sleep(wait_secs + 0.5)
                    tried.discard(key)
                    continue
                else:
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
            continue

        except httpx.TimeoutException:
            logger.warning(f"⚠️  Groq timeout on key ...{key[-8:]}, trying next")
            continue

        except Exception as e:
            logger.warning(f"⚠️  Groq unexpected error on key ...{key[-8:]}: {e}")
            continue


# ── Ollama call ────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, system: str) -> str:
    import httpx

    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = _get_config("OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M"))
    max_tokens   = _get_config("OLLAMA_MAX_TOKENS", 1500)

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
            "The model may be loading — try again, or set LLM_PROVIDER=groq in .env."
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
                logger.warning(f"🦙 Ollama timed out on attempt {attempt}, retrying once...")
                continue
            raise RuntimeError(
                f"Ollama call failed: {err_msg}\n"
                "Make sure Ollama is running (ollama serve) or set "
                "LLM_PROVIDER=groq in your .env to disable the Ollama fallback."
            ) from None

    raise RuntimeError("Ollama failed after 2 attempts")


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$",          "", text, flags=re.MULTILINE)
    return text.strip()


# ── Phase 15.4 — Kick off background key validation at import time ────────────
if _groq_keys:
    _validate_keys_on_startup()
