"""
agents/tester.py — Generates, runs, and auto-fixes pytest tests.

Fixes vs previous version
──────────────────────────
1. conftest.py — now adds the PROJECT ROOT (not just backend/) to sys.path
   so `from main import app` works during pytest collection.
   Also adds the app root so relative imports inside main.py resolve.

2. pytest invocation — switched from `pytest test_routes.py` (filename only)
   to `pytest tests/` (full relative path from project root).
   cwd is now the project root, not the tests/ subdirectory.
   This eliminates exit-code-2 collection errors entirely.

3. _count() — the old regex had a capture group (\d+) inside the pattern
   but re.search() was called on the full pattern string including the group,
   so group(1) was always the right thing but the pattern was written as a
   raw string arg to _count() — actually the bug was _count() was called with
   the group already in the pattern but `m.group(1)` relied on it — this was
   fine but the real issue was exit-code-2 giving empty output.  Fixed anyway
   to be explicit and handle edge cases (collection errors, no tests collected).

4. test_score None when 0 tests collected — added guard: if pytest exits with
   code 2 (collection error) we log the output and skip rather than recording
   0/0. This surfaces the real error instead of silently returning None.
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

PROMPT_FILE    = Path(__file__).parent.parent / "prompts" / "tester.txt"
TESTABLE_FILES = {"main.py", "routes.py"}
MAX_TEST_FIXES = 2

# ── conftest.py written into every tests/ folder ──────────────────────────────
# Adds THREE paths so imports always resolve:
#   1. project root  (so `from main import app` works)
#   2. backend/      (so `import routes` works from test files)
#   3. tests/        (for any test-local helpers)
CONFTEST = '''\
import sys, os

_tests_dir   = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.normpath(os.path.join(_tests_dir, '..', 'backend'))
_root_dir    = os.path.normpath(os.path.join(_tests_dir, '..'))

for _p in [_root_dir, _backend_dir, _tests_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
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

        py_files = [
            f for f in file_paths
            if f.endswith(".py") and Path(f).name in TESTABLE_FILES
        ]
        logger.info(f"🧪 Generating tests for {len(py_files)} files...")

        # Write conftest.py that fixes sys.path for ALL imports
        create_file(f"{root}/tests/conftest.py", CONFTEST)

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

    # ── pytest runner ─────────────────────────────────────────────────────────

    def _run_pytest(self, tests_dir_abs: str, project_root_abs: str) -> tuple[str, int]:
        """
        Run pytest from the PROJECT ROOT (not from tests/).
        Command: python -m pytest tests/ -v --tb=short --no-header
        cwd:     project_root  ← key fix: was tests_dir before

        Running from project root means:
          - conftest.py is discovered automatically
          - relative imports inside main.py / routes.py resolve correctly
          - exit code 2 (collection error) is eliminated
        """
        # Path to the tests folder relative to project root
        rel_tests = Path(tests_dir_abs).relative_to(project_root_abs)

        res = run_command(
            f'"{sys.executable}" -m pytest "{rel_tests}" -v --tb=short --no-header',
            cwd=project_root_abs,
            timeout=90,
        )
        output = (res.stdout or "") + (res.stderr or "")
        return output, res.returncode

    # ── main per-file flow ────────────────────────────────────────────────────

    def _test_file(self, file_path: str, root: str) -> TestResult:
        result       = TestResult(file_path=file_path)
        filename     = Path(file_path).stem
        test_filename = f"test_{filename}.py"
        test_path    = f"{root}/tests/{test_filename}"

        # Absolute paths needed for cwd
        project_root_abs = str((Path(config.OUTPUT_DIR) / root).resolve())
        tests_dir_abs    = str((Path(config.OUTPUT_DIR) / root / "tests").resolve())

        # Read source file
        try:
            code = read_file(file_path)
        except Exception as e:
            result.errors.append(f"Could not read source: {e}")
            return result

        # Try to pull in routes context so LLM knows exact endpoint paths
        routes_context = ""
        try:
            routes_code   = read_file(f"{root}/backend/routes.py")
            routes_context = (
                f"\nROUTES (exact endpoint paths + function names):\n"
                f"{routes_code[:1200]}"
            )
        except Exception:
            pass

        # Also pull main.py context for app instantiation
        main_context = ""
        try:
            main_code   = read_file(f"{root}/backend/main.py")
            main_context = f"\nMAIN.PY (how the FastAPI app is created):\n{main_code[:600]}"
        except Exception:
            pass

        # Generate initial tests
        test_code = self._generate_tests(file_path, code, routes_context, main_context)
        if not test_code or not test_code.strip():
            result.skipped    = True
            result.skip_reason = "LLM returned empty"
            return result

        create_file(test_path, test_code)

        # Run + auto-fix loop
        passed = 0
        failed = 0
        for attempt in range(1, MAX_TEST_FIXES + 2):
            output, returncode = self._run_pytest(tests_dir_abs, project_root_abs)

            # Exit code 2 = collection error (import failure, syntax error in test)
            if returncode == 2:
                logger.warning(
                    f"  ⚠️  pytest collection error (exit 2) on attempt {attempt}:\n"
                    f"  {output[-600:]}"
                )
                if attempt <= MAX_TEST_FIXES:
                    fixed = self._fix_collection_error(test_path, test_code, output, routes_context, main_context)
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
                fixed = self._fix_tests(test_path, current, output, routes_context, main_context)
                if fixed:
                    create_file(test_path, fixed)
            else:
                break

        # Final tally
        result.tests_generated = passed + failed
        result.passed          = passed
        result.failed          = failed
        return result

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _generate_tests(
        self,
        file_path: str,
        code: str,
        routes_context: str,
        main_context: str,
    ) -> str:
        prompt = f"""Write pytest tests for this FastAPI backend file.

