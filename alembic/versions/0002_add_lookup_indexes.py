"""Index the columns every status poll filters on.

The original schema declared no index at all. `get_build_progress` and
`get_project_files` both filter on `build_id` and are on the path the dashboard
polls; each was a full scan over every row of every build — 1,023 progress rows
and 1,164 file rows across 73 builds, on every poll.

This revision is also the first thing that could only have been done this way.
`Base.metadata.create_all()` creates indexes only for tables it creates, so the
live database — whose tables already existed — got none of them, and the old
`ALTER TABLE ... except OperationalError` block could not add an index at all.

Revision ID: 0002_indexes
Revises: 0001_baseline
Create Date: 2026-08-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_indexes"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


#: (index name, table, columns)
_INDEXES = [
    ("ix_files_build_id", "files", ["build_id"]),
    ("ix_build_progress_build_id", "build_progress", ["build_id"]),
    ("ix_projects_created_at", "projects", ["created_at"]),
]


def _existing(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    # A database created by `create_all` already has these; one that predates
    # this revision does not. Both are stamped at the baseline, so the revision
    # has to be idempotent rather than assume which it is looking at.
    bind = op.get_bind()
    for name, table, cols in _INDEXES:
        if name in _existing(bind, table):
            continue
        op.create_index(name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    for name, table, _cols in _INDEXES:
        if name in _existing(bind, table):
            op.drop_index(name, table_name=table)
