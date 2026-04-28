"""
agents/base_agent.py — Shared base class for all agents.
Every agent inherits from this.

Phase 15.1: think_json() now retries up to 3x with exponential backoff
            (0.5s, 1s, 2s) and appends a stricter JSON instruction on each retry.
"""
import logging
import json
import re
import time
from typing import Any

import llm_client

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(self, name: str, system_prompt: str):
        self.name = name
        self.system_prompt = system_prompt
        logger.info(f"🤖 Agent initialized: {self.name}")

    def think(self, prompt: str) -> str:
        """Send a prompt to the LLM, return response with fences stripped."""
        logger.info(f"🧠 [{self.name}] Thinking...")
        response = llm_client.generate_text(prompt, system=self.system_prompt)
        response = llm_client._strip_fences(response)
        logger.debug(f"[{self.name}] Response: {response[:200]}...")
        return response

    def think_json(self, prompt: str, retries: int = 3) -> dict | list:
        """
        Send a prompt and parse the response as JSON.
        Retries up to `retries` times with exponential backoff: 0.5s, 1s, 2s.
        On each retry the prompt is appended with a strict JSON-only instruction
        so the LLM knows exactly what went wrong.
        """
        last_error = None
        current_prompt = prompt

        for attempt in range(1, retries + 1):
            raw = self.think(current_prompt)
            try:
                return self._parse_json(raw)
            except ValueError as e:
                last_error = e
                if attempt < retries:
                    wait = 0.5 * (2 ** (attempt - 1))   # 0.5s → 1s → 2s
                    logger.warning(
                        f"[{self.name}] JSON parse failed "
                        f"(attempt {attempt}/{retries}), retrying in {wait:.1f}s — {e}"
                    )
                    time.sleep(wait)
                    # Append strict instruction so model doesn't repeat the mistake
                    current_prompt = (
                        f"{prompt}\n\n"
                        "IMPORTANT: Your previous response could not be parsed as JSON. "
                        "Return ONLY a valid JSON object or array. "
                        "No markdown, no explanation, no code fences. "
                        "Start your response with {{ or [ and end with }} or ]."
                    )
                else:
                    logger.error(
                        f"[{self.name}] JSON parse failed after {retries} attempts. "
                        f"Last error: {e}"
                    )

        raise ValueError(
            f"[{self.name}] Could not parse JSON after {retries} attempts. "
            f"Last error: {last_error}"
        )

    def _parse_json(self, text: str) -> dict | list:
        """Strip markdown fences and parse JSON."""
        cleaned = re.sub(r"```(?:json)?\s*", "", text)
        cleaned = re.sub(r"```", "", cleaned).strip()

        start = min(
            (cleaned.find("{") if "{" in cleaned else len(cleaned)),
            (cleaned.find("[") if "[" in cleaned else len(cleaned)),
        )
        end = max(cleaned.rfind("}"), cleaned.rfind("]")) + 1
        json_str = cleaned[start:end]

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Could not parse JSON: {e}\nRaw: {text[:300]}")

    def run(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"{self.name} must implement run()")
