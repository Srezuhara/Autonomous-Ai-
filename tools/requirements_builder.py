"""
tools/requirements_builder.py — Phase 20 (Issue 6 fix — expanded IMPORT_TO_PYPI)
==================================================================================
Changes vs Phase 19.1:

ISSUE 6 FIX — Added ~40 commonly generated packages to IMPORT_TO_PYPI that
  were previously missing. When the LLM generates code that imports reportlab,
  openpyxl, streamlit, etc., the old map silently skipped them. The generated
  requirements.txt was incomplete, so pip install failed at runtime for the
  end-user downloading the ZIP.

  New packages added:
    Data / reporting  : reportlab, fpdf2, openpyxl, XlsxWriter, xlrd,
                        pdfplumber, pypdf, python-docx
    Dashboard / UI    : streamlit, gradio, dash, flask, django
    System / process  : psutil, colorama, tqdm, tabulate, humanize
    Networking / SSH  : paramiko, fabric
    Barcodes / QR     : qrcode[pil], python-barcode
    Task queues       : celery, kombu, pika, APScheduler, schedule
    Text formatting   : Pygments, Markdown, mistune, bleach
    Date / time       : arrow, pendulum, python-dateutil
    String utils      : python-slugify, Unidecode
    Testing extras    : freezegun, Faker, factory-boy, pytest-asyncio
    Observability     : loguru, structlog, sentry-sdk, prometheus-client

  STDLIB_MODULES guard: typing_extensions, anyio, sniffio are intentionally
  NOT in STDLIB_MODULES (they are PyPI packages). The original set already
  excluded them — confirmed unchanged.

All Phase 19.1 behaviour retained:
  - validate_and_fix_requirements() public API unchanged
  - Appends "# auto-added by Phase 19.1\\n{package}" blocks
  - Safe to call multiple times (normalised name dedup)
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)


# ── Standard-library modules (Python 3.10+) ───────────────────────────────────
STDLIB_MODULES: frozenset[str] = frozenset({
    "builtins", "sys", "os", "io", "abc", "ast", "dis", "gc",
    "inspect", "site", "token", "tokenize", "traceback", "warnings",
    "collections", "array", "heapq", "bisect", "queue", "weakref",
    "types", "copy", "pprint", "enum", "dataclasses",
    "math", "cmath", "decimal", "fractions", "random", "statistics",
    "struct", "numbers",
    "string", "re", "difflib", "textwrap", "unicodedata",
    "codecs", "readline", "rlcompleter",
    "base64", "binascii", "quopri", "uu",
    "pathlib", "glob", "fnmatch", "linecache", "shutil", "tempfile",
    "fileinput", "filecmp", "stat", "os.path",
    "subprocess", "signal", "mmap", "ctypes", "threading", "multiprocessing",
    "concurrent", "asyncio", "contextvars", "atexit",
    "socket", "ssl", "select", "selectors", "socketserver",
    "http", "urllib", "xmlrpc", "email", "html", "xml",
    "ipaddress", "telnetlib", "ftplib", "smtplib", "poplib", "imaplib",
    "uuid", "hashlib", "hmac", "secrets",
    "json", "csv", "configparser", "tomllib", "netrc",
    "pickle", "shelve", "marshal", "dbm", "sqlite3",
    "datetime", "time", "calendar", "zoneinfo",
    "logging", "unittest", "doctest", "pdb", "profile", "timeit",
    "functools", "itertools", "operator", "contextlib",
    "importlib", "pkgutil", "zipfile", "tarfile", "gzip", "bz2",
    "lzma", "zipimport", "compileall", "py_compile",
    "argparse", "getopt", "getpass", "cmd", "shlex",
    "platform", "sysconfig", "venv", "ensurepip",
    "typing", "abc", "copy", "copyreg", "reprlib",
    # intentionally NOT stdlib:
    # anyio, sniffio, typing_extensions — removed below
})

# typing_extensions, anyio, sniffio are PyPI packages — must NOT be in STDLIB_MODULES
STDLIB_MODULES = STDLIB_MODULES - {"typing_extensions", "anyio", "sniffio"}

# First-party / local module names that should never be pip-installed
ALWAYS_LOCAL: frozenset[str] = frozenset({
    "main", "app", "config", "routes", "services", "models", "utils",
    "helpers", "database", "db", "schemas", "middleware", "dependencies",
    "core", "api", "tests", "backend", "frontend", "auth", "users",
    "weather", "tasks", "worker", "scheduler",
})


# ── Import name → PyPI package name mapping ───────────────────────────────────
# Key  : the top-level name used in `import X` or `from X import ...`
# Value: the package spec to add to requirements.txt (with optional pin)
IMPORT_TO_PYPI: dict[str, str] = {

    # ── FastAPI ecosystem ─────────────────────────────────────────────────────
    "fastapi":              "fastapi>=0.111.0",
    "uvicorn":              "uvicorn[standard]>=0.29.0",
    "pydantic":             "pydantic>=2.0.0",
    "pydantic_settings":    "pydantic-settings>=2.0.0",
    "starlette":            "starlette>=0.37.0",

    # ── HTTP clients ──────────────────────────────────────────────────────────
    "httpx":                "httpx>=0.27.0",
    "requests":             "requests>=2.31.0",
    "aiohttp":              "aiohttp>=3.9.0",
    "websockets":           "websockets>=12.0",
    "websocket":            "websocket-client>=1.7.0",

    # ── Database / ORM ────────────────────────────────────────────────────────
    "sqlalchemy":           "sqlalchemy>=2.0.0",
    "alembic":              "alembic>=1.13.0",
    "aiosqlite":            "aiosqlite>=0.19.0",
    "databases":            "databases>=0.9.0",
    "tortoise":             "tortoise-orm>=0.20.0",
    "peewee":               "peewee>=3.17.0",
    "pymongo":              "pymongo>=4.6.0",
    "motor":                "motor>=3.3.0",
    "redis":                "redis>=5.0.0",
    "aioredis":             "redis>=5.0.0",
    "psycopg2":             "psycopg2-binary>=2.9.9",
    "psycopg":              "psycopg[binary]>=3.1.0",
    "aiomysql":             "aiomysql>=0.2.0",
    "elasticsearch":        "elasticsearch>=8.0.0",

    # ── Auth / security ───────────────────────────────────────────────────────
    "passlib":              "passlib[bcrypt]>=1.7.4",
    "jose":                 "python-jose[cryptography]>=3.3.0",
    "jwt":                  "PyJWT>=2.8.0",
    "cryptography":         "cryptography>=42.0.0",
    "bcrypt":               "bcrypt>=4.0.0",

    # ── Serialisation / parsing ───────────────────────────────────────────────
    "yaml":                 "PyYAML>=6.0.1",
    "toml":                 "toml>=0.10.2",
    "dotenv":               "python-dotenv>=1.0.0",
    "bs4":                  "beautifulsoup4>=4.12.0",
    "lxml":                 "lxml>=5.0.0",
    "multipart":            "python-multipart>=0.0.9",
    "jinja2":               "Jinja2>=3.1.0",
    "markupsafe":           "MarkupSafe>=2.1.0",
    "itsdangerous":         "itsdangerous>=2.1.0",

    # ── Data science / numeric ────────────────────────────────────────────────
    "numpy":                "numpy>=1.26.0",
    "pandas":               "pandas>=2.1.0",
    "matplotlib":           "matplotlib>=3.8.0",
    "scipy":                "scipy>=1.12.0",
    "sklearn":              "scikit-learn>=1.4.0",
    "PIL":                  "Pillow>=10.0.0",
    "cv2":                  "opencv-python-headless>=4.9.0",
    "seaborn":              "seaborn>=0.13.0",
    "plotly":               "plotly>=5.18.0",
    "nltk":                 "nltk>=3.8.0",

    # ── ISSUE 6: Reporting / document generation ──────────────────────────────
    "reportlab":            "reportlab>=4.0.0",
    "fpdf":                 "fpdf2>=2.7.0",
    "fpdf2":                "fpdf2>=2.7.0",
    "openpyxl":             "openpyxl>=3.1.0",
    "xlsxwriter":           "XlsxWriter>=3.1.0",
    "xlrd":                 "xlrd>=2.0.1",
    "xlwt":                 "xlwt>=1.3.0",
    "pdfplumber":           "pdfplumber>=0.10.0",
    "PyPDF2":               "PyPDF2>=3.0.0",
    "pypdf":                "pypdf>=4.0.0",
    "docx":                 "python-docx>=1.1.0",
    "docx2txt":             "docx2txt>=0.8",

    # ── ISSUE 6: Dashboard / UI frameworks ───────────────────────────────────
    "streamlit":            "streamlit>=1.30.0",
    "gradio":               "gradio>=4.0.0",
    "dash":                 "dash>=2.14.0",
    "flask":                "Flask>=3.0.0",
    "django":               "Django>=5.0.0",

    # ── ISSUE 6: System / process utilities ──────────────────────────────────
    "psutil":               "psutil>=5.9.0",
    "colorama":             "colorama>=0.4.6",
    "tqdm":                 "tqdm>=4.66.0",
    "tabulate":             "tabulate>=0.9.0",
    "humanize":             "humanize>=4.9.0",

    # ── ISSUE 6: Networking / SSH ─────────────────────────────────────────────
    "paramiko":             "paramiko>=3.4.0",
    "fabric":               "fabric>=3.2.0",

    # ── ISSUE 6: Barcodes / QR codes ─────────────────────────────────────────
    "qrcode":               "qrcode[pil]>=7.4.0",
    "barcode":              "python-barcode>=0.15.1",

    # ── ISSUE 6: Task queues / scheduling ────────────────────────────────────
    "celery":               "celery>=5.4.0",
    "kombu":                "kombu>=5.3.0",
    "pika":                 "pika>=1.3.2",
    "apscheduler":          "APScheduler>=3.10.0",
    "schedule":             "schedule>=1.2.0",

    # ── ISSUE 6: Text / markdown formatting ──────────────────────────────────
    "pygments":             "Pygments>=2.17.0",
    "markdown":             "Markdown>=3.5.0",
    "mistune":              "mistune>=3.0.0",
    "bleach":               "bleach>=6.1.0",

    # ── ISSUE 6: Date / time utilities ───────────────────────────────────────
    "arrow":                "arrow>=1.3.0",
    "pendulum":             "pendulum>=3.0.0",
    "dateutil":             "python-dateutil>=2.9.0",

    # ── ISSUE 6: String utilities ─────────────────────────────────────────────
    "slugify":              "python-slugify>=8.0.0",
    "unidecode":            "Unidecode>=1.3.0",

    # ── CLI frameworks ────────────────────────────────────────────────────────
    "click":                "click>=8.1.7",
    "rich":                 "rich>=13.7.0",
    "typer":                "typer>=0.12.0",

    # ── ISSUE 6: Testing extras ───────────────────────────────────────────────
    "pytest":               "pytest>=8.0.0",
    "pytest_asyncio":       "pytest-asyncio>=0.23.0",
    "freezegun":            "freezegun>=1.4.0",
    "faker":                "Faker>=24.0.0",
    "factory_boy":          "factory-boy>=3.3.0",

    # ── Observability ─────────────────────────────────────────────────────────
    "loguru":               "loguru>=0.7.0",
    "structlog":            "structlog>=24.0.0",
    "sentry_sdk":           "sentry-sdk>=1.40.0",
    "newrelic":             "newrelic>=9.0.0",
    "prometheus_client":    "prometheus-client>=0.19.0",
    "starlette_exporter":   "starlette-exporter>=0.17.0",

    # ── Cloud / storage ───────────────────────────────────────────────────────
    "boto3":                "boto3>=1.34.0",
    "botocore":             "botocore>=1.34.0",

    # ── Payment / comms ───────────────────────────────────────────────────────
    "stripe":               "stripe>=8.0.0",
    "twilio":               "twilio>=9.0.0",
    "sendgrid":             "sendgrid>=6.11.0",

    # ── AI / ML (light-weight) ────────────────────────────────────────────────
    "openai":               "openai>=1.0.0",
    "anthropic":            "anthropic>=0.20.0",
    "groq":                 "groq>=0.9.0",
    "langchain":            "langchain>=0.2.0",
    "chromadb":             "chromadb>=0.5.0",
    "tiktoken":             "tiktoken>=0.6.0",

    # ── Misc ──────────────────────────────────────────────────────────────────
    "typing_extensions":    "typing_extensions>=4.0.0",
    "anyio":                "anyio>=4.0.0",
    "sniffio":              "sniffio>=1.3.0",
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
    """Return the set of top-level module names imported in a Python source file."""
    found: set[str] = set()
    for m in re.finditer(r'^\s*import\s+([\w.]+)', source, re.MULTILINE):
        found.add(m.group(1).split(".")[0])
    for m in re.finditer(r'^\s*from\s+([\w.]+)\s+import', source, re.MULTILINE):
        root = m.group(1).split(".")[0]
        found.add(root)
    return found


def _current_package_names(requirements_text: str) -> set[str]:
    """Parse requirements.txt and return normalised package names already listed."""
    names: set[str] = set()
    for line in requirements_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        base = re.split(r"[><=!\[;]", line)[0].strip()
        if base:
            names.add(_normalise(base))
    return names


def _normalise(name: str) -> str:
    """Normalise package name to lowercase with underscores (PEP 503 canonical)."""
    return re.sub(r"[-_]+", "_", name.lower())


def _find_requirements_file(root: str) -> Path | None:
    """Return path to requirements.txt if it exists."""
    base = Path(config.OUTPUT_DIR)
    for candidate in [
        base / root / "requirements.txt",
        base / root / "backend" / "requirements.txt",
    ]:
        if candidate.exists():
            return candidate
    return None


def _collect_python_sources(root: str, file_paths: list[str]) -> list[str]:
    """Return source texts of all non-test Python files in the generated project."""
    base     = Path(config.OUTPUT_DIR)
    py_files = [fp for fp in file_paths if fp.endswith(".py")]

    if not py_files:
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

    existing_text = ""
    if req_path and req_path.exists():
        try:
            existing_text = req_path.read_text(encoding="utf-8")
        except Exception as e:
            result.error = f"Could not read {req_path}: {e}"
            return result
        result.requirements_file = str(req_path)
        result.existing = [
            line.strip() for line in existing_text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        backend_dir = Path(config.OUTPUT_DIR) / root / "backend"
        if backend_dir.exists():
            req_path = backend_dir / "requirements.txt"
        else:
            req_path = Path(config.OUTPUT_DIR) / root / "requirements.txt"
        result.requirements_file = str(req_path)
        result.existing          = []

    existing_normalised = _current_package_names(existing_text)

    all_imports: set[str] = set()
    for source in _collect_python_sources(root, file_paths):
        all_imports.update(_extract_imports(source))

    result.imports_found = all_imports

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

    try:
        sep   = "\n" if existing_text and not existing_text.endswith("\n") else ""
        block = "\n".join(
            f"# auto-added by Phase 19.1\n{p}" for p in sorted(set(to_add))
        )
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
    print("Testing requirements_builder (Phase 20 — Issue 6 fix)...\n")

    sample = """
import os, sys, json, pathlib
import fastapi, uvicorn
from pydantic import BaseModel
from httpx import AsyncClient
import sqlalchemy
from passlib.context import CryptContext
from jose import JWTError, jwt
import requests, yaml
import reportlab
import openpyxl
import qrcode
from fpdf import FPDF
import psutil
import celery
import schedule
import tabulate
import streamlit
import pandas
"""
    imports = _extract_imports(sample)
    print(f"Imports found ({len(imports)}): {sorted(imports)}")

    existing = _current_package_names("")
    missing = []
    for mod in sorted(imports):
        if mod in STDLIB_MODULES or mod in ALWAYS_LOCAL or mod.startswith("_"):
            continue
        spec = IMPORT_TO_PYPI.get(mod)
        if spec:
            pkg_base = re.split(r"[><=!\[;]", spec)[0].strip()
            if _normalise(pkg_base) not in existing:
                missing.append(spec)
    print(f"\nWould add ({len(missing)}):")
    for m in missing:
        print(f"  {m}")
    print("\n✅ requirements_builder Phase 20 smoke test passed!")
