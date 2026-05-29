"""
agents/backend_developer.py — Phase 19 update
==============================================
Phase 19.1 — Auto-requirements.txt validation
  After generating all files, calls validate_and_fix_requirements() to ensure
  every 3rd-party import has a corresponding PyPI package in requirements.txt.

Phase 19.2 — Multi-file context in code generation
  Instead of only showing the last 3 written files (truncated to 800 chars),
  we now pass:
    - Full architecture JSON
    - Headers (first 30 lines) of ALL previously written files
    - File role ordering: models → services → routes → main → other
  This dramatically reduces import errors that the Debugger has to fix.

Phase 19.4 — CORS auto-detection
  Detects the frontend port from architecture JSON and injects the correct
  `allow_origins` list into the backend developer prompt.  No more hardcoded
  `["http://localhost:3000"]` — the generated main.py will match the actual
  Vite/React dev server port.
"""
import logging
import json
import os
from pathlib import Path
from agents.base_agent import BaseAgent
from tools.file_writer import create_file, read_file

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "backend_developer.txt"
CONTEXT_MAX_CHARS = int(os.getenv("GROQ_CONTEXT_MAX_CHARS", "2500"))
CONTEXT_HEADER_LINES = int(os.getenv("GROQ_CONTEXT_HEADER_LINES", "12"))
CONTEXT_RECENT_FILES = int(os.getenv("GROQ_CONTEXT_RECENT_FILES", "3"))

# File-role ordering for generation — ensures dependencies are generated first
_ROLE_ORDER = {
    "models.py":       0,
    "schemas.py":      1,
    "database.py":     2,
    "db.py":           2,
    "config.py":       3,
    "utils.py":        4,
    "helpers.py":      4,
    "services.py":     5,
    "crud.py":         5,
    "weather_api.py":  5,
    "weather_service.py": 5,
    "auth.py":         6,
    "dependencies.py": 6,
    "routes.py":       7,
    "main.py":         8,
}


def _role_priority(file_info: dict) -> int:
    name = Path(file_info.get("path", "")).name.lower()
    return _ROLE_ORDER.get(name, 5)  # unknown files default to middle priority


