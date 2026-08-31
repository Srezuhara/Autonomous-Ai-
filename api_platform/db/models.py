"""
SQLAlchemy models for the platform database (Phase B1).

These mirror the DDL `api_platform/database.py` has executed since Phase 14,
column for column, including every column that arrived later through the
hand-rolled `ALTER TABLE ... except OperationalError` block. That block is the
thing this replaces: it could add a column but never rename, drop, backfill or
re-type one, and it left no record of what a given database had been through.

One deliberate departure from what the DDL *says*.
---------------------------------------------------
`created_at`, `completed_at` and `timestamp` are declared TIMESTAMP in the
original DDL, but every writer stores `datetime.isoformat()` — a string — and
every reader, every route and the API's JSON serialisation treat them as
strings. SQLite is dynamically typed, so that has always worked.

Declaring them `DateTime` here would make SQLAlchemy parse them back into
`datetime` objects, silently changing the type every consumer receives from
`str` to `datetime`. That is a behaviour change wearing the costume of a schema
definition, and the seam this phase is built on ("reimplement the bodies, change
no call sites") would be broken by it. They are `String`, and the ISO strings
round-trip byte for byte.
"""

from __future__ import annotations

from sqlalchemy import (
    Column, Float, ForeignKey, Integer, String, Text, Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Project(Base):
    __tablename__ = "projects"

    build_id = Column(String, primary_key=True)
    prompt = Column(Text, nullable=False)
    app_name = Column(String)
    app_type = Column(String)
    complexity = Column(String)
    status = Column(String, nullable=False)
    debug_score = Column(String)
    review_score = Column(Float)
    test_score = Column(String)
    output_path = Column(String)
    # ISO-8601 strings — see the module docstring.
    created_at = Column(String, nullable=False)
    completed_at = Column(String)
    duration_seconds = Column(Float)

    # Phase 17
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    # Phase 21: why a build ended as done_with_context, and how far it got.
    completion_reason = Column(Text)
    progress_percent = Column(Float)

    # Phase 23: JSON {model: tokens}. The totals above cannot say which model's
    # daily quota a build spent, which is what the token ledger needs to rebuild
    # itself after a restart instead of estimating.
    tokens_by_model = Column(Text)

    # Whether the thing that was built actually works, and how we know.
    smoke_summary = Column(Text)
    # JSON list of VerificationOutcome dicts. A NOT_RUN entry here is the record
    # that a build went unverified, which used to be indistinguishable from one
    # that passed.
    verification = Column(Text)
    build_shape = Column(String)

    files = relationship(
        "ProjectFile", back_populates="project",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    progress = relationship(
        "BuildProgress", back_populates="project",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class ProjectFile(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    build_id = Column(
        String, ForeignKey("projects.build_id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path = Column(Text, nullable=False)
    file_type = Column(String)

    project = relationship("Project", back_populates="files")


class BuildProgress(Base):
    __tablename__ = "build_progress"

    id = Column(Integer, primary_key=True, autoincrement=True)
    build_id = Column(
        String, ForeignKey("projects.build_id", ondelete="CASCADE"),
        nullable=False,
    )
    step = Column(Integer, nullable=False)
    step_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    timestamp = Column(String, nullable=False)
    data = Column(Text)

    project = relationship("Project", back_populates="progress")


# `get_build_progress` and `get_project_files` both filter on build_id and are
# on the status path every poll hits. The original schema declared no index at
# all, so both were full scans over every row of every build.
Index("ix_files_build_id", ProjectFile.build_id)
Index("ix_build_progress_build_id", BuildProgress.build_id)

# The project list is always ordered by created_at DESC.
Index("ix_projects_created_at", Project.created_at)


#: Column names a caller may set through `update_project(**fields)`. The old
#: implementation interpolated caller-supplied keys straight into an UPDATE
#: statement; restricting to the mapped columns closes that off without
#: changing any legitimate call.
PROJECT_COLUMNS = frozenset(c.name for c in Project.__table__.columns)
