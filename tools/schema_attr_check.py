"""
tools/schema_attr_check.py — an attribute a model never declared
================================================================

The defect a runtime probe structurally cannot see.

`routes.py` and `schemas.py` are separate LLM calls that agree on a class name
and disagree on its fields. Row 3 shipped this:

    routes.py   INSERT INTO supplier (name, contact) ... reads sup.contact
    schemas.py  class SupplierBase: name, contact_email    -> AttributeError

    routes.py   INSERT INTO product (..., sku, ...)     ... reads prod.sku
    schemas.py  class ProductBase: name, description, price, supplier_id
                                                           -> AttributeError

Both files import perfectly. Nothing raises until a request arrives with a body,
and until 2026-08-30 the probe sent `json={}` to every write route, so the
handler never ran and the build scored 16/16 with four dead endpoints.

The fixed probe finds these — but only the ones a request reaches, and only
after a build has run. This finds them by reading the source, before a single
token is spent, and it catches the one shape the probe still cannot see: a
repair that **silences** an AttributeError by writing `data.get("sku")` into a
*nullable* column. Nothing fails at request time; a NULL is simply written where
a value belonged. That corruption scored 15/16 against the correct repair's
14/16, which is why a smoke score cannot be the acceptance test for a repair.

Precision over recall, the same stance as `tools/sql_schema_check.py`: a false
positive spends an LLM call editing correct code and tells a user their working
build is broken. Everything it cannot resolve with certainty, it skips —

  * a model whose base class chain does not end at `BaseModel` in this project
    (an unresolved base may declare the very field in question);
  * a model that accepts unknown fields (`extra="allow"`);
  * a parameter that is reassigned in the function body;
  * an annotation that is a container other than `Optional[...]`;
  * anything reached through `getattr`, `**spread` or a string annotation it
    cannot resolve.

Deterministic and free: no LLM, no tokens.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

# Attributes every pydantic model carries whatever its fields are. Reading one
# is not drift.  Both v1 and v2 spellings, because generated code has used each.
_MODEL_API = {
    "dict", "json", "copy", "schema", "schema_json", "construct", "parse_obj",
    "parse_raw", "parse_file", "from_orm", "validate", "update_forward_refs",
    "model_dump", "model_dump_json", "model_copy", "model_validate",
    "model_validate_json", "model_construct", "model_json_schema",
    "model_fields", "model_fields_set", "model_extra", "model_config",
    "model_post_init", "model_rebuild", "__fields__", "__dict__", "__class__",
}

_BASE_MODEL_NAMES = {"BaseModel", "pydantic.BaseModel"}

_SKIP_DIRS = {"__pycache__", "venv", ".venv", "node_modules", ".git",
              "alembic", "migrations"}


@dataclass
class AttrIssue:
    """One read of an attribute the annotated model does not declare."""
    file:    str            # OUTPUT_DIR-relative, forward slashes
    line:    int
    param:   str            # the local name that was read
    model:   str            # the model it is annotated with
    attr:    str            # the attribute that does not exist
    declared: tuple = ()    # the fields it does declare

    def __str__(self) -> str:
        # Naming the real fields is what makes this repairable in one call: the
        # model does not have to guess whether `contact` was a rename or an
        # omission, which is exactly the ambiguity that made it silence the
        # error instead of fixing it.
        fields = ", ".join(self.declared) if self.declared else "no fields at all"
        return (
            f"`{self.param}.{self.attr}` is read at line {self.line}, but "
            f"`{self.param}` is a `{self.model}`, which declares {fields}. "
            f"This raises AttributeError on every call that reaches it. Either "
            f"use the field that exists, or add `{self.attr}` to {self.model} "
            f"where it is defined — do NOT replace the read with a .get() or a "
            f"default, which writes an empty value into the database instead."
        )


@dataclass
class AttrReport:
    models: dict = field(default_factory=dict)   # name -> frozenset(readable)
    declared: dict = field(default_factory=dict)  # name -> frozenset(fields)
    issues: list = field(default_factory=list)   # AttrIssue
    open_models: set = field(default_factory=set)  # names deliberately not checked


# ── Collecting the models ─────────────────────────────────────────────────────

def _base_names(node: ast.ClassDef) -> list[str]:
    """Base class names, both `X` and `module.X`, ignoring generics."""
    names = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _accepts_extra(node: ast.ClassDef) -> bool:
    """`extra="allow"` — reading an undeclared attribute is then legitimate."""
    for stmt in ast.walk(node):
        if isinstance(stmt, ast.keyword) and stmt.arg == "extra":
            if isinstance(stmt.value, ast.Constant) and stmt.value.value == "allow":
                return True
        # v1 spelling: class Config: extra = "allow"
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "extra":
                    if (isinstance(stmt.value, ast.Constant)
                            and stmt.value.value == "allow"):
                        return True
    return False


def _own_names(node: ast.ClassDef) -> tuple:
    """
    `(everything readable on this class, the fields it declares)`.

    The two are different and both are needed. Reading a validator method or an
    unannotated class attribute is legitimate, so it must not be reported as
    missing — but only annotated names are *fields*, and the fields are what
    goes into the repair prompt. Telling a model that `SupplierBase` declares
    `model_config` and `title_not_empty` invites it to reach for one of them.
    """
    readable: set[str] = set()
    fields: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name = stmt.target.id
            readable.add(name)
            if name not in _MODEL_API and not name.startswith("_"):
                fields.add(name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    readable.add(target.id)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            readable.add(stmt.name)
        elif isinstance(stmt, ast.ClassDef):
            readable.add(stmt.name)
    return readable, fields


def collect_models(sources: dict) -> tuple[dict, set, dict]:
    """
    Every pydantic model in the project, and the ones that must not be checked.

    Returns `({name: frozenset(readable)}, {open model names},
    {name: frozenset(declared fields)})`. A model is *open* — collected but
    never used to report a defect — when its base chain leaves the project or it
    accepts extra fields, because then the absence of a field here is not
    evidence the field does not exist.
    """
    classes: dict = {}   # name -> (readable, fields, base names, accepts_extra)
    for path, source in sources.items():
        try:
            tree = ast.parse(source)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                readable, fields = _own_names(node)
                classes[node.name] = (
                    readable, fields, _base_names(node), _accepts_extra(node)
                )

    models: dict = {}
    open_models: set = set()
    declared: dict = {}

    def resolve(name: str, seen: set) -> tuple:
        """(readable, fields, is_model, is_open) for a class name."""
        if name in _BASE_MODEL_NAMES:
            return set(), set(), True, False
        if name in seen or name not in classes:
            # Unknown base: it may declare the field we are about to call
            # missing, so anything inheriting it is not checkable.
            return set(), set(), False, True
        seen.add(name)
        own, own_fields, bases, extra = classes[name]
        readable, fields = set(own), set(own_fields)
        is_model, is_open = False, extra
        for base in bases:
            b_read, b_fields, b_model, b_open = resolve(base, seen)
            readable |= b_read
            fields |= b_fields
            is_model = is_model or b_model
            is_open = is_open or b_open
        return readable, fields, is_model, is_open

    for name in classes:
        readable, fields, is_model, is_open = resolve(name, set())
        if not is_model:
            continue
        models[name] = frozenset(readable)
        declared[name] = frozenset(fields)
        if is_open:
            open_models.add(name)

    return models, open_models, declared


# ── Reading the usages ────────────────────────────────────────────────────────

def _annotation_model(node, models: dict) -> str:
    """
    The model name an annotation resolves to, or "".

    `X`, `schemas.X` and `Optional[X]` resolve. `List[X]` deliberately does not:
    the parameter is a list, and `param.attr` on it is not a field read.
    """
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id if node.id in models else ""
    if isinstance(node, ast.Attribute):
        return node.attr if node.attr in models else ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # A string annotation, "schemas.ProductCreate" or "ProductCreate".
        name = node.value.strip().rsplit(".", 1)[-1]
        return name if name in models else ""
    if isinstance(node, ast.Subscript):
        head = node.value
        head_name = (head.id if isinstance(head, ast.Name)
                     else head.attr if isinstance(head, ast.Attribute) else "")
        if head_name in ("Optional",):
            return _annotation_model(node.slice, models)
        if head_name in ("Union",):
            # Optional spelled the long way: Union[X, None].
            parts = (node.slice.elts if isinstance(node.slice, ast.Tuple)
                     else [node.slice])
            named = [_annotation_model(p, models) for p in parts]
            named = [n for n in named if n]
            return named[0] if len(named) == 1 else ""
        return ""
    return ""


def _rebound(func: ast.AST, name: str) -> bool:
    """Is this local name assigned anywhere in the function body?

    If it is, the annotation no longer describes what the attribute is read on,
    and reporting would be a guess.
    """
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            target = node.target
            if isinstance(target, ast.Name) and target.id == name:
                return True
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return True
    return False


def _check_function(func, models: dict, open_models: set, declared: dict,
                    rel: str, issues: list) -> None:
    typed: dict = {}
    args = func.args
    for arg in list(args.args) + list(args.posonlyargs) + list(args.kwonlyargs):
        model = _annotation_model(arg.annotation, models)
        if model and model not in open_models and not _rebound(func, arg.arg):
            typed[arg.arg] = model

    # A local with an explicit annotation is as good a promise as a parameter.
    for node in ast.walk(func):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            model = _annotation_model(node.annotation, models)
            if model and model not in open_models:
                typed[node.target.id] = model

    if not typed:
        return

    for node in ast.walk(func):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name):
            continue
        model = typed.get(node.value.id)
        if not model:
            continue
        attr = node.attr
        if attr in _MODEL_API or attr.startswith("_"):
            continue
        if attr in models.get(model, frozenset()):
            continue
        issues.append(AttrIssue(
            file=rel, line=getattr(node, "lineno", 0), param=node.value.id,
            model=model, attr=attr,
            declared=tuple(sorted(declared.get(model, frozenset()))),
        ))


def check_project_attributes(root: str) -> AttrReport:
    """
    Every attribute read that the annotated pydantic model does not declare.

    `root` is the project folder under OUTPUT_DIR — the same convention every
    other tool here takes, because generated paths are OUTPUT_DIR-relative and a
    bare open() silently reads nothing. Never raises.
    """
    report = AttrReport()
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        if not project.is_dir():
            return report
    except Exception:
        return report

    sources: dict = {}
    try:
        for path in sorted(project.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            try:
                sources[path] = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
    except Exception:
        return report

    if not sources:
        return report

    report.models, report.open_models, report.declared = collect_models(sources)
    if not report.models:
        return report

    for path, source in sources.items():
        try:
            tree = ast.parse(source)
            rel = str(path.relative_to(base)).replace("\\", "/")
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    _check_function(node, report.models, report.open_models,
                                    report.declared, rel, report.issues)
                except Exception:
                    continue

    # The same read in a create and an update handler is one defect.
    seen, unique = set(), []
    for issue in report.issues:
        key = (issue.file, issue.model, issue.attr)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    report.issues = unique

    if report.issues:
        logger.info(
            f"🧬 Schema attribute check: {len(report.issues)} undeclared "
            f"field read(s) — "
            + "; ".join(f"{i.model}.{i.attr}" for i in report.issues[:5])
        )
    return report


def _project_sources(root: str) -> dict:
    base = Path(config.OUTPUT_DIR)
    project = base / root
    sources: dict = {}
    if not project.is_dir():
        return sources
    for path in sorted(project.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            sources[path] = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return sources


def find_model_definition(root: str, class_name: str) -> tuple:
    """
    Where a pydantic model is defined, and what it declares.

    Returns `(OUTPUT_DIR-relative path, (fields...))`, or `("", ())` when the
    class is not a resolvable model in this project. Used by the pipeline to
    decide whether a runtime AttributeError belongs in the file that raised or
    in the file that defines the class it names. Never raises.
    """
    try:
        base = Path(config.OUTPUT_DIR)
        sources = _project_sources(root)
        if not sources:
            return "", ()
        models, open_models, declared = collect_models(sources)
        if class_name not in models or class_name in open_models:
            return "", ()
        for path, source in sources.items():
            try:
                tree = ast.parse(source)
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    rel = str(path.relative_to(base)).replace("\\", "/")
                    return rel, tuple(sorted(declared[class_name]))
    except Exception:
        pass
    return "", ()


def check_schema_attributes(root: str) -> VerificationOutcome:
    """The same check as a VerificationOutcome, for the verification surface."""
    report = check_project_attributes(root)

    if not report.models:
        return VerificationOutcome.not_applicable(
            "schema_attr",
            detail="this project declares no pydantic models",
        )

    checked = len(report.models) - len(report.open_models)
    detail = (
        f"{checked} model(s) checked field-by-field "
        f"({len(report.open_models)} skipped as open)"
    )
    if report.issues:
        return VerificationOutcome.failed(
            "schema_attr", [str(i) for i in report.issues], detail=detail,
            evidence={"undeclared": [f"{i.model}.{i.attr}" for i in report.issues]},
        )
    return VerificationOutcome.verified("schema_attr", detail=detail)
