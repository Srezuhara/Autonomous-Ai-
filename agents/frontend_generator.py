"""
agents/frontend_generator.py — Phase 19.2 update
==================================================
Phase 19.2 — Multi-file context in code generation
  - Shows ALL previously written frontend files (not just last 3)
  - Takes first 30 lines per file (not a char-limit that can cut mid-line)
  - Also injects the full architecture file list as project structure context
  - Groups JS/JSX/TS/TSX by role:
      config/types → hooks → utils → components → pages → App → main

This ensures later files (App.tsx, main.tsx) see the full import surface of
earlier ones, preventing "Cannot find module" errors at build time.
"""
import logging
import json
import os
from pathlib import Path
from agents.base_agent import BaseAgent
from tools.file_writer import create_file, read_file

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "frontend_generator.txt"
CONTEXT_MAX_CHARS = int(os.getenv("GROQ_CONTEXT_MAX_CHARS", "2500"))
CONTEXT_HEADER_LINES = int(os.getenv("GROQ_CONTEXT_HEADER_LINES", "12"))
CONTEXT_RECENT_FILES = int(os.getenv("GROQ_CONTEXT_RECENT_FILES", "3"))

# File types this agent handles
FRONTEND_TYPES = {"javascript", "jsx", "typescript", "tsx", "css", "html", "json"}

# ── Phase 19.2: role-based generation order ──────────────────────────────────
_ROLE_ORDER = {
    # Config / type definitions first
    "vite.config.ts":  0,
    "vite.config.js":  0,
    "tailwind.config.js": 0,
    "postcss.config.js":  0,
    "tsconfig.json":   0,
    "package.json":    0,
    "index.css":       1,
    "globals.css":     1,
    "tokens.css":      1,
    # Type declaration files
    "types.ts":        2,
    "types.d.ts":      2,
    # API / client layer
    "client.ts":       3,
    "api.ts":          3,
    # Hooks
    "useAuth.ts":      4,
    "useApi.ts":       4,
    # Utilities / helpers
    "utils.ts":        5,
    "helpers.ts":      5,
    "lib.ts":          5,
    # Components
    "components":      6,   # matched by prefix
    # Pages
    "pages":           7,   # matched by prefix
    # Root app
    "App.tsx":         8,
    "App.jsx":         8,
    "App.ts":          8,
    "App.js":          8,
    # Entry point last
    "main.tsx":        9,
    "main.jsx":        9,
    "index.tsx":       9,
    "index.html":      9,
}


def _role_priority(file_info: dict) -> int:
    path = file_info.get("path", "")
    name = Path(path).name

    # Exact match
    if name in _ROLE_ORDER:
        return _ROLE_ORDER[name]

    # Prefix match (components/, pages/)
    parts = Path(path).parts
    for part in parts:
        if part.lower() in ("components", "component"):
            return 6
        if part.lower() in ("pages", "page", "views"):
            return 7
        if part.lower() in ("hooks", "hook"):
            return 4
        if part.lower() in ("utils", "lib", "helpers"):
            return 5

    # Default: middle of the pack
    return 5


class FrontendGenerator(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("FrontendGenerator", system_prompt)

    def run(self, intent: dict, architecture: dict) -> list[str]:
        """
        Generate frontend code for all JS/JSX/HTML/CSS files in the architecture.

        Phase 19.2: files generated in role-order; full-header context passed.

        Returns list of file paths that were written.
        """
        root = architecture.get("root_folder", "project")
        frontend_files = [
            f for f in architecture.get("files", [])
            if f.get("type") in FRONTEND_TYPES
        ]

        # ── Phase 19.2: sort by role ──────────────────────────────────────────
        frontend_files_sorted = sorted(frontend_files, key=_role_priority)

        logger.info(
            f"🎨 Generating frontend: {len(frontend_files_sorted)} files "
            f"(role-ordered)"
        )
        written = []

        for file_info in frontend_files_sorted:
            path        = file_info["path"]
            description = file_info["description"]
            full_path   = f"{root}/{path}"

            # Phase 19.2: full context from all previously written files
            context = self._gather_full_context(root, written)

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

    # ── Phase 19.2: full-header multi-file context ────────────────────────────

    def _gather_full_context(self, root: str, written_paths: list[str]) -> str:
        """
        Return the first 30 lines of every already-written file, labelled by
        relative path. This gives the LLM full import visibility.

        Replaces the old _gather_context() which only showed the last 3 files
        truncated to 800 chars each.
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
    ) -> str:
        # Detect file type for language-specific instructions
        ext = Path(file_path).suffix.lower()
        lang_hint = {
            ".js":   "React JavaScript",
            ".jsx":  "React JSX",
            ".ts":   "TypeScript",
            ".tsx":  "React TypeScript",
            ".css":  "CSS",
            ".html": "HTML",
            ".json": "JSON config",
        }.get(ext, "JavaScript")

        # Full project file list for structural awareness
        arch_files = [
            f"{f.get('path')} ({f.get('type', 'file')})"
            for f in architecture.get("files", [])
        ]
        arch_summary = "\n".join(f"- {path}" for path in arch_files)

        prompt = f"""
Generate the complete {lang_hint} code for this file.

APP SPEC:
{json.dumps(intent, indent=2)}

FILE TO WRITE:
Path: {file_path}
Purpose: {description}

PROJECT STRUCTURE (all planned files):
{arch_summary}

ALREADY WRITTEN FILES (import context — use these exact paths for imports):
{context if context else "None yet — this is the first file."}

The backend API runs at: http://localhost:8000

Write the complete, working {lang_hint} code for: {file_path}
"""
        return self.think(prompt)


# ── Smoke test ────────────────────────────────────────────────────────────────
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

    print("Step 5: Generating frontend (Phase 19.2)...")
    written = FrontendGenerator().run(intent, arch)

    print(f"\n=== Frontend Generation Complete ===")
    print(f"Files written ({len(written)}):")
    for f in written:
        print(f"  ✅ {f}")
