"""
database.py — Observability data store.

Uses SQLite so there are zero external dependencies.
Every Devin session we create gets a row in the `tasks` table.
The dashboard reads from this table to show status, timing, and PR links.

"""

import sqlite3
import os
from datetime import datetime
from .config import DATABASE_PATH


def get_connection():
    """
    Opens a connection to the SQLite database.
    Creates the data directory if it doesn't exist yet
    (important for the first run inside Docker).
    """
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    # Return rows as dictionaries instead of plain tuples —
    # much easier to work with in the rest of the app.
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Creates the tasks table if it doesn't already exist.
    Called once at app startup.

    Each row represents one issue → Devin session → PR lifecycle.
    """
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,

                -- The GitHub issue that triggered this task
                issue_number    INTEGER NOT NULL,
                issue_title     TEXT NOT NULL,
                issue_url       TEXT NOT NULL,

                -- The Devin session created to fix this issue
                session_id      TEXT,
                session_url     TEXT,

                -- Lifecycle status: pending → running → completed / failed
                status          TEXT DEFAULT 'pending',

                -- The PR Devin opened (null until session completes)
                pr_url          TEXT,

                -- Timing — lets us calculate "time to PR" metrics
                created_at      TEXT DEFAULT (datetime('now')),
                started_at      TEXT,
                finished_at     TEXT,

                -- Any error message if the session failed
                error_message   TEXT
            )
        """)
        conn.commit()


def log_task(issue_number: int, issue_title: str, issue_url: str) -> int:
    """
    Creates a new task row when a webhook fires.
    Returns the new row's ID so we can update it later.
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO tasks (issue_number, issue_title, issue_url, status)
            VALUES (?, ?, ?, 'pending')
        """, (issue_number, issue_title, issue_url))
        conn.commit()
        return cursor.lastrowid


def update_task_session(task_id: int, session_id: str, session_url: str):
    """
    Once Devin accepts the task, record the session ID and URL.
    The session URL links directly into the Devin UI — great for the dashboard.
    """
    with get_connection() as conn:
        conn.execute("""
            UPDATE tasks
            SET session_id  = ?,
                session_url = ?,
                status      = 'running',
                started_at  = datetime('now')
            WHERE id = ?
        """, (session_id, session_url, task_id))
        conn.commit()


def update_task_completed(task_id: int, pr_url: str):
    """
    Mark a task as successfully completed when Devin opens a PR.
    """
    with get_connection() as conn:
        conn.execute("""
            UPDATE tasks
            SET status      = 'completed',
                pr_url      = ?,
                finished_at = datetime('now')
            WHERE id = ?
        """, (pr_url, task_id))
        conn.commit()


def update_task_failed(task_id: int, error_message: str):
    """
    Mark a task as failed — either Devin errored or timed out.
    Recording failure is just as important as recording success
    for honest observability.
    """
    with get_connection() as conn:
        conn.execute("""
            UPDATE tasks
            SET status        = 'failed',
                finished_at   = datetime('now'),
                error_message = ?
            WHERE id = ?
        """, (error_message, task_id))
        conn.commit()


def get_all_tasks() -> list[dict]:
    """
    Returns all tasks ordered by most recent first.
    Used by the /api/tasks endpoint that the dashboard polls.
    """
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM tasks ORDER BY created_at DESC
        """).fetchall()
        return [dict(row) for row in rows]


def get_stats() -> dict:
    """
    Returns summary statistics for the dashboard header.
    Answers the VP of Engineering question at a glance.
    """
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'completed'"
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'failed'"
        ).fetchone()[0]
        running = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'running'"
        ).fetchone()[0]

        # Average time from task creation to PR — in minutes
        avg_time = conn.execute("""
            SELECT AVG(
                (julianday(finished_at) - julianday(created_at)) * 24 * 60
            )
            FROM tasks
            WHERE status = 'completed'
            AND finished_at IS NOT NULL
        """).fetchone()[0]

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "success_rate": round((completed / total * 100) if total > 0 else 0, 1),
            "avg_minutes_to_pr": round(avg_time, 1) if avg_time else None
        }
    
def get_running_tasks() -> list[dict]:
    """
    Returns all tasks currently in running or pending state.
    Used by the PR webhook handler to find which task a 
    new Devin PR belongs to.
    """
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM tasks 
            WHERE status IN ('running', 'pending')
            ORDER BY created_at DESC
        """).fetchall()
        return [dict(row) for row in rows]
