"""
api_platform/database.py  (Phase B1 — SQLAlchemy + Alembic behind the seam)
===========================================================================
The function signatures in this module are the seam the whole platform is
written against: `runner.py`, all five route modules, `main.py` and three test
suites call them, and none of those changed when the storage underneath did.
Only the bodies here were reimplemented.

What changed
------------
  - Storage is SQLAlchemy (`api_platform/db/`), not hand-written sqlite3.
  - `DATABASE_URL` selects the backend. Unset, it is derived from `DB_PATH`
    exactly as before, so the local workflow and the existing
    `generated_projects/platform.db` are untouched. Postgres is opt-in.
  - Schema changes are Alembic revisions. The old
    `ALTER TABLE ... except OperationalError` block could add a column but never
    rename, drop, backfill or re-type one, and left no record of what any given
    database had been through. `initialize_db()` still reconciles legacy columns
    on an unstamped database, because a database that predates Alembic has to be
    brought up to the baseline before it can be stamped at it.
  - `datetime.utcnow()` (deprecated in 3.12) is `datetime.now(timezone.utc)`.
    The stored format is unchanged: a naive ISO-8601 string, so existing rows
    and new ones sort and compare against each other exactly as before.

What deliberately did NOT change
--------------------------------
  - Every function returns plain `dict`s with the same keys, in the same types.
    `created_at` and friends stay ISO strings — see `db/models.py` for why
    turning them into `datetime` objects would be a silent API change.
  - `DB_PATH` remains a module-level name that can be reassigned. Three test
    suites do exactly that, and the engine is resolved lazily so it keeps
    working.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, insert, select, text, update

from api_platform.db import (
    Base, BuildProgress, Project, ProjectFile, PROJECT_COLUMNS,
    dispose_all, get_engine, session_scope,
)

try:
    from config import OUTPUT_DIR
except ImportError:
    OUTPUT_DIR = "generated_projects"

logger = logging.getLogger(__name__)

DB_PATH = Path(OUTPUT_DIR) / "platform.db"


def _utcnow_iso() -> str:
    """
    Now, as the platform has always stored it.

    `datetime.utcnow()` is deprecated from 3.12. Its replacement is
    timezone-aware, and `.isoformat()` on an aware datetime appends "+00:00" —
    which would make new rows sort and compare differently from the ~50 rows
    already on disk. Dropping the tzinfo keeps the stored format identical.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


# ── Legacy reconciliation ─────────────────────────────────────────────────────
# Columns added after the Phase 14 baseline, in the order they arrived. A
# database created before Alembic may be missing any suffix of this list, and
# has to be brought to the baseline before it can be stamped at it — stamping an
# out-of-date database would tell Alembic a lie it never re-checks.
_LEGACY_COLUMNS = [
    ("prompt_tokens",     "INTEGER DEFAULT 0"),
    ("completion_tokens", "INTEGER DEFAULT 0"),
    ("total_tokens",      "INTEGER DEFAULT 0"),
    ("completion_reason", "TEXT"),
    ("progress_percent",  "REAL"),
    ("tokens_by_model",   "TEXT"),
    ("smoke_summary",     "TEXT"),
    ("verification",      "TEXT"),
    ("build_shape",       "TEXT"),
]


def _reconcile_legacy_columns(engine) -> list[str]:
    """Add any baseline column an Alembic-less database is missing."""
    added: list[str] = []
    if engine.dialect.name != "sqlite":
        return added
    with engine.begin() as conn:
        have = {
            row[1] for row in conn.exec_driver_sql(
                "PRAGMA table_info(projects)"
            ).fetchall()
        }
        if not have:
            return added
        for name, ddl in _LEGACY_COLUMNS:
            if name in have:
                continue
            try:
                conn.exec_driver_sql(
                    f"ALTER TABLE projects ADD COLUMN {name} {ddl}"
                )
                added.append(name)
            except Exception:
                # Another process may have added it between the read and here.
                pass
    return added


def _alembic_config(engine):
    """The Alembic config, pointed at the database this process is using."""
    try:
        from alembic.config import Config
    except Exception:
        return None
    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not ini.is_file():
        return None
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.attributes["connection"] = None
    return cfg


def _under_version_control(engine) -> bool:
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "sqlite":
                row = conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='alembic_version'"
                ).fetchone()
            else:
                row = conn.exec_driver_sql(
                    "SELECT to_regclass('alembic_version')"
                ).fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def _migrate(engine) -> None:
    """
    Bring the database under Alembic, then up to head.

    The ~50 live builds in `platform.db` must survive, so a database that
    already carries the baseline schema is *stamped* at the baseline rather than
    migrated to it — re-running the baseline would try to create tables that
    hold real data. Only after that does it get the revisions that came later.

    Both halves matter. Stamping alone leaves a database sitting at the
    baseline forever; `create_all` cannot help, because it creates indexes only
    for tables it creates, so the live database had none of the lookup indexes
    revision 0002 adds.
    """
    try:
        from alembic import command
    except Exception:
        return  # Alembic is optional at runtime; the schema is already correct.

    cfg = _alembic_config(engine)
    if cfg is None:
        return

    try:
        if not _under_version_control(engine):
            command.stamp(cfg, "0001_baseline")
            logger.info(
                "🗃️  Existing database stamped at the Alembic baseline"
            )
        command.upgrade(cfg, "head")
    except Exception as e:
        logger.warning(f"⚠️  Alembic migration skipped: {e}")


