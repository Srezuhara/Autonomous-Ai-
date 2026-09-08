"""
tools/sql_schema_check.py — Phase 23

Catch SQL that queries a column the schema does not define.

WHY THIS EXISTS
---------------
`main.py` and `routes.py` are written by separate LLM calls, and they drift.
Row 3 on 2026-08-29 created the table with one column name and queried another:

    main.py    CREATE TABLE supplier (id …, name TEXT, contact_email TEXT)
    routes.py  SELECT id, name, contact FROM supplier

Both files import perfectly. Every affected endpoint raises
`OperationalError: no such column: contact` the moment a request arrives — five
of row 3's nineteen routes, invisible to every gate the pipeline had, because
nothing executes SQL until a request runs.

PRECISION OVER RECALL
---------------------
A false positive here costs an LLM call and edits code that was right, which is
the expensive failure mode this module exists to reduce. So the analysis is
deliberately conservative and skips anything it cannot resolve with confidence:

  * `SELECT *` — no column list to check.
  * queries built by string concatenation or f-strings — the text is not known.
  * subqueries and CTEs — table scope is ambiguous.
  * a table with no CREATE TABLE anywhere in the project — the schema may live
    in a migration or an ORM, so silence is correct.
  * bare (unqualified) column names in a multi-table query — the column could
    legitimately belong to either side of the join.

A qualified `alias.column` IS checked even across joins, because the alias
resolves the table unambiguously.
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import config
from tools.verification import VerificationOutcome

logger = logging.getLogger(__name__)

# SQL keywords and functions that can appear where a column name would.
_NOT_A_COLUMN = {
    "select", "from", "where", "and", "or", "not", "null", "as", "on", "in",
    "is", "like", "between", "order", "by", "group", "having", "limit",
    "offset", "join", "left", "right", "inner", "outer", "full", "cross",
    "union", "all", "distinct", "case", "when", "then", "else", "end",
    "count", "sum", "avg", "min", "max", "coalesce", "ifnull", "cast",
    "asc", "desc", "true", "false", "exists",
}

_CREATE_TABLE_HEAD = re.compile(
    r"""CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["'`\[]?(\w+)["'`\]]?\s*\(""",
    re.IGNORECASE,
)
_SELECT = re.compile(r"SELECT\s+(.*?)\s+FROM\s+(.*?)(?:\s+WHERE|\s+GROUP|\s+ORDER|\s+LIMIT|$)",
                     re.IGNORECASE | re.DOTALL)
_INSERT = re.compile(r"INSERT\s+INTO\s+[\"'`\[]?(\w+)[\"'`\]]?\s*\(([^)]*)\)",
                     re.IGNORECASE)
_UPDATE = re.compile(r"UPDATE\s+[\"'`\[]?(\w+)[\"'`\]]?\s+SET\s+(.*?)(?:\s+WHERE|$)",
                     re.IGNORECASE | re.DOTALL)
# A python string literal, single or triple quoted. Only literals are analysed:
# a concatenated or f-string query is not fully known at rest.
_STRINGS = re.compile(r'(?:"""(.*?)"""|\'\'\'(.*?)\'\'\'|"([^"\n]*)"|\'([^\'\n]*)\')',
                      re.DOTALL)


@dataclass
class SchemaIssue:
    table:   str
    column:  str
    file:    str
    known:   tuple = ()

    def __str__(self) -> str:
        # Naming the real columns is what makes this repairable in one call:
        # the model does not have to guess what `contact` was meant to be.
        cols = ", ".join(self.known) if self.known else "unknown"
        return (
            f"SQL in this file reads column `{self.column}` from table "
            f"`{self.table}`, which has no such column. The table is created "
            f"with: {cols}. Use the real column name — the CREATE TABLE is the "
            f"source of truth, so fix the query, not the schema."
        )


