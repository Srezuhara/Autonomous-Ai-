"""
Phase 22 Test Suite — Generation Quality & Runtime Verification
================================================================
Offline tests. No server and no LLM calls required — every LLM boundary is
stubbed. The runtime smoke tests boot real (tiny) FastAPI apps written to a
temp directory, so they exercise the actual subprocess probe.

Run: python test_phase22.py
"""
import shutil
import sys
import textwrap
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config
from tools.code_introspect import (
    analyze_module as _analyze_module, analyze_file,
    find_phantom_imports, find_dangling_js_imports,
)


def analyze_module(src: str):
    """Dedent test literals before parsing — indented source is a SyntaxError."""
    return _analyze_module(textwrap.dedent(src))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        PASS.append(name)
        print(f"  [PASS]  {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL]  {name}  {detail}")


TMP = Path(config.OUTPUT_DIR) / "_phase22_tmp"


def write(rel: str, content: str) -> Path:
    p = TMP / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def reset():
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)


reset()

# ── 1. Route handlers are distinguished from ordinary functions ───────────────
print("\n[1] Route handler detection")

ROUTES_SRC = """
    from fastapi import APIRouter, Depends
    from services import fetch_items
    from db import Database

    router = APIRouter()

    @router.get("/items")
    async def list_items(db: Database = Depends()):
        return fetch_items(db)

    @router.post("/items")
    async def create_item(payload: dict):
        # TODO: implement
        return {}

    def helper(x):
        return x * 2
"""
facts = analyze_module(ROUTES_SRC)

check("route handlers detected", facts.route_handlers == ["list_items", "create_item"],
      str(facts.route_handlers))
check("non-route function not treated as a handler", facts.plain_functions == ["helper"],
      str(facts.plain_functions))
check("router presence detected", facts.has_router)
check("file classified as fastapi", facts.is_fastapi)

# ── 2. Stub detection, including the todo_app false positive ─────────────────
print("\n[2] Stub detection")

check("TODO-commented handler flagged as stub", "create_item" in facts.stub_functions,
      str(facts.stub_functions))
check("implemented handler not flagged", "list_items" not in facts.stub_functions,
      str(facts.stub_functions))
check("plain helper not flagged", "helper" not in facts.stub_functions)

# The bug this guards: substring matching over raw source flagged every
# `sqlite3.connect('todo_app.db')` because "todo_app" contains "todo".
TODO_APP_SRC = """
    import sqlite3

    class Database:
        def connect(self):
            self.conn = sqlite3.connect('todo_app.db')
            self.cursor = self.conn.cursor()
"""
todo_facts = analyze_module(TODO_APP_SRC)
check("'todo_app.db' filename does not fake a TODO stub",
      "connect" not in todo_facts.stub_functions, str(todo_facts.stub_functions))

EMPTY_RETURN_SRC = """
    from fastapi import APIRouter
    router = APIRouter()

    @router.get("/x")
    async def get_x():
        return []
"""
check("bare `return []` handler flagged as stub",
      "get_x" in analyze_module(EMPTY_RETURN_SRC).stub_functions)

NOT_IMPL_SRC = """
    def deliberate():
        raise NotImplementedError("caller must override")
"""
check("explicit NotImplementedError is not a stub",
      "deliberate" not in analyze_module(NOT_IMPL_SRC).stub_functions)

# ── 3. Depends() targets, including the bare form ────────────────────────────
print("\n[3] Dependency detection")

check("bare `Depends()` resolves via the annotation", facts.depends_names == ["Database"],
      str(facts.depends_names))

EXPLICIT_DEP = """
    from fastapi import APIRouter, Depends
    from deps import get_db
    router = APIRouter()

    @router.get("/y")
    def y(db = Depends(get_db)):
        return db
"""
check("explicit `Depends(get_db)` detected",
      analyze_module(EXPLICIT_DEP).depends_names == ["get_db"])

# ── 4. Mockable targets exclude handlers, framework names and Depends ────────
print("\n[4] Valid patch targets")

check("imported helper is a valid patch target", "fetch_items" in facts.mockable,
      str(facts.mockable))
check("route handler is never a patch target",
      not any(h in facts.mockable for h in facts.route_handlers), str(facts.mockable))
check("Depends target is not a patch target", "Database" not in facts.mockable,
      str(facts.mockable))
check("framework names excluded", "Depends" not in facts.mockable and
      "APIRouter" not in facts.mockable, str(facts.mockable))

# ── 5. Phantom imports, including function-body ones ────────────────────────
print("\n[5] Phantom import detection")

