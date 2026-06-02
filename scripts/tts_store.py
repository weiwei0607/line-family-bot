"""
TTS audio + cron + dedup persistence for line-family-bot.
Supports SQLite (local/dev) and PostgreSQL (Render production).
from __future__ import annotations
"""

import contextlib
import logging
import os
import threading
from datetime import datetime, timedelta

USE_PG = bool(os.environ.get("DATABASE_URL"))
DB_PATH = os.environ.get("TTS_DB_PATH", "./data/tts_store.db")
PH = "%s" if USE_PG else "?"
_logger = logging.getLogger(__name__)

if USE_PG:
    import psycopg2
else:
    import sqlite3

_write_lock = threading.Lock()


# ─── Connection helpers ───────────────────────────────────


@contextlib.contextmanager
def _transaction():
    """Yield a cursor; commit on success, rollback on exception."""
    if USE_PG:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
    else:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Schema init ──────────────────────────────────────────


def _init():
    blob_type = "BYTEA" if USE_PG else "BLOB"
    with _transaction() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS tts_audio (
                filename TEXT PRIMARY KEY,
                audio_blob {blob_type},
                mime_type TEXT DEFAULT 'audio/mpeg',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cron_log (
                task_name TEXT PRIMARY KEY,
                run_date TEXT,
                run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_dedup (
                dedup_key TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT,
                expires_at TIMESTAMP
            )
            """
        )
        if not USE_PG:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kv_expires ON kv(expires_at)")
        else:
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_kv_expires'
                    ) THEN
                        CREATE INDEX idx_kv_expires ON kv(expires_at);
                    END IF;
                END
                $$;
                """
            )


_init()


# ─── TTS ──────────────────────────────────────────────────


def save_tts_audio(filename: str, audio_bytes: bytes, mime_type: str = "audio/mpeg") -> None:
    try:
        with _write_lock, _transaction() as cur:
            cur.execute(
                f"""
                INSERT INTO tts_audio (filename, audio_blob, mime_type) VALUES ({PH}, {PH}, {PH})
                ON CONFLICT(filename) DO UPDATE SET
                    audio_blob=EXCLUDED.audio_blob,
                    mime_type=EXCLUDED.mime_type,
                    created_at=CURRENT_TIMESTAMP
                """,
                (filename, audio_bytes, mime_type),
            )
            # Keep only last 2 days (48h) of TTS audio
            cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
            cur.execute(
                f"DELETE FROM tts_audio WHERE created_at < {PH}",
                (cutoff,),
            )
            _maybe_cleanup(cur)
    except Exception as exc:
        _logger.warning("tts_store save error: %s", exc)


def get_tts_audio(filename: str) -> tuple[bytes, str] | None:
    try:
        with _transaction() as cur:
            cur.execute(
                f"SELECT audio_blob, mime_type FROM tts_audio WHERE filename = {PH}",
                (filename,),
            )
            row = cur.fetchone()
            if row:
                return row[0], row[1]
    except Exception as exc:
        _logger.warning("tts_store get error: %s", exc)
    return None


def delete_tts_audio(filename: str) -> None:
    try:
        with _write_lock, _transaction() as cur:
            cur.execute(f"DELETE FROM tts_audio WHERE filename = {PH}", (filename,))
    except Exception as exc:
        _logger.warning("tts_store delete error: %s", exc)


def _maybe_cleanup(cur):
    """Cleanup old cron_log (>90d) and expired webhook_dedup entries."""
    import random
    if random.random() > 0.01:
        return
    try:
        cutoff_cron = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        cur.execute(f"DELETE FROM cron_log WHERE run_date <= {PH}", (cutoff_cron,))
        cutoff_webhook = (datetime.now() - timedelta(hours=1)).isoformat()
        cur.execute(f"DELETE FROM webhook_dedup WHERE created_at <= {PH}", (cutoff_webhook,))
    except Exception as exc:
        _logger.warning("tts_store cleanup error: %s", exc)


# ─── Cron idempotency ─────────────────────────────────────


def cron_is_done(task_name: str, date_str: str | None = None) -> bool:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        with _transaction() as cur:
            cur.execute(
                f"SELECT 1 FROM cron_log WHERE task_name = {PH} AND run_date = {PH}",
                (task_name, date_str),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        _logger.warning("cron_is_done error: %s", exc)
        return False


def cron_mark_done(task_name: str, date_str: str | None = None) -> None:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        with _write_lock, _transaction() as cur:
            cur.execute(
                f"""
                INSERT INTO cron_log (task_name, run_date) VALUES ({PH}, {PH})
                ON CONFLICT(task_name) DO UPDATE SET
                    run_date=EXCLUDED.run_date,
                    run_at=CURRENT_TIMESTAMP
                """,
                (task_name, date_str),
            )
            _maybe_cleanup(cur)
    except Exception as exc:
        _logger.warning("cron_mark_done error: %s", exc)


def cron_try_mark_done(task_name: str, date_str: str | None = None) -> bool:
    """Atomically check-and-set: returns True only if newly marked for this date."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        with _write_lock, _transaction() as cur:
            cur.execute(
                f"SELECT 1 FROM cron_log WHERE task_name = {PH} AND run_date = {PH}",
                (task_name, date_str),
            )
            if cur.fetchone() is not None:
                return False
            cur.execute(
                f"INSERT INTO cron_log (task_name, run_date) VALUES ({PH}, {PH})",
                (task_name, date_str),
            )
            _maybe_cleanup(cur)
            return True
    except Exception as exc:
        _logger.warning("cron_try_mark_done error: %s", exc)
        return False


# ─── Webhook deduplication ────────────────────────────────


def webhook_seen(dedup_key: str, ttl_seconds: int = 300) -> bool:
    """Return True if this webhook was already processed."""
    try:
        with _transaction() as cur:
            cutoff = (datetime.now() - timedelta(seconds=ttl_seconds)).isoformat()
            cur.execute(
                f"SELECT 1 FROM webhook_dedup WHERE dedup_key = {PH} AND created_at > {PH}",
                (dedup_key, cutoff),
            )
            if cur.fetchone():
                return True
            cur.execute(
                f"""
                INSERT INTO webhook_dedup (dedup_key) VALUES ({PH})
                ON CONFLICT(dedup_key) DO UPDATE SET created_at=CURRENT_TIMESTAMP
                """,
                (dedup_key,),
            )
            # Cleanup old keys
            cutoff_old = (datetime.now() - timedelta(seconds=ttl_seconds * 2)).isoformat()
            cur.execute(
                f"DELETE FROM webhook_dedup WHERE created_at <= {PH}",
                (cutoff_old,),
            )
            _maybe_cleanup(cur)
            return False
    except Exception as exc:
        _logger.warning("webhook_seen error: %s", exc)
        return False  # fail open


# ─── Generic KV store (for vote, quiz, etc.) ──────────────


def kv_get(key: str, default=None):
    try:
        with _transaction() as cur:
            now = datetime.now().isoformat()
            cur.execute(
                f"SELECT value FROM kv WHERE key = {PH} AND (expires_at IS NULL OR expires_at > {PH})",
                (key, now),
            )
            row = cur.fetchone()
            if row:
                import json
                try:
                    return json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    return row[0]
    except Exception as exc:
        _logger.warning("kv_get error: %s", exc)
    return default


def kv_set(key: str, value, ttl_seconds: int | None = None):
    import json
    expires = None
    if ttl_seconds:
        expires = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
    try:
        with _write_lock, _transaction() as cur:
            cur.execute(
                f"""
                INSERT INTO kv (key, value, expires_at) VALUES ({PH}, {PH}, {PH})
                ON CONFLICT(key) DO UPDATE SET
                    value=EXCLUDED.value,
                    expires_at=EXCLUDED.expires_at
                """,
                (key, json.dumps(value, ensure_ascii=False), expires),
            )
    except Exception as exc:
        _logger.warning("kv_set error: %s", exc)


def kv_delete(key: str):
    try:
        with _write_lock, _transaction() as cur:
            cur.execute(f"DELETE FROM kv WHERE key = {PH}", (key,))
    except Exception as exc:
        _logger.warning("kv_delete error: %s", exc)


def webhook_cleanup(ttl_seconds: int = 600) -> None:
    try:
        with _write_lock, _transaction() as cur:
            cutoff = (datetime.now() - timedelta(seconds=ttl_seconds)).isoformat()
            cur.execute(f"DELETE FROM webhook_dedup WHERE created_at <= {PH}", (cutoff,))
        # Reclaim SQLite space (skip for PostgreSQL)
        if not USE_PG:
            with _transaction() as cur:
                cur.execute("PRAGMA incremental_vacuum(50)")
    except Exception as exc:
        _logger.warning("webhook_cleanup error: %s", exc)