@dataclass
class MissingTable:
    """A table the code queries that no CREATE TABLE in the project creates."""
    table: str
    files: tuple = ()          # where it is queried, OUTPUT_DIR-relative
    created: tuple = ()        # the tables that ARE created, for contrast
    columns: tuple = ()        # the columns the queries read from it

    def __str__(self) -> str:
        where = ", ".join(self.files) if self.files else "the project"
        made = ", ".join(self.created) if self.created else "none"
        # Naming the columns the queries actually use is what makes this
        # repairable in one call. Without them the repair invents a plausible
        # table and the endpoints trade `no such table` for `no such column`,
        # which is what the first probe measured: the repair created
        # `stock_movement` and the queries wanted `movement_type`.
        cols = (f" Its queries read these columns: {', '.join(self.columns)}."
                if self.columns else "")
        return (
            f"SQL in {where} queries table `{self.table}`, which this project "
            f"never creates. The tables it does create are: {made}.{cols} Every "
            f"call that reaches this query raises `no such table: {self.table}` "
            f"at request time. Add the CREATE TABLE for `{self.table}` beside "
            f"the others — do NOT change the query to use a table that already "
            f"exists, which would read the wrong rows."
        )


@dataclass
class SchemaReport:
    tables: dict = field(default_factory=dict)          # table -> {columns}
    issues: list = field(default_factory=list)          # SchemaIssue
    #: table -> the files that query it. Collected before the "not in schema"
    #: skip, because a table absent from the schema is exactly the case below.
    queried: dict = field(default_factory=dict)
    #: table -> the columns its queries read. For a table that exists this is
    #: redundant with the schema; for one that does not, it is the only
    #: description of the table the code expects.
    queried_columns: dict = field(default_factory=dict)
    #: files containing at least one CREATE TABLE — the repair target for a
    #: missing one, because that is where its siblings live.
    schema_files: list = field(default_factory=list)
    missing: list = field(default_factory=list)         # MissingTable


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside parentheses."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _iter_create_tables(sql_text: str):
    """
    `(name, body)` for every CREATE TABLE, finding the body by matching
    parentheses rather than by looking for a terminator.

    The regex this replaces ended in `\\)\\s*;` — it required a semicolon after
    the closing bracket. A statement passed to `cursor.execute("CREATE TABLE
    ...")` does not have one, and needs none, so for those projects
    `parse_schema` returned {} and this entire module went silent: no schema
    means no column is ever checked, and the check reported nothing rather than
    reporting that it could not run. Found on 2026-09-03 on a build whose
    main.py creates two tables exactly that way.

    Matching brackets also handles `price DECIMAL(10, 2)`, which is why the
    terminator was there in the first place.
    """
    for m in _CREATE_TABLE_HEAD.finditer(sql_text):
        start = m.end() - 1                    # at the opening "("
        depth = 0
        for i in range(start, len(sql_text)):
            ch = sql_text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    yield m.group(1), sql_text[start + 1:i]
                    break


def parse_schema(sql_text: str) -> dict:
    """table name -> set of column names, from CREATE TABLE statements."""
    tables: dict = {}
    for name, body in _iter_create_tables(sql_text):
        cols = set()
        for part in _split_top_level(body):
            head = part.strip().split()
            if not head:
                continue
            first = head[0].strip('"\'`[]')
            # Table-level constraints are not columns.
            if first.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK",
                                 "CONSTRAINT", "KEY", "INDEX"}:
                continue
            cols.add(first)
        if cols:
            tables.setdefault(name, set()).update(cols)
    return tables


def _iter_sql_literals(source: str):
    """Yield string literals from Python source that look like SQL."""
    for m in _STRINGS.finditer(source):
        text = next((g for g in m.groups() if g), "")
        if not text:
            continue
        if re.search(r"\b(SELECT|INSERT\s+INTO|UPDATE)\b", text, re.IGNORECASE):
            yield text


def _from_clause_tables(clause: str) -> tuple[dict, bool]:
    """
    Map alias -> table for a FROM clause. Returns (mapping, is_single_table).

    `FROM stock_movement sm JOIN product p ON …` -> {"sm": "stock_movement",
    "stock_movement": "stock_movement", "p": "product", "product": "product"}
    """
    mapping: dict = {}
    # Strip ON conditions so their identifiers are not mistaken for tables.
    cleaned = re.sub(r"\bON\b.*?(?=\bJOIN\b|$)", " ", clause,
                     flags=re.IGNORECASE | re.DOTALL)
    chunks = re.split(r"\b(?:LEFT|RIGHT|INNER|OUTER|FULL|CROSS)?\s*JOIN\b|,",
                      cleaned, flags=re.IGNORECASE)
    count = 0
    for chunk in chunks:
        tokens = [t.strip('"\'`[]') for t in chunk.split() if t.strip()]
        tokens = [t for t in tokens if t.upper() != "AS"]
        if not tokens:
            continue
        table = tokens[0]
        if not re.fullmatch(r"\w+", table) or table.lower() in _NOT_A_COLUMN:
            continue
        count += 1
        mapping[table] = table
        if len(tokens) > 1 and re.fullmatch(r"\w+", tokens[1]):
            mapping[tokens[1]] = table
    return mapping, count == 1