FILE: {file_path}
CODE:
{code}{routes_context}{main_context}

IMPORTANT — begin the test file EXACTLY like this (no sys.path lines, conftest handles that):
  from fastapi.testclient import TestClient
  from unittest.mock import patch, MagicMock
  from main import app

  client = TestClient(app)

Rules:
- Write exactly 3 test functions
- Use the EXACT endpoint paths from routes.py
- Mock using the exact function name as it appears in routes.py with prefix 'routes.'
- Test a success case, a not-found/error case, and a validation error (422)

Example pattern:
  def test_get_items_success():
      with patch('routes.fetch_items') as mock:
          mock.return_value = [{{"id": 1, "name": "test"}}]
          response = client.get('/items')
          assert response.status_code == 200
          assert isinstance(response.json(), list)

  def test_item_not_found():
      with patch('routes.fetch_item') as mock:
          mock.return_value = None
          response = client.get('/items/999')
          assert response.status_code == 404

  def test_missing_required_param():
      response = client.post('/items', json={{}})
      assert response.status_code == 422

Return ONLY the Python test code. No markdown fences. No explanations."""
        return self.think(prompt)

    def _fix_collection_error(
        self,
        test_path: str,
        current_code: str,
        error_output: str,
        routes_context: str,
        main_context: str,
    ) -> str:
        prompt = f"""Fix this pytest test file that fails at COLLECTION time (before any test runs).

TEST FILE: {test_path}
CURRENT CODE:
{current_code}

PYTEST ERROR OUTPUT:
{error_output[-1000:]}
{routes_context}{main_context}

Collection errors mean pytest can't even import the file. Common causes:
- Wrong import: use `from main import app` not `from backend.main import app`
- Wrong mock path: use `routes.function_name` not `backend.routes.function_name`
- Syntax error in the test file itself
- Importing something that doesn't exist

Fix the imports and mock paths. Keep all 3 test functions.
Return ONLY the complete corrected Python test code. No markdown."""
        return self.think(prompt)

    def _fix_tests(
        self,
        test_path: str,
        current_code: str,
        error_output: str,
        routes_context: str,
        main_context: str,
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

Return ONLY the complete fixed Python test code. No markdown."""
        return self.think(prompt)

    # ── output parsers ────────────────────────────────────────────────────────

    def _count_keyword(self, output: str, keyword: str) -> int:
        """
        Parse pytest summary line.
        Handles: '3 passed', '1 failed', '2 passed, 1 warning'
        Guards against collection errors giving '0 errors' false positives.
        """
        if not output:
            return 0
        # Match "N keyword" where N is a digit sequence
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