PHANTOM_SRC = """
    from fastapi import APIRouter
    import json
    from services import helper
    router = APIRouter()

    @router.get("/w")
    async def w():
        from weather import get_weather
        return get_weather()
"""
pf = analyze_module(PHANTOM_SRC)
phantom = find_phantom_imports(pf, {"services", "routes", "main"})
names = [m for m, _ in phantom]

check("function-body import of a missing module is flagged", "weather" in names, str(phantom))
check("the enclosing function is reported",
      any(m == "weather" and fn == "w" for m, fn in phantom), str(phantom))
check("stdlib import not flagged", "json" not in names, str(names))
check("planned local module not flagged", "services" not in names, str(names))
check("installed package not flagged", "fastapi" not in names, str(names))

# ── 6. Dangling frontend imports ────────────────────────────────────────────
print("\n[6] Dangling JS import detection")

write("frontend/src/App.js", """
    import React from 'react';
    import TodoList from './TodoList';
    import TodoForm from './TodoForm';
    import Header from './Header';
    import './styles.css';
    export default function App() { return <TodoList />; }
""")
write("frontend/src/Header.js", "export default function Header() { return null; }")

dangling = find_dangling_js_imports(TMP)
specs = sorted({spec for _, spec, _ in dangling})

check("missing component imports are flagged", specs == ["./TodoForm", "./TodoList"], str(specs))
check("existing component not flagged", "./Header" not in specs, str(specs))
check("css asset import not flagged", "./styles.css" not in specs, str(specs))

# ── 7. The tester never suggests patching a route handler ───────────────────
print("\n[7] Tester mock guidance (the 1/9 root cause)")

from agents.tester import Tester

routes_file = write("backend/routes.py", ROUTES_SRC)
tester = Tester.__new__(Tester)
guidance = tester._build_mock_examples(str(routes_file), [])

check("guidance is produced", bool(guidance.strip()))

# A handler name may appear ONLY inside the "NEVER write ..." warning — never
# in the valid-patch-target block the model is told to copy.
_target_block = guidance.split("VALID PATCH TARGETS", 1)[-1] if "VALID PATCH TARGETS" in guidance else ""
check("handler never offered as a patch target",
      "list_items" not in _target_block and "create_item" not in _target_block,
      _target_block[:200])
check("handler name appears only in the prohibition",
      guidance.index("patch('routes.list_items')") > guidance.index("NEVER"),
      guidance[:200])
check("explicitly forbids patching handlers", "NEVER" in guidance and "handler" in guidance.lower())
check("teaches dependency_overrides for Depends targets",
      "dependency_overrides" in guidance, guidance[:200])
check("offers the imported helper as the patch target",
      "patch('routes.fetch_items')" in guidance, guidance[:400])

# A file with handlers but no imported helpers must NOT invent a target.
bare_file = write("backend/bare_routes.py", EMPTY_RETURN_SRC)
bare_guidance = tester._build_mock_examples(str(bare_file), [])
check("no patch target invented when none exists",
      "Do not" in bare_guidance and "invent" in bare_guidance, bare_guidance[:200])

# ── 8. Backend developer defect scan ────────────────────────────────────────
print("\n[8] Backend generator self-verification")

from agents.backend_developer import BackendDeveloper

bd = BackendDeveloper.__new__(BackendDeveloper)
arch = {"files": [{"path": "backend/routes.py"}, {"path": "backend/main.py"},
                  {"path": "backend/db.py"}, {"path": "backend/services.py"}]}
planned = bd._planned_modules(arch)

check("planned modules derived from architecture",
      {"routes", "main", "db", "services"} <= planned, str(planned))

phantom_file = write("backend/phantom.py", PHANTOM_SRC)
blob = " ".join(bd._scan_defects(str(phantom_file), planned))
check("phantom import reported", "weather" in blob, blob[:200])
check("function-body import location reported", "inside w()" in blob, blob[:200])

# routes.py from section 1 carries a TODO stub handler AND a real one.
stub_file = write("backend/stubby.py", ROUTES_SRC)
stub_blob = " ".join(bd._scan_defects(str(stub_file), planned | {"db"}))
check("stub handler reported", "stub" in stub_blob.lower(), stub_blob[:200])
check("stub report names the offending handler", "create_item" in stub_blob, stub_blob[:200])
check("implemented handler not named as a stub",
      "list_items" not in stub_blob.split("route handler")[-1].split(".")[0],
      stub_blob[:200])

clean_file = write("backend/clean.py", """
    from fastapi import APIRouter
    from services import helper
    router = APIRouter()

    @router.get("/ok")
    async def ok():
        return {"items": helper()}
""")
check("clean file produces no defects", bd._scan_defects(str(clean_file), planned) == [],
      str(bd._scan_defects(str(clean_file), planned)))

