"""
tools/dependency_installer.py — Package installation tools for AI agents.

Phase 18 changes:
─────────────────
1. WINDOWS_BUILD_BLOCKLIST — packages that require C++ compiler / cmake / GPU drivers
   on Windows. These will NEVER successfully pip-install without Visual Studio or
   special pre-built wheels. Instead of wasting 3 retry attempts, we skip them
   immediately and return a clear failure with a replacement suggestion.

2. HEAVY_PACKAGES_BLOCKLIST — packages too large to install within the 120s timeout
   (tensorflow, torch, etc.). Same early-exit strategy.

3. DOTTED_PATH_PACKAGES — packages whose names look like dotted module paths
   (e.g. "ai_pdf_reader", "backend.routes"). These are local module names, not
   PyPI packages. Filtered out before any install attempt.

4. pip_install() now checks all three lists before spawning pip, returning a
   descriptive ExecutionResult(success=False) instantly instead of hanging.

5. extract_missing_package() now also strips dotted-path package names and
   returns None for them so the debugger loop won't try to install them.
"""
import logging
import platform
import sys
from pathlib import Path

# Force UTF-8 stdout encoding to avoid UnicodeEncodeErrors on some terminals
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from tools.code_executor import run_command, ExecutionResult

logger = logging.getLogger(__name__)

# ── Packages that require a C/C++ compiler or GPU drivers on Windows ──────────
# These cannot be installed via plain pip on Windows without Visual Studio.
# The debugger should NOT waste retries on them — rewrite the source instead.
WINDOWS_BUILD_BLOCKLIST: set[str] = {
    # Face recognition / computer vision (need dlib → cmake + VS)
    "face_recognition", "dlib", "cmake",
    # Heavy CV / ML (GPU drivers, CUDA, or large native builds)
    "torch", "torchvision", "torchaudio",
    "tensorflow", "tensorflow-cpu", "tensorflow-gpu", "tf-nightly",
    "keras",
    # Other notorious Windows build failures
    "cv2", "opencv-python", "opencv-python-headless", "opencv-contrib-python",
    "pyaudio", "portaudio",
    "mysqlclient",
    "psycopg2",        # use psycopg2-binary instead
    "lxml",            # often fails without libxml2
    "Pillow",          # usually fine but on some envs needs zlib
    "cryptography",    # sometimes needs Rust compiler
    "cffi",
    "grpcio",
    "protobuf",        # usually fine but occasionally needs protoc
    "pywin32",         # Windows-only, but sometimes causes build issues
    "py-xgboost",
    "lightgbm",
    "catboost",
    "shapely",
    "fiona",
    "pyproj",
    "gdal", "GDAL",
}

# Safe replacements for blocked packages (offered in the error message)
BLOCKLIST_REPLACEMENTS: dict[str, str] = {
    "face_recognition":  "Use hashlib + a simple file-based identity store instead",
    "dlib":              "face_recognition/dlib cannot be installed without Visual C++",
    "torch":             "Use simpler numpy/scipy alternatives or mock the dependency",
    "torchvision":       "Requires torch; avoid heavy ML packages in generated apps",
    "tensorflow":        "tensorflow is too large (>500 MB). Use a lightweight alternative",
    "tensorflow-cpu":    "Use httpx to call an external ML API instead",
    "keras":             "Requires tensorflow; avoid in generated apps",
    "cv2":               "Install opencv-python-headless via: pip install opencv-python-headless",
    "opencv-python":     "Try: pip install opencv-python-headless",
    "psycopg2":          "Use: pip install psycopg2-binary",
}

# ── Packages that reliably time out during install (> 120 s on most machines) ──
HEAVY_PACKAGES_TIMEOUT_BLOCKLIST: set[str] = {
    "tensorflow", "tensorflow-cpu", "tensorflow-gpu", "tf-nightly",
    "torch", "torchvision", "torchaudio",
    "keras",
    "jax", "jaxlib",
    "paddle", "paddlepaddle",
    "mxnet",
    "theano",
    "caffe",
    "detectron2",
    "mmcv", "mmdet",
    "transformers",      # ~500 MB — allow only if user explicitly requests it
    "sentence-transformers",
    "spacy",             # large models; base package is ok but often pulled with models
    "en-core-web-sm",
    "scipy",             # usually fine but blocks some envs; allow via requirements.txt
}

