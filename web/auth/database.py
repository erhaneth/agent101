# web/auth/database.py

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _db_path() -> Path:
    return Path(os.getenv("AUTH_DB_PATH", str(PROJECT_ROOT / "data" / "factcrafter.db")))


def _database_url() -> str:
    return os.getenv("AUTH_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()


def _is_postgres() -> bool:
    return _database_url().startswith(("postgres://", "postgresql://"))


@dataclass
class User:
    id: str
    email: str
    name: str
    picture: Optional[str]
    google_sub: Optional[str]
    created_at: str

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
            "created_at": self.created_at,
        }


def _connect() -> sqlite3.Connection:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_postgres() -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(_database_url(), row_factory=dict_row)


def _placeholder() -> str:
    return "%s" if _is_postgres() else "?"


def _connection() -> Any:
    return _connect_postgres() if _is_postgres() else _connect()


def init_db() -> None:
    with _connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                picture TEXT,
                google_sub TEXT UNIQUE,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_user_by_id(user_id: str) -> Optional[User]:
    with _connection() as conn:
        row = conn.execute(f"SELECT * FROM users WHERE id = {_placeholder()}", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_google_sub(google_sub: str) -> Optional[User]:
    with _connection() as conn:
        row = conn.execute(
            f"SELECT * FROM users WHERE google_sub = {_placeholder()}",
            (google_sub,),
        ).fetchone()
    return _row_to_user(row) if row else None


def upsert_google_user(*, google_sub: str, email: str, name: str, picture: str | None) -> User:
    existing = get_user_by_google_sub(google_sub)
    if existing:
        with _connection() as conn:
            conn.execute(
                f"""
                UPDATE users
                SET email = {_placeholder()}, name = {_placeholder()}, picture = {_placeholder()}
                WHERE id = {_placeholder()}
                """,
                (email, name, picture, existing.id),
            )
            conn.commit()
        return User(
            id=existing.id,
            email=email,
            name=name,
            picture=picture,
            google_sub=google_sub,
            created_at=existing.created_at,
        )

    user_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    ph = _placeholder()
    with _connection() as conn:
        conn.execute(
            f"""
            INSERT INTO users (id, email, name, picture, google_sub, created_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """,
            (user_id, email, name, picture, google_sub, created_at),
        )
        conn.commit()
    return User(
        id=user_id,
        email=email,
        name=name,
        picture=picture,
        google_sub=google_sub,
        created_at=created_at,
    )


def ensure_dev_user(user_id: str, email: str, name: str) -> User:
    existing = get_user_by_id(user_id)
    if existing:
        return existing
    created_at = datetime.now(timezone.utc).isoformat()
    ph = _placeholder()
    with _connection() as conn:
        if _is_postgres():
            conn.execute(
                f"""
                INSERT INTO users (id, email, name, picture, google_sub, created_at)
                VALUES ({ph}, {ph}, {ph}, NULL, NULL, {ph})
                ON CONFLICT(id) DO NOTHING
                """,
                (user_id, email, name, created_at),
            )
        else:
            conn.execute(
                f"""
                INSERT OR IGNORE INTO users (id, email, name, picture, google_sub, created_at)
                VALUES ({ph}, {ph}, {ph}, NULL, NULL, {ph})
                """,
                (user_id, email, name, created_at),
            )
        conn.commit()
    return get_user_by_id(user_id) or User(
        id=user_id,
        email=email,
        name=name,
        picture=None,
        google_sub=None,
        created_at=created_at,
    )


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        picture=row["picture"],
        google_sub=row["google_sub"],
        created_at=row["created_at"],
    )


init_db()
