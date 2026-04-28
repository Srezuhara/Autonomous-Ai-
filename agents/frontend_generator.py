"""
agents/frontend_generator.py — Generates React/Tailwind frontend code.
"""
import logging
import json
from pathlib import Path
from agents.base_agent import BaseAgent
from tools.file_writer import create_file, read_file

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "frontend_generator.txt"

# File types this agent handles
FRONTEND_TYPES = {"javascript", "jsx", "typescript", "tsx", "css", "html", "json"}


class FrontendGenerator(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("FrontendGenerator", system_prompt)

    def run(self, intent: dict, architecture: dict) -> list[str]:
        """
        Generate frontend code for all JS/JSX/HTML files in the architecture.

        Args:
            intent:       output from IntentAnalyzer
            architecture: output from Architect

        Returns:
            list of file paths that were written
        """
        root = architecture.get("root_folder", "project")
        frontend_files = [
            f for f in architecture.get("files", [])
            if f.get("type") in FRONTEND_TYPES
        ]

        logger.info(f"🎨 Generating frontend: {len(frontend_files)} files")
        written = []

        for file_info in frontend_files:
            path = file_info["path"]
            description = file_info["description"]
            full_path = f"{root}/{path}"

            context = self._gather_context(root, written)

            code = self._generate_file(
                intent=intent,
                architecture=architecture,
                file_path=path,
                description=description,
                context=context,
            )

            create_file(full_path, code)
            written.append(full_path)
            logger.info(f"✅ Generated: {full_path}")

        return written

    def _generate_file(
        self,
        intent: dict,
        architecture: dict,
        file_path: str,
        description: str,
        context: str,
    ) -> str:
        # Detect file type for language-specific instructions
        ext = Path(file_path).suffix.lower()
        lang_hint = {
            ".js": "React JavaScript",
            ".jsx": "React JSX",
            ".ts": "TypeScript",
            ".tsx": "React TypeScript",
            ".css": "CSS",
            ".html": "HTML",
            ".json": "JSON config",
        }.get(ext, "JavaScript")

        prompt = f"""
Generate the complete {lang_hint} code for this file.

APP SPEC:
{json.dumps(intent, indent=2)}

FILE TO WRITE:
Path: {file_path}
Purpose: {description}

PROJECT STRUCTURE:
{json.dumps([f["path"] for f in architecture.get("files", [])], indent=2)}

ALREADY WRITTEN FILES (for context/imports):
{context if context else "None yet — this is the first file."}

The backend API runs at: http://localhost:8000

Write the complete, working {lang_hint} code for: {file_path}
"""
        return self.think(prompt)

    def _gather_context(self, root: str, written_paths: list[str]) -> str:
        """Read already-written files to give the LLM context."""
        if not written_paths:
            return ""
        snippets = []
        for path in written_paths[-3:]:
            try:
                content = read_file(path)
                snippets.append(f"--- {path} ---\n{content[:800]}")
            except Exception:
                pass
        return "\n\n".join(snippets)


# ── Smoke test ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from agents.intent_analyzer import IntentAnalyzer
    from agents.planner import Planner
    from agents.architect import Architect
    from agents.backend_developer import BackendDeveloper

    user_prompt = "Build a weather dashboard that shows temperature, humidity and a 5-day forecast"

    print("Step 1: Analyzing intent...")
    intent = IntentAnalyzer().run(user_prompt)

    print("Step 2: Planning...")
    steps = Planner().run(intent)

    print("Step 3: Architecting...")
    arch = Architect().run(intent, steps)

    print("Step 4: Generating backend...")
    BackendDeveloper().run(intent, arch)

    print("Step 5: Generating frontend...")
    written = FrontendGenerator().run(intent, arch)

    print(f"\n=== Frontend Generation Complete ===")
    print(f"Files written ({len(written)}):")
    for f in written:
        print(f"  ✅ {f}")
