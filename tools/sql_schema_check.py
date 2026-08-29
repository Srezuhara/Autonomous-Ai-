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

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import config

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

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?(\w+)[\"'`\]]?\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
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
class SchemaReport:
    tables: dict = field(default_factory=dict)          # table -> {columns}
    issues: list = field(default_factory=list)          # SchemaIssue


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


def parse_schema(sql_text: str) -> dict:
    """table name -> set of column names, from CREATE TABLE statements."""
    tables: dict = {}
    for name, body in _CREATE_TABLE.findall(sql_text):
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


def _check_select(sql: str, schema: dict, file: str, issues: list) -> None:
    for collist, from_clause in _SELECT.findall(sql):
        if "(" in from_clause and re.search(r"\bSELECT\b", from_clause, re.IGNORECASE):
            continue                                   # subquery: skip
        aliases, single = _from_clause_tables(from_clause)
        if not aliases:
            continue
        for expr in _split_top_level(collist):
            expr = re.sub(r"\s+AS\s+\w+$", "", expr, flags=re.IGNORECASE).strip()
            if "*" in expr or "(" in expr:
                continue                               # star or function: skip
            qualified = re.fullmatch(r"(\w+)\.(\w+)", expr)
            if qualified:
                alias, col = qualified.groups()
                table = aliases.get(alias)
                if table and table in schema and col not in schema[table]:
                    issues.append(SchemaIssue(table, col, file, tuple(sorted(schema[table]))))
            elif single and re.fullmatch(r"\w+", expr):
                if expr.lower() in _NOT_A_COLUMN:
                    continue
                table = next(iter(set(aliases.values())))
                if table in schema and expr not in schema[table]:
                    issues.append(SchemaIssue(table, expr, file, tuple(sorted(schema[table]))))


def _check_insert_update(sql: str, schema: dict, file: str, issues: list) -> None:
    for table, collist in _INSERT.findall(sql):
        if table not in schema:
            continue
        for col in _split_top_level(collist):
            col = col.strip('"\'`[]')
            if re.fullmatch(r"\w+", col) and col not in schema[table]:
                issues.append(SchemaIssue(table, col, file, tuple(sorted(schema[table]))))
    for table, assigns in _UPDATE.findall(sql):
        if table not in schema:
            continue
        for part in _split_top_level(assigns):
            m = re.match(r"\s*[\"'`\[]?(\w+)[\"'`\]]?\s*=", part)
            if m and m.group(1) not in schema[table]:
                issues.append(SchemaIssue(table, m.group(1), file, tuple(sorted(schema[table]))))


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
                _check_select(sql, report.tables, rel, report.issues)
                _check_insert_update(sql, report.tables, rel, report.issues)
            except Exception:
                continue

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