broken_file = write("backend/broken.py", "def f(:\n    pass\n")
check("unparseable file reported, never raises",
      any("does not parse" in d for d in bd._scan_defects(str(broken_file), planned)))

# ── 8b. @contextmanager used as a FastAPI dependency ───────────────────────
print("\n[8b] Context-manager dependency detection")

# The defect a live build shipped: all 3 data endpoints returned 500 with
# "'_GeneratorContextManager' object has no attribute 'query'".
CTX_MAIN = """
    import sqlite3
    from contextlib import contextmanager
    from fastapi import FastAPI

    app = FastAPI()

    @contextmanager
    def get_db():
        conn = sqlite3.connect("app.db")
        try:
            yield conn
        finally:
            conn.close()
"""
CTX_ROUTES = """
    from fastapi import APIRouter, Depends
    router = APIRouter()

    def _get_db():
        from main import get_db
        return get_db()

    @router.get("/tasks")
    def list_tasks(db = Depends(_get_db)):
        return db.query("x").all()
"""
GOOD_ROUTES = """
    from fastapi import APIRouter, Depends
    from main import get_db
    router = APIRouter()

    @router.get("/tasks")
    def list_tasks(db = Depends(get_db)):
        return db.execute("select 1")
"""

ctx_main   = write("backend/ctx_main.py", CTX_MAIN)
ctx_routes = write("backend/ctx_routes.py", CTX_ROUTES)
good_routes = write("backend/good_routes.py", GOOD_ROUTES)

check("@contextmanager function is recorded",
      analyze_file(str(ctx_main)).contextmanagers == ["get_db"],
      str(analyze_file(str(ctx_main)).contextmanagers))

ctx_set = set(analyze_file(str(ctx_main)).contextmanagers)
ctx_planned = planned | {"ctx_main", "ctx_routes", "good_routes"}

indirect = " ".join(bd._scan_defects(str(ctx_routes), ctx_planned, ctx_set))
check("wrapper returning a context manager is caught",
      "_get_db" in indirect and "contextmanager" in indirect, indirect[:200])
check("the defect explains the runtime symptom",
      "_GeneratorContextManager" in indirect, indirect[:200])

DIRECT_ROUTES = """
    from fastapi import APIRouter, Depends
    from main import get_db
    router = APIRouter()

    @router.get("/tasks")
    def list_tasks(db = Depends(get_db)):
        return db.execute("select 1")
"""
direct_file = write("backend/direct_routes.py", DIRECT_ROUTES)
direct = " ".join(bd._scan_defects(str(direct_file), ctx_planned, ctx_set))
check("direct Depends on a context manager is caught", "contextmanager" in direct,
      direct[:200])

check("a correct generator dependency is not flagged",
      not any("contextmanager" in d
              for d in bd._scan_defects(str(good_routes), ctx_planned, set())),
      str(bd._scan_defects(str(good_routes), ctx_planned, set())))

# ── 9. Scaffold placeholders use valid comment syntax ───────────────────────
print("\n[9] Architect scaffold placeholders")

from agents.architect import _placeholder_for, PLACEHOLDER_MARKER

sql_ph = _placeholder_for("backend/schema.sql", "DB schema")
check("SQL placeholder uses -- comments", sql_ph.startswith("--") and "#" not in sql_ph, sql_ph)
check("JSON placeholder is valid JSON", _placeholder_for("a/b.json", "x").strip() == "{}")
check("CSS placeholder uses /* */", _placeholder_for("a/b.css", "x").startswith("/*"))
check("HTML placeholder uses <!-- -->", _placeholder_for("a/i.html", "x").startswith("<!--"))
check("Python placeholder still uses #", _placeholder_for("a/b.py", "x").startswith("#"))
check("marker preserved for the audit", PLACEHOLDER_MARKER in sql_ph)

# ── 10. Runtime smoke test — the real "does it work" gate ───────────────────
print("\n[10] Runtime smoke test")

from tools.runtime_smoke import smoke_test_app

SMOKE_ROOT = "_phase22_smoke"
smoke_dir = Path(config.OUTPUT_DIR) / SMOKE_ROOT
if smoke_dir.exists():
    shutil.rmtree(smoke_dir, ignore_errors=True)
(smoke_dir / "backend").mkdir(parents=True, exist_ok=True)

