"""
tools/code_executor.py — Code execution tools for AI agents.
Agents use these to run code and capture output/errors.

Phase 19 bug fix:
  Bug 1 — run_python() timeout was 30s, too short for modules that import
  matplotlib, pandas, scipy, etc. at the module level.  These packages
  trigger slow __init__ execution during the import-check even though we
  never call their functions.

  Fix:
    - Default timeout raised to 90s (covers even slow first-import of pandas).
    - _detect_heavy_imports() scans the source file for known slow packages
      and extends the timeout further to 150s when found.
    - The extended timeout is logged so it is visible in build output.
"""
import logging
import subprocess
import sys
import re
from pathlib import Path
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)


# ── Heavy packages whose first import can take 10-60s ────────────────────────
# When any of these appear in the source file we give the import-check extra
# time so it doesn't false-positive as a "bug" that triggers a debug loop.
_HEAVY_IMPORT_PACKAGES: frozenset[str] = frozenset({
    "matplotlib", "pandas", "numpy", "scipy", "sklearn", "sklearn",
    "seaborn", "plotly", "bokeh", "altair",
    "tensorflow", "keras", "torch", "torchvision",
    "cv2", "PIL", "skimage",
    "nltk", "spacy", "gensim", "transformers",
    "statsmodels", "pyarrow", "polars",
    "openpyxl", "xlrd", "xlwt",
    "reportlab", "fpdf", "pdfplumber",
    "sqlalchemy",   # first import on some envs can be slow
    "chromadb",
})

# Timeout (seconds) used when heavy packages are detected
_HEAVY_TIMEOUT = 150
# Default timeout for normal files
_DEFAULT_TIMEOUT = 90


