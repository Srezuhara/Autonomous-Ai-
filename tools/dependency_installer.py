"""
tools/dependency_installer.py — Package installation tools for AI agents.
Agents use these to install missing packages during the debugging loop.
"""
import logging
import sys
from pathlib import Path

from tools.code_executor import run_command, ExecutionResult

logger = logging.getLogger(__name__)


def pip_install(package: str) -> ExecutionResult:
    """
    Install a Python package into the current venv.
    The agent calls this when it catches an ImportError / ModuleNotFoundError.
    """
    logger.info(f"📦 Installing Python package: {package}")
    # Use sys.executable to guarantee we install into the active venv
    result = run_command(
        f'"{sys.executable}" -m pip install {package} --quiet',
        timeout=120,
    )
    if result.success:
        logger.info(f"✅ Installed: {package}")
    else:
        logger.error(f"❌ Failed to install: {package}\n{result.stderr}")
    return result


def pip_install_requirements(requirements_file: str) -> ExecutionResult:
    """Install all packages from a requirements.txt file."""
    path = Path(requirements_file)
    if not path.exists():
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"Requirements file not found: {requirements_file}",
            returncode=-1,
        )
    logger.info(f"📦 Installing from: {requirements_file}")
    return run_command(
        f'"{sys.executable}" -m pip install -r "{requirements_file}" --quiet',
        timeout=300,
    )


def npm_install(package: str = "", cwd: str = ".") -> ExecutionResult:
    """
    Run npm install in a directory.
    Pass package name to install a specific package,
    or leave empty to install from package.json.
    """
    cmd = f"npm install {package}".strip()
    logger.info(f"📦 npm: {cmd} in {cwd}")
    return run_command(cmd, cwd=cwd, timeout=180)


def extract_missing_package(error_text: str) -> str | None:
    """
    Parse a Python error message and extract the missing package name.
    Used by the debugging loop to auto-install missing deps.

    Example:
        "ModuleNotFoundError: No module named 'requests'"
        → returns "requests"
    """
    import re
    patterns = [
        r"No module named '([^']+)'",
        r"ModuleNotFoundError: No module named \"([^\"]+)\"",
        r"ImportError: cannot import name '.+' from '([^']+)'",
    ]
    for pattern in patterns:
        match = re.search(pattern, error_text)
        if match:
            # Handle submodule case: 'package.submodule' → 'package'
            return match.group(1).split(".")[0]
    return None


# ── Smoke test ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing dependency_installer tools...\n")

    # Test extract_missing_package
    print("--- Test 1: extract missing package name ---")
    error = "ModuleNotFoundError: No module named 'rich'"
    pkg = extract_missing_package(error)
    print(f"Extracted package: '{pkg}'")
    assert pkg == "rich", "Extraction failed!"
    print("✅ Extraction works")

    # Test pip_install with a safe already-installed package
    print("\n--- Test 2: pip install (already installed package) ---")
    result = pip_install("requests")
    print(result)

    print("\n✅ dependency_installer tests passed!")