def _check_select(sql: str, schema: dict, file: str, issues: list,
                  queried: dict | None = None,
                  columns: dict | None = None) -> None:
    for collist, from_clause in _SELECT.findall(sql):
        if "(" in from_clause and re.search(r"\bSELECT\b", from_clause, re.IGNORECASE):
            continue                                   # subquery: skip
        aliases, single = _from_clause_tables(from_clause)
        if not aliases:
            continue
        if queried is not None:
            for t in set(aliases.values()):
                queried.setdefault(t, set()).add(file)
        for expr in _split_top_level(collist):
            expr = re.sub(r"\s+AS\s+\w+$", "", expr, flags=re.IGNORECASE).strip()
            if "*" in expr or "(" in expr:
                continue                               # star or function: skip
            qualified = re.fullmatch(r"(\w+)\.(\w+)", expr)
            if qualified:
                alias, col = qualified.groups()
                table = aliases.get(alias)
                if table and columns is not None:
                    columns.setdefault(table, set()).add(col)
                if table and table in schema and col not in schema[table]:
                    issues.append(SchemaIssue(table, col, file, tuple(sorted(schema[table]))))
            elif single and re.fullmatch(r"\w+", expr):
                if expr.lower() in _NOT_A_COLUMN:
                    continue
                table = next(iter(set(aliases.values())))
                if columns is not None:
                    columns.setdefault(table, set()).add(expr)
                if table in schema and expr not in schema[table]:
                    issues.append(SchemaIssue(table, expr, file, tuple(sorted(schema[table]))))


def _check_insert_update(sql: str, schema: dict, file: str, issues: list,
                         queried: dict | None = None,
                         columns: dict | None = None) -> None:
    for table, collist in _INSERT.findall(sql):
        if queried is not None:
            queried.setdefault(table, set()).add(file)
        if columns is not None:
            for col in _split_top_level(collist):
                col = col.strip('"\'`[]')
                if re.fullmatch(r"\w+", col):
                    columns.setdefault(table, set()).add(col)
        if table not in schema:
            continue
        for col in _split_top_level(collist):
            col = col.strip('"\'`[]')
            if re.fullmatch(r"\w+", col) and col not in schema[table]:
                issues.append(SchemaIssue(table, col, file, tuple(sorted(schema[table]))))
    for table, assigns in _UPDATE.findall(sql):
        if queried is not None:
            queried.setdefault(table, set()).add(file)
        if table not in schema:
            continue
        for part in _split_top_level(assigns):
            m = re.match(r"\s*[\"'`\[]?(\w+)[\"'`\]]?\s*=", part)
            if m and m.group(1) not in schema[table]:
                issues.append(SchemaIssue(table, m.group(1), file, tuple(sorted(schema[table]))))


#: Never reported as a missing table.
_NOT_A_TABLE = {
    "sqlite_master", "sqlite_sequence", "sqlite_temp_master", "dual",
    "information_schema", "pg_catalog",
}

#: Anything here means tables may be created by something this module cannot
#: read, so "nothing creates it" is no longer a safe inference.
_ORM_MARKERS = (
    "sqlalchemy", "declarative_base", "metadata.create_all", "alembic",
    "django.db", "peewee", "tortoise", "sqlmodel",
)


def _schema_lives_elsewhere(sources: dict, project) -> bool:
    """Could this project be creating tables somewhere this module cannot see?"""
    try:
        for name in ("alembic", "migrations"):
            if (project / name).is_dir():
                return True
    except Exception:
        return True                       # unreadable: assume yes, report nothing
    for source in sources.values():
        low = source.lower()
        if any(marker in low for marker in _ORM_MARKERS):
            return True
    return False


