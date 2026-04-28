"""
agents/documenter.py — Generates README.md and API docs for generated projects.
Phase 9 of the AI App Builder pipeline.
"""
import logging
import json
from pathlib import Path
from dataclasses import dataclass, field
from agents.base_agent import BaseAgent
from tools.file_writer import read_file, create_file, list_files

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "documenter.txt"


@dataclass
class DocResult:
    app_name:       str
    readme_path:    str  = ""
    sections:       list = field(default_factory=list)
    error:          str  = ""

    def __str__(self):
        if self.error:
            return f"❌ {self.app_name} — {self.error}"
        return f"✅ {self.app_name} — wrote {self.readme_path} ({len(self.sections)} sections)"


class Documenter(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("Documenter", system_prompt)

    def run(self, intent: dict, architecture: dict,
            backend_files: list[str],
            review_results: list = None) -> DocResult:
        """Generate README.md for the project."""
        app_name = intent.get("app_name", "project")
        root     = architecture.get("root_folder", app_name)
        logger.info(f"📝 Generating documentation for: {app_name}")

        # Gather context from key files
        context = self._gather_context(root, backend_files)

        # Build review summary if available
        review_summary = ""
        if review_results:
            scores = [r.score for r in review_results if r.score]
            avg = sum(scores) / len(scores) if scores else 0
            review_summary = f"\nCode quality avg score: {avg:.1f}/10"

        prompt = f"""Generate a README.md for this project.

APP SPEC:
{json.dumps(intent, indent=2)}

PROJECT FILES:
{context}
{review_summary}

Generate the complete README.md following the format in your instructions.
Use the actual endpoint paths, env vars, and file names from the project files above."""

        try:
            readme_content = self.think(prompt)
            if not readme_content:
                return DocResult(app_name=app_name, error="LLM returned empty")

            readme_path = f"{root}/README.md"
            create_file(readme_path, readme_content)

            # Count sections written
            sections = [line.strip() for line in readme_content.splitlines()
                       if line.startswith("## ") or line.startswith("# ")]

            result = DocResult(
                app_name=app_name,
                readme_path=readme_path,
                sections=sections,
            )
            logger.info(str(result))
            return result

        except Exception as e:
            logger.error(f"Documentation failed: {e}")
            return DocResult(app_name=app_name, error=str(e))

    def _gather_context(self, root: str, backend_files: list[str]) -> str:
        """Read key files to give the LLM accurate content for docs."""
        snippets = []

        # Priority files for documentation
        priority = ["main.py", "routes.py", "services.py", "weather_api.py", "models.py"]

        for filename in priority:
            for fp in backend_files:
                if Path(fp).name == filename:
                    try:
                        content = read_file(fp)
                        # Extract imports and function signatures only (save tokens)
                        lines = content.splitlines()
                        key_lines = [
                            l for l in lines
                            if (l.startswith("import ") or
                                l.startswith("from ") or
                                l.startswith("@app.") or
                                l.startswith("@router.") or
                                l.startswith("async def ") or
                                l.startswith("def ") or
                                "APIRouter" in l or
                                "FastAPI" in l or
                                "os.getenv" in l or
                                "environ" in l)
                        ]
                        snippet = "\n".join(key_lines[:20])
                        snippets.append(f"--- {fp} ---\n{snippet}")
                    except Exception:
                        pass
                    break

        return "\n\n".join(snippets) if snippets else "No backend files available."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    documenter = Documenter()
    intent = {
        "app_name": "weather_dashboard",
        "app_type": "dashboard",
        "description": "Weather dashboard showing temperature, humidity and 5-day forecast",
        "features": ["current weather", "5-day forecast", "humidity tracking"],
        "tech_stack": {"backend": "FastAPI", "frontend": "React + Tailwind", "other": ["OpenWeatherMap API"]},
    }
    arch = {"root_folder": "weather_dashboard"}
    result = documenter.run(intent, arch, ["weather_dashboard/backend/main.py"])
    print(result)