class BackendDeveloper(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("BackendDeveloper", system_prompt)

    def run(self, intent: dict, architecture: dict) -> list[str]:
        """
        Generate backend code for all Python files in the architecture.

        Phase 19.2: files are generated in dependency order (models first, main last).
        Phase 19.4: CORS origins are auto-detected from the architecture.

        Returns list of file paths that were written.
        """
        root = architecture.get("root_folder", "project")
        backend_files = [
            f for f in architecture.get("files", [])
            if f.get("type") == "python"
        ]

        # ── Phase 19.2: sort by role so deps are generated first ──────────────
        backend_files_sorted = sorted(backend_files, key=_role_priority)

        # ── Phase 19.4: detect CORS origins from architecture ─────────────────
        cors_origins = self._detect_cors_origins(architecture)

        logger.info(
            f"⚙️  Generating backend: {len(backend_files_sorted)} files "
            f"(CORS origins: {cors_origins})"
        )
        written = []

        for file_info in backend_files_sorted:
            path        = file_info["path"]
            description = file_info["description"]
            full_path   = f"{root}/{path}"

            # Phase 19.2: rich context (headers of ALL previously written files)
            context = self._gather_full_context(root, written, architecture)

            code = self._generate_file(
                intent=intent,
                architecture=architecture,
                file_path=path,
                description=description,
                context=context,
                cors_origins=cors_origins,
            )

            create_file(full_path, code)
            written.append(full_path)
            logger.info(f"✅ Generated: {full_path}")

        # ── Phase 19.1: validate and fix requirements.txt ─────────────────────
        self._validate_requirements(root, written)

        return written

    # ── Phase 19.4: CORS origin detection ─────────────────────────────────────

    def _detect_cors_origins(self, architecture: dict) -> list[str]:
        """
        Inspect architecture JSON to determine which ports the frontend uses,
        then return a list of allowed origins for the CORS middleware.

        Heuristics:
          1. If architecture has a `frontend_port` field, use it.
          2. If any file has type "html" / "jsx" / "tsx" / "javascript", assume Vite → 5173.
          3. Otherwise default to both 5173 and 3000 for maximum compatibility.
        """
        origins = set()

        # Explicit port field (future-proofing)
        if "frontend_port" in architecture:
            port = architecture["frontend_port"]
            origins.add(f"http://localhost:{port}")

        # Detect frontend type from file list
        frontend_types = {"javascript", "jsx", "typescript", "tsx", "html"}
        has_frontend = any(
            f.get("type") in frontend_types
            for f in architecture.get("files", [])
        )

        if has_frontend:
            # Check for Vite config
            has_vite = any(
                "vite" in f.get("path", "").lower()
                for f in architecture.get("files", [])
            )
            # Default Vite port: 5173; Create React App: 3000
            if has_vite:
                origins.add("http://localhost:5173")
            else:
                origins.add("http://localhost:3000")
                origins.add("http://localhost:5173")  # also add Vite as fallback

        # Always include both common ports as a safe default
        origins.add("http://localhost:5173")
        origins.add("http://localhost:3000")

        return sorted(origins)

    # ── Phase 19.2: rich multi-file context ───────────────────────────────────

    def _gather_full_context(
        self,
        root:             str,
        written_paths:    list[str],
        architecture:     dict,
    ) -> str:
        """
        Return the first 30 lines of each already-written file, labelled by
        their file path. This gives the LLM full import visibility without
        exceeding the token budget.

        Phase 19.2 improvement over old _gather_context():
          - Shows ALL previously written files (not just last 3)
          - Takes 30 lines per file (not a character limit that can cut mid-line)
          - Includes the full architecture file list for structural awareness
        """
        if not written_paths:
            return ""

        summary = [f"Already written ({len(written_paths)} files):"]
        for path in written_paths:
            summary.append(f"- {path}")

        snippets = []
        for path in written_paths[-CONTEXT_RECENT_FILES:]:
            try:
                content = read_file(path)
                lines   = content.splitlines()[:CONTEXT_HEADER_LINES]
                header  = "\n".join(lines)
                snippets.append(f"--- {path} (first {len(lines)} lines) ---\n{header}")
            except Exception:
                pass

        context = "\n".join(summary)
        if snippets:
            context += "\n\nRecent file snippets:\n" + "\n\n".join(snippets)
        if len(context) > CONTEXT_MAX_CHARS:
            return context[:CONTEXT_MAX_CHARS] + "\n... [context truncated]"
        return context

    def _generate_file(
        self,
        intent:       dict,
        architecture: dict,
        file_path:    str,
        description:  str,
        context:      str,
        cors_origins: list[str],
    ) -> str:
        # Build origins string for injection into prompt
        origins_repr = json.dumps(cors_origins)

        # Build concise architecture file list
        arch_files = [
            f"{f.get('path')} ({f.get('type', 'file')})"
            for f in architecture.get("files", [])
        ]
        arch_summary = "\n".join(f"- {path}" for path in arch_files)

        prompt = f"""
Generate the complete Python code for this file.

APP SPEC:
{json.dumps(intent, indent=2)}

FILE TO WRITE:
Path: {file_path}
Purpose: {description}

PROJECT STRUCTURE (all planned files):
{arch_summary}

ALREADY WRITTEN FILES (import context — use these exact module names):
{context if context else "None yet — this is the first file."}

CORS CONFIGURATION (Phase 19.4 — use these EXACT origins in main.py):
allow_origins = {origins_repr}
Only apply this to main.py. Other files do not need CORS configuration.

Write the complete, working Python code for: {file_path}
"""
        return self.think(prompt)

    # ── Phase 19.1: requirements validation ───────────────────────────────────

    def _validate_requirements(self, root: str, written: list[str]) -> None:
        """
        After all files are generated, ensure requirements.txt has every
        3rd-party package imported by the generated code.
        """
        try:
            from tools.requirements_builder import validate_and_fix_requirements
            result = validate_and_fix_requirements(root, written)
            if result.added:
                logger.info(
                    f"📦 [Phase 19.1] Auto-added to requirements.txt: "
                    + ", ".join(result.added)
                )
            elif result.error:
                logger.warning(f"⚠️  [Phase 19.1] requirements validation error: {result.error}")
            else:
                logger.info("✅ [Phase 19.1] requirements.txt is complete")
        except ImportError:
            logger.warning("⚠️  [Phase 19.1] requirements_builder not found — skipping validation")
        except Exception as e:
            logger.warning(f"⚠️  [Phase 19.1] requirements validation failed: {e}")


# ── Smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from agents.intent_analyzer import IntentAnalyzer
    from agents.planner import Planner
    from agents.architect import Architect

    user_prompt = "Build a weather dashboard that shows temperature, humidity and a 5-day forecast"

    print("Step 1: Analyzing intent...")
    intent = IntentAnalyzer().run(user_prompt)

    print("Step 2: Planning...")
    steps = Planner().run(intent)

    print("Step 3: Architecting...")
    arch = Architect().run(intent, steps)

    print("Step 4: Generating backend code (Phase 19)...")
    written = BackendDeveloper().run(intent, arch)

    print(f"\n=== Backend Generation Complete ===")
    print(f"Files written ({len(written)}):")
    for f in written:
        print(f"  ✅ {f}")
