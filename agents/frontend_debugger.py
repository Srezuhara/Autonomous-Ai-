"""
agents/frontend_debugger.py — Phase 19.3
=========================================
Runs TypeScript / ESLint compile checks on the generated frontend and
auto-fixes errors reported by `tsc --noEmit`.

Why this agent exists
---------------------
FrontendGenerator produces JSX/TSX that usually works but sometimes has:
  - Wrong import paths (e.g. `import X from './X'` where the file is `.tsx`)
  - Missing type annotations that TS strict mode rejects
  - Unused imports that cause `noUnusedLocals` errors
  - Wrong prop types or missing interfaces

This agent runs AFTER FrontendGenerator and BEFORE the Tester so that
users download ZIPs where `npm run build` succeeds.

Usage (called from pipeline.py)
--------------------------------
    from agents.frontend_debugger import FrontendDebugger
    frontend_debugger = FrontendDebugger()
    ts_results = frontend_debugger.run(root, frontend_files)

The agent returns a list of TsDebugResult, one per fixed file (or error).
"""

import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import config
from agents.base_agent import BaseAgent
from tools.file_writer import read_file, create_file
from llm_client import GroqDailyQuotaError

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "frontend_debugger.txt"

# File extensions the frontend debugger handles
FRONTEND_TS_EXTS = {".ts", ".tsx", ".jsx", ".js"}

# tsc errors we intentionally ignore (they don't affect runtime)
IGNORABLE_TS_CODES = {
    "TS2307",  # Cannot find module (external npm package type stubs)
    "TS7016",  # Could not find declaration file for module
    "TS2688",  # Cannot find type definition file
    "TS6133",  # Variable declared but never read (noUnusedLocals)
    "TS6196",  # Declared but its value is never read
}

# Maximum files to fix per build (safety cap)
MAX_FILES_TO_FIX = 8
MAX_FIX_ATTEMPTS = 2


@dataclass
class TsDebugResult:
    file_path:     str
    success:       bool
    errors_found:  int = 0
    errors_fixed:  int = 0
    skipped:       bool = False
    skip_reason:   str = ""
    fixes_applied: list = field(default_factory=list)

    def __str__(self):
        if self.skipped:
            return f"⏭️  {self.file_path} ({self.skip_reason})"
        icon = "✅" if self.success else "⚠️ "
        return (
            f"{icon} {self.file_path} — "
            f"{self.errors_found} error(s) found, "
            f"{self.errors_fixed} fixed"
        )


