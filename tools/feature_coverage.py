"""
tools/feature_coverage.py — did it build what was asked for?
============================================================

`intent["features"]` is a list the IntentAnalyzer extracts from the user's
prompt — "CRUD for Supplier", "low-stock report endpoint", "filter by tag". A
repo-wide search shows it reaching exactly one place: `agents/documenter.py`,
where it is printed into the README. Nothing compares it to what was built.

So a build could implement two of six requested features and every gate would
stay green: the files import, the tests pass, the routes that DO exist answer
200. "It works" and "it is what you asked for" are different questions, and the
pipeline only ever asked the first.

The method
----------
For each requested feature, look for evidence in the artifact: a route path, a
handler or function name, a CLI subcommand, a class. Report a feature as missing
only when **none** of its meaningful words appear anywhere.

Precision over recall, the same discipline as `tools/sql_schema_check.py` and
for the same reason — a false "you didn't build this" would send a repair pass
at an application that is already complete, and would train the reader to
ignore the report. So:

  * a feature matches if ANY of its content words is found, not all;
  * words are normalised crudely (plurals, common verb endings) rather than
    stemmed properly, because over-normalising creates false matches;
  * very short and very generic words are ignored entirely — "the", "data",
    "system", "app" match everything and prove nothing;
  * a feature with no usable content words is skipped, not reported.

The result is a floor, not a ceiling: it catches the feature nobody implemented
at all, which is the failure that matters. It cannot tell you a route exists but
returns the wrong shape — the runtime probe and the schema checks are for that.

Deterministic and free — no LLM, no tokens.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import config
from tools.build_shape import detect_shapes
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

# Words that appear in almost every generated project and so prove nothing.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "to", "of", "in", "on", "by",
    "from", "at", "as", "is", "are", "be", "it", "its", "this", "that", "each",
    "all", "any", "per", "via", "into", "over", "using", "use", "used",
    "app", "application", "system", "data", "database", "db", "api", "endpoint",
    "endpoints", "route", "routes", "page", "pages", "support", "supports",
    "feature", "features", "user", "users", "simple", "basic", "full", "new",
    "add", "adds", "allow", "allows", "able", "can", "should", "must", "will",
    "plus", "also", "one", "two", "three", "four", "five", "six",
    "value", "values", "field", "fields", "item", "items", "entry", "entries",
    "management", "manager", "handling", "handle", "handles",
}

# CRUD verbs are meaningful as a group but are present in every generated
# backend, so on their own they are not evidence that a SPECIFIC feature exists.
_WEAK = {
    "crud", "create", "read", "update", "delete", "list", "get", "post", "put",
    "patch", "remove", "edit", "view", "show", "display", "store", "save",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def _normalise(word: str) -> str:
    """
    Crude singularisation, deliberately not a stemmer.

    "suppliers" -> "supplier", "queries" -> "queri" -> close enough to match
    "query" after the same treatment. A real stemmer would collapse more pairs
    and also collapse unrelated ones, which is the wrong trade here: a false
    match hides a missing feature, which is the thing we are looking for.
    """
    w = word.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("ses"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _content_words(text: str) -> set[str]:
    """
    The meaningful words in a phrase, with identifiers broken up.

    "CRUD for StockMovement" has to yield {crud, stock, movement}, not
    {crud, stockmovement}. The artifact spells the same idea as a route
    `/stock_movements/` and a class `StockMovement`, and comparing an unsplit
    token against split ones matches nothing — row 3 was reported as missing
    "CRUD for StockMovement" while serving five routes for it.
    """
    out = set()
    for raw in _WORD_RE.findall(text or ""):
        for piece in _split_identifier(raw) or [raw]:
            if len(piece) < 3:
                continue
            norm = _normalise(piece)
            if norm in _STOPWORDS or len(norm) < 3:
                continue
            out.add(norm)
    return out


def _split_identifier(name: str) -> list[str]:
    """`list_low_stock` / `listLowStock` / `LowStockReport` -> parts."""
    parts = re.split(r"[_\-./{}]+", name)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        out.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", part))
    return out


def _artifact_vocabulary(project_dir: Path) -> tuple[set[str], dict]:
    """
    Every word the built artifact uses in a name a user would recognise.

    Route paths, function and class names, CLI subcommand strings, and the
    visible text of any HTML page. Deliberately NOT comments or docstrings: the
    documenter writes the requested features into prose, so counting prose would
    let a project "implement" a feature by describing it.
    """
    vocab: set[str] = set()
    evidence = {"routes": [], "functions": 0, "classes": 0, "html_pages": 0}

    route_re = re.compile(
        r"""@\w+\.(?:get|post|put|patch|delete|route)\s*\(\s*['"]([^'"]+)['"]""",
        re.IGNORECASE,
    )
    # `add_parser("serve")` names a subcommand. For flags, match the literal
    # anywhere rather than only the first argument of the call: argparse takes
    # the short form first, so `add_argument("-d", "--dry-run", ...)` puts
    # "-d" in the position a first-argument regex reads, and the long name --
    # the only one carrying meaning -- was never seen. Row 4 was reported as
    # missing its "dry-run flag" while implementing it.
    subparser_re = re.compile(r"""add_parser\s*\(\s*['"]([^'"]+)['"]""")
    flag_re = re.compile(r"""['"](--[A-Za-z][\w-]*)['"]""")

    for path in project_dir.rglob("*.py"):
        if "__pycache__" in str(path) or path.name.startswith("test_"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for route in route_re.findall(text):
            evidence["routes"].append(route)
            for part in _split_identifier(route):
                vocab.add(_normalise(part))

        for name in subparser_re.findall(text) + flag_re.findall(text):
            for part in _split_identifier(name):
                vocab.add(_normalise(part))

        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                evidence["functions"] += 1
            elif isinstance(node, ast.ClassDef):
                evidence["classes"] += 1
            else:
                continue
            for part in _split_identifier(node.name):
                vocab.add(_normalise(part))

    for path in project_dir.rglob("*.html"):
        if "node_modules" in str(path):
            continue
        evidence["html_pages"] += 1
        try:
            html = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        visible = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        visible = re.sub(r"(?s)<[^>]+>", " ", visible)
        for word in _WORD_RE.findall(visible):
            vocab.add(_normalise(word))

    vocab.discard("")
    return vocab, evidence


def check_feature_coverage(root: str, intent: dict) -> VerificationOutcome:
    """
    Compare `intent["features"]` against what the artifact actually contains.
    Never raises.
    """
    features = [f for f in (intent or {}).get("features", []) if str(f).strip()]
    if not features:
        return VerificationOutcome.not_applicable(
            "feature_coverage",
            detail="the request did not enumerate any features to check",
        )

    try:
        project_dir = (Path(config.OUTPUT_DIR) / root).resolve()
    except Exception as e:
        return VerificationOutcome.not_run(
            "feature_coverage", detail=f"cannot resolve project dir: {e}"
        )
    if not project_dir.is_dir():
        return VerificationOutcome.not_run(
            "feature_coverage", detail="project directory does not exist"
        )

    vocab, ev = _artifact_vocabulary(project_dir)
    if not vocab:
        return VerificationOutcome.not_run(
            "feature_coverage",
            detail="the artifact exposes no readable names to compare against",
        )

    shapes = detect_shapes(project_dir, rel_to=Path(config.OUTPUT_DIR))
    missing: list[str] = []
    covered = 0

    for feature in features:
        words = _content_words(str(feature))
        strong = {w for w in words if w not in _WEAK}
        # A feature described only in CRUD verbs ("create and delete") has no
        # distinguishing content; every backend would match it, so checking it
        # would prove nothing either way.
        if not strong:
            continue
        if strong & vocab:
            covered += 1
        else:
            missing.append(str(feature))

    checked = covered + len(missing)
    detail = (
        f"{covered}/{checked} requested feature(s) have supporting code "
        f"({len(ev['routes'])} route(s), {ev['functions']} function(s) "
        f"across {shapes.describe()})"
    )
    evidence = {"covered": covered, "checked": checked,
                "missing": missing, "routes": ev["routes"][:25]}

    if missing:
        findings = [
            f"the request asked for \"{m}\" and nothing in the generated code "
            f"refers to it"
            for m in missing
        ]
        return VerificationOutcome.failed(
            "feature_coverage", findings, shape=shapes.describe(),
            detail=detail, evidence=evidence,
        )
    return VerificationOutcome.verified(
        "feature_coverage", shape=shapes.describe(),
        detail=detail, evidence=evidence,
    )