def check_project_sql(root: str, file_paths: list[str]) -> SchemaReport:
    """
    Collect the schema from every CREATE TABLE in the project, then check every
    SQL literal against it. Never raises.
    """
    report = SchemaReport()
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        if not project.is_dir():
            return report
    except Exception:
        return report

    sources: dict = {}
    try:
        candidates = [p for p in project.rglob("*.py")
                      if "__pycache__" not in p.parts and "venv" not in p.parts]
        candidates += list(project.rglob("*.sql"))
    except Exception:
        return report

    for path in candidates:
        try:
            sources[path] = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

    # Pass 1: the schema, from anywhere in the project.
    all_sql = "\n".join(sources.values())
    report.tables = parse_schema(all_sql)
    if not report.tables:
        return report

    # Pass 2: every SQL literal, checked against it.
    for path, source in sources.items():
        try:
            rel = str(path.relative_to(base)).replace("\\", "/")
        except Exception:
            rel = str(path)
        literals = ([source] if path.suffix == ".sql"
                    else list(_iter_sql_literals(source)))
        for sql in literals:
            if path.suffix == ".sql":
                continue                              # the schema itself
            try:
                _check_select(sql, report.tables, rel, report.issues,
                              report.queried, report.queried_columns)
                _check_insert_update(sql, report.tables, rel, report.issues,
                                     report.queried, report.queried_columns)
            except Exception:
                continue

    # ── A queried table that is never created ────────────────────────────────
    #
    # The module's stated rule is that a table with no CREATE TABLE anywhere is
    # NOT reported, because "the schema may live in a migration or an ORM". That
    # is right in general and wrong in one specific, checkable case: when this
    # project creates its OTHER tables inline. Row 3 on 2026-09-03 created
    # `supplier` and `warehouse` in main.py and queried `product` and
    # `stock_movement`, which nothing created — 8 of its 9 failing endpoints,
    # every one raising `no such table` at request time, and no check said a
    # word. Reaching this point at all means `report.tables` is non-empty, so
    # the inline-schema condition already holds.
    #
    # Two exits, both because the premise stops holding:
    #   * an ORM or migrations in the project — the tables it does not create
    #     inline may be created by metadata, and this cannot see that;
    #   * a name that is not a plain identifier, or a known system table.
    for path, source in sources.items():
        if "CREATE TABLE" in source.upper():
            try:
                report.schema_files.append(
                    str(path.relative_to(base)).replace("\\", "/"))
            except Exception:
                pass

    if not _schema_lives_elsewhere(sources, project):
        created = tuple(sorted(report.tables))
        for table, files in sorted(report.queried.items()):
            if table in report.tables or table.lower() in _NOT_A_TABLE:
                continue
            report.missing.append(MissingTable(
                table=table, files=tuple(sorted(files)), created=created,
                columns=tuple(sorted(report.queried_columns.get(table, ())))))

    if report.missing:
        logger.info(
            f"🗄️  SQL schema check: {len(report.missing)} queried table(s) that "
            f"nothing creates — "
            + "; ".join(m.table for m in report.missing[:5])
        )

    # De-duplicate: the same mismatch in five queries is one defect.
    seen, unique = set(), []
    for i in report.issues:
        key = (i.file, i.table, i.column)
        if key not in seen:
            seen.add(key)
            unique.append(i)
    report.issues = unique

    if report.issues:
        logger.info(
            f"🗄️  SQL schema check: {len(report.issues)} column mismatch(es) — "
            + "; ".join(f"{i.table}.{i.column}" for i in report.issues[:5])
        )
    return report


# ── Which database file the project actually opens ────────────────────────────
#
# WHY THIS EXISTS
# ---------------
# Row 2 on 2026-09-08 created its three tables in `bookmark.db` and served every
# request out of `bookmarks.db`:
#
#     main.py      DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bookmark.db")
#                  ... CREATE TABLE bookmarks / tags / bookmark_tags
#     services.py  DB_PATH = os.getenv("DB_PATH", "bookmarks.db")
#                  ... SELECT ... FROM bookmarks
#
# Every file imports. Every table in the schema is queried, and every column
# matches — the check above is entirely correct to pass it. The two modules
# simply address two different SQLite files, and SQLite creates the missing one,
# empty, on connect. All nine endpoints answered 500 `no such table: bookmarks`
# while this module reported "3 table(s) created, 3 queried — verified".
#
# That is the same shape as the defect the module docstring opens with: two
# files written by separate LLM calls, drifting. The column check catches drift
# WITHIN a database; this catches drift BETWEEN databases.
#
# PRECISION OVER RECALL, as everywhere else here. Only literal, statically
# resolvable paths are compared. A path built at runtime, joined from parts, or
# read from an environment variable with no literal default is skipped — an
# unknown path is not evidence of a mismatch, and a false positive here spends
# an LLM call rewriting code that was right.

