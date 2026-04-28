"""
agents/intent_analyzer.py — Extracts structured requirements from a user prompt.
"""
import logging
from pathlib import Path
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "intent_analyzer.txt"


class IntentAnalyzer(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("IntentAnalyzer", system_prompt)

    def run(self, user_prompt: str) -> dict:
        """
        Analyze a user prompt and return structured requirements.

        Args:
            user_prompt: e.g. "Build a weather dashboard with React"

        Returns:
            dict with app_name, features, tech_stack, etc.
        """
        logger.info(f"🔍 Analyzing intent: '{user_prompt}'")

        prompt = f"""
Analyze this app idea and extract structured requirements:

USER PROMPT: {user_prompt}

Return the JSON requirements object.
"""
        result = self.think_json(prompt)
        logger.info(f"✅ Intent analyzed: {result.get('app_name')} ({result.get('complexity')} complexity)")
        return result


# ── Smoke test ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json

    agent = IntentAnalyzer()
    result = agent.run("Build a weather dashboard that shows temperature, humidity and a 5-day forecast using a free weather API")

    print("\n=== Intent Analysis Result ===")
    print(json.dumps(result, indent=2))
