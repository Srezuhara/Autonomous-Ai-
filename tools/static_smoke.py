"""
Serve a static frontend and actually fetch it (Phase 23, §4.32).

`web_asset_check` reads the page: it proves a reference *looks* resolvable.
Nothing proved one *resolves*. For a project that is only a static page, every
executing check answered `not_applicable`, so once §4.31 made "verified" mean
"something ran the artifact", a legitimate static-page build could no longer
demonstrate that it works at all. That gap was created by the fix, and this
closes it.

What it does: starts a real HTTP server rooted at the page's directory, GETs
the page, and GETs every local asset the page references. A `<script src>` that
404s is invisible to a parser and fatal in a browser, and this is the check that
sees it.

What it deliberately does NOT do: run the JavaScript. That needs a headless
browser — a heavy dependency for a project whose runner is a plain venv, and not
required to close this gap. So the claim this check makes is exact: the page and
the files it asks for are served, not that the script behaves. Anything stronger
belongs to a browser-based check, on its own evidence.

No network egress: absolute and protocol-relative URLs are recorded and skipped,
so a CDN being down never fails a build.

Never raises. The server is always torn down.
"""

from __future__ import annotations

import http.server
import logging
import re
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

import config
from tools.build_shape import detect_shapes
from tools.verification import VerificationOutcome
from tools.web_asset_check import _Assets

logger = logging.getLogger(__name__)

#: Per-request budget. Generous: the server is local and serving a file, so
#: anything near this is a hang rather than a slow response.
REQUEST_TIMEOUT = 10