#: Suffixes that make a string recognisably a database file rather than any
#: other literal that happens to reach `connect()`.
_DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")


@dataclass
class DbPathReport:
    #: file -> the database file(s) that module opens, as basenames
    by_file: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    #: file -> findings, for `_refine_and_remediate`
    repair_targets: dict = field(default_factory=dict)


def _resolve_str(node, consts: dict, depth: int = 0):
    """
    Best-effort literal value of an AST node, or None when it is not statically
    known. Only evaluates string operations on values already known to be
    literals — it never executes project code.
    """
    if depth > 6:                      # cyclic or pathological nesting
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute):
            # os.getenv("X", "default") / os.environ.get("X", "default").
            # With no default the value is unknown at rest, so skip it.
            if fn.attr in ("getenv", "get") and len(node.args) >= 2:
                return _resolve_str(node.args[1], consts, depth + 1)
            # "sqlite:///./x.db".replace("sqlite:///", "", 1) — the idiom every
            # generated project uses to turn a SQLAlchemy URL into a file path.
            if fn.attr == "replace" and len(node.args) >= 2:
                base = _resolve_str(fn.value, consts, depth + 1)
                old = _resolve_str(node.args[0], consts, depth + 1)
                new = _resolve_str(node.args[1], consts, depth + 1)
                if base is not None and old is not None and new is not None:
                    return base.replace(old, new)
    return None


def _db_basename(value):
    """
    The database file a path or URL names, or None when it is not one.

    Compared by basename deliberately: `./bookmark.db` and `bookmark.db` are the
    same file addressed two ways, while `bookmark.db` and `bookmarks.db` are
    two files that differ by one character — which is exactly how this defect
    presents, and why it survives a reading.
    """
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if ":memory:" in v:
        return None                    # legitimately per-connection
    if "://" in v:                     # a URL that was never split apart
        v = v.split("://", 1)[1].lstrip("/")
    v = v.replace("\\", "/").rstrip("/")
    base = v.rsplit("/", 1)[-1]
    if not base.lower().endswith(_DB_SUFFIXES):
        return None
    return base


