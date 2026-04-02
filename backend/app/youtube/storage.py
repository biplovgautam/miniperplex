from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from app.core.config import settings

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None

_DB_PATH = Path(settings.youtube_db_path)
logger = logging.getLogger(__name__)


def _ensure_db_dir() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _using_postgres() -> bool:
    return bool(settings.youtube_db_url)


def _get_sqlite_connection() -> sqlite3.Connection:
    _ensure_db_dir()
    conn = sqlite3.connect(_DB_PATH.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _get_postgres_connection():
    if psycopg is None:
        raise RuntimeError("psycopg is not installed")
    return psycopg.connect(settings.youtube_db_url, row_factory=dict_row)


def check_db_connection() -> bool:
    if _using_postgres():
        try:
            with _get_postgres_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            logger.info("YouTube metadata database connected (Postgres).")
            return True
        except Exception as exc:
            logger.warning("YouTube metadata database connection failed: %s", exc)
            return False

    try:
        init_db()
        logger.info("YouTube metadata database ready (SQLite).")
        return True
    except Exception as exc:
        logger.warning("YouTube metadata SQLite initialization failed: %s", exc)
        return False


def init_db() -> None:
    if _using_postgres():
        with _get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS videos (
                        video_id TEXT PRIMARY KEY,
                        title TEXT,
                        channel TEXT,
                        published_at TIMESTAMP,
                        url TEXT,
                        transcript TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )
        return

    with _get_sqlite_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                title TEXT,
                channel TEXT,
                published_at TEXT,
                url TEXT,
                transcript TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def video_exists(video_id: str) -> bool:
    if _using_postgres():
        with _get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM videos WHERE video_id = %s LIMIT 1", (video_id,)
                )
                return cursor.fetchone() is not None

    with _get_sqlite_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM videos WHERE video_id = ? LIMIT 1", (video_id,)
        )
        return cursor.fetchone() is not None


def get_video(video_id: str) -> dict[str, Any] | None:
    if _using_postgres():
        with _get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM videos WHERE video_id = %s", (video_id,))
                row = cursor.fetchone()
                return dict(row) if row else None

    with _get_sqlite_connection() as conn:
        cursor = conn.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def insert_video(
    video_id: str,
    title: str,
    channel: str,
    published_at: str | None,
    url: str,
    transcript: str,
) -> None:
    if _using_postgres():
        with _get_postgres_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO videos (
                        video_id, title, channel, published_at, url, transcript
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (video_id)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        channel = EXCLUDED.channel,
                        published_at = EXCLUDED.published_at,
                        url = EXCLUDED.url,
                        transcript = EXCLUDED.transcript
                    """,
                    (video_id, title, channel, published_at, url, transcript),
                )
        return

    with _get_sqlite_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO videos (
                video_id, title, channel, published_at, url, transcript
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (video_id, title, channel, published_at, url, transcript),
        )
        conn.commit()
