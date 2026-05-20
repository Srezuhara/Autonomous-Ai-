"""
agents/base_agent.py — Shared base class for all agents.

v3.5.0 changes (on top of Phase 15.1):
  1. __init__ now calls get_agent_token_budget(self.name) once and stores
     the result as self._token_budget. No more blanket 2048.
  2. think() passes both self._token_budget (as max_tokens) and self.name
     (as agent_name) to generate_text(). This is the only line that changed
     in the actual logic — everything else is identical.
  3. The agent_name param tells llm_client which model to use (heavy vs fast)
     and which token budget to reserve against the Groq daily quota.

Phase 15.1 retained unchanged:
  think_json() retries up to 3× with exponential backoff (0.5s, 1s, 2s)
  and appends a stricter JSON instruction on each retry.
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
        self.name          = name
        self.system_prompt = system_prompt
        # Look up the right-sized token budget for this agent once at init.
        # This avoids reserving 2048 tokens for every call regardless of need.
        self._token_budget = llm_client.get_agent_token_budget(self.name)
        logger.info(
            f"🤖 Agent initialized: {self.name} "
            f"(model: {'heavy 70b' if self.name.lower().replace(' ','') in {'architect','backenddeveloper','frontendgenerator'} else 'fast 8b'}, "
            f"budget: {self._token_budget} tokens)"
        )

    def think(self, prompt: str, max_tokens: int = None) -> str:
        """
        Send a prompt to the LLM and return the response with fences stripped.

        Passes self.name as agent_name so llm_client can:
          1. Route to the correct model (heavy 70b vs fast 8b)
          2. Log which agent is making the call

        max_tokens defaults to self._token_budget (right-sized per agent).
        Pass an explicit value only when you genuinely need to override —
        for example a very long code file that won't fit in 1200 tokens.
        """
        budget = max_tokens if max_tokens is not None else self._token_budget
        logger.info(f"🧠 [{self.name}] Thinking...")
        response = llm_client.generate_text(
            prompt,
            system=self.system_prompt,
            max_tokens=budget,
            agent_name=self.name,      # ← the only change vs old base_agent
        )
        response = llm_client._strip_fences(response)
        logger.debug(f"[{self.name}] Response: {response[:200]}...")
        return response

    def think_json(self, prompt: str, retries: int = 3) -> dict | list:
        """
        Send a prompt and parse the response as JSON.
        Retries up to `retries` times with exponential backoff: 0.5s, 1s, 2s.
        On each retry the prompt is appended with a strict JSON-only instruction
        so the LLM knows exactly what went wrong.
        Unchanged from Phase 15.1.
        """
        last_error     = None
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
        """Strip markdown fences and parse JSON. Unchanged."""
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
