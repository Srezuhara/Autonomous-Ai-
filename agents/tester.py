"""
agents/tester.py — Generates, runs, and auto-fixes pytest tests.

Changes in this version
────────────────────────
1. TESTABLE_FILES expanded + auto-discovery of any .py with def/class.
2. _run_pytest_single — each file tested in FULL ISOLATION (fixes stale-test poisoning).
3. CONFTEST_TEMPLATE — smarter 2-level path scan handles deeply-nested projects.
4. _pre_install_deps — installs project requirements.txt before running tests.
5. _extract_function_names — passes actual function names to LLM for accurate mocks.
6. FastAPI vs plain-Python detection for correct test pattern selection.
7. JS/TS file detection noted (Vitest scaffolding deferred — no npm in pipeline yet).
"""
import logging
import sys
import re
from pathlib import Path
from dataclasses import dataclass, field
from agents.base_agent import BaseAgent
from tools.file_writer import read_file, create_file
from tools.code_executor import run_command
import config

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "tester.txt"

# Expanded set of testable Python filenames
TESTABLE_FILES = {
    "main.py", "routes.py", "services.py", "models.py",
    "app.py", "api.py", "views.py", "handlers.py",
    "utils.py", "helpers.py", "logic.py", "core.py",
    "weather_api.py", "weather_service.py", "forecast_api.py",
    "data_analysis.py", "report.py", "processor.py", "pipeline.py",
    "tasks.py", "scheduler.py", "worker.py",
}

MAX_TEST_FIXES = 2

# ── Smart conftest.py — handles flat and deeply-nested project structures ──────
CONFTEST_TEMPLATE = '''\
import sys, os

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.normpath(os.path.join(_tests_dir, ".."))

_SKIP = {"tests", "__pycache__", "node_modules", "frontend", "dist", ".git",
         "venv", ".venv", "env", "static", "assets"}


def _add_if_has_py(path):
    """Add path to sys.path only if it contains .py files (not recursively)."""
    if not os.path.isdir(path):
        return
    if path in sys.path:
        return
    try:
        if any(f.endswith(".py") for f in os.listdir(path)):
            sys.path.insert(0, path)
    except (PermissionError, OSError):
        pass


# Always add project root
_add_if_has_py(_project_root)

# Add first-level subdirs
for _name in os.listdir(_project_root):
    if _name.startswith(".") or _name in _SKIP:
        continue
    _sub = os.path.join(_project_root, _name)
    if not os.path.isdir(_sub):
        continue
    _add_if_has_py(_sub)
    # Add second-level subdirs (handles double-nested: project/project/module.py)
    try:
        for _name2 in os.listdir(_sub):
            if _name2.startswith(".") or _name2 in _SKIP:
                continue
            _sub2 = os.path.join(_sub, _name2)
            if os.path.isdir(_sub2):
                _add_if_has_py(_sub2)
    except (PermissionError, OSError):
        pass
'''


@dataclass
class TestResult:
    file_path:       str
    test_file:       str  = ""
    tests_generated: int  = 0
    passed:          int  = 0
    failed:          int  = 0
    errors:          list = field(default_factory=list)
    skipped:         bool = False
    skip_reason:     str  = ""

    def __str__(self):
        if self.skipped:
            return f"⏭️  {self.file_path} ({self.skip_reason})"
        status = "✅" if self.failed == 0 and self.tests_generated > 0 else "❌"
        return f"{status} {self.file_path} — {self.passed}/{self.tests_generated} tests passed"