def _detect_heavy_imports(file_path: Path) -> bool:
    """
    Return True if the source file imports any known slow/heavy package.
    Uses a simple regex scan rather than parsing the AST, so it is fast
    and does not require the file to be valid Python.
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    pattern = re.compile(
        r'^\s*(?:import|from)\s+('
        + "|".join(re.escape(p) for p in _HEAVY_IMPORT_PACKAGES)
        + r')\b',
        re.MULTILINE,
    )
    return bool(pattern.search(source))


@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int

    def __str__(self):
        status = "✅ Success" if self.success else "❌ Failed"
        out = f"\nSTDOUT:\n{self.stdout}" if self.stdout else ""
        err = f"\nSTDERR:\n{self.stderr}" if self.stderr else ""
        return f"{status} (exit {self.returncode}){out}{err}"


def run_command(command: str, cwd: str = None, timeout: int = 60) -> ExecutionResult:
    """
    Run a shell command and return structured result.
    cwd: working directory (absolute or relative to OUTPUT_DIR)
    """
    work_dir = None
    if cwd:
        candidate = Path(cwd)
        if candidate.is_absolute():
            work_dir = candidate
        else:
            work_dir = Path(config.OUTPUT_DIR) / cwd

    logger.info(f"⚡ Running: {command}")
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        execution = ExecutionResult(
            success=result.returncode == 0,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            returncode=result.returncode,
        )
        if execution.success:
            logger.info("✅ Command succeeded")
        else:
            logger.warning(f"❌ Command failed (exit {result.returncode})")
        return execution

    except subprocess.TimeoutExpired:
        logger.error(f"⏰ Command timed out after {timeout}s: {command}")
        return ExecutionResult(
            success=False, stdout="",
            stderr=f"Timed out after {timeout} seconds", returncode=-1,
        )
    except Exception as e:
        logger.error(f"💥 Command error: {e}")
        return ExecutionResult(
            success=False, stdout="", stderr=str(e), returncode=-1,
        )


def run_python(file_path: str, timeout: int = _DEFAULT_TIMEOUT) -> ExecutionResult:
    """
    Validate a Python file by checking its syntax and imports.

    Uses 'python -c "import <module>"' style check — this catches:
      - Syntax errors
      - Import errors (missing packages or wrong paths)

    Does NOT execute the file as a script, so FastAPI servers,
    uvicorn.run() etc. won't actually start and hang.

    Runs from the file's OWN directory so local imports resolve correctly.

    Phase 19 Bug 1 fix:
      - Default timeout raised from 30s to 90s.
      - Auto-detects heavy imports (matplotlib, pandas, scipy …) and extends
        the timeout to 150s for those files, preventing false "Timed out"
        errors that were silently misclassified as runtime-ignorable errors
        by the Debugger and never fixed.
    """
    full_path = (Path(config.OUTPUT_DIR) / file_path).resolve()
    if not full_path.exists():
        return ExecutionResult(
            success=False, stdout="",
            stderr=f"File not found: {full_path}", returncode=-1,
        )

    run_dir = full_path.parent
    module_name = full_path.stem  # filename without .py

    # ── Phase 19 Bug 1: extend timeout for heavy-import files ─────────────────
    effective_timeout = timeout
    if _detect_heavy_imports(full_path):
        effective_timeout = _HEAVY_TIMEOUT
        logger.info(
            f"⏱️  Heavy imports detected in {full_path.name} — "
            f"extending import-check timeout to {effective_timeout}s"
        )
    else:
        logger.info(f"🐍 Running Python: {full_path} (cwd: {run_dir.name})")

    # Use compile + import check instead of running as script.
    # This validates syntax AND all imports without executing server code.
    check_code = (
        f"import sys, os; "
        f"sys.path.insert(0, r'{run_dir}'); "
        f"sys.path.insert(0, r'{run_dir.parent}'); "
        f"import py_compile; "
        f"py_compile.compile(r'{full_path}', doraise=True); "
        f"import importlib.util; "
        f"spec = importlib.util.spec_from_file_location('{module_name}', r'{full_path}'); "
        f"mod = importlib.util.module_from_spec(spec); "
        f"spec.loader.exec_module(mod)"
    )

    return run_command(
        f'"{sys.executable}" -c "{check_code}"',
        cwd=str(run_dir),
        timeout=effective_timeout,
    )


def run_python_script(file_path: str, timeout: int = 30) -> ExecutionResult:
    """
    Actually RUN a Python file as a script (not just import-check).
    Use this when you want to execute a script end-to-end (e.g. a migration).
    NOT used for FastAPI apps — use run_python() for those.
    """
    full_path = (Path(config.OUTPUT_DIR) / file_path).resolve()
    if not full_path.exists():
        return ExecutionResult(
            success=False, stdout="",
            stderr=f"File not found: {full_path}", returncode=-1,
        )
    run_dir = full_path.parent
    logger.info(f"🐍 Running Script: {full_path} (cwd: {run_dir.name})")
    return run_command(
        f'"{sys.executable}" "{full_path}"',
        cwd=str(run_dir),
        timeout=timeout,
    )


def run_python_code(code: str, timeout: int = 30) -> ExecutionResult:
    """Run a string of Python code directly."""
    logger.info("🐍 Running inline Python code")
    return run_command(f'"{sys.executable}" -c "{code}"', timeout=timeout)


# ── Smoke test ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing code_executor tools...\n")

    print("--- Test 1: echo command ---")
    result = run_command("echo Hello from code_executor!")
    print(result)

    print("\n--- Test 2: inline Python ---")
    result = run_python_code("print(2 + 2)")
    print(result)

    print("\n--- Test 3: expected failure ---")
    result = run_python_code("import non_existent_module")
    print(result)
    print(f"Captured error: {'ModuleNotFoundError' in result.stderr}")

    print("\n--- Test 4: heavy import detection (no file, just regex) ---")
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("import matplotlib.pyplot as plt\nimport pandas as pd\n")
        tmp = f.name
    heavy = _detect_heavy_imports(Path(tmp))
    os.unlink(tmp)
    print(f"Heavy import detected: {heavy}")
    assert heavy, "Should have detected matplotlib/pandas"

    print("\n✅ code_executor tests passed!")
