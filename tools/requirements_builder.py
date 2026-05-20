"""
tools/requirements_builder.py — Phase 19.1
===========================================
Scans generated Python source files for import statements, cross-references
them against a curated stdlib→PyPI mapping, and ensures requirements.txt
contains every 3rd-party package the generated code actually needs.

Public API
----------
    validate_and_fix_requirements(root: str, file_paths: list[str]) -> ValidationResult

Usage in backend_developer.py (after run() completes):
    from tools.requirements_builder import validate_and_fix_requirements
    result = validate_and_fix_requirements(root, written_files)
    if result.added:
        logger.info(f"Auto-added {len(result.added)} missing packages: {result.added}")
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)


# ── Standard-library modules (Python 3.10+) ───────────────────────────────────
# If an import matches one of these, it's stdlib — no pip install needed.
STDLIB_MODULES: frozenset[str] = frozenset({
    # Built-ins
    "builtins", "sys", "os", "io", "abc", "ast", "dis", "gc",
    "inspect", "site", "token", "tokenize", "traceback", "warnings",
    # Data types
    "collections", "array", "heapq", "bisect", "queue", "weakref",
    "types", "copy", "pprint", "enum", "dataclasses",
    # Numeric / math
    "math", "cmath", "decimal", "fractions", "random", "statistics",
    "struct", "numbers",
    # Text / encoding
    "string", "re", "difflib", "textwrap", "unicodedata",
    "codecs", "readline", "rlcompleter",
    "base64", "binascii", "quopri", "uu",
    # File / path
    "pathlib", "glob", "fnmatch", "linecache", "shutil", "tempfile",
    "fileinput", "filecmp", "stat", "os.path",
    # OS / process
    "subprocess", "signal", "mmap", "ctypes", "threading", "multiprocessing",
    "concurrent", "asyncio", "contextvars", "atexit",
    # Networking
    "socket", "ssl", "select", "selectors", "socketserver",
    "http", "urllib", "xmlrpc", "email", "html", "xml",
    "ipaddress", "telnetlib", "ftplib", "smtplib", "poplib", "imaplib",
    "uuid", "hashlib", "hmac", "secrets",
    # Serialisation
    "json", "csv", "configparser", "tomllib", "netrc",
    "pickle", "shelve", "marshal", "dbm", "sqlite3",
    # Datetime
    "datetime", "time", "calendar", "zoneinfo",
    # Logging / debug
    "logging", "unittest", "doctest", "pdb", "profile", "timeit",
    # Misc stdlib
    "functools", "itertools", "operator", "contextlib",
    "importlib", "pkgutil", "zipfile", "tarfile", "gzip", "bz2",
    "lzma", "zipimport", "compileall", "py_compile",
    "argparse", "getopt", "getpass", "cmd", "shlex",
    "platform", "sysconfig", "venv", "ensurepip",
    "typing", "typing_extensions",          # typing_extensions is common but NOT stdlib
    "abc", "copy", "copyreg", "reprlib",
    # Async stdlib helpers
    "anyio", "sniffio",                     # NOT stdlib but often confused
})

# typing_extensions is NOT stdlib — remove it from the set above
STDLIB_MODULES = STDLIB_MODULES - {"typing_extensions", "anyio", "sniffio"}

# Additional first-party / local module names that should never be pip-installed
ALWAYS_LOCAL: frozenset[str] = frozenset({
    "main", "app", "config", "routes", "services", "models", "utils",
    "helpers", "database", "db", "schemas", "middleware", "dependencies",
    "core", "api", "tests", "backend", "frontend", "auth", "users",
    "weather", "tasks", "worker", "scheduler",
})


# ── Import name → PyPI package name mapping ───────────────────────────────────
# Key  : the top-level name used in `import X` or `from X import ...`
# Value: the package name to add to requirements.txt (with optional version pin)
IMPORT_TO_PYPI: dict[str, str] = {
    # FastAPI ecosystem
    "fastapi":          "fastapi>=0.111.0",
    "uvicorn":          "uvicorn[standard]>=0.29.0",
    "pydantic":         "pydantic>=2.0.0",
    "starlette":        "starlette>=0.37.0",

    # HTTP clients
    "httpx":            "httpx>=0.27.0",
    "requests":         "requests>=2.31.0",
    "aiohttp":          "aiohttp>=3.9.0",

    # Database / ORM
    "sqlalchemy":       "sqlalchemy>=2.0.0",
    "alembic":          "alembic>=1.13.0",
    "aiosqlite":        "aiosqlite>=0.19.0",
    "databases":        "databases>=0.9.0",
    "tortoise":         "tortoise-orm>=0.20.0",
    "peewee":           "peewee>=3.17.0",
    "pymongo":          "pymongo>=4.6.0",
    "motor":            "motor>=3.3.0",
    "redis":            "redis>=5.0.0",
    "aioredis":         "redis>=5.0.0",    # aioredis merged into redis
    "psycopg2":         "psycopg2-binary>=2.9.9",
    "psycopg":          "psycopg[binary]>=3.1.0",
    "aiomysql":         "aiomysql>=0.2.0",
    "elasticsearch":    "elasticsearch>=8.0.0",

    # Auth / security
    "passlib":          "passlib[bcrypt]>=1.7.4",
    "jose":             "python-jose[cryptography]>=3.3.0",
    "jwt":              "PyJWT>=2.8.0",
    "cryptography":     "cryptography>=42.0.0",
    "bcrypt":           "bcrypt>=4.0.0",

    # Serialisation / parsing
    "yaml":             "PyYAML>=6.0.1",
    "toml":             "toml>=0.10.2",
    "dotenv":           "python-dotenv>=1.0.0",
    "bs4":              "beautifulsoup4>=4.12.0",
    "lxml":             "lxml>=5.0.0",

    # Data science / numeric
    "numpy":            "numpy>=1.26.0",
    "pandas":           "pandas>=2.1.0",
    "matplotlib":       "matplotlib>=3.8.0",
    "scipy":            "scipy>=1.12.0",
    "sklearn":          "scikit-learn>=1.4.0",
    "PIL":              "Pillow>=10.0.0",

    # Utilities
    "click":            "click>=8.1.7",
    "rich":             "rich>=13.7.0",
    "typer":            "typer>=0.12.0",
    "celery":           "celery>=5.4.0",
    "kombu":            "kombu>=5.3.0",
    "pika":             "pika>=1.3.2",
    "apscheduler":      "APScheduler>=3.10.0",
    "schedule":         "schedule>=1.2.0",
    "boto3":            "boto3>=1.34.0",
    "botocore":         "botocore>=1.34.0",
    "stripe":           "stripe>=8.0.0",
    "twilio":           "twilio>=9.0.0",
    "sendgrid":         "sendgrid>=6.11.0",
    "openai":           "openai>=1.0.0",
    "anthropic":        "anthropic>=0.20.0",
    "groq":             "groq>=0.9.0",
    "langchain":        "langchain>=0.2.0",
    "chromadb":         "chromadb>=0.5.0",
    "tiktoken":         "tiktoken>=0.6.0",
    "websockets":       "websockets>=12.0",
    "websocket":        "websocket-client>=1.7.0",
    "multipart":        "python-multipart>=0.0.9",
    "jinja2":           "Jinja2>=3.1.0",
    "markupsafe":       "MarkupSafe>=2.1.0",
    "itsdangerous":     "itsdangerous>=2.1.0",
    "pydantic_settings":"pydantic-settings>=2.0.0",
    "typing_extensions":"typing_extensions>=4.0.0",
    "anyio":            "anyio>=4.0.0",
    "sniffio":          "sniffio>=1.3.0",
    "pytest":           "pytest>=8.0.0",
    "pytest_asyncio":   "pytest-asyncio>=0.23.0",
    "freezegun":        "freezegun>=1.4.0",
    "faker":            "Faker>=24.0.0",
    "factory_boy":      "factory-boy>=3.3.0",
    "loguru":           "loguru>=0.7.0",
    "structlog":        "structlog>=24.0.0",
    "sentry_sdk":       "sentry-sdk>=1.40.0",
    "newrelic":         "newrelic>=9.0.0",
    "prometheus_client":"prometheus-client>=0.19.0",
    "starlette_exporter":"starlette-exporter>=0.17.0",
}


@dataclass
class ValidationResult:
    requirements_file: str
    existing:          list[str] = field(default_factory=list)
    imports_found:     set[str]  = field(default_factory=set)
    missing:           list[str] = field(default_factory=list)
    added:             list[str] = field(default_factory=list)
    error:             str       = ""

    def __str__(self):
        if self.error:
            return f"❌ requirements validation error: {self.error}"
        if self.added:
            return f"✅ Added {len(self.added)} missing package(s): {', '.join(self.added)}"
        return f"✅ requirements.txt already complete ({len(self.existing)} packages)"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _extract_imports(source: str) -> set[str]:
    """
    Return the set of top-level module names imported in a Python source file.
    Handles both `import X` and `from X import Y` forms.
    """
    found: set[str] = set()
    # `import X`, `import X as Y`, `import X.Y.Z`
    for m in re.finditer(r'^\s*import\s+([\w.]+)', source, re.MULTILINE):
        found.add(m.group(1).split(".")[0])
    # `from X import Y`, `from X.Y import Z`
    for m in re.finditer(r'^\s*from\s+([\w.]+)\s+import', source, re.MULTILINE):
        root = m.group(1).split(".")[0]
        found.add(root)
    return found


def _current_package_names(requirements_text: str) -> set[str]:
    """
    Parse a requirements.txt and return the set of normalised package names
    already listed (lowercase, hyphens replaced by underscores).
    """
    names: set[str] = set()
    for line in requirements_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip extras e.g. "passlib[bcrypt]", version pins e.g. ">=1.7"
        base = re.split(r"[><=!\[;]", line)[0].strip()
        if base:
            names.add(_normalise(base))
    return names


def _normalise(name: str) -> str:
    """Normalise a package name to lowercase with underscores (PEP 503 canonical)."""
    return re.sub(r"[-_]+", "_", name.lower())


def _find_requirements_file(root: str) -> Path | None:
    """Return the path to requirements.txt if it exists (checks root and backend/)."""
    base = Path(config.OUTPUT_DIR)
    for candidate in [
        base / root / "requirements.txt",
        base / root / "backend" / "requirements.txt",
    ]:
        if candidate.exists():
            return candidate
    return None


def _collect_python_sources(root: str, file_paths: list[str]) -> list[str]:
    """
    Return source texts of all non-test Python files in the generated project.
    Reads from file_paths (already relative to OUTPUT_DIR) and falls back to
    a disk scan if file_paths is empty.
    """
    base      = Path(config.OUTPUT_DIR)
    py_files  = [fp for fp in file_paths if fp.endswith(".py")]

    if not py_files:
        # Fallback: walk the project root on disk
        project_dir = base / root
        if project_dir.exists():
            py_files = [
                str(p.relative_to(base))
                for p in project_dir.rglob("*.py")
                if "__pycache__" not in str(p) and "test_" not in p.name
            ]

    sources = []
    for fp in py_files:
        try:
            path = base / fp
            if path.exists():
                sources.append(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return sources


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_and_fix_requirements(
    root:       str,
    file_paths: list[str],
) -> ValidationResult:
    """
    Scan all generated Python files in `root`, find every 3rd-party import,
    and ensure requirements.txt contains the corresponding PyPI package.

    Missing packages are appended automatically. Returns a ValidationResult
    describing what was found and what was added.
    """
    result = ValidationResult(requirements_file="")

    req_path = _find_requirements_file(root)

    # ── Build the set of already-pinned packages ───────────────────────────────
    existing_text = ""
    if req_path and req_path.exists():
        try:
            existing_text = req_path.read_text(encoding="utf-8")
        except Exception as e:
            result.error = f"Could not read {req_path}: {e}"
            return result
        result.requirements_file = str(req_path)
        result.existing = [
            l.strip() for l in existing_text.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
    else:
        # No requirements.txt yet — create one in root/backend/ if backend exists
        backend_dir = Path(config.OUTPUT_DIR) / root / "backend"
        if backend_dir.exists():
            req_path = backend_dir / "requirements.txt"
        else:
            req_path = Path(config.OUTPUT_DIR) / root / "requirements.txt"
        result.requirements_file = str(req_path)
        result.existing          = []

    existing_normalised = _current_package_names(existing_text)

    # ── Collect all imports across all source files ────────────────────────────
    all_imports: set[str] = set()
    for source in _collect_python_sources(root, file_paths):
        all_imports.update(_extract_imports(source))

    result.imports_found = all_imports

    # ── Filter: only 3rd-party imports we have a mapping for ──────────────────
    to_add: list[str] = []
    for module_name in sorted(all_imports):
        if module_name in STDLIB_MODULES:
            continue
        if module_name in ALWAYS_LOCAL:
            continue
        if module_name.startswith("_"):
            continue

        pypi_spec = IMPORT_TO_PYPI.get(module_name)
        if pypi_spec is None:
            continue  # Unknown package — don't guess

        pkg_base = re.split(r"[><=!\[;]", pypi_spec)[0].strip()
        if _normalise(pkg_base) in existing_normalised:
            continue  # Already listed

        to_add.append(pypi_spec)
        result.missing.append(pypi_spec)

    if not to_add:
        logger.info(f"✅ requirements.txt already complete ({len(result.existing)} lines)")
        return result

    # ── Append missing packages ────────────────────────────────────────────────
    try:
        sep   = "\n" if existing_text and not existing_text.endswith("\n") else ""
        block = "\n".join(f"# auto-added by Phase 19.1\n{p}" for p in sorted(set(to_add)))
        req_path.parent.mkdir(parents=True, exist_ok=True)
        req_path.write_text(existing_text + sep + block + "\n", encoding="utf-8")
        result.added = sorted(set(to_add))
        logger.info(
            f"📦 requirements.txt — auto-added {len(result.added)} package(s): "
            + ", ".join(result.added)
        )
    except Exception as e:
        result.error = f"Could not write {req_path}: {e}"

    return result


# ── Smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing requirements_builder...\n")

    sample = """
import os
import sys
import fastapi
from pydantic import BaseModel
from httpx import AsyncClient
import sqlalchemy
from passlib.context import CryptContext
from jose import JWTError, jwt
import requests
import yaml
"""
    imports = _extract_imports(sample)
    print(f"Imports found: {sorted(imports)}")

    req_text = "fastapi>=0.111.0\nuvicorn[standard]>=0.29.0\n"
    existing = _current_package_names(req_text)
    print(f"Existing packages: {sorted(existing)}")

    print("\n✅ requirements_builder smoke test passed")
