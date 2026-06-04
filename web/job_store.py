from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def default_job_db_path() -> Path:
    return Path(os.getenv("JOB_DB_PATH", str(PROJECT_ROOT / "data" / "factcrafter.db")))


def default_job_database_url() -> str:
    return os.getenv("JOB_DATABASE_URL", "").strip()


class JobStore:
    def __init__(self, path: str | Path | None = None, *, database_url: str | None = None) -> None:
        self.path = Path(path) if path is not None else default_job_db_path()
        self.database_url = (database_url if database_url is not None else default_job_database_url()).strip()
        self.init_db()

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_postgres(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row)

    def init_db(self) -> None:
        if self.is_postgres:
            with self._connect_postgres() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        goal TEXT NOT NULL,
                        status TEXT NOT NULL,
                        current_step TEXT,
                        completed_steps_json TEXT NOT NULL,
                        events_json TEXT NOT NULL,
                        state_json TEXT NOT NULL,
                        run_id TEXT,
                        artifact_dir TEXT,
                        error TEXT,
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        locked_by TEXT,
                        locked_at TEXT,
                        last_heartbeat_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                self._ensure_postgres_columns(conn)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_updated ON jobs (user_id, updated_at)")
                conn.commit()
            return

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step TEXT,
                    completed_steps_json TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    run_id TEXT,
                    artifact_dir TEXT,
                    error TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    locked_by TEXT,
                    locked_at TEXT,
                    last_heartbeat_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_sqlite_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_updated ON jobs (user_id, updated_at)")
            conn.commit()

    def _ensure_sqlite_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        columns = {
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
            "locked_by": "TEXT",
            "locked_at": "TEXT",
            "last_heartbeat_at": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")

    def _ensure_postgres_columns(self, conn: Any) -> None:
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cancel_requested INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locked_by TEXT")
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locked_at TEXT")
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_heartbeat_at TEXT")

    def upsert(self, record: dict) -> None:
        params = (
            record["id"],
            record["user_id"],
            record["goal"],
            record["status"],
            record.get("current_step"),
            _json(record.get("completed_steps", [])),
            _json(record.get("events", [])),
            _json(record.get("state", {})),
            record.get("run_id"),
            record.get("artifact_dir"),
            record.get("error"),
            int(record.get("attempt_count", 0) or 0),
            1 if record.get("cancel_requested") else 0,
            record.get("locked_by"),
            record.get("locked_at"),
            record.get("last_heartbeat_at"),
            record["created_at"],
            record["updated_at"],
        )
        if self.is_postgres:
            with self._connect_postgres() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        id, user_id, goal, status, current_step, completed_steps_json,
                        events_json, state_json, run_id, artifact_dir, error, attempt_count,
                        cancel_requested, locked_by, locked_at, last_heartbeat_at, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET
                        user_id = excluded.user_id,
                        goal = excluded.goal,
                        status = excluded.status,
                        current_step = excluded.current_step,
                        completed_steps_json = excluded.completed_steps_json,
                        events_json = excluded.events_json,
                        state_json = excluded.state_json,
                        run_id = excluded.run_id,
                        artifact_dir = excluded.artifact_dir,
                        error = excluded.error,
                        attempt_count = excluded.attempt_count,
                        cancel_requested = excluded.cancel_requested,
                        locked_by = excluded.locked_by,
                        locked_at = excluded.locked_at,
                        last_heartbeat_at = excluded.last_heartbeat_at,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at
                    """,
                    params,
                )
                conn.commit()
            return

        with self._connect() as conn:
            conn.execute(
                """
                    INSERT INTO jobs (
                        id, user_id, goal, status, current_step, completed_steps_json,
                        events_json, state_json, run_id, artifact_dir, error, attempt_count,
                        cancel_requested, locked_by, locked_at, last_heartbeat_at, created_at, updated_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    user_id = excluded.user_id,
                    goal = excluded.goal,
                    status = excluded.status,
                    current_step = excluded.current_step,
                    completed_steps_json = excluded.completed_steps_json,
                    events_json = excluded.events_json,
                    state_json = excluded.state_json,
                    run_id = excluded.run_id,
                    artifact_dir = excluded.artifact_dir,
                    error = excluded.error,
                    attempt_count = excluded.attempt_count,
                    cancel_requested = excluded.cancel_requested,
                    locked_by = excluded.locked_by,
                    locked_at = excluded.locked_at,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                params,
            )
            conn.commit()

    def list(self, user_id: str | None = None, *, limit: int | None = None) -> list[dict]:
        query = "SELECT * FROM jobs"
        params: list[object] = []
        if user_id is not None:
            query += " WHERE user_id = %s" if self.is_postgres else " WHERE user_id = ?"
            params.append(user_id)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT %s" if self.is_postgres else " LIMIT ?"
            params.append(limit)

        if self.is_postgres:
            with self._connect_postgres() as conn:
                rows = conn.execute(query, params).fetchall()
            return [_row_to_record(row) for row in rows]

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_record(row) for row in rows]

    def get(self, job_id: str) -> dict | None:
        if self.is_postgres:
            with self._connect_postgres() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
            return _row_to_record(row) if row else None

        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_record(row) if row else None

    def load_all(self) -> list[dict]:
        return self.list()

    def claim_next_queued(self, *, worker_id: str | None = None, max_attempts: int = 3) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        worker = worker_id or f"worker-{uuid.uuid4()}"
        if self.is_postgres:
            with self._connect_postgres() as conn:
                with conn.transaction():
                    row = conn.execute(
                        """
                        SELECT * FROM jobs
                        WHERE status = 'queued' AND attempt_count < %s
                        ORDER BY created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                        """,
                        (max_attempts,),
                    ).fetchone()
                    if row is None:
                        return None
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'running',
                            attempt_count = attempt_count + 1,
                            cancel_requested = 0,
                            locked_by = %s,
                            locked_at = %s,
                            last_heartbeat_at = %s,
                            updated_at = %s
                        WHERE id = %s AND status = 'queued'
                        """,
                        (worker, now, now, now, row["id"]),
                    )
            return self.get(row["id"])

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued' AND attempt_count < ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (max_attempts,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None

            conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    attempt_count = attempt_count + 1,
                    cancel_requested = 0,
                    locked_by = ?,
                    locked_at = ?,
                    last_heartbeat_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (worker, now, now, now, row["id"]),
            )
            conn.commit()

        claimed = self.get(row["id"])
        return claimed

    def cancel_queued(
        self,
        job_id: str,
        user_id: str,
        *,
        event: dict,
        error: str,
    ) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        if self.is_postgres:
            with self._connect_postgres() as conn:
                with conn.transaction():
                    row = conn.execute(
                        """
                        SELECT * FROM jobs
                        WHERE id = %s AND user_id = %s
                        FOR UPDATE
                        """,
                        (job_id, user_id),
                    ).fetchone()
                    if row is None or row["status"] != "queued":
                        return None
                    events = list(_loads(row["events_json"], []))
                    events.append(event)
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'canceled',
                            current_step = NULL,
                            cancel_requested = 1,
                            events_json = %s,
                            error = %s,
                            locked_by = NULL,
                            locked_at = NULL,
                            last_heartbeat_at = NULL,
                            updated_at = %s
                        WHERE id = %s AND user_id = %s AND status = 'queued'
                        """,
                        (_json(events), error, now, job_id, user_id),
                    )
            return self.get(job_id)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE id = ? AND user_id = ?
                """,
                (job_id, user_id),
            ).fetchone()
            if row is None or row["status"] != "queued":
                conn.commit()
                return None
            events = list(_loads(row["events_json"], []))
            events.append(event)
            conn.execute(
                """
                UPDATE jobs
                SET status = 'canceled',
                    current_step = NULL,
                    cancel_requested = 1,
                    events_json = ?,
                    error = ?,
                    locked_by = NULL,
                    locked_at = NULL,
                    last_heartbeat_at = NULL,
                    updated_at = ?
                WHERE id = ? AND user_id = ? AND status = 'queued'
                """,
                (_json(events), error, now, job_id, user_id),
            )
            conn.commit()
        return self.get(job_id)

    def request_cancel(
        self,
        job_id: str,
        user_id: str,
        *,
        event: dict,
    ) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        active_statuses = ("running", "awaiting_review")
        if self.is_postgres:
            with self._connect_postgres() as conn:
                with conn.transaction():
                    row = conn.execute(
                        """
                        SELECT * FROM jobs
                        WHERE id = %s AND user_id = %s
                        FOR UPDATE
                        """,
                        (job_id, user_id),
                    ).fetchone()
                    if row is None or row["status"] not in active_statuses:
                        return None
                    events = list(_loads(row["events_json"], []))
                    events.append(event)
                    conn.execute(
                        """
                        UPDATE jobs
                        SET cancel_requested = 1,
                            events_json = %s,
                            updated_at = %s
                        WHERE id = %s AND user_id = %s
                          AND status IN ('running', 'awaiting_review')
                        """,
                        (_json(events), now, job_id, user_id),
                    )
            return self.get(job_id)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE id = ? AND user_id = ?
                """,
                (job_id, user_id),
            ).fetchone()
            if row is None or row["status"] not in active_statuses:
                conn.commit()
                return None
            events = list(_loads(row["events_json"], []))
            events.append(event)
            conn.execute(
                """
                UPDATE jobs
                SET cancel_requested = 1,
                    events_json = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                  AND status IN ('running', 'awaiting_review')
                """,
                (_json(events), now, job_id, user_id),
            )
            conn.commit()
        return self.get(job_id)

    def mark_canceled(
        self,
        job_id: str,
        *,
        event: dict,
        error: str,
    ) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        if self.is_postgres:
            with self._connect_postgres() as conn:
                with conn.transaction():
                    row = conn.execute(
                        "SELECT * FROM jobs WHERE id = %s FOR UPDATE",
                        (job_id,),
                    ).fetchone()
                    if row is None:
                        return None
                    events = list(_loads(row["events_json"], []))
                    events.append(event)
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'canceled',
                            cancel_requested = 1,
                            events_json = %s,
                            error = %s,
                            locked_by = NULL,
                            locked_at = NULL,
                            last_heartbeat_at = NULL,
                            updated_at = %s
                        WHERE id = %s
                        """,
                        (_json(events), error, now, job_id),
                    )
            return self.get(job_id)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                conn.commit()
                return None
            events = list(_loads(row["events_json"], []))
            events.append(event)
            conn.execute(
                """
                UPDATE jobs
                SET status = 'canceled',
                    cancel_requested = 1,
                    events_json = ?,
                    error = ?,
                    locked_by = NULL,
                    locked_at = NULL,
                    last_heartbeat_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (_json(events), error, now, job_id),
            )
            conn.commit()
        return self.get(job_id)

    def heartbeat(self, job_id: str, *, worker_id: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if self.is_postgres:
            query = "UPDATE jobs SET last_heartbeat_at = %s, updated_at = %s WHERE id = %s"
            params: tuple[object, ...] = (now, now, job_id)
            if worker_id:
                query += " AND locked_by = %s"
                params = (now, now, job_id, worker_id)
            with self._connect_postgres() as conn:
                conn.execute(query, params)
                conn.commit()
            return

        query = "UPDATE jobs SET last_heartbeat_at = ?, updated_at = ? WHERE id = ?"
        params = (now, now, job_id)
        if worker_id:
            query += " AND locked_by = ?"
            params = (now, now, job_id, worker_id)
        with self._connect() as conn:
            conn.execute(query, params)
            conn.commit()

    def recover_stale_running_jobs(
        self,
        *,
        stale_after_seconds: int = 900,
        max_attempts: int = 3,
    ) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        cutoff_iso = cutoff.isoformat()
        failed_reason = "Job exceeded retry limit after worker heartbeat expired."
        if self.is_postgres:
            with self._connect_postgres() as conn:
                with conn.transaction():
                    failed = conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'failed',
                            error = COALESCE(error, %s),
                            locked_by = NULL,
                            locked_at = NULL,
                            updated_at = %s
                        WHERE status = 'running'
                          AND attempt_count >= %s
                          AND COALESCE(last_heartbeat_at, updated_at) < %s
                        RETURNING id
                        """,
                        (failed_reason, datetime.now(timezone.utc).isoformat(), max_attempts, cutoff_iso),
                    ).fetchall()
                    retried = conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'queued',
                            error = NULL,
                            locked_by = NULL,
                            locked_at = NULL,
                            updated_at = %s
                        WHERE status = 'running'
                          AND attempt_count < %s
                          AND COALESCE(last_heartbeat_at, updated_at) < %s
                        RETURNING id
                        """,
                        (datetime.now(timezone.utc).isoformat(), max_attempts, cutoff_iso),
                    ).fetchall()
                return len(failed) + len(retried)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            failed_cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = COALESCE(error, ?),
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = ?
                WHERE status = 'running'
                  AND attempt_count >= ?
                  AND COALESCE(last_heartbeat_at, updated_at) < ?
                """,
                (failed_reason, datetime.now(timezone.utc).isoformat(), max_attempts, cutoff_iso),
            )
            retried_cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    error = NULL,
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = ?
                WHERE status = 'running'
                  AND attempt_count < ?
                  AND COALESCE(last_heartbeat_at, updated_at) < ?
                """,
                (datetime.now(timezone.utc).isoformat(), max_attempts, cutoff_iso),
            )
            conn.commit()
        return int(failed_cursor.rowcount or 0) + int(retried_cursor.rowcount or 0)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


def _loads(value: str, fallback: object) -> object:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row_to_record(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "goal": row["goal"],
        "status": row["status"],
        "current_step": row["current_step"],
        "completed_steps": _loads(row["completed_steps_json"], []),
        "events": _loads(row["events_json"], []),
        "state": _loads(row["state_json"], {}),
        "run_id": row["run_id"],
        "artifact_dir": row["artifact_dir"],
        "error": row["error"],
        "attempt_count": row["attempt_count"],
        "cancel_requested": bool(row["cancel_requested"]),
        "locked_by": row["locked_by"],
        "locked_at": row["locked_at"],
        "last_heartbeat_at": row["last_heartbeat_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
