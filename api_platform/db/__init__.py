"""
Engine and session management for the platform database (Phase B1).

Two constraints shaped this file, and both are easy to break by accident.

**The engine must resolve lazily.** `test_phase17`, `test_phase21` and
`test_phase23` all reassign `api_platform.database.DB_PATH` to a temporary file
and expect the next call to read and write there. An engine created at import
time would ignore that and quietly keep using the real `platform.db` — the
tests would still pass while writing to the live database, which is the worst
of both outcomes. So the URL is recomputed on every call and engines are cached
per-URL.

**Postgres is opt-in, and today's workflow is unchanged.** `DATABASE_URL`
overrides everything; with it unset the URL is derived from the current
`DB_PATH`, exactly the file the platform has always used.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from api_platform.db.models import (  # noqa: F401  (re-exported)
    Base, BuildProgress, Project, ProjectFile, PROJECT_COLUMNS,
)

logger = logging.getLogger(__name__)

_engines: dict[str, Engine] = {}
_sessionmakers: dict[str, sessionmaker] = {}
_lock = threading.Lock()

#: Sized against `JobRunner.max_workers` (3). Each worker drives one build and
#: a build touches the database on every step boundary; the pool exists so those
#: three do not serialise behind a single connection.
DEFAULT_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "3"))
DEFAULT_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "2"))


def current_url() -> str:
    """
    The database URL to use right now.

    `DATABASE_URL` wins. Otherwise it is derived from the *current* value of
    `api_platform.database.DB_PATH`, read at call time so the test seam and any
    runtime reassignment keep working.
    """
    explicit = os.getenv("DATABASE_URL", "").strip()
    if explicit:
        # ":memory:" is the shorthand generated projects use; accept it here too
        # rather than producing a URL SQLAlchemy cannot parse.
        if explicit == ":memory:":
            return "sqlite://"
        return explicit

    from api_platform import database as _db  # circular by design; see docstring
    return "sqlite:///" + str(Path(_db.DB_PATH).resolve()).replace("\\", "/")


def get_engine(url: str | None = None) -> Engine:
    """A cached engine for `url`, created on first use."""
    url = url or current_url()
    with _lock:
        engine = _engines.get(url)
        if engine is not None:
            return engine

        parsed = make_url(url)
        kwargs: dict = {"future": True, "pool_pre_ping": True}

        if parsed.get_backend_name() == "sqlite":
            # The platform writes from the request thread and from three worker
            # threads, so the connection cannot be pinned to its creator.
            kwargs["connect_args"] = {"check_same_thread": False}
            if parsed.database and parsed.database != ":memory:":
                Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
                # NullPool, deliberately: connect per operation and close after,
                # exactly the lifecycle the raw-sqlite3 layer had.
                #
                # A pool holds the file open between calls, and on Windows an
                # open handle makes the file undeletable — three test suites
                # point DB_PATH at a temp database and then delete it, and they
                # got PermissionError [WinError 32] the moment this pooled.
                # SQLite gains nothing from pooling anyway: there is no
                # handshake to amortise, and concurrent writers serialise on the
                # database lock regardless of how many connections exist.
                from sqlalchemy.pool import NullPool
                kwargs["poolclass"] = NullPool
            else:
                # An in-memory SQLite database is per-connection; pooling it
                # normally would hand each caller a different, empty database.
                from sqlalchemy.pool import StaticPool
                kwargs["poolclass"] = StaticPool
        else:
            # Where a real connection pool earns its keep. Sized against
            # JobRunner.max_workers (3): each worker drives one build and a
            # build touches the database at every step boundary.
            kwargs["pool_size"] = DEFAULT_POOL_SIZE
            kwargs["max_overflow"] = DEFAULT_MAX_OVERFLOW

        engine = create_engine(url, **kwargs)

        if parsed.get_backend_name() == "sqlite":
            @event.listens_for(engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):
                # WAL and foreign_keys were set by the old raw-sqlite3 layer on
                # every connection. Losing them here would silently drop the
                # ON DELETE CASCADE the schema relies on.
                cur = dbapi_conn.cursor()
                try:
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.execute("PRAGMA foreign_keys=ON")
                finally:
                    cur.close()

        _engines[url] = engine
        return engine


def get_sessionmaker(url: str | None = None) -> sessionmaker:
    url = url or current_url()
    with _lock:
        maker = _sessionmakers.get(url)
    if maker is None:
        maker = sessionmaker(
            bind=get_engine(url), expire_on_commit=False, future=True,
        )
        with _lock:
            _sessionmakers[url] = maker
    return maker


def session_scope(url: str | None = None):
    """A transactional session context manager."""
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        session = get_sessionmaker(url)()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _scope()


def dispose_all() -> None:
    """Drop every cached engine. Tests that swap DB_PATH around use this."""
    with _lock:
        engines = list(_engines.values())
        _engines.clear()
        _sessionmakers.clear()
    for engine in engines:
        try:
            engine.dispose()
        except Exception:
            pass
