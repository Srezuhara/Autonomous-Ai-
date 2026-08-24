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
from tools.code_introspect import analyze_file, find_phantom_imports

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

        # ── Phase 22: fill SQL schema files nothing else owns ─────────────────
        written.extend(self._generate_sql_files(intent, architecture, root, written))

        # ── Phase 22: deterministic defect scan + targeted repair ─────────────
        # Runs before requirements validation so any import the repair pass
        # removes or adds is reflected in requirements.txt.
        self._verify_and_repair(intent, architecture, root, written)

        # ── Phase 19.1: validate and fix requirements.txt ─────────────────────
        self._validate_requirements(root, written)

        return written

    # ── Phase 22: SQL schema generation ───────────────────────────────────────

    def _generate_sql_files(
        self, intent: dict, architecture: dict, root: str, written: list[str]
    ) -> list[str]:
        """
        Fill .sql files planned by the architect.

        No generator owned these: BackendDeveloper filtered on type=="python"
        and FrontendGenerator on the JS/CSS/HTML types, so a planned schema.sql
        kept its scaffold placeholder all the way into the shipped ZIP — while
        SETUP.md told the user to run it.
        """
        sql_files = [
            f for f in architecture.get("files", [])
            if str(f.get("path", "")).lower().endswith(".sql")
        ]
        if not sql_files:
            return []

        # The data layer is the useful context for a schema: models + db access.
        model_context = ""
        for path in written:
            name = Path(path).name.lower()
            if name in ("models.py", "schemas.py", "db.py", "database.py"):
                try:
                    model_context += f"\n--- {name} ---\n{read_file(path)[:1200]}\n"
                except Exception:
                    pass

        created: list[str] = []
        for file_info in sql_files:
            path      = file_info["path"]
            full_path = f"{root}/{path}"
            logger.info(f"🗄️  [Phase 22] Generating SQL schema: {full_path}")

            prompt = f"""Write the complete SQL schema for this file.

FILE: {path}
PURPOSE: {file_info.get('description', 'database schema')}

APP SPEC:
{json.dumps(intent, indent=2)[:900]}

THE PYTHON DATA LAYER THIS SCHEMA MUST MATCH:
{model_context if model_context else "(no models generated)"}

RULES:
- Plain SQLite-compatible SQL. No ORM syntax, no Python.
- Use CREATE TABLE IF NOT EXISTS for every table.
- Column names and types MUST match what the Python data layer reads and writes.
- Include PRIMARY KEY and NOT NULL constraints where appropriate.
- No INSERT statements of fake seed data.
- SQL comments use `--`, never `#`.

Return ONLY raw SQL. No markdown, no explanation."""
            try:
                sql = self.think(prompt)
            except Exception as e:
                logger.warning(f"⚠️  [Phase 22] SQL generation failed for {path}: {e}")
                continue

            if not sql or not sql.strip():
                continue

            create_file(full_path, sql)
            created.append(full_path)
            logger.info(f"✅ [Phase 22] Generated: {full_path}")

        return created

    # ── Phase 22: self-verification ───────────────────────────────────────────

    def _planned_modules(self, architecture: dict) -> set[str]:
        """Module names that the architecture says will exist."""
        modules: set[str] = set()
        for f in architecture.get("files", []):
            path = f.get("path", "")
            if not path:
                continue
            p = Path(path)
            if p.suffix == ".py":
                modules.add(p.stem)
            for part in p.parts[:-1]:
                modules.add(part)
        return modules

    def _scan_defects(
        self, path: str, planned: set[str], ctx_managers: set[str] | None = None
    ) -> list[str]:
        """Deterministic, zero-token defect list for one generated file."""
        facts = analyze_file(path)
        if facts.parse_error:
            return [f"the file does not parse: {facts.parse_error}"]

        defects: list[str] = []

        # A @contextmanager used as a FastAPI dependency injects the context
        # manager object instead of the yielded value. Every handler that touches
        # it then dies with "'_GeneratorContextManager' object has no attribute
        # ...". The definition and the use are usually in different files, so the
        # set of context managers is collected across the whole project.
        known_ctx = set(ctx_managers or ()) | set(facts.contextmanagers)
        for dep in facts.depends_names:
            wrapped = facts.returns_call_to.get(dep, "")
            if dep in known_ctx:
                culprit, how = dep, f"`{dep}` is decorated with @contextmanager"
            elif wrapped and wrapped in known_ctx:
                culprit, how = wrapped, (
                    f"`{dep}` returns `{wrapped}()`, and `{wrapped}` is decorated "
                    f"with @contextmanager"
                )
            else:
                continue
            defects.append(
                f"{how}, but it is used as a FastAPI dependency via Depends({dep}). "
                f"FastAPI injects the context-manager object rather than the yielded "
                f"value, so every handler using it raises "
                f"\"'_GeneratorContextManager' object has no attribute ...\" at "
                f"request time. Make the dependency a plain generator function that "
                f"yields (drop @contextmanager from `{culprit}`), and have handlers "
                f"depend on it directly."
            )

        stub_handlers = [f for f in facts.stub_functions if f in facts.route_handlers]
        other_stubs   = [f for f in facts.stub_functions if f not in facts.route_handlers]

        if stub_handlers:
            defects.append(
                f"{len(stub_handlers)} route handler(s) are unimplemented stubs "
                f"({', '.join(stub_handlers)}). They return a placeholder instead of "
                f"real data. Implement the actual query/logic for each one."
            )
        if other_stubs:
            defects.append(
                f"{len(other_stubs)} function(s) are unimplemented stubs "
                f"({', '.join(other_stubs)}). Write their real bodies."
            )

        for module, fn_name in find_phantom_imports(facts, planned):
            where = f" inside {fn_name}()" if fn_name else ""
            defects.append(
                f"imports `{module}`{where}, which is not a planned project file and "
                f"is not an installed package. Remove it and use a module that exists, "
                f"or implement the behaviour inline."
            )

        local_deferred = [
            (m, fn) for m, fn in facts.deferred_imports
            if m.split(".")[0] in planned
        ]
        for module, fn_name in local_deferred:
            defects.append(
                f"imports `{module}` inside {fn_name}() instead of at module level. "
                f"Move it to the top of the file."
            )

        return defects

    def _verify_and_repair(
        self, intent: dict, architecture: dict, root: str, written: list[str]
    ) -> None:
        """
        Scan every generated file for defects the import check cannot see, and
        spend ONE targeted LLM call per offending file to fix them.

        Costs zero tokens on a clean generation. The defects targeted here
        (stub handlers, phantom imports, function-body imports) all pass the
        `python <file>` import gate, so nothing downstream would catch them —
        the todo_app build shipped all three.
        """
        planned = self._planned_modules(architecture)

        # Collect @contextmanager definitions across the whole project first —
        # a dependency is typically defined in main.py and consumed in routes.py.
        ctx_managers: set[str] = set()
        for path in written:
            if path.endswith(".py"):
                try:
                    ctx_managers.update(analyze_file(path).contextmanagers)
                except Exception:
                    pass

        repaired, failed = 0, 0

        for path in written:
            if not path.endswith(".py"):
                continue
            try:
                defects = self._scan_defects(path, planned, ctx_managers)
            except Exception as e:
                logger.warning(f"⚠️  [Phase 22] defect scan failed for {path}: {e}")
                continue
            if not defects:
                continue

            logger.info(f"🔧 [Phase 22] {path}: {len(defects)} defect(s) — repairing")
            for d in defects:
                logger.info(f"     • {d}")

            try:
                fixed = self._repair_file(intent, architecture, path, defects)
            except Exception as e:
                logger.warning(f"⚠️  [Phase 22] repair call failed for {path}: {e}")
                failed += 1
                continue

            if not fixed or not fixed.strip():
                failed += 1
                continue

            create_file(path, fixed)

            remaining = self._scan_defects(path, planned, ctx_managers)
            if remaining:
                failed += 1
                logger.warning(
                    f"⚠️  [Phase 22] {path}: {len(remaining)} defect(s) remain after repair"
                )
            else:
                repaired += 1
                logger.info(f"✅ [Phase 22] {path}: clean after repair")

        if repaired or failed:
            logger.info(
                f"🔧 [Phase 22] Self-verification complete: "
                f"{repaired} file(s) repaired, {failed} still degraded"
            )
        else:
            logger.info("✅ [Phase 22] Self-verification: all generated files clean")

    def _repair_file(
        self, intent: dict, architecture: dict, path: str, defects: list[str]
    ) -> str:
        """One targeted repair call. Returns the corrected full file source."""
        try:
            current = read_file(path)
        except Exception:
            return ""

        planned_list = "\n".join(
            f"- {f.get('path')}" for f in architecture.get("files", [])
        )
        defect_list = "\n".join(f"{i}. {d}" for i, d in enumerate(defects, 1))

        prompt = f"""This generated file has defects that must be fixed.

FILE: {path}

DEFECTS FOUND:
{defect_list}

PLANNED PROJECT FILES (the ONLY local modules you may import):
{planned_list}

APP SPEC:
{json.dumps(intent, indent=2)[:1200]}

CURRENT CODE:
{current}

Rewrite the file so every defect above is resolved:
- Replace every stub with a real, working implementation.
- Import only planned project modules or installed third-party packages.
- All imports at the top of the file, never inside a function body.
- Keep the existing public names (router, function names, model classes) so the
  rest of the project still imports correctly.
- Do not add code belonging to any other file.

Return ONLY the complete corrected Python code. No markdown, no explanation."""
        return self.think(prompt)

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

IMPORT DIRECTION CONTRACT:
- models.py may not import any local project modules.
- services.py may import models.py only; it must not import routes.py, main.py, app.py,
  or sibling feature modules that import services.py.
- routes.py may import services.py and models.py.
- main.py may import routes.py only for the API router.
- Never create circular imports. Never include code for any other file inside this file.
- Do not invent a different domain. If the app is a CSV/PDF report generator, do not
  create weather models, weather routes, or weather services.
- If the user says a UI is optional, choose the planned primary entrypoint and do not
  wire Streamlit and FastAPI together unless both are explicitly required.

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
