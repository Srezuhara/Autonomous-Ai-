"""
agents/reviewer.py — Code quality review agent.
Phase 15.2: added _parse_score() to safely handle "7/10", "7.5", null, etc.
            Score is validated to int 1-10 before being stored in ReviewResult.
"""
import logging
from pathlib import Path
from dataclasses import dataclass, field
from agents.base_agent import BaseAgent
from tools.file_writer import read_file

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "reviewer.txt"
SKIP_FILES = {"__init__.py", "config.py"}


@dataclass
class ReviewResult:
    file_path:   str
    score:       int   = 0
    issues:      list  = field(default_factory=list)
    suggestions: list  = field(default_factory=list)
    summary:     str   = ""
    error:       str   = ""

    def __str__(self):
        return f"[{self.score}/10] {self.file_path} — {self.summary}"


class Reviewer(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("Reviewer", system_prompt)

    def run(self, file_paths: list[str]) -> list[ReviewResult]:
        """Review all Python backend files."""
        py_files = [
            f for f in file_paths
            if f.endswith(".py") and Path(f).name not in SKIP_FILES
        ]
        logger.info(f"🔍 Reviewing {len(py_files)} files...")

        results = []
        for fp in py_files:
            result = self._review_file(fp)
            results.append(result)
            logger.info(f"  {result}")

        valid_scores = [r.score for r in results if r.score and r.score > 0]
        avg = sum(valid_scores) / max(len(valid_scores), 1)
        logger.info(f"🔍 Review complete — avg score: {avg:.1f}/10")
        return results

    def _parse_score(self, raw) -> int:
        """
        Safely convert LLM score output to int 1-10.

        Handles all formats the LLM might return:
          - int:     7       → 7
          - float:   7.5     → 7
          - str:     "7"     → 7
          - str:     "7.5"   → 7
          - str:     "7/10"  → 7
          - str:     "7.5/10"→ 7
          - None:    None    → 0  (signals missing / error)
          - out of range: 0  → 0

        Returns 0 if unparseable so downstream _safe_review_score()
        correctly skips it (uses `is not None` check, not truthiness).
        """
        if raw is None:
            return 0
        try:
            # Split on "/" handles "7/10" or "7.5/10" — take the first part
            val = int(float(str(raw).split("/")[0].strip()))
            if 1 <= val <= 10:
                return val
            logger.warning(f"[Reviewer] Score {val} out of range 1-10, treating as 0")
            return 0
        except (ValueError, TypeError) as e:
            logger.warning(f"[Reviewer] Could not parse score {raw!r}: {e}")
            return 0

    def _review_file(self, file_path: str) -> ReviewResult:
        try:
            code = read_file(file_path)
        except Exception as e:
            return ReviewResult(file_path=file_path, error=str(e))

        prompt = f"""Review this Python file:

FILE: {file_path}

CODE:
{code}

Return the JSON review object."""

        try:
            data = self.think_json(prompt)
            return ReviewResult(
                file_path=file_path,
                score=self._parse_score(data.get("score")),
                issues=data.get("issues", []),
                suggestions=data.get("suggestions", []),
                summary=data.get("summary", ""),
            )
        except Exception as e:
            logger.error(f"Review failed for {file_path}: {e}")
            return ReviewResult(file_path=file_path, error=str(e))

    def summary(self, results: list[ReviewResult]) -> str:
        lines = [f"\n{'='*50}", "  REVIEW SUMMARY", f"{'='*50}"]
        for r in results:
            if r.error:
                lines.append(f"  ❌ {r.file_path} — ERROR: {r.error}")
            else:
                lines.append(f"  {r}")
                for issue in r.issues:
                    lines.append(f"     ⚠️  {issue}")
        scores = [r.score for r in results if r.score and r.score > 0]
        if scores:
            lines.append(f"\n  Average score: {sum(scores)/len(scores):.1f}/10")
        lines.append(f"{'='*50}\n")
        return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    reviewer = Reviewer()
    results = reviewer.run(["weather_dashboard/backend/main.py"])
    print(reviewer.summary(results))
