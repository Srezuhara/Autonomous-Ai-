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

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
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