def initialize_db():
    """Create tables if they don't exist and bring an old schema up to date."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine()

    Base.metadata.create_all(engine)

    added = _reconcile_legacy_columns(engine)
    if added:
        logger.info(
            f"🗃️  Added {len(added)} legacy column(s) predating Alembic: "
            f"{', '.join(added)}"
        )

    _migrate(engine)


@contextmanager
def get_connection():
    """
    A raw DBAPI connection, kept for anything that still wants one.

    The platform's own code no longer uses this — every function below goes
    through SQLAlchemy — but it was public, and a caller holding a
    `sqlite3.Row`-shaped cursor should not break because the layer underneath
    changed.
    """
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _as_dict(obj) -> dict:
    """A mapped row as the plain dict every caller of this module expects."""
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


# ── Projects ──────────────────────────────────────────────────────────────────

def create_project(build_id: str, prompt: str) -> dict:
    now = _utcnow_iso()
    with session_scope() as s:
        s.add(Project(
            build_id=build_id, prompt=prompt, status="pending", created_at=now,
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
        ))
    return {
        "build_id":  build_id,
        "prompt":    prompt,
        "status":    "pending",
        "created_at": now,
    }


def get_project(build_id: str) -> dict | None:
    with session_scope() as s:
        row = s.get(Project, build_id)
        return _as_dict(row) if row else None


#: The columns `list_projects` has always returned. It is a strict subset of the
#: table — `prompt` aside, the heavy JSON blobs (verification, smoke_summary)
#: are deliberately not in the list view.
_LIST_COLUMNS = (
    "build_id", "prompt", "app_name", "app_type", "complexity", "status",
    "debug_score", "review_score", "test_score", "output_path",
    "created_at", "completed_at", "duration_seconds",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "completion_reason", "progress_percent", "tokens_by_model",
)


def list_projects(limit: int = 100, offset: int = 0) -> list[dict]:
    cols = [getattr(Project, name) for name in _LIST_COLUMNS]
    with session_scope() as s:
        rows = s.execute(
            select(*cols)
            .order_by(Project.created_at.desc())
            .limit(limit).offset(offset)
        ).all()
    return [dict(zip(_LIST_COLUMNS, r)) for r in rows]


def update_project(build_id: str, **fields) -> bool:
    if not fields:
        return False

    # The previous implementation interpolated caller-supplied keys directly
    # into the SET clause. Every real call passes a literal column name, so
    # rejecting anything else costs nothing and closes the hole.
    unknown = set(fields) - PROJECT_COLUMNS
    if unknown:
        raise ValueError(
            f"update_project received column(s) that do not exist: "
            f"{', '.join(sorted(unknown))}"
        )

    with session_scope() as s:
        result = s.execute(
            update(Project)
            .where(Project.build_id == build_id)
            .values(**fields)
        )
        return result.rowcount > 0


def delete_project(build_id: str) -> bool:
    with session_scope() as s:
        # ON DELETE CASCADE covers files/build_progress, but only when the
        # sqlite pragma is on — which `db/__init__` sets per connection. The
        # explicit deletes make the behaviour independent of that, because a
        # half-deleted build is worse than a slow one.
        s.execute(delete(ProjectFile).where(ProjectFile.build_id == build_id))
        s.execute(delete(BuildProgress).where(BuildProgress.build_id == build_id))
        result = s.execute(delete(Project).where(Project.build_id == build_id))
        return result.rowcount > 0


# ── Files ─────────────────────────────────────────────────────────────────────

def add_project_file(
    build_id: str, file_path: str, file_type: str | None = None
):
    with session_scope() as s:
        s.add(ProjectFile(
            build_id=build_id, file_path=file_path, file_type=file_type,
        ))


def get_project_files(build_id: str) -> list[dict]:
    cols = ("id", "build_id", "file_path", "file_type")
    with session_scope() as s:
        rows = s.execute(
            select(*[getattr(ProjectFile, c) for c in cols])
            .where(ProjectFile.build_id == build_id)
        ).all()
    return [dict(zip(cols, r)) for r in rows]


# ── Build progress ────────────────────────────────────────────────────────────

def add_build_step(
    build_id:  str,
    step:      int,
    step_name: str,
    status:    str,
    data:      str | None = None,
):
    with session_scope() as s:
        s.add(BuildProgress(
            build_id=build_id, step=step, step_name=step_name, status=status,
            timestamp=_utcnow_iso(), data=data,
        ))


def get_build_progress(build_id: str) -> list[dict]:
    cols = ("id", "build_id", "step", "step_name", "status", "timestamp", "data")
    with session_scope() as s:
        rows = s.execute(
            select(*[getattr(BuildProgress, c) for c in cols])
            .where(BuildProgress.build_id == build_id)
            .order_by(BuildProgress.step.asc())
        ).all()
    return [dict(zip(cols, r)) for r in rows]
