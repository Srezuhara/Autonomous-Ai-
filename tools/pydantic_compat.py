"""
tools/pydantic_compat.py — Phase 23

Rewrite pydantic **V1** config keys that V2 silently ignores.

WHY THIS EXISTS
---------------
Generated `schemas.py` files keep reaching for the V1 idiom:

    class ProductRead(BaseModel):
        id: int
        name: str

        class Config:
            orm_mode = True

The project installs `pydantic>=2.0.0`. Under V2 `orm_mode` is not an error and
not a failure — it is *ignored*, with a `UserWarning` buried in stderr among the
other import noise:

    UserWarning: Valid config keys have changed in V2:
    * 'orm_mode' has been renamed to 'from_attributes'

So `from_attributes` is never set. Every `response_model` that must serialize a
row or ORM object then fails at REQUEST time — a 500 the import check cannot
see, because the module imports perfectly well. Twenty occurrences across the
generated projects on 2026-08-29.

These renames are exact: V2 kept the same semantics under a new name, so the
rewrite is deterministic and costs no tokens. Anything whose meaning changed
between versions is deliberately NOT handled here — `@validator` becomes
`@field_validator` with a different signature, and rewriting it blindly would
turn working code into broken code. Those belong to the LLM repair path.

Note what is NOT rewritten: `.json()`. It is a V1 model method, but in this
codebase almost every occurrence is `response.json()` on an httpx/TestClient
response — 68 of them — and rewriting those would break every generated test.
`.dict()` is likewise left alone: deprecated under V2, but it still works.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)


# V1 name -> V2 name. Only keys whose meaning is unchanged by the rename.
CONFIG_KEY_RENAMES = {
    "orm_mode":                       "from_attributes",
    "schema_extra":                   "json_schema_extra",
    "allow_population_by_field_name": "populate_by_name",
    "anystr_strip_whitespace":        "str_strip_whitespace",
    "min_anystr_length":              "str_min_length",
    "max_anystr_length":              "str_max_length",
}


@dataclass
class CompatResult:
    files_changed: list[str] = field(default_factory=list)
    renames:       list[str] = field(default_factory=list)
    error:         str = ""


def _rewrite(source: str) -> tuple[str, list[str]]:
    """Return (new_source, renames_applied) for one file's text."""
    applied: list[str] = []
    out = source
    for old, new in CONFIG_KEY_RENAMES.items():
        # Only an assignment at the start of a line (inside `class Config:`),
        # never a substring of some longer identifier and never inside a string.
        pattern = re.compile(rf"^(\s*){re.escape(old)}(\s*=\s*)", re.MULTILINE)
        out, n = pattern.subn(rf"\g<1>{new}\g<2>", out)
        if n:
            applied.extend([f"{old} -> {new}"] * n)
    return out, applied


def fix_pydantic_v1_config(root: str, file_paths: list[str]) -> CompatResult:
    """
    Rewrite V1 config keys in every generated Python file under `root`.

    `file_paths` holds OUTPUT_DIR-relative paths, the same convention
    file_writer uses. Never raises: a compat pass must not fail a build.
    """
    result = CompatResult()
    try:
        base = Path(config.OUTPUT_DIR)
    except Exception as e:            # pragma: no cover - config is always there
        result.error = str(e)
        return result

    for rel in file_paths:
        if not str(rel).endswith(".py"):
            continue
        path = Path(rel)
        if not path.is_file():
            path = base / rel
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except Exception:
            continue

        new_source, applied = _rewrite(source)
        if not applied:
            continue
        try:
            path.write_text(new_source, encoding="utf-8")
        except Exception as e:
            result.error = f"Could not write {path}: {e}"
            continue
        result.files_changed.append(str(rel).replace("\\", "/"))
        result.renames.extend(applied)

    if result.files_changed:
        logger.info(
            f"🧬 pydantic V2 compat: {len(result.renames)} key(s) renamed in "
            f"{len(result.files_changed)} file(s) — "
            + ", ".join(sorted(set(result.renames)))
        )
    return result