# An app whose /broken route reproduces the todo_app defect exactly: an import
# inside the handler body of a module that does not exist.
(smoke_dir / "backend" / "main.py").write_text(textwrap.dedent("""
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/ok")
    def ok():
        return {"status": "ok"}

    @app.get("/items/{item_id}")
    def item(item_id: int):
        return {"id": item_id}

    @app.get("/broken")
    def broken():
        from nonexistent_module_xyz import thing
        return thing()
"""), encoding="utf-8")

res = smoke_test_app(SMOKE_ROOT)

check("smoke test ran", res.ran, res.error[:200])
check("app loaded", res.app_loaded, res.error[:200])
check("entry point located", res.entry.endswith("main.py"), res.entry)
check("all declared routes probed", res.total == 3, f"total={res.total}")
check("working route passes", any(p.path == "/ok" and p.ok for p in res.probes))
check("path parameter filled in and probed",
      any(p.path == "/items/{item_id}" and p.ok for p in res.probes),
      str([(p.path, p.status) for p in res.probes]))
check("handler-body phantom import caught as 500",
      any(p.path == "/broken" and p.status == 500 for p in res.probes),
      str([(p.path, p.status) for p in res.probes]))
check("failure count is accurate", len(res.failures) == 1, str(res.failures))
check("summary reports the ratio", "2/3" in res.summary(), res.summary())

# An app that cannot even be imported.
BOOM_ROOT = "_phase22_boom"
boom_dir = Path(config.OUTPUT_DIR) / BOOM_ROOT
if boom_dir.exists():
    shutil.rmtree(boom_dir, ignore_errors=True)
(boom_dir / "backend").mkdir(parents=True, exist_ok=True)
(boom_dir / "backend" / "main.py").write_text(textwrap.dedent("""
    from fastapi import FastAPI
    import totally_missing_package_abc
    app = FastAPI()
"""), encoding="utf-8")

boom = smoke_test_app(BOOM_ROOT)
check("app that fails to import is reported, not crashed", boom.ran and not boom.app_loaded,
      f"ran={boom.ran} loaded={boom.app_loaded} err={boom.error[:120]}")
check("boot failure explains itself", "totally_missing_package_abc" in boom.error, boom.error[:200])

# A project with no FastAPI app at all must degrade quietly.
NOAPP_ROOT = "_phase22_noapp"
noapp_dir = Path(config.OUTPUT_DIR) / NOAPP_ROOT
if noapp_dir.exists():
    shutil.rmtree(noapp_dir, ignore_errors=True)
noapp_dir.mkdir(parents=True, exist_ok=True)
(noapp_dir / "script.py").write_text("print('hello')\n", encoding="utf-8")

noapp = smoke_test_app(NOAPP_ROOT)
check("no-FastAPI project skips cleanly", not noapp.ran and "entry point" in noapp.error,
      f"ran={noapp.ran} err={noapp.error}")
check("missing project reports an error rather than raising",
      smoke_test_app("_phase22_does_not_exist").error != "")

# ── 11. Pipeline wires the smoke test into remediation ─────────────────────
print("\n[11] Pipeline integration")

from agents.pipeline import Pipeline, BuildResult

pipe = Pipeline.__new__(Pipeline)
res_ok = BuildResult(user_prompt="x")
res_ok.architecture = {"root_folder": SMOKE_ROOT}
findings = pipe._smoke_test_runtime(res_ok)

check("pipeline surfaces the failing endpoint", len(findings) == 1, str(findings))
check("finding names the broken route", findings and "/broken" in findings[0], str(findings))
check("smoke summary recorded on the build", "2/3" in res_ok.smoke_summary, res_ok.smoke_summary)

res_none = BuildResult(user_prompt="x")
res_none.architecture = {"root_folder": NOAPP_ROOT}
check("no entry point produces no findings", pipe._smoke_test_runtime(res_none) == [])

res_boom = BuildResult(user_prompt="x")
res_boom.architecture = {"root_folder": BOOM_ROOT}
boom_findings = pipe._smoke_test_runtime(res_boom)
check("app that will not boot is a finding",
      len(boom_findings) == 1 and "does not start" in boom_findings[0], str(boom_findings))

res_empty = BuildResult(user_prompt="x")
res_empty.architecture = {}
check("missing root_folder never raises", pipe._smoke_test_runtime(res_empty) == [])

# ── 12. Debugger no longer corrupts multi-line statements ──────────────────
print("\n[12] Debugger multi-line statement handling")

import ast
from agents.debugger import Debugger

dbg = Debugger.__new__(Debugger)

MULTILINE_DB = """\
import os
from sqlalchemy import create_engine

engine = create_engine(
    os.getenv("DATABASE_URL"),
    connect_args={"check_same_thread": False},
)
Session = sessionmaker(autocommit=False, bind=engine)
Base.metadata.create_all(bind=engine)

def keep_me():
    return 1
"""