#: Schemes and shapes a browser resolves without touching the document root.
_SKIP_PREFIXES = ("http://", "https://", "//", "data:", "blob:", "mailto:",
                  "tel:", "javascript:", "#")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler without the per-request logging to stderr."""

    def log_message(self, *_args):
        pass


def _serve(directory: Path):
    """(server, thread, base_url) for `directory`, on an ephemeral port."""
    handler = type(
        "_Rooted", (_QuietHandler,),
        {"__init__": lambda self, *a, **kw: _QuietHandler.__init__(
            self, *a, directory=str(directory), **kw)},
    )
    # Port 0: let the OS pick, so parallel checks never collide.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.timeout = REQUEST_TIMEOUT
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.socket.getsockname()[:2]
    return server, thread, f"http://{host}:{port}"


def _get(url: str) -> tuple:
    """(status, body_length, error). Never raises."""
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read()
            return resp.status, len(body), ""
    except urllib.error.HTTPError as e:
        return e.code, 0, ""
    except (urllib.error.URLError, socket.timeout) as e:
        return None, 0, str(getattr(e, "reason", e))
    except Exception as e:  # a malformed URL, mostly
        return None, 0, f"{type(e).__name__}: {e}"


def _asset_refs(html: str) -> list:
    """Every local file the page asks the browser to load, deduplicated."""
    parser = _Assets()
    try:
        parser.feed(html)
    except Exception:
        # A page too malformed to parse is web_asset_check's finding to make,
        # not this one's. Fetch what we can, which may be nothing.
        pass

    refs = [src for src, _is_module in parser.scripts]
    refs += list(parser.links) + list(parser.images)

    out, seen = [], set()
    for ref in refs:
        ref = (ref or "").strip()
        if not ref or ref.lower().startswith(_SKIP_PREFIXES):
            continue
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


_MOUNT = re.compile(
    r"""\.mount\(\s*['"](/[^'"]*)['"]\s*,\s*StaticFiles\(\s*directory\s*=\s*"""
    r"""([^)]*?['"]([^'"]+)['"][^)]*)\)""")


def _mounted_file(project_dir: Path, path: str) -> str:
    """The project file a backend `StaticFiles` mount serves for `path`, or "".

    A page the BACKEND renders -- a Jinja template -- is not rooted at its own
    directory, and `/static/styles.css` in it is the app's `/static` mount to
    answer. `bookmark_manager_e1266aab` mounts `../frontend/static`, has
    `frontend/static/styles.css` on disk, and this check reported the file as
    "not in the project -- `web_assets` names it in full" while `web_assets`
    said verified. Two checks disagreeing about one file is how a harness
    fails a sound page.

    Resolved by the directory literal's tail (`frontend/static`), because the
    expression around it -- `os.path.abspath(...)`, `Path(__file__).parent /`
    -- is resolved at runtime. That is safe for one reason: `StaticFiles`
    checks its directory exists when it is constructed and raises at import
    if not, so an app `runtime_smoke` could load had every mounted directory.
    """
    for py in project_dir.rglob("*.py"):
        if "venv" in py.parts or "site-packages" in py.parts:
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for prefix, _expr, literal in _MOUNT.findall(src):
            prefix = "/" + prefix.strip("/")
            if not path.startswith(prefix.rstrip("/") + "/"):
                continue
            rest = path[len(prefix.rstrip("/")) + 1:]
            tail = "/".join(p for p in literal.replace("\\", "/").split("/")
                            if p not in ("", ".", ".."))
            if not tail or not rest:
                continue
            hits = [f for f in project_dir.rglob(rest.split("/")[-1])
                    if f.is_file() and f.relative_to(project_dir).as_posix()
                    .endswith(f"{tail}/{rest}")]
            if len(hits) == 1:
                return hits[0].relative_to(project_dir).as_posix()
    return ""


def smoke_test_static(root: str) -> VerificationOutcome:
    """
    Serve this project's pages and fetch them. Never raises.

    `root` is the project folder name under OUTPUT_DIR.
    """
    try:
        project_dir = (Path(config.OUTPUT_DIR) / root).resolve()
    except Exception as e:
        return VerificationOutcome.not_run(
            "static_smoke", detail=f"cannot resolve project dir: {e}")
    if not project_dir.is_dir():
        return VerificationOutcome.not_run(
            "static_smoke", detail="project directory does not exist")

    try:
        shapes = detect_shapes(project_dir, rel_to=Path(config.OUTPUT_DIR))
    except Exception as e:
        return VerificationOutcome.not_run(
            "static_smoke", detail=f"shape detection failed: {e}")

    if not shapes.html_files:
        return VerificationOutcome.not_applicable(
            "static_smoke", shape=shapes.describe(),
            detail="this project ships no HTML page")

    findings: list[str] = []
    evidence: dict = {"pages": [], "skipped_remote": 0}
    pages_served = 0
    assets_checked = 0
    mounted = 0

    for rel_page in shapes.html_files:
        page_abs = (Path(config.OUTPUT_DIR) / rel_page).resolve()
        if not page_abs.is_file():
            continue

        # Document root is the page's own directory, which is how a browser
        # opening that file resolves "./app.js". A project whose page lives in
        # frontend/ and references ../shared/x.css is out of the served tree,
        # and the fetch reports that honestly rather than hiding it.
        server = thread = None
        try:
            server, thread, base = _serve(page_abs.parent)

            status, length, err = _get(f"{base}/{page_abs.name}")
            record = {"page": rel_page, "status": status, "bytes": length,
                      "assets": []}

            if status != 200:
                findings.append(
                    f"{rel_page} is not served: "
                    + (f"HTTP {status}" if status else f"no response ({err})")
                )
                evidence["pages"].append(record)
                continue
            if length == 0:
                findings.append(f"{rel_page} is served but is empty")
                evidence["pages"].append(record)
                continue

            pages_served += 1
            html = page_abs.read_text(encoding="utf-8", errors="replace")

            for ref in _asset_refs(html):
                # Strip query/fragment the way a server would.
                path = unquote(urlparse(ref).path)
                if not path:
                    continue
                url = f"{base}/{path.lstrip('/')}"
                a_status, a_len, a_err = _get(url)
                assets_checked += 1
                record["assets"].append(
                    {"ref": ref, "status": a_status, "bytes": a_len})
                if a_status == 200:
                    continue

                # A root-absolute reference the backend serves from a mount.
                if path.startswith("/"):
                    served = _mounted_file(project_dir, path)
                    if served:
                        record["assets"][-1]["mounted"] = served
                        mounted += 1
                        continue

                # `web_asset_check` already reports an asset that is absent from
                # the project, and reports it better — it names the page and the
                # reference statically. Restating it here would file one defect
                # twice under two check names, which this codebase has a rule
                # against. So the verdict stays honest (the page really is
                # broken) while the finding defers instead of duplicating.
                on_disk = (page_abs.parent / path.lstrip("/")).exists()
                if not on_disk:
                    findings.append(
                        f"{rel_page} loads `{ref}`, which is not served "
                        f"(HTTP {a_status}) because it is not in the project — "
                        f"`web_assets` names it in full"
                    )
                else:
                    # Only execution finds this: the file IS there, and the
                    # server still cannot hand it over — a path that escapes the
                    # document root, or a case mismatch that works on Windows
                    # and 404s everywhere else.
                    findings.append(
                        f"{rel_page} loads `{ref}`: the file exists in the "
                        f"project but the server "
                        + (f"answers HTTP {a_status}" if a_status
                           else f"never responds ({a_err})")
                        + " — it is not reachable from the page's directory"
                    )

            evidence["pages"].append(record)
        except Exception as e:
            return VerificationOutcome.not_run(
                "static_smoke", shape=shapes.describe(),
                detail=f"the check itself raised {type(e).__name__}: {e}")
        finally:
            if server is not None:
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
            if thread is not None:
                thread.join(timeout=5)

    if not pages_served:
        return VerificationOutcome.not_run(
            "static_smoke", shape=shapes.describe(),
            detail="pages were declared but none could be served",
            evidence=evidence)

    detail = (f"served {pages_served} page(s) over HTTP and fetched "
              f"{assets_checked} local asset(s)")
    if mounted:
        # Said, not buried: these were NOT fetched from this server. They are
        # on disk where the app's StaticFiles mount serves them from.
        detail += (f"; {mounted} of them are served by the backend's "
                   f"StaticFiles mount and were found on disk under it")

    if findings:
        return VerificationOutcome.failed(
            "static_smoke", findings=findings, shape=shapes.describe(),
            detail=detail, evidence=evidence)

    return VerificationOutcome.verified(
        "static_smoke", shape=shapes.describe(), detail=detail,
        evidence=evidence)
