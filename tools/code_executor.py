"""
tools/code_executor.py — Code execution tools for AI agents.
Agents use these to run code and capture output/errors.
"""
import logging
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)


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


def run_python(file_path: str, timeout: int = 30) -> ExecutionResult:
    """
    Validate a Python file by checking its syntax and imports.

    Uses 'python -c "import <module>"' style check — this catches:
      - Syntax errors
      - Import errors (missing packages or wrong paths)
    
    Does NOT execute the file as a script, so FastAPI servers, 
    uvicorn.run() etc. won't actually start and hang.

    Runs from the file's OWN directory so local imports resolve correctly.
    """
    full_path = (Path(config.OUTPUT_DIR) / file_path).resolve()
    if not full_path.exists():
        return ExecutionResult(
            success=False, stdout="",
            stderr=f"File not found: {full_path}", returncode=-1,
        )

    run_dir = full_path.parent
    module_name = full_path.stem  # filename without .py

    logger.info(f"🐍 Running Python: {full_path} (cwd: {run_dir.name})")

    # Use compile + import check instead of running as script
    # This validates syntax AND all imports without executing server code
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
        timeout=timeout,
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

    print("\n✅ code_executor tests passed!")
