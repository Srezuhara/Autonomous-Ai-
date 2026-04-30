"""
config.py — Central configuration loaded from .env
Enhanced with connection health checks for Stage 2.
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── LLM settings ───────────────────────────────────────────
LLM_PROVIDER   = os.getenv("LLM_PROVIDER", "both")      # groq | ollama | both
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M")

# ── App settings ───────────────────────────────────────────
LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "generated_projects")


def test_groq_connection() -> bool:
    """Test Groq API connection."""
    if not GROQ_API_KEY:
        return False
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )
        logger.info("✅ Groq connection successful")
        return True
    except Exception as e:
        logger.warning(f"⚠️  Groq connection test failed: {e}")
        return False


def test_ollama_connection() -> bool:
    """Test Ollama server connection."""
    try:
        import requests
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        logger.info("✅ Ollama connection successful")
        return True
    except Exception as e:
        logger.warning(f"⚠️  Ollama connection test failed: {e}")
        return False


def test_connections() -> dict:
    """
    Test all LLM provider connections.
    Returns dict with connection status for each provider.
    """
    results = {}
    
    if LLM_PROVIDER in ("groq", "both"):
        results["groq"] = test_groq_connection()
    
    if LLM_PROVIDER in ("ollama", "both"):
        results["ollama"] = test_ollama_connection()
    
    return results


def validate():
    """Raise early if critical config is missing."""
    if LLM_PROVIDER in ("groq", "both") and not GROQ_API_KEY:
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Add it to your .env file.\n"
            "Get a free key at https://console.groq.com"
        )
    if LLM_PROVIDER in ("ollama", "both") and not OLLAMA_BASE_URL:
        raise EnvironmentError("OLLAMA_BASE_URL is not set.")

OLLAMA_MAX_TOKENS = 600