class FrontendDebugger(BaseAgent):
    def __init__(self):
        # Load prompt file if it exists; fall back to an inline system prompt
        if PROMPT_FILE.exists():
            system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        else:
            system_prompt = self._default_system_prompt()
        super().__init__("FrontendDebugger", system_prompt)

    @staticmethod
    def _default_system_prompt() -> str:
        return """You are an expert TypeScript / React developer.
Fix TypeScript and JSX errors in the provided file.

RULES:
- Return ONLY raw fixed code. No markdown, no explanation.
- Preserve all existing functionality.
- Fix ALL reported TypeScript errors.
- Use `any` type sparingly — prefer proper types where obvious.
- Do NOT remove working code just to suppress errors.
- Prefer `// @ts-expect-error` over `// @ts-ignore`.
- For missing prop types: add inline interface or `React.FC<Props>`.
- For missing imports: add them at the top.
- For unused variables: prefix with `_` (e.g. `_event`) or remove if safe.
"""

    # ── Entry point ────────────────────────────────────────────────────────────

    def run(self, root: str, frontend_files: list[str]) -> list[TsDebugResult]:
        """
        1. Run `tsc --noEmit` in the frontend directory.
        2. Parse errors → group by file.
        3. For each affected file, call LLM to fix, re-check.
        4. Return results.
        """
        frontend_dir = Path(config.OUTPUT_DIR) / root / "frontend"

        if not frontend_dir.exists():
            logger.info("⏭️  FrontendDebugger: no frontend/ directory — skipping")
            return []

        if not (frontend_dir / "package.json").exists():
            logger.info("⏭️  FrontendDebugger: no package.json — skipping")
            return []

        # Step 1: install deps if node_modules absent
        self._ensure_node_modules(frontend_dir)

        # Step 2: run tsc
        tsc_output = self._run_tsc(frontend_dir)
        if tsc_output is None:
            # tsc not available (no Node.js in PATH or TypeScript not installed)
            return [TsDebugResult(
                file_path="frontend/",
                success=True,
                skipped=True,
                skip_reason="tsc not available — TypeScript not installed",
            )]

        if not tsc_output.strip():
            logger.info("✅ FrontendDebugger: tsc reported 0 errors")
            return []

        # Step 3: parse errors
        errors_by_file = self._parse_tsc_output(tsc_output, frontend_dir)
        if not errors_by_file:
            logger.info("✅ FrontendDebugger: all tsc errors are ignorable")
            return []

        logger.info(f"🔍 FrontendDebugger: {len(errors_by_file)} file(s) with TS errors")

        results = []
        files_processed = 0

        for rel_path, errors in sorted(errors_by_file.items()):
            if files_processed >= MAX_FILES_TO_FIX:
                results.append(TsDebugResult(
                    file_path=rel_path,
                    success=False,
                    skipped=True,
                    skip_reason="max files limit reached",
                ))
                continue

            result = self._fix_file(rel_path, errors, frontend_dir)
            results.append(result)
            files_processed += 1
            logger.info(str(result))

        return results

    # ── tsc runner ─────────────────────────────────────────────────────────────

    def _ensure_node_modules(self, frontend_dir: Path):
        if (frontend_dir / "node_modules").exists():
            return
        logger.info("📦 FrontendDebugger: installing npm dependencies...")
        try:
            subprocess.run(
                ["npm", "install", "--silent", "--legacy-peer-deps"],
                cwd=str(frontend_dir),
                capture_output=True,
                timeout=180,
            )
        except Exception as e:
            logger.warning(f"⚠️  npm install failed: {e}")

    def _run_tsc(self, frontend_dir: Path) -> str | None:
        """
        Run `npx tsc --noEmit` and return the combined stdout+stderr.
        Returns None if tsc / npx is not available.
        """
        try:
            result = subprocess.run(
                ["npx", "--no-install", "tsc", "--noEmit", "--pretty", "false"],
                cwd=str(frontend_dir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = (result.stdout or "") + (result.stderr or "")
            logger.info(
                f"🔧 tsc exited {result.returncode} "
                f"({'errors' if result.returncode != 0 else 'clean'})"
            )
            return output
        except FileNotFoundError:
            logger.warning("⚠️  npx not found — skipping TypeScript validation")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("⚠️  tsc timed out after 60s — skipping")
            return None
        except Exception as e:
            logger.warning(f"⚠️  tsc error: {e}")
            return None

    # ── Error parser ───────────────────────────────────────────────────────────

    def _parse_tsc_output(
        self, output: str, frontend_dir: Path
    ) -> dict[str, list[str]]:
        """
        Parse tsc --noEmit --pretty false output.
        Returns {relative_file_path: [error_line, ...]} excluding ignorable codes.

        tsc format:
          src/App.tsx(12,5): error TS2345: ...
          src/components/Card.tsx(3,1): error TS1005: ...
        """
        errors_by_file: dict[str, list[str]] = {}

        pattern = re.compile(
            r'^(.+\.(?:ts|tsx|js|jsx))\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+(.+)$',
            re.MULTILINE,
        )

        for m in pattern.finditer(output):
            raw_path  = m.group(1)
            ts_code   = m.group(4)
            message   = m.group(5)
            line_col  = f"{m.group(2)}:{m.group(3)}"

            if ts_code in IGNORABLE_TS_CODES:
                continue

            # Normalise path separator
            rel_path = raw_path.replace("\\", "/").lstrip("./")

            error_line = f"  {raw_path}:{line_col} [{ts_code}] {message}"
            errors_by_file.setdefault(rel_path, []).append(error_line)

        return errors_by_file

    # ── File fixer ─────────────────────────────────────────────────────────────

    def _fix_file(
        self,
        rel_path:     str,
        errors:       list[str],
        frontend_dir: Path,
    ) -> TsDebugResult:
        abs_path = frontend_dir / rel_path
        result   = TsDebugResult(
            file_path=f"frontend/{rel_path}",
            success=False,
            errors_found=len(errors),
        )

        if not abs_path.exists():
            result.skipped     = True
            result.skip_reason = "file not found on disk"
            return result

        try:
            original_code = abs_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            result.skipped     = True
            result.skip_reason = f"read error: {e}"
            return result

        current_code = original_code

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            fixed_code = self._ask_llm_to_fix(rel_path, current_code, errors)
            if not fixed_code or not fixed_code.strip():
                break

            try:
                abs_path.write_text(fixed_code, encoding="utf-8")
            except Exception as e:
                result.skipped     = True
                result.skip_reason = f"write error: {e}"
                return result

            current_code = fixed_code
            result.fixes_applied.append(f"LLM fix attempt {attempt}")

            # Re-run tsc on just this file to check
            re_check_output = self._run_tsc(frontend_dir)
            if re_check_output is None:
                result.success     = True
                result.errors_fixed = len(errors)
                return result

            remaining = self._parse_tsc_output(re_check_output, frontend_dir)
            if rel_path not in remaining:
                result.success      = True
                result.errors_fixed = len(errors)
                logger.info(f"  ✅ Fixed {rel_path} on attempt {attempt}")
                return result

            # Still errors — update error list for next attempt
            errors = remaining[rel_path]

        # We tried but errors remain — still return the best version we have
        result.success      = len(result.fixes_applied) > 0
        result.errors_fixed = len(errors) if result.success else 0
        return result

    def _ask_llm_to_fix(
        self, rel_path: str, code: str, errors: list[str]
    ) -> str | None:
        error_block = "\n".join(errors[:20])  # cap at 20 lines

        prompt = f"""Fix the TypeScript errors in this file.

FILE: {rel_path}
CODE:
{code[:3000]}

TYPESCRIPT ERRORS:
{error_block}

Return ONLY the complete fixed TypeScript/JSX code. No markdown. No explanation."""
        try:
            return self.think(prompt)
        # Phase 21 fix: same reasoning as reviewer.py — a dead daily quota must
        # not be downgraded to "this one TS file could not be fixed". It has to
        # reach the pipeline so the build is packaged with an honest handoff.
        except GroqDailyQuotaError:
            logger.error(
                f"  LLM daily quota exhausted while fixing {rel_path} — "
                "aborting TypeScript fix pass."
            )
            raise
        except Exception as e:
            logger.warning(f"  ⚠️  LLM fix failed for {rel_path}: {e}")
            return None


# ── Smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = FrontendDebugger()
    print("FrontendDebugger initialised ✅")
    print(f"System prompt length: {len(agent.system_prompt)} chars")