commented = MULTILINE_DB
for pat in (r'^engine\s*=\s*create_engine',
            r'^Session\s*=\s*sessionmaker',
            r'^Base\.metadata\.create_all'):
    commented = dbg._comment_out_statement(commented, pat)

parses = True
try:
    ast.parse(commented)
except SyntaxError:
    parses = False

check("file still parses after disabling the DB connection", parses, commented)
check("every line of the multi-line call is commented",
      "# )" in commented and '#     os.getenv' in commented, commented)
check("single-line statements still commented",
      "# Session = sessionmaker" in commented and
      "# Base.metadata.create_all" in commented, commented)
check("unrelated code untouched", "def keep_me():" in commented and
      "\n    return 1" in commented, commented)
check("already-commented lines are not double-commented",
      "# # " not in dbg._comment_out_statement(commented, r'^engine'), commented)

# ── 13. Frontend resolver refuses malformed import paths ───────────────────
print("\n[13] Dangling-import repair guardrails")

from agents.frontend_generator import FrontendGenerator

fg = FrontendGenerator.__new__(FrontendGenerator)
proj = TMP / "proj"
(proj / "frontend" / "src" / "components").mkdir(parents=True, exist_ok=True)
(proj / "tests").mkdir(parents=True, exist_ok=True)

src_importer = proj / "frontend" / "src" / "App.jsx"
src_importer.write_text("import X from './components/X';", encoding="utf-8")
test_importer = proj / "tests" / "test_frontend.js"
test_importer.write_text("import App from '../proj/frontend/src/app.js';", encoding="utf-8")

check("genuine missing component is created",
      fg._should_create_component(
          proj, str(src_importer), "./components/X",
          str(proj / "frontend" / "src" / "components" / "X.jsx")))

# The exact defect a live build produced: a test importing a path that
# duplicates the project name, which spawned todo_app/todo_app/frontend/...
check("test-file import never spawns a component",
      not fg._should_create_component(
          proj, str(test_importer), "../proj/frontend/src/app.js",
          str(proj / "proj" / "frontend" / "src" / "app.js")))

check("import escaping src/ is refused",
      not fg._should_create_component(
          proj, str(src_importer), "../../elsewhere/Y",
          str(proj / "elsewhere" / "Y.jsx")))

check("target outside the project is refused",
      not fg._should_create_component(
          proj, str(src_importer), "../../../etc/Z",
          str(TMP.parent / "etc" / "Z.jsx")))

# ── 14. The CLI drives the real pipeline ───────────────────────────────────
print("\n[14] CLI uses Pipeline.run()")

import re as _re

main_src = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")

check("CLI calls Pipeline.run()", "pipeline.run(user_prompt)" in main_src)
check("CLI no longer re-implements the step loop",
      "def run_with_steps" not in main_src, "run_with_steps still present")
check("CLI passes a progress callback",
      "Pipeline(progress_callback=" in main_src)
check("CLI surfaces the quota handoff document",
      "session_context_path" in main_src)

# Every step name the pipeline emits must render with a real label, or the CLI
# shows raw identifiers for steps it does not know about.
import main as cli_main

pipeline_src = (Path(__file__).parent / "agents" / "pipeline.py").read_text(encoding="utf-8")
emitted = set(_re.findall(r'_emit_progress\(\s*\d+\s*,\s*"([a-z_]+)"', pipeline_src))
emitted |= set(_re.findall(r'^\s+\(\d+,\s*"([a-z_]+)"', pipeline_src, _re.MULTILINE))
missing = sorted(emitted - set(cli_main._STEP_DISPLAY))

check("every pipeline step has a CLI label", not missing, f"unmapped: {missing}")
check("frontend_debugger is now shown (the old CLI skipped it entirely)",
      "frontend_debugger" in cli_main._STEP_DISPLAY)
check("remediation step is shown", "remediation" in cli_main._STEP_DISPLAY)

# ── Cleanup ────────────────────────────────────────────────────────────────
for d in (TMP, smoke_dir, boom_dir, noapp_dir):
    shutil.rmtree(d, ignore_errors=True)

# ── Summary ────────────────────────────────────────────────────────────────
total = len(PASS) + len(FAIL)
print(f"\n{'='*58}")
print(f"  Phase 22 Test Results: {len(PASS)}/{total} passed")
print(f"{'='*58}")
if FAIL:
    print("\n  Failures:")
    for f in FAIL:
        print(f"  [FAIL]  {f}")
    sys.exit(1)
print("\n  All tests passed. Phase 22 is fully implemented.")
