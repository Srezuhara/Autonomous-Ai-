"""
Locate and replace a single top-level block in a Python file.

Why this exists
---------------
Every repair prompt in `agents/debugger.py` used to end "Return ONLY the complete
fixed Python code", which pays for the file twice: once to send it, once to get
it back. Groq's free tier allows 8,000 tokens per minute covering prompt AND
completion together, so a full-file rewrite is impossible above roughly 11KB —
and matrix row 3 (2026-08-28) shipped twelve dead endpoints because its
10,775-character `routes.py` sat exactly on that wall.

Repairing one block instead makes file size stop mattering, and it makes the
repair-shrinkage guard structurally unable to fire: code that is never re-emitted
cannot be dropped.

The anchor comes free. `tools/runtime_smoke` already reports the traceback as
`backend/routes.py:53 in list_tasks_endpoint`, which is exactly a file, a line
and a name.
"""

import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Block:
    """A top-level statement, addressed by the lines it occupies (1-based)."""
    name: str
    start_line: int
    end_line: int
    source: str

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


def _node_name(node) -> str:
    name = getattr(node, "name", None)
    if name:
        return name
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                return target.id
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "<imports>"
    return "<module-level statement>"


def _span(node) -> tuple:
    """
    First and last line of a node, decorators included.

    `node.lineno` on a decorated function points at the `def`, not at the `@`.
    Excluding the decorators would be wrong twice over: the replacement would be
    spliced in below them, duplicating whatever the model returned, and the bug
    itself is sometimes IN the decorator — matrix row 2 failed to boot on a
    `@router.get(..., response_model=List[BookmarkOut])` naming a plain class.
    """
    start = node.lineno
    for decorator in getattr(node, "decorator_list", []) or []:
        # The `@` sits one line above the decorator expression only when the
        # expression itself starts the line, which is the usual formatting.
        start = min(start, decorator.lineno)
    end = getattr(node, "end_lineno", None) or node.lineno
    return start, end


def locate_block(source: str, line: int = None, function: str = None) -> Block | None:
    """
    The smallest top-level statement matching `function`, or containing `line`.

    A name match wins when one is given and found: a traceback naming a function
    is more precise than its line number, which can point into a nested call.
    `<module>` frames fall through to the line, which lands on the enclosing
    top-level statement — the decorated function, for row 2's import-time error.

    Returns None when the file will not parse or nothing matches, which is the
    caller's signal to fall back to rewriting the whole file.
    """
    if not source:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        logger.debug(f"code_patcher: cannot parse source ({e})")
        return None

    lines = source.splitlines()

    def build(node) -> Block:
        start, end = _span(node)
        end = min(end, len(lines))
        return Block(
            name=_node_name(node),
            start_line=start,
            end_line=end,
            source="\n".join(lines[start - 1:end]),
        )

    if function and function != "<module>":
        for node in tree.body:
            if getattr(node, "name", None) == function:
                return build(node)
        # A method: return the class that holds it, since replacing a method in
        # isolation would need the class body's indentation reproduced exactly.
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for child in node.body:
                if getattr(child, "name", None) == function:
                    return build(node)

    if line:
        for node in tree.body:
            start, end = _span(node)
            if start <= line <= end:
                return build(node)

    return None


def splice(source: str, block: Block, replacement: str) -> str | None:
    """
    Put `replacement` where `block` was, and only if the result still parses.

    Returning None rather than a broken file is the point: the debugger writes
    whatever comes back to disk, so a malformed reply must be refused here.
    """
    if not replacement or not replacement.strip():
        return None

    lines = source.splitlines()
    if block.start_line < 1 or block.end_line > len(lines):
        return None

    body = replacement.strip("\n").rstrip()
    patched = lines[:block.start_line - 1] + body.split("\n") + lines[block.end_line:]
    out = "\n".join(patched)
    if source.endswith("\n"):
        out += "\n"

    try:
        ast.parse(out)
    except SyntaxError as e:
        logger.warning(f"code_patcher: spliced result does not parse ({e}); refusing it")
        return None
    return out


def imported_symbols(source: str) -> dict:
    """
    `{symbol: module}` for everything this file imports by name.

    Used to answer "the thing that blew up — did this file define it, or just
    import it?". A `from services import BookmarkOut` means a complaint about
    `BookmarkOut` is a complaint about services.py.
    """
    out: dict = {}
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return out

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.module or node.level:      # relative imports resolve elsewhere
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                out[alias.asname or alias.name] = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name] = alias.name
    return out


def file_digest(source: str, exclude: Block = None) -> str:
    """
    The rest of the file, compressed to what a repair needs to know about it:
    the imports it can rely on and the top-level names it must not collide with.

    This replaces sending the whole file as context, which is the cost the whole
    module exists to avoid.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    imports: list = []
    names: list = []
    lines = source.splitlines()
    for node in tree.body:
        start, _ = _span(node)
        if exclude and start == exclude.start_line:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            segment = "\n".join(lines[node.lineno - 1:(node.end_lineno or node.lineno)])
            imports.append(segment.strip())
        else:
            name = _node_name(node)
            if name and not name.startswith("<"):
                kind = "class" if isinstance(node, ast.ClassDef) else (
                    "def" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    else "name")
                names.append(f"{kind} {name}")

    parts = []
    if imports:
        parts.append("IMPORTS ALREADY IN THIS FILE:\n" + "\n".join(imports))
    if names:
        parts.append("OTHER TOP-LEVEL NAMES IN THIS FILE (leave them alone):\n  "
                     + ", ".join(names))
    return "\n\n".join(parts)