# ── Dotted or underscore paths that are local project modules, not PyPI pkgs ──
# If extract_missing_package() returns one of these, it's a relative-import
# error in the generated code, NOT a missing PyPI package.
_LOCAL_MODULE_PREFIXES: tuple[str, ...] = (
    # Common generated project names
    "ai_pdf_reader", "weather_dashboard", "todo_app", "task_manager",
    "blog_platform", "chat_app", "ecommerce", "booking_app",
    # Common submodule names that look like packages
    "backend", "frontend", "routes", "services", "models",
    "database", "db", "schemas", "middleware", "core", "api",
    "utils", "helpers", "config", "tests",
)

# ── Known incorrect or hallucinated PyPI packages ────────────────────────────
# The LLM sometimes imports these incorrectly (e.g., 'import cors' or 'import jwt'),
# but installing these packages from PyPI is a dead-end or conflicts with
# other standard libraries/proper packages. The code must be rewritten instead.
HALLUCINATED_OR_WRONG_PACKAGES: set[str] = {
    "cors",          # Wrong! FastAPI uses fastapi.middleware.cors.CORSMiddleware
    "jwt",           # Wrong! direct pip install jwt conflicts with PyJWT. Use PyJWT.
    "crypto",        # Wrong! Use pycryptodome instead.
    "sqlite",        # Standard library! Never pip install.
    "sqlite3",       # Standard library! Never pip install.
    "postgres",      # Wrong! Use psycopg2-binary instead.
    "postgresql",    # Wrong! Use psycopg2-binary instead.
    "mysql",         # Wrong! Use pymysql or mysqlclient instead.
    "pydantic_core", # Wrong! Internal binary dependency of pydantic.
}


def _is_local_module(package: str) -> bool:
    """Return True if the package name looks like a local project module."""
    lower = package.lower().replace("-", "_")
    # Has dots → definitely a dotted path (e.g. "ai_pdf_reader.backend.vault")
    if "." in package:
        return True
    # Matches a known local prefix
    for prefix in _LOCAL_MODULE_PREFIXES:
        if lower == prefix or lower.startswith(prefix + "_"):
            return True
    return False


def _is_windows() -> bool:
    return platform.system() == "Windows"


