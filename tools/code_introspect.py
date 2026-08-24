"""
tools/code_introspect.py — Phase 22
====================================
Deterministic AST introspection of generated backend files. Zero LLM calls.

WHY THIS EXISTS
---------------
The tester used to hand the LLM this instruction, for every function it found
in a file:

    EXACT MOCK SYNTAX — copy-paste these:
      with patch('routes.get_todo_items') as mock_get_todo_items:
    CRITICAL: ONLY use the function names above in ALL patch() calls.

For routes.py those function names ARE the route handlers. Patching a route
handler does nothing: FastAPI captured the function object at decoration time
and stores it in `app.routes`, so rebinding the module global afterwards is
never observed. Every such test asserted against the real (unimplemented)
handler and failed — the todo_app build scored 1/9 almost entirely for this
reason.

The distinction this module draws:

  route handlers      → NEVER patch. They are the code under test.
  imported callables  → the correct patch target. `patch('routes.get_weather')`
                        works when routes.py did `from weather import
                        get_weather`, because the handler resolves that global
                        at call time.
  Depends(...) deps   → not patchable either; override them with
                        `app.dependency_overrides[dep] = ...`.
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Modules whose exported names are framework plumbing, never useful as a
# `patch()` target in a generated test.
_FRAMEWORK_MODULES = {
    "fastapi", "starlette", "pydantic", "typing", "typing_extensions",
    "dataclasses", "enum", "abc", "__future__",
}
_FRAMEWORK_NAMES = {
    "Depends", "APIRouter", "FastAPI", "HTTPException", "BaseModel", "Field",
    "Query", "Path", "Body", "Header", "Cookie", "Form", "File", "UploadFile",
    "Request", "Response", "JSONResponse", "status", "List", "Dict", "Optional",
    "Any", "Union", "Annotated",
}

# Decorator attributes that register an HTTP route on a router/app object.
_HTTP_METHODS = {
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
    "websocket",
}

# Decorator *base* names that indicate a FastAPI router or application.
_ROUTER_BASES = {"router", "app", "api", "api_router", "v1", "routes"}


@dataclass
class ModuleFacts:
    """What a single generated Python module actually contains."""

    route_handlers:   list[str] = field(default_factory=list)
    # name -> the module it was imported from (module-level imports only)
    imported_names:   dict[str, str] = field(default_factory=dict)
    # imported names that a route handler actually calls -> best patch targets
    called_imports:   list[str] = field(default_factory=list)
    # callables referenced inside Depends(...) — need dependency_overrides
    depends_names:    list[str] = field(default_factory=list)
    # functions decorated with @contextmanager (invalid as FastAPI dependencies)
    contextmanagers:  list[str] = field(default_factory=list)
    # function name -> name it returns the result of, e.g. `def _get_db():
    # return get_db()`. Used to catch dependencies that wrap a context manager.
    returns_call_to:  dict[str, str] = field(default_factory=dict)
    # imports that appear inside a function body (invisible to the import check)
    deferred_imports: list[tuple[str, str]] = field(default_factory=list)
    # functions whose body is a TODO stub / bare return of an empty literal
    stub_functions:   list[str] = field(default_factory=list)
    plain_functions:  list[str] = field(default_factory=list)
    has_router:       bool = False
    has_app:          bool = False
    parse_error:      str | None = None

    @property
    def is_fastapi(self) -> bool:
        return self.has_router or self.has_app or bool(self.route_handlers)

    @property
    def mockable(self) -> list[str]:
        """Names that can be patched as `<module>.<name>` and be observed."""
        seen, out = set(), []
        for n in self.called_imports:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out


def _decorator_marks_route(node: ast.expr) -> bool:
    """True when a decorator is `@router.get(...)`, `@app.post(...)`, etc."""
    call = node.func if isinstance(node, ast.Call) else node
    if not isinstance(call, ast.Attribute):
        return False
    if call.attr.lower() not in _HTTP_METHODS:
        return False
    base = call.value
    if isinstance(base, ast.Name):
        # Accept any object whose name suggests a router, plus the common
        # `<something>_router` convention the debugger normalises away.
        low = base.id.lower()
        return low in _ROUTER_BASES or low.endswith("_router") or low.endswith("_app")
    return False


# Matched as whole words inside COMMENTS only. Substring matching over raw
# source produced a false positive that mattered: `sqlite3.connect('todo_app.db')`
# contains "todo" — every db.connect() in a to-do app was reported as a stub.
_TODO_COMMENT_RE = re.compile(
    r"#.*\b(TODO|TO\s+DO|FIXME|XXX|IMPLEMENT\s+ME|NOT\s+IMPLEMENTED)\b",
    re.IGNORECASE,
)


def _is_stub_body(node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> bool:
    """
    A stub is a function that either carries a TODO marker in a comment, or
    whose entire body is a docstring/pass/`return <empty literal>`.
    """
    try:
        segment = ast.get_source_segment(source, node) or ""
    except Exception:
        segment = ""
    if _TODO_COMMENT_RE.search(segment):
        return True

    body = [s for s in node.body if not (
        isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
        and isinstance(s.value.value, str)
    )]
    if not body:
        return True                      # docstring only
    if len(body) == 1:
        only = body[0]
        if isinstance(only, ast.Pass):
            return True
        if isinstance(only, ast.Raise):
            return False                 # explicit NotImplementedError is honest
        if isinstance(only, ast.Return) and isinstance(only.value, (ast.List, ast.Dict, ast.Set)):
            # `return []` with nothing else is an unimplemented handler
            return not only.value.elts if isinstance(only.value, (ast.List, ast.Set)) \
                else not only.value.keys
        if isinstance(only, ast.Return) and only.value is None:
            return True
    return False


def _annotation_name(annotation: ast.expr | None) -> str | None:
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    return None


def _collect_depends(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """
    Names referenced by `Depends(...)` in a function signature.

    Handles the bare form too: `db: Database = Depends()` takes the dependency
    from the parameter's type annotation. The todo_app build used exactly this
    form, so missing it meant reporting no dependencies at all.
    """
    found: list[str] = []
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    # defaults align to the TAIL of the positional list
    padded = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    pairs: list[tuple[ast.arg | None, ast.expr | None]] = list(zip(positional, padded))
    pairs += list(zip(args.kwonlyargs, args.kw_defaults))

    for arg, default in pairs:
        if not (isinstance(default, ast.Call) and isinstance(default.func, ast.Name)):
            continue
        if default.func.id != "Depends":
            continue
        if default.args:
            target = default.args[0]
            name = _annotation_name(target)
            if name:
                found.append(name)
        elif arg is not None:
            name = _annotation_name(arg.annotation)
            if name:
                found.append(name)
    return found


def analyze_module(source: str) -> ModuleFacts:
    """Parse one Python source file. Never raises."""
    facts = ModuleFacts()
    try:
        tree = ast.parse(source)
    except Exception as e:                      # syntax error → caller decides
        facts.parse_error = str(e)
        return facts

    # ── module-level imports ─────────────────────────────────────────────────
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                facts.imported_names[bound] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                bound = alias.asname or alias.name
                facts.imported_names[bound] = module
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if not isinstance(tgt, ast.Name):
                    continue
                val = node.value
                if isinstance(val, ast.Call) and isinstance(val.func, ast.Name):
                    if val.func.id == "APIRouter":
                        facts.has_router = True
                    elif val.func.id == "FastAPI":
                        facts.has_app = True

    # ── functions: handlers vs. plain, stubs, deferred imports ───────────────
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # @contextmanager on a FastAPI dependency injects the context-manager
        # OBJECT, not the yielded value — every use then fails with
        # "'_GeneratorContextManager' object has no attribute ...". FastAPI
        # dependencies must be plain generator functions.
        for dec in node.decorator_list:
            dec_name = dec.func if isinstance(dec, ast.Call) else dec
            label = (dec_name.attr if isinstance(dec_name, ast.Attribute)
                     else dec_name.id if isinstance(dec_name, ast.Name) else "")
            if label in ("contextmanager", "asynccontextmanager"):
                facts.contextmanagers.append(node.name)

        is_route = any(_decorator_marks_route(d) for d in node.decorator_list)
        if is_route:
            facts.route_handlers.append(node.name)
        else:
            facts.plain_functions.append(node.name)

        if _is_stub_body(node, source):
            facts.stub_functions.append(node.name)

        # `return other()` — record the wrapped callable.
        for stmt in node.body:
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
                callee = stmt.value.func
                if isinstance(callee, ast.Name):
                    facts.returns_call_to[node.name] = callee.id
                elif isinstance(callee, ast.Attribute):
                    facts.returns_call_to[node.name] = callee.attr

        facts.depends_names.extend(_collect_depends(node))

        # imports hiding inside the body — these never run at import-check time
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for alias in sub.names:
                    facts.deferred_imports.append((alias.name.split(".")[0], node.name))
            elif isinstance(sub, ast.ImportFrom) and sub.module:
                facts.deferred_imports.append((sub.module.split(".")[0], node.name))

        # imported names this function calls → valid patch targets
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            if isinstance(fn, ast.Name) and fn.id in facts.imported_names:
                facts.called_imports.append(fn.id)
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.value.id in facts.imported_names:
                    facts.called_imports.append(fn.value.id)

    # de-duplicate while preserving order
    facts.depends_names = list(dict.fromkeys(facts.depends_names))
    facts.called_imports = [
        n for n in dict.fromkeys(facts.called_imports)
        # a Depends target is overridden, not patched
        if n not in facts.depends_names
        and n not in _FRAMEWORK_NAMES
        and facts.imported_names.get(n, "").split(".")[0] not in _FRAMEWORK_MODULES
    ]
    facts.stub_functions = list(dict.fromkeys(facts.stub_functions))
    return facts


def is_resolvable_module(name: str) -> bool:
    """True when `name` is stdlib or actually installed in this environment."""
    import importlib.util
    import sys as _sys

    if not name:
        return True
    if name in getattr(_sys, "stdlib_module_names", frozenset()):
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def find_phantom_imports(
    facts: ModuleFacts, local_modules: set[str]
) -> list[tuple[str, str | None]]:
    """
    Imports that resolve to nothing: not a planned/local module, not stdlib,
    not installed. Returns (module, enclosing_function_or_None).

    Function-body imports are reported with their function name because those
    are the dangerous ones — they do not run during the import check, so the
    file "passes" debug and then 500s on the first request.
    """
    phantom: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    for bound, module in facts.imported_names.items():
        base = (module or bound).split(".")[0]
        if not base or base in local_modules or base in seen:
            continue
        if is_resolvable_module(base):
            continue
        seen.add(base)
        phantom.append((base, None))

    for module, fn_name in facts.deferred_imports:
        base = module.split(".")[0]
        if not base or base in seen:
            continue
        if base in local_modules or is_resolvable_module(base):
            continue
        seen.add(base)
        phantom.append((base, fn_name))

    return phantom


_JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs")
_JS_IMPORT_RE = re.compile(
    r"""(?:from\s+|require\(\s*|import\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]"""
)
# Extensions that resolve to a real asset rather than a component to generate.
_JS_ASSET_EXTS = (".css", ".scss", ".sass", ".less", ".json", ".svg", ".png",
                  ".jpg", ".jpeg", ".gif", ".webp")


def _js_target_exists(base) -> bool:
    from pathlib import Path as _P

    base = _P(base)
    if base.exists() and base.is_file():
        return True
    for ext in _JS_EXTS:
        if base.with_suffix(ext).exists():
            return True
        if (base / f"index{ext}").exists():
            return True
    return False


def find_dangling_js_imports(root_dir) -> list[tuple[str, str, str]]:
    """
    Relative imports in JS/TS files that point at files which do not exist.

    Returns (importer_absolute_path, import_specifier, intended_absolute_path).
    Plain-JS projects get no tsc validation at all, so nothing else in the
    pipeline ever looks at these — the frontend simply fails to build.
    """
    from pathlib import Path as _P

    root = _P(root_dir)
    if not root.exists():
        return []

    SKIP = {"node_modules", ".git", "dist", "build", "__pycache__", ".next"}
    dangling: list[tuple[str, str, str]] = []

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in _JS_EXTS:
            continue
        if any(part in SKIP for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for spec in _JS_IMPORT_RE.findall(text):
            if spec.lower().endswith(_JS_ASSET_EXTS):
                continue
            target = (path.parent / spec).resolve()
            if _js_target_exists(target):
                continue
            dangling.append((str(path), spec, str(target)))

    return dangling


def analyze_file(path: str) -> ModuleFacts:
    """Read and analyze a file. Never raises."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return analyze_module(fh.read())
    except Exception as e:
        facts = ModuleFacts()
        facts.parse_error = str(e)
        return facts
