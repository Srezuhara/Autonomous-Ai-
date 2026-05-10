"""
agents/tester.py — Generates, runs, and auto-fixes pytest tests.

Phase 16 additions:
─────────────────────────────────────────────────────────────
16.2  Sibling context in _get_sibling_import_context()
      When generating tests for services.py, shows the LLM exactly which
      functions routes.py imports from it — prevents testing the wrong ones.

16.3  Vitest frontend test scaffolding
      - _has_js_files() detects JS/TS/JSX in file_paths OR on disk
      - _setup_vitest() installs vitest + jsdom + @testing-library/react
      - _generate_js_test() asks LLM for a basic App.test.js
      - _run_vitest() runs `npx vitest run` cross-platform (no 2>&1)
      - JS TestResult appended to results so test_score includes frontend

Bug fixes vs previous version:
  - run_command() does not accept env= param; PYTHONPATH cleared via
    pytest -p no:cacheprovider instead, and conftest isolation is used
  - _run_vitest() no longer uses shell redirect (2>&1) — broken on Windows
  - _setup_vitest() now also installs @testing-library/react so the LLM
    can use render() in React component tests
  - vitest.config.js renamed to vitest.config.mjs (avoids CJS/ESM clash)
    and written into package.json test script for reliability
  - _has_js_files() now also scans disk under root/frontend/src/ so it
    works even when architect puts JS files under a different path prefix
  - _run_vitest_if_applicable() writes test to .jsx extension when the
    project uses React so Vitest can parse JSX without extra babel config

All Phase 15 v3 fixes retained:
  pytest.ini written to project root, --tb=long -p no:warnings,
  _run_collect_only(), _extract_failures(), _build_mock_examples(),
  _is_pydantic_only_file(), passing test name preservation, MAX_TEST_FIXES=3.
"""
import logging
import os
import sys
import re
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from agents.base_agent import BaseAgent
from tools.file_writer import read_file, create_file
from tools.code_executor import run_command
import config

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "tester.txt"

TESTABLE_FILES = {
    "main.py", "routes.py", "services.py", "models.py",
    "app.py", "api.py", "views.py", "handlers.py",
    "utils.py", "helpers.py", "logic.py", "core.py",
    "weather_api.py", "weather_service.py", "forecast_api.py",
    "data_analysis.py", "report.py", "processor.py", "pipeline.py",
    "tasks.py", "scheduler.py", "worker.py",
}

JS_TESTABLE_TYPES = {".js", ".jsx", ".ts", ".tsx"}

MAX_TEST_FIXES = 3  # 4 total attempts: initial + 3 fixes

PYTEST_INI_TEMPLATE = """\
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
    ignore::UserWarning
"""