def pip_install(package: str) -> ExecutionResult:
    """
    Install a Python package into the current venv.

    Phase 18: Immediately rejects:
      - Packages in the Windows build blocklist (on Windows)
      - Packages that time out on install (on any platform)
      - Dotted-path / local module names that are not PyPI packages
    """
    clean = package.strip().split("[")[0].split("==")[0].split(">=")[0].split("<=")[0]
    lower = clean.lower().replace("-", "_")

    # Guard 1: local module name masquerading as a package
    if _is_local_module(clean) or lower in HALLUCINATED_OR_WRONG_PACKAGES:
        msg = (
            f"'{clean}' is a local module or incorrect/hallucinated package. "
            f"Fix the import path in the source file instead of trying to install it."
        )
        logger.warning(f"⏭️  Skipping local/hallucinated package: {clean}")
        return ExecutionResult(success=False, stdout="", stderr=msg, returncode=-1)

    # Guard 2: heavy package that always times out
    if lower in {p.lower().replace("-", "_") for p in HEAVY_PACKAGES_TIMEOUT_BLOCKLIST}:
        replacement = BLOCKLIST_REPLACEMENTS.get(clean, "Use a lighter-weight alternative")
        msg = (
            f"'{clean}' is a very large package (>500 MB or slow build) that "
            f"reliably times out during automated install.\n"
            f"Suggestion: {replacement}\n"
            f"If you really need it, install manually: pip install {clean}"
        )
        logger.warning(f"⏭️  Skipping heavy package: {clean}")
        return ExecutionResult(success=False, stdout="", stderr=msg, returncode=-1)

    # Guard 3: Windows build-tools required
    if _is_windows() and lower in {p.lower().replace("-", "_") for p in WINDOWS_BUILD_BLOCKLIST}:
        replacement = BLOCKLIST_REPLACEMENTS.get(
            clean,
            f"'{clean}' requires Visual C++ build tools. "
            f"Install Visual Studio Build Tools or use a pre-built wheel."
        )
        msg = (
            f"'{clean}' cannot be installed on Windows without Visual C++ / cmake.\n"
            f"Suggestion: {replacement}\n"
            f"The generated code should be rewritten to avoid this dependency."
        )
        logger.warning(f"⏭️  Skipping Windows-incompatible package: {clean}")
        return ExecutionResult(success=False, stdout="", stderr=msg, returncode=-1)

    logger.info(f"📦 Installing Python package: {clean}")
    result = run_command(
        f'"{sys.executable}" -m pip install {package} --quiet',
        timeout=120,
    )
    if result.success:
        logger.info(f"✅ Installed: {clean}")
    else:
        logger.error(f"❌ Failed to install: {clean}\n{result.stderr[:300]}")
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
    # Use a longer timeout for requirements files (may have many packages)
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

    Phase 18 additions:
      - Returns None for dotted-path module names (local project modules)
      - Returns None for known-blocked packages early
      - Handles "from X.Y.Z import" errors by extracting the root package X
        and checking if it's a local module before returning it

    Example:
        "ModuleNotFoundError: No module named 'requests'"
        → returns "requests"

        "from ai_pdf_reader.backend.vault import X"
        → returns None  (local module, not a PyPI package)
    """
    import re
    patterns = [
        r"No module named '([^']+)'",
        r'No module named "([^"]+)"',
        r"ModuleNotFoundError: No module named '([^']+)'",
        r'ModuleNotFoundError: No module named "([^"]+)"',
        r"ImportError: cannot import name '.+' from '([^']+)'",
        r"ImportError: No module named '([^']+)'",
    ]
    for pattern in patterns:
        match = re.search(pattern, error_text)
        if match:
            raw = match.group(1)
            # Handle submodule case: 'package.submodule' → 'package'
            root = raw.split(".")[0]

            # Phase 18: filter out local module names & known hallucinated packages
            if (
                _is_local_module(raw)
                or _is_local_module(root)
                or raw.lower() in HALLUCINATED_OR_WRONG_PACKAGES
                or root.lower() in HALLUCINATED_OR_WRONG_PACKAGES
            ):
                logger.debug(f"extract_missing_package: '{raw}' looks like a local or incorrect package, skipping")
                return None

            return root
    return None


# ── Smoke test ────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing dependency_installer tools...\n")

    # Test extract_missing_package
    print("--- Test 1: extract normal missing package ---")
    error = "ModuleNotFoundError: No module named 'rich'"
    pkg = extract_missing_package(error)
    print(f"Extracted package: '{pkg}'")
    assert pkg == "rich", f"Extraction failed! Got {pkg}"
    print("✅ Normal extraction works")

    print("\n--- Test 2: local module detection ---")
    error2 = "ModuleNotFoundError: No module named 'ai_pdf_reader.backend.vault'"
    pkg2 = extract_missing_package(error2)
    print(f"Extracted: '{pkg2}' (should be None)")
    assert pkg2 is None, f"Should have been None! Got {pkg2}"
    print("✅ Local module filtered correctly")

    print("\n--- Test 3: dotted path detection ---")
    error3 = "ImportError: cannot import name 'BiometricVault' from 'backend.vault'"
    pkg3 = extract_missing_package(error3)
    print(f"Extracted: '{pkg3}' (should be None)")
    assert pkg3 is None, f"Should have been None! Got {pkg3}"
    print("✅ Dotted path filtered correctly")

    print("\n--- Test 4: Windows blocklist check ---")
    result = pip_install("face_recognition")
    print(f"face_recognition install blocked: {not result.success}")
    assert not result.success
    print("✅ Windows blocklist works")

    print("\n--- Test 5: heavy package blocklist ---")
    result2 = pip_install("tensorflow")
    print(f"tensorflow install blocked: {not result2.success}")
    assert not result2.success
    print("✅ Heavy package blocklist works")

    print("\n--- Test 6: pip install (already installed package) ---")
    result3 = pip_install("requests")
    print(result3)

    print("\n--- Test 7: hallucinated package detection ---")
    error_cors = "ModuleNotFoundError: No module named 'cors'"
    pkg_cors = extract_missing_package(error_cors)
    print(f"Extracted: '{pkg_cors}' (should be None)")
    assert pkg_cors is None, f"Should have been None! Got {pkg_cors}"
    
    error_jwt = "ModuleNotFoundError: No module named 'jwt'"
    pkg_jwt = extract_missing_package(error_jwt)
    print(f"Extracted: '{pkg_jwt}' (should be None)")
    assert pkg_jwt is None, f"Should have been None! Got {pkg_jwt}"

    result_cors = pip_install("cors")
    print(f"cors install blocked: {not result_cors.success}")
    assert not result_cors.success

    print("\n✅ All dependency_installer tests passed!")
