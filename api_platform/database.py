"""
Phase 14 database additions:
  - get_project_files(build_id) → list of file dicts
  - get_build_progress(build_id) → list of progress dicts
  - delete_project(build_id)    → remove row (cascade handled by FK)

These are ADDITIONS to the existing database.py.
Paste these functions into api_platform/database.py.
"""

# ──────────────────────────────────────────────────────────────────────────────
# ADD to api_platform/database.py
# ──────────────────────────────────────────────────────────────────────────────

# def get_project_files(build_id: str) -> list[dict]:
#     """Return all files associated with a build."""
#     with get_connection() as conn:
#         rows = conn.execute(
#             "SELECT id, build_id, file_path, file_type FROM files WHERE build_id = ?",
#             (build_id,),
#         ).fetchall()
#         return [dict(r) for r in rows]
#
#
# def get_build_progress(build_id: str) -> list[dict]:
#     """Return all build progress steps ordered by step number."""
#     with get_connection() as conn:
#         rows = conn.execute(
#             """SELECT id, build_id, step, step_name, status, timestamp, data
#                FROM build_progress WHERE build_id = ? ORDER BY step ASC""",
#             (build_id,),
#         ).fetchall()
#         return [dict(r) for r in rows]
#
#
# def delete_project(build_id: str) -> bool:
#     """Delete a project and all related records (cascade)."""
#     with get_connection() as conn:
#         result = conn.execute(
#             "DELETE FROM projects WHERE build_id = ?", (build_id,)
#         )
#         conn.commit()
#         return result.rowcount > 0
#
#
# def list_projects(limit: int = 100, offset: int = 0) -> list[dict]:
#     """List projects, newest first."""
#     with get_connection() as conn:
#         rows = conn.execute(
#             """SELECT build_id, prompt, app_name, app_type, complexity, status,
#                       debug_score, review_score, test_score, output_path,
#                       created_at, completed_at, duration_seconds
#                FROM projects ORDER BY created_at DESC LIMIT ? OFFSET ?""",
#             (limit, offset),
#         ).fetchall()
#         return [dict(r) for r in rows]

# ──────────────────────────────────────────────────────────────────────────────
# FULL STANDALONE database.py (Phase 14 compatible) — use this if replacing:
# ──────────────────────────────────────────────────────────────────────────────

"""
api_platform/database.py  (Phase 14 - complete version)
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    from config import OUTPUT_DIR
except ImportError:
    OUTPUT_DIR = "generated_projects"

DB_PATH = Path(OUTPUT_DIR) / "platform.db"


def initialize_db():
    """Create tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS projects (
                build_id         TEXT PRIMARY KEY,
                prompt           TEXT NOT NULL,
                app_name         TEXT,
                app_type         TEXT,
                complexity       TEXT,
                status           TEXT NOT NULL,
                debug_score      TEXT,
                review_score     REAL,
                test_score       TEXT,
                output_path      TEXT,
                created_at       TIMESTAMP NOT NULL,
                completed_at     TIMESTAMP,
                duration_seconds REAL
            );

            CREATE TABLE IF NOT EXISTS files (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                build_id  TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT,
                FOREIGN KEY (build_id) REFERENCES projects(build_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS build_progress (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                build_id  TEXT NOT NULL,
                step      INTEGER NOT NULL,
                step_name TEXT NOT NULL,
                status    TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                data      TEXT,
                FOREIGN KEY (build_id) REFERENCES projects(build_id) ON DELETE CASCADE
            );
        """)
        conn.commit()


@contextmanager
def get_connection():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


# ── Projects ──────────────────────────────────────────────────────────────────

def create_project(build_id: str, prompt: str) -> dict:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO projects (build_id, prompt, status, created_at)
               VALUES (?, ?, 'pending', ?)""",
            (build_id, prompt, now),
        )
        conn.commit()
    return {"build_id": build_id, "prompt": prompt, "status": "pending", "created_at": now}


def get_project(build_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE build_id = ?", (build_id,)
        ).fetchone()
        return dict(row) if row else None


def list_projects(limit: int = 100, offset: int = 0) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT build_id, prompt, app_name, app_type, complexity, status,
                      debug_score, review_score, test_score, output_path,
                      created_at, completed_at, duration_seconds
               FROM projects ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def update_project(build_id: str, **fields) -> bool:
    if not fields:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [build_id]
    with get_connection() as conn:
        result = conn.execute(
            f"UPDATE projects SET {set_clause} WHERE build_id = ?", values
        )
        conn.commit()
        return result.rowcount > 0


def delete_project(build_id: str) -> bool:
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM projects WHERE build_id = ?", (build_id,)
        )
        conn.commit()
        return result.rowcount > 0


# ── Files ─────────────────────────────────────────────────────────────────────

def add_project_file(build_id: str, file_path: str, file_type: str | None = None):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO files (build_id, file_path, file_type) VALUES (?, ?, ?)",
            (build_id, file_path, file_type),
        )
        conn.commit()


def get_project_files(build_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, build_id, file_path, file_type FROM files WHERE build_id = ?",
            (build_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Build progress ────────────────────────────────────────────────────────────

def add_build_step(build_id: str, step: int, step_name: str, status: str, data: str | None = None):
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO build_progress (build_id, step, step_name, status, timestamp, data)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (build_id, step, step_name, status, now, data),
        )
        conn.commit()


def get_build_progress(build_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, build_id, step, step_name, status, timestamp, data
               FROM build_progress WHERE build_id = ? ORDER BY step ASC""",
            (build_id,),
        ).fetchall()
        return [dict(r) for r in rows]
