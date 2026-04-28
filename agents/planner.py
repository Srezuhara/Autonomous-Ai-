"""
agents/planner.py — Breaks a project spec into ordered build steps.
"""
import logging
import json
from pathlib import Path
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "planner.txt"


class Planner(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("Planner", system_prompt)

    def run(self, intent: dict) -> list[dict]:
        """
        Take analyzed intent and return ordered build steps.

        Args:
            intent: output from IntentAnalyzer.run()

        Returns:
            list of step dicts with title, description, files_expected
        """
        logger.info(f"📋 Planning project: {intent.get('app_name')}")

        prompt = f"""
Create a detailed build plan for this application:

APP SPEC:
{json.dumps(intent, indent=2)}

Return the ordered JSON array of build steps.
"""
        steps = self.think_json(prompt)
        logger.info(f"✅ Plan created: {len(steps)} steps")
        return steps


# ── Smoke test ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json
    from agents.intent_analyzer import IntentAnalyzer

    # Chain: IntentAnalyzer → Planner
    intent = IntentAnalyzer().run(
        "Build a weather dashboard that shows temperature, humidity and a 5-day forecast"
    )

    steps = Planner().run(intent)

    print("\n=== Build Plan ===")
    for step in steps:
        deps = f" (depends on: {step.get('depends_on')})" if step.get('depends_on') else ""
        print(f"  Step {step['step']}: {step['title']}{deps}")
        print(f"           → {step['description'][:80]}")
        print(f"           → Files: {step.get('files_expected', [])}\n")
