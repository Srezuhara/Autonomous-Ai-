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
from tools.code_introspect import find_dangling_js_imports

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

        # ── Phase 22: create components that were imported but never planned ──
        written.extend(self._resolve_dangling_imports(intent, root, written))

        return written

    # ── Phase 22: dangling import resolution ──────────────────────────────────

    MAX_GENERATED_COMPONENTS = 6

    def _resolve_dangling_imports(
        self, intent: dict, root: str, written: list[str]
    ) -> list[str]:
        """
        Generate components that existing files import but the architecture
        never planned.

        The generator only ever writes files listed in the architecture, so when
        App.jsx imports `./TodoList` and no TodoList was planned, the import
        simply dangles. Plain-JS projects receive no tsc validation, so nothing
        downstream catches it — the frontend just fails to build. Creating the
        component is the right repair: the import expresses a real requirement.
        """
        try:
            import config
            project_dir = Path(config.OUTPUT_DIR) / root
        except Exception:
            return []

        try:
            dangling = find_dangling_js_imports(project_dir)
        except Exception as e:
            logger.warning(f"⚠️  [Phase 22] dangling-import scan failed: {e}")
            return []

        if not dangling:
            logger.info("✅ [Phase 22] Frontend: no dangling imports")
            return []

        # One component per missing target, even if several files import it.
        by_target: dict[str, tuple[str, str]] = {}
        for importer, spec, target in dangling:
            if not self._should_create_component(project_dir, importer, spec, target):
                continue
            by_target.setdefault(target, (importer, spec))

        if not by_target:
            logger.info("✅ [Phase 22] Frontend: no missing components to create")
            return []

        created: list[str] = []
        overflow = len(by_target) - self.MAX_GENERATED_COMPONENTS
        for target, (importer, spec) in list(by_target.items())[
            : self.MAX_GENERATED_COMPONENTS
        ]:
            ext  = Path(importer).suffix or ".jsx"
            dest = Path(target)
            if not dest.suffix:
                dest = dest.with_suffix(ext)

            logger.info(
                f"🎨 [Phase 22] Creating missing component {dest.name} "
                f"(imported as {spec})"
            )
            try:
                code = self._generate_missing_component(
                    intent, dest.stem, spec, importer
                )
            except Exception as e:
                logger.warning(f"⚠️  [Phase 22] could not generate {dest.name}: {e}")
                continue

            if not code or not code.strip():
                continue

            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(code, encoding="utf-8")
            except Exception as e:
                logger.warning(f"⚠️  [Phase 22] could not write {dest}: {e}")
                continue

            created.append(str(dest))
            logger.info(f"✅ [Phase 22] Created: {dest}")

        if overflow > 0:
            logger.warning(
                f"⚠️  [Phase 22] {overflow} further missing component(s) left "
                f"unresolved (cap is {self.MAX_GENERATED_COMPONENTS})"
            )
        return created

    # Importers whose broken imports must NOT spawn new source files.
    _TEST_MARKERS = ("__tests__", ".test.", ".spec.", "/tests/", "\\tests\\")

    def _should_create_component(
        self, project_dir: Path, importer: str, spec: str, target: str
    ) -> bool:
        """
        Decide whether a dangling import means "the component is missing" or
        "the import path is wrong".

        Creating a file is the right repair only for the first case. A live
        build produced `tests/test_frontend.js` importing
        `../todo_app/frontend/src/app.js` — a path that duplicates the project
        name and resolves outside the source tree. Generating a component there
        buried a junk copy of the app at `todo_app/todo_app/frontend/src/app.js`
        instead of fixing anything.
        """
        imp = importer.replace("\\", "/").lower()

        # 1. A test file with a broken path needs its path fixed, not a new
        #    component invented to match the typo.
        if any(marker.replace("\\", "/") in imp for marker in self._TEST_MARKERS):
            logger.info(
                f"  ↳ [Phase 22] Ignoring dangling import {spec} from a test file "
                f"({Path(importer).name}) — the import path is wrong, not the component"
            )
            return False

        # Resolve every path before comparing — mixing a resolved importer with
        # an unresolved target makes relative_to() fail on paths that are
        # actually fine.
        target_path  = Path(target).resolve()
        project_root = Path(project_dir).resolve()

        # 2. Never write outside the project.
        try:
            target_path.relative_to(project_root)
        except ValueError:
            logger.warning(
                f"  ↳ [Phase 22] Refusing to create {target_path} — outside the project"
            )
            return False

        # 3. Stay inside the importer's own source root. An import that climbs
        #    out of src/ is malformed rather than unsatisfied.
        importer_path = Path(importer).resolve()
        source_root = None
        for parent in importer_path.parents:
            if parent.name.lower() == "src":
                source_root = parent
                break
        if source_root is None:
            source_root = importer_path.parent

        try:
            target_path.relative_to(source_root)
        except ValueError:
            logger.warning(
                f"  ↳ [Phase 22] Refusing to create {target_path.name} — {spec} "
                f"resolves outside {source_root.name}/, so the import path is malformed"
            )
            return False

        return True

    def _generate_missing_component(
        self, intent: dict, name: str, spec: str, importer: str
    ) -> str:
        """Generate one component to satisfy an existing import."""
        try:
            importer_code = read_file(importer)[:1500]
        except Exception:
            importer_code = ""

        ext = Path(importer).suffix
        lang = "TypeScript React" if ext in (".ts", ".tsx") else "JavaScript React"

        prompt = f"""Create the missing React component `{name}`.

It is imported as `{spec}` by {Path(importer).name}, but the file was never
created. Write it so that import resolves and the app builds.

APP SPEC:
{json.dumps(intent, indent=2)[:900]}

THE FILE THAT IMPORTS IT:
{importer_code}

REQUIREMENTS:
- Language: {lang}
- Export the component as the DEFAULT export, named `{name}`.
- Accept exactly the props the importing file passes to it.
- Implement real, working behaviour — no TODO comments, no placeholder returns.
- Style with Tailwind CSS classes.
- Do not import any other component that does not already exist.

Return ONLY the raw component code. No markdown, no explanation."""
        return self.think(prompt)

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