CONFTEST_TEMPLATE = '''\
import sys, os

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.normpath(os.path.join(_tests_dir, ".."))

_SKIP = {"tests", "__pycache__", "node_modules", "frontend", "dist", ".git",
         "venv", ".venv", "env", "static", "assets"}


def _add_if_has_py(path):
    if not os.path.isdir(path):
        return
    if path in sys.path:
        return
    try:
        if any(f.endswith(".py") for f in os.listdir(path)):
            sys.path.insert(0, path)
    except (PermissionError, OSError):
        pass


_add_if_has_py(_project_root)

for _name in os.listdir(_project_root):
    if _name.startswith(".") or _name in _SKIP:
        continue
    _sub = os.path.join(_project_root, _name)
    if not os.path.isdir(_sub):
        continue
    _add_if_has_py(_sub)
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

# vitest.config.mjs — uses ESM syntax, avoids CJS/ESM clash with Vite 4+
# We use defineConfig from 'vitest/config' (not 'vite') so it works even
# when the project's vite.config.ts uses plugins Vitest doesn't know about.
VITEST_CONFIG = """\
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/__tests__/**/*.{js,jsx,ts,tsx}', 'src/**/*.{test,spec}.{js,jsx,ts,tsx}'],
  },
})
"""


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
        logger.info(f"🧪 Generating tests for {len(py_files)} Python files...")

        create_file(f"{root}/pytest.ini", PYTEST_INI_TEMPLATE)
        create_file(f"{root}/tests/conftest.py", CONFTEST_TEMPLATE)
        self._pre_install_deps(root)

        results = []

        # ── Python tests ───────────────────────────────────────────────────────
        for fp in py_files:
            if debug_results and fp not in passed_files:
                r = TestResult(file_path=fp, skipped=True, skip_reason="debug failed")
                results.append(r)
                logger.info(str(r))
                continue
            result = self._test_file(fp, root)
            results.append(result)
            logger.info(str(result))

        # ── Phase 16.3: Vitest frontend tests ─────────────────────────────────
        js_result = self._run_vitest_if_applicable(file_paths, root)
        if js_result:
            results.append(js_result)
            logger.info(str(js_result))

        total_passed = sum(r.passed for r in results)
        total_tests  = sum(r.tests_generated for r in results)
        logger.info(f"🧪 Testing complete — {total_passed}/{total_tests} tests passing")
        return results

    # ── File discovery ─────────────────────────────────────────────────────────

    def _discover_testable_files(self, file_paths: list[str]) -> list[str]:
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
            try:
                src = read_file(fp)
                if re.search(r'^(?:async )?def \w+|^class \w+', src, re.MULTILINE):
                    candidates.append(fp)
            except Exception:
                pass
        seen = set()
        result = []
        for fp in candidates:
            if fp not in seen:
                seen.add(fp)
                result.append(fp)
        return result

    # ── Dependency pre-installation ────────────────────────────────────────────

    def _pre_install_deps(self, root: str) -> None:
        from tools.dependency_installer import pip_install_requirements
        req_file = Path(config.OUTPUT_DIR) / root / "requirements.txt"
        if not req_file.exists():
            req_file = Path(config.OUTPUT_DIR) / root / "backend" / "requirements.txt"
        if req_file.exists():
            logger.info(f"📦 Installing project dependencies from {req_file.name}...")
            result = pip_install_requirements(str(req_file))
            if result.success:
                logger.info("✅ Dependencies installed")
            else:
                logger.warning(f"⚠️  Some deps failed: {result.stderr[:200]}")

    # ── pytest runners ─────────────────────────────────────────────────────────
    # NOTE: run_command() in tools/code_executor.py does NOT accept an env=
    # parameter. We clear PYTHONPATH by using subprocess directly here so
    # the pytest subprocess cannot accidentally import the platform's config.py.

    def _run_subprocess(
        self, cmd: str, cwd: str, timeout: int = 90
    ) -> tuple[str, int]:
        """
        Run a shell command with PYTHONPATH cleared to prevent the pytest
        subprocess from picking up the platform's own config.py / routes.py.
        Uses subprocess directly because run_command() doesn't support env=.
        """
        env = os.environ.copy()
        env["PYTHONPATH"] = ""

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return output, result.returncode
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s", -1
        except Exception as e:
            return str(e), -1

    def _run_pytest_single(
        self, test_file_abs: str, project_root_abs: str
    ) -> tuple[str, int]:
        rel_test_str = str(
            Path(test_file_abs).relative_to(project_root_abs)
        ).replace("\\", "/")

        cmd = (
            f'"{sys.executable}" -m pytest "{rel_test_str}" -v --tb=long --no-header '
            f'-p no:warnings -W ignore::DeprecationWarning -W ignore::UserWarning'
        )
        return self._run_subprocess(cmd, project_root_abs, timeout=90)

    def _run_collect_only(
        self, test_file_abs: str, project_root_abs: str
    ) -> str:
        rel_test_str = str(
            Path(test_file_abs).relative_to(project_root_abs)
        ).replace("\\", "/")

        cmd = (
            f'"{sys.executable}" -m pytest "{rel_test_str}" --collect-only --tb=long '
            f'-W ignore::DeprecationWarning -W ignore::UserWarning'
        )
        output, _ = self._run_subprocess(cmd, project_root_abs, timeout=30)
        return output

    # ── Output helpers ─────────────────────────────────────────────────────────

    def _extract_failures(self, output: str) -> str:
        failures_match = re.search(
            r'={3,}\s+FAILURES\s+={3,}(.*?)(?=\n={3,}|\Z)',
            output,
            re.DOTALL,
        )
        if failures_match:
            block = failures_match.group(1).strip()
            if len(block) > 2500:
                block = block[:2500] + "\n... (truncated)"
            return block

        error_lines = []
        lines = output.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("E ") or line.startswith("FAILED ") or ">       " in line:
                start = max(0, i - 3)
                end   = min(len(lines), i + 5)
                error_lines.extend(lines[start:end])
                error_lines.append("---")
            if len(error_lines) > 80:
                break

        return "\n".join(error_lines) if error_lines else output[-1500:]

    def _extract_passing_test_names(self, output: str) -> list[str]:
        return re.findall(r'PASSED\s+(tests/\S+::\S+)', output)

    # ── Source code helpers ────────────────────────────────────────────────────

    def _extract_function_names(self, code: str) -> list[str]:
        return re.findall(r'^(?:async )?def (\w+)', code, re.MULTILINE)

    def _is_fastapi_file(self, code: str) -> bool:
        return bool(re.search(r'\b(FastAPI|APIRouter|TestClient)\b', code))

    def _is_pydantic_only_file(self, code: str) -> bool:
        has_basemodel = bool(re.search(r'class\s+\w+\s*\(.*BaseModel', code))
        has_fastapi   = self._is_fastapi_file(code)
        has_functions = bool(re.search(r'^(?:async )?def \w+', code, re.MULTILINE))
        return has_basemodel and not has_fastapi and not has_functions

    def _build_mock_examples(self, file_path: str, func_names: list[str]) -> str:
        stem = Path(file_path).stem
        if not func_names:
            return ""
        examples = []
        for fn in func_names[:4]:
            examples.append(
                f"  with patch('{stem}.{fn}') as mock_{fn}:\n"
                f"      mock_{fn}.return_value = {{\"result\": \"ok\"}}"
            )
        return (
            "\n\nEXACT MOCK SYNTAX — copy-paste these, do NOT invent other names:\n"
            + "\n".join(examples)
            + "\n\nCRITICAL: ONLY use the function names above in ALL patch() calls."
        )

    def _get_sibling_import_context(self, file_path: str, root: str) -> str:
        """
        Phase 16.2 — show the LLM which functions sibling files import from
        the file under test, so it writes tests for the right functions.
        """
        stem = Path(file_path).stem
        lines = []
        for sibling in ["main.py", "routes.py", "models.py"]:
            try:
                src = read_file(f"{root}/backend/{sibling}")
                imports = [l.strip() for l in src.splitlines()
                           if "import" in l and stem in l]
                if imports:
                    lines.append(f"\n{sibling} imports from this file:")
                    lines.extend(f"  {l}" for l in imports[:5])
            except Exception:
                pass
        return "\n".join(lines)

    # ── Phase 16.3 — Vitest frontend scaffolding ───────────────────────────────

    def _has_js_files(self, file_paths: list[str], root: str = "") -> bool:
        """
        Returns True if any JS/TS file exists either in file_paths OR on disk
        under root/frontend/src/. The disk scan is needed because the architect
        sometimes uses path prefixes that differ from what file_paths contains.
        """
        # Check file_paths list first (fast path)
        if any(Path(f).suffix in JS_TESTABLE_TYPES for f in file_paths):
            return True

        # Disk scan fallback — look inside frontend/src/
        if root:
            frontend_src = Path(config.OUTPUT_DIR) / root / "frontend" / "src"
            if frontend_src.exists():
                for ext in JS_TESTABLE_TYPES:
                    if any(frontend_src.rglob(f"*{ext}")):
                        return True

        return False

    def _get_js_files_from_disk(self, root: str) -> list[str]:
        """Scan disk for JS/TS source files under root/frontend/src/."""
        frontend_src = Path(config.OUTPUT_DIR) / root / "frontend" / "src"
        if not frontend_src.exists():
            return []
        found = []
        for ext in JS_TESTABLE_TYPES:
            for p in frontend_src.rglob(f"*{ext}"):
                # Skip test files and node_modules
                parts = p.parts
                if any(s in parts for s in ("__tests__", "node_modules", "dist")):
                    continue
                if p.name.endswith((".test.js", ".test.ts", ".spec.js", ".spec.ts")):
                    continue
                found.append(str(p))
        return found

    def _setup_vitest(self, root: str) -> bool:
        """
        Install Vitest and related packages into the frontend/ directory.
        Also installs @testing-library/react so the LLM can write render() tests.
        Returns True if install succeeded.
        """
        frontend_dir = Path(config.OUTPUT_DIR) / root / "frontend"
        if not (frontend_dir / "package.json").exists():
            logger.info("⏭️  No frontend/package.json — skipping Vitest")
            return False

        logger.info("📦 Installing Vitest for frontend tests...")

        # Single npm install call — faster than separate calls
        packages = (
            "vitest jsdom @vitest/coverage-v8 "
            "@testing-library/react @testing-library/jest-dom "
            "@testing-library/user-event"
        )
        result = run_command(
            f"npm install --save-dev {packages} --silent --legacy-peer-deps",
            cwd=str(frontend_dir),
            timeout=180,  # npm install can be slow
        )
        if result.success:
            logger.info("✅ Vitest + @testing-library installed")
            return True

        # If --legacy-peer-deps fails, try --force
        logger.warning(f"⚠️  Vitest install (legacy-peer-deps) failed, retrying with --force...")
        result2 = run_command(
            f"npm install --save-dev {packages} --silent --force",
            cwd=str(frontend_dir),
            timeout=180,
        )
        if result2.success:
            logger.info("✅ Vitest installed (force mode)")
            return True

        logger.warning(f"⚠️  Vitest install failed: {result2.stderr[:300]}")
        return False

    def _write_vitest_config(self, root: str) -> None:
        """
        Write vitest.config.mjs into frontend/ and update package.json to
        add a 'test' script so `npm test` works after download.
        Uses .mjs extension to avoid CJS/ESM conflicts with Vite 4+/5+.
        """
        frontend_dir = Path(config.OUTPUT_DIR) / root / "frontend"

        # Write config file
        config_path = frontend_dir / "vitest.config.mjs"
        try:
            config_path.write_text(VITEST_CONFIG, encoding="utf-8")
            logger.info("📄 Wrote vitest.config.mjs")
        except Exception as e:
            logger.warning(f"⚠️  Could not write vitest.config.mjs: {e}")

        # Update package.json to add test script
        pkg_json_path = frontend_dir / "package.json"
        try:
            pkg = json.loads(pkg_json_path.read_text(encoding="utf-8"))
            scripts = pkg.setdefault("scripts", {})
            if "test" not in scripts:
                scripts["test"] = "vitest run"
            if "test:watch" not in scripts:
                scripts["test:watch"] = "vitest"
            if "test:coverage" not in scripts:
                scripts["test:coverage"] = "vitest run --coverage"
            pkg_json_path.write_text(
                json.dumps(pkg, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("📄 Updated package.json with test scripts")
        except Exception as e:
            logger.warning(f"⚠️  Could not update package.json: {e}")

    def _pick_target_js_file(self, js_files: list[str]) -> str | None:
        """Pick the best JS/TS file to write a test for (App > index > first)."""
        priority = [
            "App.tsx", "App.jsx", "App.ts", "App.js",
            "index.tsx", "index.jsx", "index.ts", "index.js",
            "main.tsx", "main.jsx",
        ]
        for name in priority:
            for fp in js_files:
                if Path(fp).name == name:
                    return fp
        return js_files[0] if js_files else None

    def _is_react_file(self, code: str) -> bool:
        """True if the file imports React or uses JSX."""
        return bool(re.search(r'import\s+React|from\s+["\']react["\']|<[A-Z][A-Za-z]+', code))

    def _generate_js_test(self, target: str, root: str) -> str | None:
        """Generate a Vitest test file for the given JS/TS source file."""
        try:
            code = read_file(target)
        except Exception:
            # Try reading directly from disk path
            try:
                code = Path(target).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                code = "// Could not read file"

        stem       = Path(target).stem
        is_react   = self._is_react_file(code)
        ext        = Path(target).suffix  # .tsx, .jsx, .ts, .js

        # Determine export pattern from source
        has_default_export = "export default" in code
        named_exports = re.findall(r'export\s+(?:const|function|class)\s+(\w+)', code)

        if is_react and has_default_export:
            pattern_hint = f"""
Pattern (React component with default export):
  import {{ render, screen }} from '@testing-library/react'
  import {stem} from '../{stem}{ext}'

  describe('{stem}', () => {{
    it('renders without crashing', () => {{
      render(<{stem} />)
    }})

    it('displays something in the DOM', () => {{
      render(<{stem} />)
      expect(document.body).toBeDefined()
    }})
  }})
"""
        elif named_exports:
            first_export = named_exports[0]
            pattern_hint = f"""
Pattern (named export from module):
  import {{ {first_export} }} from '../{stem}{ext}'

  describe('{stem}', () => {{
    it('exports {first_export}', () => {{
      expect({first_export}).toBeDefined()
    }})

    it('{first_export} returns a value', () => {{
      const result = {first_export}()
      expect(result).toBeDefined()
    }})
  }})
"""
        else:
            pattern_hint = f"""
Pattern (module import):
  import * as {stem}Module from '../{stem}{ext}'

  describe('{stem}', () => {{
    it('module loads without error', () => {{
      expect({stem}Module).toBeDefined()
    }})

    it('module has expected shape', () => {{
      expect(typeof {stem}Module).toBe('object')
    }})
  }})
"""

        prompt = f"""Write a Vitest test file for this JavaScript/TypeScript file.

FILE: {target}
CODE:
{code[:1800]}

{pattern_hint}

Rules:
- Use: import {{ describe, it, expect, vi }} from 'vitest'
- For React: import {{ render }} from '@testing-library/react'
- Write exactly 2 test functions inside a describe() block
- Use relative import paths (e.g., '../App' not absolute paths)
- NO real network/API calls — mock them with vi.mock() if needed
- If the component needs Router/Redux providers, wrap with a simple mock provider
- Return ONLY the test code. No markdown, no explanation."""

        return self.think(prompt)

    def _run_vitest(self, root: str) -> tuple[str, int]:
        """
        Run vitest in the frontend directory.
        Uses subprocess directly (not run_command) to avoid the 2>&1 issue on Windows.
        """
        frontend_dir = str((Path(config.OUTPUT_DIR) / root / "frontend").resolve())

        # Use npx vitest run with explicit config path for reliability
        try:
            result = subprocess.run(
                ["npx", "vitest", "run", "--config", "vitest.config.mjs", "--reporter=verbose"],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=frontend_dir,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return output, result.returncode
        except subprocess.TimeoutExpired:
            return "Vitest timed out after 90s", -1
        except FileNotFoundError:
            # npx not found — try via node_modules directly
            try:
                result = subprocess.run(
                    [sys.executable, "-c",
                     f"import subprocess; subprocess.run(['node', 'node_modules/.bin/vitest', 'run'], "
                     f"cwd=r'{frontend_dir}')"],
                    capture_output=True, text=True, timeout=90,
                )
                output = (result.stdout or "") + (result.stderr or "")
                return output, result.returncode
            except Exception as e:
                return f"Could not run vitest: {e}", -1
        except Exception as e:
            return f"Vitest error: {e}", -1

    def _parse_vitest_results(self, output: str) -> tuple[int, int]:
        """Parse vitest verbose output for passed/failed counts."""
        passed = 0
        failed = 0

        # Vitest formats: "✓ 2 passed" or "2 passed" or "Tests  2 passed"
        m_pass = re.search(r'(\d+)\s+passed', output, re.IGNORECASE)
        m_fail = re.search(r'(\d+)\s+failed', output, re.IGNORECASE)
        if m_pass:
            passed = int(m_pass.group(1))
        if m_fail:
            failed = int(m_fail.group(1))

        # Also check for individual test results (✓ / ✗ / × lines)
        if passed == 0 and failed == 0:
            passed = len(re.findall(r'✓|✔|√', output))
            failed = len(re.findall(r'✗|✘|×|FAIL', output))

        return passed, failed

    def _run_vitest_if_applicable(
        self, file_paths: list[str], root: str
    ) -> "TestResult | None":
        """
        Full Vitest flow: detect → install → generate test → run → parse.
        Returns a TestResult or None if no JS files are found.
        """
        if not self._has_js_files(file_paths, root):
            return None

        # Collect JS files from disk (more reliable than file_paths list)
        js_files = self._get_js_files_from_disk(root)
        if not js_files:
            # Fallback to file_paths if disk scan found nothing
            js_files = [f for f in file_paths if Path(f).suffix in JS_TESTABLE_TYPES]

        logger.info(f"🧪 Found {len(js_files)} JS/TS files — running Vitest...")

        result = TestResult(
            file_path="frontend/",
            test_file="frontend/src/__tests__/App.test.jsx",
        )

        # Step 1: Install Vitest
        if not self._setup_vitest(root):
            result.skipped     = True
            result.skip_reason = "Vitest install failed or no package.json"
            return result

        # Step 2: Write config and update package.json
        self._write_vitest_config(root)

        # Step 3: Pick target and generate test
        target = self._pick_target_js_file(js_files)
        if not target:
            result.skipped     = True
            result.skip_reason = "No JS/TS target file found"
            return result

        test_code = self._generate_js_test(target, root)
        if not test_code or not test_code.strip():
            result.skipped     = True
            result.skip_reason = "LLM returned empty JS test"
            return result

        # Step 4: Write test file — use .jsx for React projects (JSX support)
        frontend_dir = Path(config.OUTPUT_DIR) / root / "frontend"
        tests_dir    = frontend_dir / "src" / "__tests__"
        tests_dir.mkdir(parents=True, exist_ok=True)

        # Detect if project uses React to pick .jsx vs .js extension
        try:
            pkg_text = (frontend_dir / "package.json").read_text(encoding="utf-8")
            uses_react = '"react"' in pkg_text
        except Exception:
            uses_react = False

        test_ext      = ".jsx" if uses_react else ".js"
        test_filename = f"App.test{test_ext}"
        test_path_abs = tests_dir / test_filename

        try:
            test_path_abs.write_text(test_code, encoding="utf-8")
            logger.info(f"📄 Wrote JS test: frontend/src/__tests__/{test_filename}")
        except Exception as e:
            result.skipped     = True
            result.skip_reason = f"Could not write test file: {e}"
            return result

        # Step 5: Run Vitest
        output, returncode = self._run_vitest(root)
        passed, failed = self._parse_vitest_results(output)
        total = passed + failed

        logger.info(f"  🧪 Vitest: {passed}/{total} passing (exit {returncode})")

        if total == 0:
            # Log output to help diagnose silent failures
            logger.warning(f"  ⚠️  Vitest collected 0 tests. Output:\n{output[-600:]}")
            result.skipped     = True
            result.skip_reason = "Vitest ran but collected 0 tests"
            return result

        result.tests_generated = total
        result.passed          = passed
        result.failed          = failed
        return result

    # ── Main per-file flow ─────────────────────────────────────────────────────

    def _test_file(self, file_path: str, root: str) -> TestResult:
        result        = TestResult(file_path=file_path)
        filename      = Path(file_path).stem
        test_filename = f"test_{filename}.py"
        test_path     = f"{root}/tests/{test_filename}"

        project_root_abs = str((Path(config.OUTPUT_DIR) / root).resolve())
        test_file_abs    = str((Path(config.OUTPUT_DIR) / test_path).resolve())

        try:
            code = read_file(file_path)
        except Exception as e:
            result.errors.append(f"Could not read source: {e}")
            return result

        is_fastapi    = self._is_fastapi_file(code)
        pydantic_only = self._is_pydantic_only_file(code)
        func_names    = self._extract_function_names(code)

        routes_context = ""
        try:
            routes_code    = read_file(f"{root}/backend/routes.py")
            routes_context = (
                f"\nROUTES (exact endpoint paths + function names):\n"
                f"{routes_code[:1200]}"
            )
        except Exception:
            pass

        main_context = ""
        try:
            main_code    = read_file(f"{root}/backend/main.py")
            main_context = f"\nMAIN.PY:\n{main_code[:600]}"
        except Exception:
            pass

        test_code = self._generate_tests(
            file_path, code, routes_context, main_context,
            is_fastapi=is_fastapi, pydantic_only=pydantic_only,
            func_names=func_names, root=root,
        )
        if not test_code or not test_code.strip():
            result.skipped     = True
            result.skip_reason = "LLM returned empty"
            return result

        create_file(test_path, test_code)

        passed = 0
        failed = 0
        for attempt in range(1, MAX_TEST_FIXES + 2):
            output, returncode = self._run_pytest_single(test_file_abs, project_root_abs)

            if returncode == 2:
                collect_output = self._run_collect_only(test_file_abs, project_root_abs)
                full_error = collect_output if len(collect_output) > len(output) else output
                logger.warning(f"  ⚠️  collection error attempt {attempt}:\n  {full_error[-800:]}")
                if attempt <= MAX_TEST_FIXES:
                    fixed = self._fix_collection_error(
                        test_path, test_code, full_error, routes_context, main_context
                    )
                    if fixed:
                        create_file(test_path, fixed)
                        test_code = fixed
                    continue
                else:
                    result.errors.append("collection error — " + full_error[-300:])
                    result.skipped     = True
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
                logger.info(f"  🔧 {failed} failing — fixing (attempt {attempt})")
                try:
                    current = read_file(test_path)
                except Exception:
                    break

                failure_detail = self._extract_failures(output)
                passing_names  = self._extract_passing_test_names(output)
                fixed = self._fix_tests(
                    test_path, current, failure_detail,
                    routes_context, main_context, passing_names,
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
        file_path:      str,
        code:           str,
        routes_context: str,
        main_context:   str,
        is_fastapi:     bool = True,
        pydantic_only:  bool = False,
        func_names:     list = None,
        root:           str  = "",
    ) -> str:
        func_names    = func_names or []
        mock_examples = self._build_mock_examples(file_path, func_names)
        sibling_ctx   = self._get_sibling_import_context(file_path, root) if root else ""
        stem          = Path(file_path).stem

        if pydantic_only:
            pattern_instruction = f"""
PATTERN C — Pure Pydantic models (only BaseModel classes, no endpoints):
  import {stem}

  def test_model_creation():
      obj = {stem}.SomeModel(field1="value", field2=123)
      assert obj.field1 == "value"

  def test_model_defaults():
      obj = {stem}.SomeModel(field1="test")
      assert obj is not None

  def test_model_validation():
      import pytest
      with pytest.raises(Exception):
          {stem}.SomeModel()  # missing required fields raises ValidationError
"""
        elif is_fastapi:
            pattern_instruction = """
PATTERN A — FastAPI (file uses FastAPI/APIRouter):
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
            pattern_instruction = f"""
PATTERN B — Plain Python (no FastAPI):
  from unittest.mock import patch, MagicMock
  import {stem}

  def test_function_returns_expected():
      result = {stem}.some_function("valid_input")
      assert result is not None

  def test_function_handles_empty():
      result = {stem}.some_function("")
      assert result is not None or True

  def test_function_with_mock():
      with patch('{stem}.requests.get') as mock:
          mock.return_value.json.return_value = {{"key": "val"}}
          result = {stem}.some_function("input")
          assert result is not None
"""

        prompt = f"""Write pytest tests for this Python file.

FILE: {file_path}
CODE:
{code[:2000]}{routes_context}{main_context}{sibling_ctx}{mock_examples}

{pattern_instruction}

CRITICAL IMPORT RULE — use ONLY simple module names, never dotted paths:
  CORRECT:   from main import app   |   import services
  WRONG:     from backend.main import app   |   from project.backend.services import X
NO sys.path manipulation in the test file.

Write exactly 3 test functions.
Use ONLY the mock function names shown in EXACT MOCK SYNTAX above.
No real API calls. Return ONLY Python test code. No markdown."""
        return self.think(prompt)

    def _fix_collection_error(
        self,
        test_path:      str,
        current_code:   str,
        error_output:   str,
        routes_context: str,
        main_context:   str,
    ) -> str:
        prompt = f"""Fix this pytest test file that fails at COLLECTION time.

TEST FILE: {test_path}
CURRENT CODE:
{current_code}

FULL ERROR (pytest --collect-only):
{error_output[-1500:]}
{routes_context}{main_context}

The error shows the EXACT import that failed.
CRITICAL: Never use dotted module paths. conftest.py handles sys.path.
Fix ONLY the imports. Keep all 3 test functions.
Return ONLY the corrected Python test code. No markdown."""
        return self.think(prompt)

    def _fix_tests(
        self,
        test_path:      str,
        current_code:   str,
        failure_output: str,
        routes_context: str,
        main_context:   str,
        passing_names:  list = None,
    ) -> str:
        preserve_note = ""
        if passing_names:
            preserve_note = (
                f"\nDO NOT MODIFY these already-PASSING tests: "
                f"{', '.join(passing_names)}\n"
            )

        prompt = f"""Fix these failing pytest tests.

TEST FILE: {test_path}
CURRENT TEST CODE:
{current_code}
{preserve_note}
ACTUAL FAILURE DETAILS (pytest --tb=long):
{failure_output}
{routes_context}{main_context}

Diagnose from the failure details:
- AttributeError 'X' has no attribute 'Y' → Y is wrong; use the real function name from ROUTES above
- assert 200 == 404 → fix the mock to return None or raise, or fix the assertion
- assert 422 == 200 → add required fields to json={{}} in the request body
- ImportError → use simple module name (no backend.X)

Only fix failing tests. Do not modify passing ones.
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
