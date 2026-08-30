"""
tools/web_asset_check.py — does the page it shipped actually load?
==================================================================

The plain HTML/CSS/JS frontend had one check: a regex in
`Pipeline._audit_js_imports` looking for **relative** import specifiers that
point at files which do not exist. Nothing opens the HTML. Nothing resolves a
`<script src>`. The placeholder audit's suffix tuple is
`(".py", ".sql", ".txt", ".md", ".json")`, so an unfilled `index.html` or
`styles.css` scaffold is invisible to it too. `tsc` and Vitest both require
`frontend/package.json`, which this shape does not have, so both skip.

Matrix row 2 shipped through all of that broken. `frontend/app.js` begins:

    import React from "react";
    import axios from "axios";

loaded from `index.html` as `<script type="module">`, with React supplied as a
UMD global. Bare specifiers do not resolve in a browser module without an import
map or a bundler, so the page fails on load. The relative-import regex passes it
happily, because these imports are not relative.

The cause is upstream and worth naming: `prompts/architect.txt` mandates *"plain
HTML/CSS/JavaScript for ALL frontend code"* while
`prompts/frontend_generator.txt` mandates React, Tailwind and axios with a
default export. The generator obeys the second and the architect plans for the
first.

What this checks
----------------
1. Every `<script src>`, `<link href>` and `<img src>` that is a local path
   resolves to a file that exists.
2. A `<script type="module">` (inline or file) does not use a bare specifier,
   unless an import map or a bundler config declares it.
3. A non-module `<script src>` file does not use `import`/`export` at all —
   that is a syntax error in a classic script.
4. `fetch()` / `axios` URL paths line up with the routes the backend actually
   serves. This is the frontend analogue of `tools/sql_schema_check.py`: two
   files written by separate LLM calls, agreeing on a contract nothing checks.

Precision over recall throughout, as in `sql_schema_check`. Anything dynamic — a
template literal, a variable URL, a path built at runtime — is skipped rather
than guessed at, because a false positive spends an LLM repair call on correct
code.

Deterministic and free — no LLM, no tokens, no browser.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from pathlib import Path

import config
from tools.build_shape import detect_shapes
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

# A specifier the browser can resolve on its own.
_RESOLVABLE = re.compile(r"^(?:https?:)?//|^/|^\.{1,2}/|^data:|^blob:|^#|^mailto:")

# `import x from "y"` / `export … from "y"` / bare `import "y"`.
_JS_IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*(?:import\s[^;\n]*?\sfrom\s|import\s+|export\s[^;\n]*?\sfrom\s)"""
    r"""['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# A URL literal handed to fetch() or an axios method. Quoted literals only:
# a template literal or a variable is a runtime value we must not guess at.
_FETCH_RE = re.compile(
    r"""(?:fetch\s*\(|axios\s*\.\s*(?:get|post|put|patch|delete)\s*\(|"""
    r"""axios\s*\(\s*\{[^}]*?url\s*:\s*)\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)

_API_BASE_RE = re.compile(
    r"""(?:const|let|var)\s+(\w+)\s*=\s*['"]([^'"]+)['"]""",
)

# fetch(`${BASE}/bookmarks/${id}`) — the overwhelmingly common shape, and the
# one row 2 uses. Quoted-literal URLs are handled by _FETCH_RE; this covers the
# template literal whose FIRST interpolation is a base constant, because then
# everything after it is a static path we can check. A template literal that
# starts with anything else is a runtime value and is skipped.
_FETCH_TEMPLATE_RE = re.compile(
    r"""(?:fetch\s*\(|axios\s*\.\s*(?:get|post|put|patch|delete)\s*\()\s*"""
    r"""`\$\{(\w+)\}([^`]*)`""",
    re.IGNORECASE,
)


class _Assets(HTMLParser):
    """Collects the local files a page asks the browser to load."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts:       list[tuple[str, bool]] = []   # (src, is_module)
        self.inline_modules: list[str] = []
        self.links:         list[str] = []
        self.images:        list[str] = []
        self.has_import_map = False
        self._in_module_script = False
        self._in_import_map    = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script":
            stype = a.get("type", "").lower()
            if stype == "importmap":
                self.has_import_map = True
                self._in_import_map = True
                return
            src = a.get("src", "")
            if src:
                self.scripts.append((src, stype == "module"))
            elif stype == "module":
                self._in_module_script = True
        elif tag == "link":
            href = a.get("href", "")
            if href:
                self.links.append(href)
        elif tag == "img":
            src = a.get("src", "")
            if src:
                self.images.append(src)

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_module_script = False
            self._in_import_map = False

    def handle_data(self, data):
        if self._in_module_script and data.strip():
            self.inline_modules.append(data)


def _rel(path: Path) -> str:
    """OUTPUT_DIR-relative, forward slashes — how the pipeline spells paths."""
    try:
        return str(path.resolve().relative_to(
            Path(config.OUTPUT_DIR).resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _resolve(page: Path, spec: str) -> Path | None:
    """The file a local reference points at, or None when it is not local."""
    spec = spec.split("?")[0].split("#")[0].strip()
    if not spec or spec.startswith(("http://", "https://", "//", "data:", "blob:",
                                    "mailto:", "#")):
        return None
    if spec.startswith("/"):
        return None      # server-absolute; depends on how it is served
    return (page.parent / spec)


def _bare_specifiers(source: str) -> list[str]:
    out = []
    for spec in _JS_IMPORT_RE.findall(source):
        if not _RESOLVABLE.match(spec):
            out.append(spec)
    return out


def _declared_routes(project_dir: Path) -> set[str]:
    """
    Every route path the backend declares, by pattern.

    Read statically rather than by booting the app: this runs for projects whose
    app may not boot, and the point is to compare two documents.
    """
    routes: set[str] = set()
    decorator = re.compile(
        r"""@\w+\.(?:get|post|put|patch|delete|route)\s*\(\s*['"]([^'"]+)['"]""",
        re.IGNORECASE,
    )
    prefix_re = re.compile(
        r"""include_router\s*\([^)]*?prefix\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE
    )
    prefixes = {""}
    for path in project_dir.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        text = _read(path)
        routes.update(decorator.findall(text))
        prefixes.update(prefix_re.findall(text))

    expanded = set(routes)
    for prefix in prefixes:
        if not prefix:
            continue
        for route in routes:
            expanded.add(prefix.rstrip("/") + route)
    return expanded


def _route_matches(url_path: str, declared: set[str]) -> bool:
    """
    Does this URL correspond to a declared route pattern?

    A declared `/items/{item_id}` matches a called `/items/1`. Compare segment
    counts and treat any `{...}` segment as a wildcard.
    """
    url = url_path.rstrip("/") or "/"
    for pattern in declared:
        pat = pattern.rstrip("/") or "/"
        if pat == url:
            return True
        p_parts, u_parts = pat.strip("/").split("/"), url.strip("/").split("/")
        if len(p_parts) != len(u_parts):
            continue
        if all(
            p.startswith("{") and p.endswith("}") or p == u
            for p, u in zip(p_parts, u_parts)
        ):
            return True
    return False


def check_web_assets(root: str) -> VerificationOutcome:
    """Verify a generated static frontend. Never raises."""
    try:
        project_dir = (Path(config.OUTPUT_DIR) / root).resolve()
    except Exception as e:
        return VerificationOutcome.not_run(
            "web_assets", detail=f"cannot resolve project dir: {e}"
        )
    if not project_dir.is_dir():
        return VerificationOutcome.not_run(
            "web_assets", detail="project directory does not exist"
        )

    shapes = detect_shapes(project_dir, rel_to=Path(config.OUTPUT_DIR))
    if not shapes.html_files:
        return VerificationOutcome.not_applicable(
            "web_assets", shape=shapes.describe(),
            detail="this project ships no HTML page",
        )

    findings: list[str] = []
    empty_pages: list[str] = []
    evidence: dict = {"pages": [], "checked_routes": 0}
    bundled = shapes.has_node_frontend

    for rel_page in shapes.html_files:
        page = Path(config.OUTPUT_DIR) / rel_page
        html = _read(page)
        if not html.strip():
            findings.append(f"{rel_page} is empty — the page has no content")
            empty_pages.append(rel_page)
            continue

        parser = _Assets()
        try:
            parser.feed(html)
        except Exception as e:
            findings.append(f"{rel_page} could not be parsed as HTML: {e}")
            continue

        evidence["pages"].append(rel_page)

        # 1. Local references must exist.
        for spec, _ in parser.scripts:
            target = _resolve(page, spec)
            if target is not None and not target.is_file():
                findings.append(
                    f"{rel_page} loads a script that does not exist: `{spec}`"
                )
        for spec in parser.links + parser.images:
            target = _resolve(page, spec)
            if target is not None and not target.is_file():
                findings.append(
                    f"{rel_page} references a file that does not exist: `{spec}`"
                )

        # 2 & 3. Module vs classic script rules.
        allow_bare = parser.has_import_map or bundled
        for source in parser.inline_modules:
            if allow_bare:
                break
            for spec in _bare_specifiers(source):
                findings.append(
                    f"{rel_page} has an inline module importing `{spec}`, which "
                    f"a browser cannot resolve without an import map or a bundler"
                )

        # A file a module imports is itself a module, and so is whatever IT
        # imports. Row 2's app.js is reached only this way — the page's inline
        # module does `import BookmarkManager from "./app.js"` — so checking
        # just the <script src> tags never opened the file that was broken.
        module_seeds: list[Path] = []
        for source in parser.inline_modules:
            for spec in _JS_IMPORT_RE.findall(source):
                target = _resolve(page, spec)
                if target is not None and target.is_file():
                    module_seeds.append(target)

        for spec, is_module in parser.scripts:
            target = _resolve(page, spec)
            if target is None or not target.is_file():
                continue
            if is_module:
                module_seeds.append(target)
                continue
            source = _read(target)
            if _JS_IMPORT_RE.search(source):
                findings.append(
                    f"{spec} uses `import`/`export` but {rel_page} loads it as "
                    f"a classic script — add type=\"module\" or the browser "
                    f"raises a syntax error before any of it runs"
                )

        if not allow_bare:
            seen: set[Path] = set()
            queue = list(module_seeds)
            while queue:
                mod = queue.pop(0)
                try:
                    key = mod.resolve()
                except Exception:
                    key = mod
                if key in seen or not mod.is_file():
                    continue
                seen.add(key)
                source = _read(mod)
                rel_mod = _rel(mod)
                for bare in _bare_specifiers(source):
                    findings.append(
                        f"{rel_mod} is loaded as a module and imports `{bare}`, "
                        f"a bare specifier a browser cannot resolve without an "
                        f"import map or a bundler — the page fails on load"
                    )
                for spec2 in _JS_IMPORT_RE.findall(source):
                    nxt = _resolve(mod, spec2)
                    if nxt is not None and nxt.is_file():
                        queue.append(nxt)

    # 4. The frontend's URLs against the backend's routes.
    declared = _declared_routes(project_dir)
    if declared:
        js_files = [
            p for p in project_dir.rglob("*.js")
            if "node_modules" not in str(p) and "__pycache__" not in str(p)
        ]
        for js in js_files:
            source = _read(js)
            rel_js = _rel(js)
            bases = dict(_API_BASE_RE.findall(source))

            # `${API_URL}/bookmarks/${id}` — the base resolves, the rest is a
            # static path, and an interpolated segment is a path parameter.
            for var, tail in _FETCH_TEMPLATE_RE.findall(source):
                base = bases.get(var)
                if base is None:
                    continue
                origin_path = re.sub(r"^https?://[^/]+", "", base).rstrip("/")
                path_part = origin_path + re.sub(r"\$\{[^}]*\}", "1", tail)
                path_part = re.sub(r"/+", "/", path_part.split("?")[0])
                if not path_part.startswith("/"):
                    continue
                evidence["checked_routes"] += 1
                if not _route_matches(path_part, declared):
                    findings.append(
                        f"{rel_js} calls `{path_part}`, which the backend does "
                        f"not serve. Declared routes: "
                        f"{', '.join(sorted(declared)[:6])}"
                    )

            for url in _FETCH_RE.findall(source):
                path_part = re.sub(r"^https?://[^/]+", "", url).split("?")[0]
                if not path_part.startswith("/"):
                    # Relative to a base we cannot resolve confidently. Skipping
                    # is the precision-over-recall choice: guessing the join and
                    # being wrong spends a repair call on correct code.
                    continue
                evidence["checked_routes"] += 1
                if not _route_matches(path_part, declared):
                    findings.append(
                        f"{rel_js} calls `{path_part}`, which the backend does "
                        f"not serve. Declared routes: "
                        f"{', '.join(sorted(declared)[:6])}"
                    )

    detail = (
        f"parsed {len(evidence['pages'])} page(s), "
        f"{evidence['checked_routes']} frontend call(s) checked against "
        f"{len(declared)} declared route(s)"
    )
    if findings:
        outcome = VerificationOutcome.failed(
            "web_assets", findings, shape="static_frontend",
            detail=detail, evidence=evidence,
        )
        # A page with no content is not a page with a problem. A broken asset
        # reference is bad and still leaves something to look at; an empty file
        # is the artifact not existing.
        for page in empty_pages:
            outcome.mark_fatal(f"{page} is an empty page")
        return outcome
    return VerificationOutcome.verified(
        "web_assets", shape="static_frontend", detail=detail, evidence=evidence
    )