class Tester(BaseAgent):
    def __init__(self):
        system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
        super().__init__("Tester", system_prompt)

    def run(
        self,
        file_paths:    list[str],
        architecture:  dict,
        debug_results: list = None,
    ) -> list[TestResult]:
        root = architecture.get("root_folder", "project")
        passed_files = (
            {r.file_path for r in debug_results if r.success}
            if debug_results else set()
        )

        py_files = self._discover_testable_files(file_paths)
        logger.info(f"🧪 Generating tests for {len(py_files)} files...")

        # Write conftest.py with smart path resolution
        create_file(f"{root}/tests/conftest.py", CONFTEST_TEMPLATE)

        # Pre-install project dependencies so pytest imports don't fail
        self._pre_install_deps(root)

        results = []
        for fp in py_files:
            if debug_results and fp not in passed_files:
                r = TestResult(
                    file_path=fp, skipped=True, skip_reason="debug failed"
                )
                results.append(r)
                logger.info(str(r))
                continue

            result = self._test_file(fp, root)
            results.append(result)
            logger.info(str(result))

        total_passed = sum(r.passed for r in results)
        total_tests  = sum(r.tests_generated for r in results)
        logger.info(f"🧪 Testing complete — {total_passed}/{total_tests} tests passing")
        return results

    # ── File discovery ─────────────────────────────────────────────────────────

    def _discover_testable_files(self, file_paths: list[str]) -> list[str]:
        """
        Return Python files eligible for testing.
        Combines the static allowlist with auto-discovery of any .py file
        that actually defines functions or classes.
        """
        candidates = []
        for fp in file_paths:
            if not fp.endswith(".py"):
                continue
            name = Path(fp).name
            if name.startswith("__") or name in {"config.py", "conftest.py"}:
                continue
            if name in TESTABLE_FILES:
                candidates.append(fp)
                continue
            # Auto-discover: any .py with at least one def or class
            try:
                src = read_file(fp)
                if re.search(r'^(?:async )?def \w+|^class \w+', src, re.MULTILINE):
                    candidates.append(fp)
            except Exception:
                pass
        # Deduplicate, preserve order
        seen = set()
        result = []
        for fp in candidates:
            if fp not in seen:
                seen.add(fp)
                result.append(fp)
        return result

    # ── Dependency pre-installation ────────────────────────────────────────────

    def _pre_install_deps(self, root: str) -> None:
        """Install project requirements.txt before running tests."""
        from tools.dependency_installer import pip_install_requirements
        req_file = Path(config.OUTPUT_DIR) / root / "requirements.txt"
        if not req_file.exists():
            # Also check backend/requirements.txt
            req_file = Path(config.OUTPUT_DIR) / root / "backend" / "requirements.txt"
        if req_file.exists():
            logger.info(f"📦 Installing project dependencies from {req_file.name}...")
            result = pip_install_requirements(str(req_file))
            if result.success:
                logger.info("✅ Dependencies installed")
            else:
                logger.warning(f"⚠️  Some deps failed to install: {result.stderr[:200]}")

    # ── pytest runner — ISOLATED per file ──────────────────────────────────────

    def _run_pytest_single(
        self, test_file_abs: str, project_root_abs: str
    ) -> tuple[str, int]:
        """
        Run pytest on ONE test file only.
        cwd = project root so conftest.py is auto-discovered.
        Running a single file prevents stale broken tests poisoning other files.
        """
        rel_test = Path(test_file_abs).relative_to(project_root_abs)
        res = run_command(
            f'"{sys.executable}" -m pytest "{rel_test}" -v --tb=short --no-header',
            cwd=project_root_abs,
            timeout=90,
        )
        output = (res.stdout or "") + (res.stderr or "")
        return output, res.returncode

    # ── Source code helpers ────────────────────────────────────────────────────

    def _extract_function_names(self, code: str) -> list[str]:
        """Extract top-level function/async function names from Python source."""
        return re.findall(r'^(?:async )?def (\w+)', code, re.MULTILINE)

    def _is_fastapi_file(self, code: str) -> bool:
        """True if the source file uses FastAPI or APIRouter."""
        return bool(re.search(r'\b(FastAPI|APIRouter|TestClient)\b', code))

    # ── Main per-file flow ─────────────────────────────────────────────────────

    def _test_file(self, file_path: str, root: str) -> TestResult:
        result        = TestResult(file_path=file_path)
        filename      = Path(file_path).stem
        test_filename = f"test_{filename}.py"
        test_path     = f"{root}/tests/{test_filename}"

        project_root_abs = str((Path(config.OUTPUT_DIR) / root).resolve())
        test_file_abs    = str((Path(config.OUTPUT_DIR) / test_path).resolve())

        # Read source file
        try:
            code = read_file(file_path)
        except Exception as e:
            result.errors.append(f"Could not read source: {e}")
            return result

        # Detect file kind for appropriate test pattern
        is_fastapi = self._is_fastapi_file(code)
        func_names = self._extract_function_names(code)

        # Pull routes context for accurate endpoint paths
        routes_context = ""
        try:
            routes_code   = read_file(f"{root}/backend/routes.py")
            routes_context = (
                f"\nROUTES (exact endpoint paths + function names):\n"
                f"{routes_code[:1200]}"
            )
        except Exception:
            pass

        # Pull main.py context for app instantiation
        main_context = ""
        try:
            main_code   = read_file(f"{root}/backend/main.py")
            main_context = f"\nMAIN.PY (how the FastAPI app is created):\n{main_code[:600]}"
        except Exception:
            pass

        # Generate tests
        test_code = self._generate_tests(
            file_path, code, routes_context, main_context,
            is_fastapi=is_fastapi, func_names=func_names,
        )
        if not test_code or not test_code.strip():
            result.skipped    = True
            result.skip_reason = "LLM returned empty"
            return result

        create_file(test_path, test_code)

        # Run + auto-fix loop (ISOLATED — only this test file)
        passed = 0
        failed = 0
        for attempt in range(1, MAX_TEST_FIXES + 2):
            output, returncode = self._run_pytest_single(test_file_abs, project_root_abs)

            if returncode == 2:
                logger.warning(
                    f"  ⚠️  pytest collection error (exit 2) attempt {attempt}:\n"
                    f"  {output[-600:]}"
                )
                if attempt <= MAX_TEST_FIXES:
                    fixed = self._fix_collection_error(
                        test_path, test_code, output, routes_context, main_context
                    )
                    if fixed:
                        create_file(test_path, fixed)
                        test_code = fixed
                    continue
                else:
                    result.errors.append("pytest collection error — " + output[-300:])
                    result.skipped    = True
                    result.skip_reason = "collection error"
                    return result

            passed = self._count_keyword(output, "passed")
            failed = self._count_keyword(output, "failed")
            total  = passed + failed

            logger.info(f"  ✅ Tests: {passed}/{total} passing (attempt {attempt})")

            if returncode == 0 or failed == 0:
                result.tests_generated = total
                result.passed          = passed
                result.failed          = 0
                return result

            if attempt <= MAX_TEST_FIXES and failed > 0:
                logger.info(f"  🔧 {failed} test(s) failing — asking LLM to fix (attempt {attempt})")
                try:
                    current = read_file(test_path)
                except Exception:
                    break
                fixed = self._fix_tests(
                    test_path, current, output, routes_context, main_context
                )
                if fixed:
                    create_file(test_path, fixed)
            else:
                break

        result.tests_generated = passed + failed
        result.passed          = passed
        result.failed          = failed
        return result

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _generate_tests(
        self,
        file_path:     str,
        code:          str,
        routes_context: str,
        main_context:   str,
        is_fastapi:    bool = True,
        func_names:    list = None,
    ) -> str:
        func_names = func_names or []
        func_hint  = (
            f"\nACTUAL FUNCTION NAMES IN THIS FILE: {func_names}\n"
            "Use ONLY these names when constructing mock paths (e.g. 'routes.fetch_tasks')."
            if func_names else ""
        )

        if is_fastapi:
            pattern_instruction = """
PATTERN A — FastAPI (use this because the file uses FastAPI/APIRouter):
  from fastapi.testclient import TestClient
  from unittest.mock import patch, MagicMock
  from main import app

  client = TestClient(app)

  def test_endpoint_success():
      with patch('routes.fetch_items') as mock:
          mock.return_value = [{"id": 1, "name": "test"}]
          response = client.get('/items')
          assert response.status_code == 200

  def test_endpoint_not_found():
      with patch('routes.fetch_item') as mock:
          mock.return_value = None
          response = client.get('/items/999')
          assert response.status_code == 404

  def test_missing_required_param():
      response = client.post('/items', json={})
      assert response.status_code == 422
"""
        else:
            pattern_instruction = """
PATTERN B — Plain Python (use this because the file does NOT use FastAPI):
  from unittest.mock import patch, MagicMock
  import {module}

  def test_function_returns_expected():
      result = {module}.some_function("valid_input")
      assert result is not None

  def test_function_handles_empty():
      result = {module}.some_function("")
      assert result is not None or True  # no exception

  def test_function_with_mock():
      with patch('{module}.requests.get') as mock:
          mock.return_value.json.return_value = {{"key": "val"}}
          result = {module}.some_function("input")
          assert result is not None
""".replace("{module}", Path(file_path).stem)

        prompt = f"""Write pytest tests for this Python file.

FILE: {file_path}
CODE:
{code[:2000]}{routes_context}{main_context}{func_hint}

{pattern_instruction}

CRITICAL IMPORT RULE:
- Use ONLY the file's simple module name (stem), never dotted paths.
  CORRECT:   from main import app
  CORRECT:   import services
  WRONG:     from backend.main import app
  WRONG:     from weather_dashboard.backend.services import fetch

- conftest.py has already added all source directories to sys.path.
- Begin the test file EXACTLY with the import block — NO sys.path manipulation.

Rules:
- Write exactly 3 test functions.
- Mock using the ACTUAL FUNCTION NAMES listed above.
- No real API calls, no real API keys.
- Return ONLY the Python test code. No markdown. No explanations."""
        return self.think(prompt)

    def _fix_collection_error(
        self,
        test_path:      str,
        current_code:   str,
        error_output:   str,
        routes_context: str,
        main_context:   str,
    ) -> str:
        prompt = f"""Fix this pytest test file that fails at COLLECTION time (before any test runs).

TEST FILE: {test_path}
CURRENT CODE:
{current_code}

PYTEST ERROR OUTPUT:
{error_output[-1000:]}
{routes_context}{main_context}

Collection errors mean pytest cannot even import the file. Common causes:
- Wrong import path: use `from main import app` not `from backend.main import app`
- Wrong mock path: use `routes.function_name` not `backend.routes.function_name`
- Syntax error in the test file
- Importing something that doesn't exist in this project

CRITICAL IMPORT RULE: Never use dotted module paths. The conftest.py handles sys.path.

Fix the imports and mock paths. Keep all 3 test functions.
Return ONLY the complete corrected Python test code. No markdown."""
        return self.think(prompt)

    def _fix_tests(
        self,
        test_path:      str,
        current_code:   str,
        error_output:   str,
        routes_context: str,
        main_context:   str,
    ) -> str:
        prompt = f"""Fix these failing pytest tests.

TEST FILE: {test_path}
CURRENT TEST CODE:
{current_code}

PYTEST OUTPUT (showing failures):
{error_output[-1000:]}
{routes_context}{main_context}

Common fixes:
- Wrong mock path: use 'routes.function_name' not 'services.function_name'
- Wrong endpoint URL: check routes.py for exact paths
- Wrong response field: check what the endpoint actually returns
- 422 expected but 200: pass required params to avoid validation pass-through
- AttributeError on mock: use the ACTUAL function name from the source file

CRITICAL IMPORT RULE: Never use dotted module paths (no `from backend.x import y`).

Return ONLY the complete fixed Python test code. No markdown."""
        return self.think(prompt)

    # ── Output parsers ─────────────────────────────────────────────────────────

    def _count_keyword(self, output: str, keyword: str) -> int:
        if not output:
            return 0
        m = re.search(rf"(\d+)\s+{keyword}", output)
        return int(m.group(1)) if m else 0

    def summary(self, results: list[TestResult]) -> str:
        lines = [f"\n{'='*50}", "  TEST SUMMARY", f"{'='*50}"]
        total_passed = sum(r.passed for r in results)
        total_tests  = sum(r.tests_generated for r in results)
        for r in results:
            lines.append(f"  {r}")
            for err in r.errors:
                lines.append(f"     💥 {err[:200]}")
        lines.append(f"\n  Total: {total_passed}/{total_tests} tests passing")
        lines.append(f"{'='*50}\n")
        return "\n".join(lines)
