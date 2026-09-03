"""
Alembic environment for the platform database.

The URL is taken from `api_platform.db.current_url()` rather than from
alembic.ini, so `alembic upgrade head` and the running server can never disagree
about which database they are pointed at — DATABASE_URL, or the file DB_PATH
names, in both cases.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api_platform.db import current_url  # noqa: E402
from api_platform.db.models import Base  # noqa: E402

config = context.config

# `configure_logger` is alembic's documented escape hatch for an embedded run,
# and `api_platform/database.py` sets it to False. Even with
# `disable_existing_loggers=False`, `fileConfig` REPLACES the root handlers with
# alembic.ini's, so a host application loses its own logging the moment it runs a
# migration — which the server does at startup, before it does anything else.
if config.config_file_name is not None and config.attributes.get(
        "configure_logger", True):
    try:
        # `disable_existing_loggers=False` is load-bearing, and its absence cost
        # three sessions of build logs. `fileConfig` defaults to True, which
        # REPLACES the root handlers with alembic.ini's and marks every logger
        # already created as disabled. The server runs migrations at startup, so
        # from that moment on nothing from `agents.*` was ever emitted again:
        # five session logs in this repo stop mid-startup at exactly the line
        # after alembic runs, and two live rows were assessed with no log at all.
        #
        # It was diagnosed twice before this and both diagnoses were wrong —
        # first block buffering (disproved: the file was the same size after the
        # process exited), then the detached launch (disproved: a FileHandler the
        # server owned stopped at the same line). The tell was the timestamp.
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    except Exception:
        pass

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or current_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER a column in place; batch mode rewrites the table.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)

    if connectable is None:
        section = config.get_section(config.config_ini_section) or {}
        section["sqlalchemy.url"] = _url()
        connectable = engine_from_config(
            section, prefix="sqlalchemy.", poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
