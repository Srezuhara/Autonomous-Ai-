"""Baseline: the schema as it stood at the end of Phase 23.

This revision describes what `platform.db` already contains — the Phase 14
tables plus every column that arrived afterwards through the hand-rolled
`ALTER TABLE ... except OperationalError` block.

It exists to be **stamped**, not run, on any database that predates Alembic:
the ~50 live builds must survive, and re-creating their tables would destroy
them. `initialize_db()` reconciles a legacy database up to this schema and then
stamps it here. Only a genuinely empty database ever runs the upgrade.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("build_id", sa.String(), primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("app_name", sa.String()),
        sa.Column("app_type", sa.String()),
        sa.Column("complexity", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("debug_score", sa.String()),
        sa.Column("review_score", sa.Float()),
        sa.Column("test_score", sa.String()),
        sa.Column("output_path", sa.String()),
        # ISO-8601 strings, not DateTime — see api_platform/db/models.py.
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String()),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), server_default="0"),
        sa.Column("total_tokens", sa.Integer(), server_default="0"),
        sa.Column("completion_reason", sa.Text()),
        sa.Column("progress_percent", sa.Float()),
        sa.Column("tokens_by_model", sa.Text()),
        sa.Column("smoke_summary", sa.Text()),
        sa.Column("verification", sa.Text()),
        sa.Column("build_shape", sa.String()),
    )
    op.create_index("ix_projects_created_at", "projects", ["created_at"])

    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("build_id", sa.String(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String()),
        sa.ForeignKeyConstraint(
            ["build_id"], ["projects.build_id"], ondelete="CASCADE",
        ),
    )
    op.create_index("ix_files_build_id", "files", ["build_id"])

    op.create_table(
        "build_progress",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("build_id", sa.String(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("timestamp", sa.String(), nullable=False),
        sa.Column("data", sa.Text()),
        sa.ForeignKeyConstraint(
            ["build_id"], ["projects.build_id"], ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_build_progress_build_id", "build_progress", ["build_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_build_progress_build_id", table_name="build_progress")
    op.drop_table("build_progress")
    op.drop_index("ix_files_build_id", table_name="files")
    op.drop_table("files")
    op.drop_index("ix_projects_created_at", table_name="projects")
    op.drop_table("projects")