def _module_db_paths(source: str) -> set:
    """The database file(s) a single module opens, as far as they are literal."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    # Module-level string constants, including ones assigned inside an `if`,
    # which is where the sqlite-URL idiom above always lands.
    consts: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                value = _resolve_str(node.value, consts)
                if value is not None:
                    consts.setdefault(target.id, value)

    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in ("connect", "create_engine"):
            continue
        base = _db_basename(_resolve_str(node.args[0], consts))
        if base:
            found.add(base)
    return found


def _is_test_file(rel: str) -> bool:
    """
    Tests get their own database on purpose. Comparing them against the
    application's would report a mismatch on every well-written project.
    """
    parts = rel.lower().split("/")
    return any(p in ("test", "tests") for p in parts) or \
        parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def check_project_db_paths(root: str, schema_files=None) -> DbPathReport:
    """
    Whether the project creates its tables in the same database it queries.
    Never raises.
    """
    report = DbPathReport()
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        if not project.is_dir():
            return report
        candidates = [p for p in project.rglob("*.py")
                      if "__pycache__" not in p.parts and "venv" not in p.parts]
    except Exception:
        return report

    entry_files: list = []
    for path in sorted(candidates):
        try:
            rel = str(path.relative_to(base)).replace("\\", "/")
            if _is_test_file(rel):
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            paths = _module_db_paths(source)
        except Exception:
            continue
        # The module the process starts in: it builds the app (and so owns the
        # lifespan that creates the schema), or it is the conventional entry
        # point for a CLI, which has no app to look for.
        if "FastAPI(" in source or rel.rsplit("/", 1)[-1] == "main.py":
            entry_files.append(rel)
        if paths:
            report.by_file[rel] = sorted(paths)

    distinct = sorted({p for ps in report.by_file.values() for p in ps})
    if len(distinct) < 2:
        return report                  # one database, or none it can resolve

    # Which database is the real one. Not "the file with a CREATE TABLE" — row 2
    # had a CREATE TABLE in BOTH modules, one of them in a `init_db()` nothing
    # ever calls, and anchoring on the schema made this check fall silent on the
    # very build it was written for. The database that actually exists at
    # request time is the one the ENTRY module opens, because that is the module
    # whose startup path runs.
    entry_paths: set = set()
    for rel, paths in report.by_file.items():
        if rel in entry_files:
            entry_paths.update(paths)
    if len(entry_paths) != 1:
        # No single entry database to compare against: which path is the wrong
        # one is then a guess, and a guess here rewrites correct code.
        return report

    anchor = next(iter(entry_paths))
    for rel, paths in sorted(report.by_file.items()):
        if rel in entry_files:
            continue
        for other in [p for p in paths if p != anchor]:
            report.issues.append(
                f"`{rel}` opens `{other}`, but the application initialises "
                f"`{anchor}` at startup. SQLite creates a missing file empty on "
                f"connect, so every query through this module raises `no such "
                f"table` at request time while the schema itself is perfectly "
                f"correct. Point this module at `{anchor}` so it reads the "
                f"database the app actually creates — do NOT add a CREATE TABLE "
                f"here, which leaves the project with two live databases that "
                f"drift apart."
            )
            report.repair_targets.setdefault(rel, []).append(
                report.issues[-1])
    return report


def check_sql_schema(root: str) -> VerificationOutcome:
    """The same check as a VerificationOutcome, for the verification surface.

    This did not exist until 2026-09-03, and neither did any call to this module
    from the pipeline: it ran only in `tools/verify_corpus.py`, over projects
    that had already shipped. So the one check that can see a query and a schema
    disagree has never run during a build.
    """
    try:
        base = Path(config.OUTPUT_DIR)
        project = base / root
        files = [
            str(p.relative_to(base)).replace("\\", "/")
            for p in sorted(project.rglob("*.py"))
            if "__pycache__" not in p.parts
        ] if project.is_dir() else []
    except Exception:
        files = []

    report = check_project_sql(root, files)

    if not report.tables:
        return VerificationOutcome.not_applicable(
            "sql_schema",
            detail=("this project creates no tables inline, so there is no "
                    "schema here to check SQL against"),
        )

    # Whether the schema and the queries address the same database FILE. The
    # column analysis above cannot see this: it compares statements, and two
    # statements can agree perfectly while running against different files.
    db_paths = check_project_db_paths(root, report.schema_files)

    detail = (f"{len(report.tables)} table(s) created, "
              f"{len(report.queried)} queried")
    if db_paths.by_file:
        opened = sorted({p for ps in db_paths.by_file.values() for p in ps})
        detail += f", in {len(opened)} database file(s) ({', '.join(opened)})"
    findings = (
        [str(i) for i in report.issues]
        + [str(m) for m in report.missing]
        + list(db_paths.issues)
    )
    if not findings:
        return VerificationOutcome.verified("sql_schema", detail=detail)

    # A missing table is repaired where the other CREATE TABLEs are, which is
    # never the file the traceback names — that one is wherever the query runs.
    targets: dict = {}
    if report.missing and report.schema_files:
        where = report.schema_files[0]
        targets[where] = [str(m) for m in report.missing]
    # A path mismatch is repaired in the module that opens the WRONG file, not
    # in the one that holds the schema — the schema is right.
    for where, issues in db_paths.repair_targets.items():
        targets.setdefault(where, []).extend(issues)

    return VerificationOutcome.failed(
        "sql_schema", findings, detail=detail,
        evidence={
            "missing_tables": [m.table for m in report.missing],
            "column_mismatches": [f"{i.table}.{i.column}" for i in report.issues],
            "database_files": sorted(
                {p for ps in db_paths.by_file.values() for p in ps}),
            "repair_targets": targets,
        },
    )
