from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def artifact_database_url() -> str:
    return os.getenv("ARTIFACT_DATABASE_URL", "").strip()


def artifact_db_path() -> str:
    return os.getenv("ARTIFACT_DB_PATH", "").strip()


def artifact_store_enabled() -> bool:
    return bool(artifact_database_url() or artifact_db_path())


class ArtifactStore:
    def __init__(self, path: str | Path | None = None, *, database_url: str | None = None) -> None:
        self.database_url = (
            database_url if database_url is not None else artifact_database_url()
        ).strip()
        configured_path = path if path is not None else artifact_db_path()
        self.path = Path(configured_path) if configured_path else PROJECT_ROOT / "data" / "artifacts.db"
        self.init_db()

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))

    def _connect_sqlite(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_postgres(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _connection(self) -> Any:
        return self._connect_postgres() if self.is_postgres else self._connect_sqlite()

    def _placeholder(self) -> str:
        return "%s" if self.is_postgres else "?"

    def init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_artifacts (
                    user_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, run_id, filename)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_artifacts_user_run ON run_artifacts (user_id, run_id)"
            )
            conn.commit()

    def put_text(
        self,
        *,
        user_id: str | None,
        run_id: str,
        filename: str,
        content: str,
        content_type: str,
    ) -> None:
        uid = user_id or ""
        created_at = datetime.now(timezone.utc).isoformat()
        ph = self._placeholder()
        with self._connection() as conn:
            if self.is_postgres:
                conn.execute(
                    f"""
                    INSERT INTO run_artifacts (user_id, run_id, filename, content, content_type, created_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT(user_id, run_id, filename) DO UPDATE SET
                        content = excluded.content,
                        content_type = excluded.content_type,
                        created_at = excluded.created_at
                    """,
                    (uid, run_id, filename, content, content_type, created_at),
                )
            else:
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO run_artifacts
                        (user_id, run_id, filename, content, content_type, created_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    """,
                    (uid, run_id, filename, content, content_type, created_at),
                )
            conn.commit()

    def get_text(self, *, user_id: str | None, run_id: str, filename: str) -> str | None:
        uid = user_id or ""
        ph = self._placeholder()
        with self._connection() as conn:
            row = conn.execute(
                f"""
                SELECT content FROM run_artifacts
                WHERE user_id = {ph} AND run_id = {ph} AND filename = {ph}
                """,
                (uid, run_id, filename),
            ).fetchone()
        return row["content"] if row else None

    def get_json(self, *, user_id: str | None, run_id: str, filename: str) -> Any:
        content = self.get_text(user_id=user_id, run_id=run_id, filename=filename)
        if content is None:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def list_run_summaries(self, *, user_id: str | None, limit: int = 50) -> list[dict]:
        uid = user_id or ""
        ph = self._placeholder()
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT run_id, content FROM run_artifacts
                WHERE user_id = {ph} AND filename = 'summary.json'
                ORDER BY run_id DESC
                LIMIT {ph}
                """,
                (uid, limit),
            ).fetchall()

        summaries = []
        for row in rows:
            try:
                summary = json.loads(row["content"])
            except json.JSONDecodeError:
                continue
            summary["run_id"] = row["run_id"]
            summaries.append(summary)
        return summaries


def configured_artifact_store() -> ArtifactStore | None:
    if not artifact_store_enabled():
        return None
    return ArtifactStore()
