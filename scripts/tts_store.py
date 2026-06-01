"""
TTS audio + cron + dedup persistence for line-family-bot.
"""

import os
import sqlite3
import threading
import logging
from datetime import datetime, timedelta

DB_PATH = os.environ.get("TTS_DB_PATH", "/tmp/tts_store.db")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

_write_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS tts_audio (
                filename TEXT PRIMARY KEY,
                audio_blob BLOB,
                mime_type TEXT DEFAULT 'audio/mpeg',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS cron_log (
                task_name TEXT PRIMARY KEY,
                run_date TEXT,
                run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS webhook_dedup (
                dedup_key TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.commit()


_init()


# ─── TTS ──────────────────────────────────────────────────

def save_tts_audio(filename: str, audio_bytes: bytes, mime_type: str = "audio/mpeg") -> None:
    try:
        with _write_lock, _conn() as c:
            c.execute(
                "INSERT INTO tts_audio (filename, audio_blob, mime_type) VALUES (?, ?, ?) "
                "ON CONFLICT(filename) DO UPDATE SET audio_blob=excluded.audio_blob, mime_type=excluded.mime_type",
                (filename, audio_bytes, mime_type),
            )
            c.execute(
                "DELETE FROM tts_audio WHERE filename IN ("
                "SELECT filename FROM tts_audio ORDER BY created_at DESC LIMIT -1 OFFSET 100"
                ")"
            )
            c.commit()
    except sqlite3.Error as exc:
        logging.warning("tts_store save error: %s", exc)


def get_tts_audio(filename: str) -> tuple[bytes, str] | None:
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT audio_blob, mime_type FROM tts_audio WHERE filename = ?",
                (filename,),
            ).fetchone()
            if row:
                return row[0], row[1]
    except sqlite3.Error as exc:
        logging.warning("tts_store get error: %s", exc)
    return None


def delete_tts_audio(filename: str) -> None:
    try:
        with _write_lock, _conn() as c:
            c.execute("DELETE FROM tts_audio WHERE filename = ?", (filename,))
            c.commit()
    except sqlite3.Error as exc:
        logging.warning("tts_store delete error: %s", exc)


# ─── Cron idempotency ─────────────────────────────────────

def cron_is_done(task_name: str, date_str: str | None = None) -> bool:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT 1 FROM cron_log WHERE task_name = ? AND run_date = ?",
                (task_name, date_str),
            ).fetchone()
            return row is not None
    except sqlite3.Error as exc:
        logging.warning("cron_is_done error: %s", exc)
        return False


def cron_mark_done(task_name: str, date_str: str | None = None) -> None:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        with _write_lock, _conn() as c:
            c.execute(
                "INSERT INTO cron_log (task_name, run_date) VALUES (?, ?) "
                "ON CONFLICT(task_name) DO UPDATE SET run_date=excluded.run_date, run_at=CURRENT_TIMESTAMP",
                (task_name, date_str),
            )
            c.commit()
    except sqlite3.Error as exc:
        logging.warning("cron_mark_done error: %s", exc)


# ─── Webhook deduplication ────────────────────────────────

def webhook_seen(dedup_key: str, ttl_seconds: int = 300) -> bool:
    """Return True if this webhook was already processed."""
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT 1 FROM webhook_dedup WHERE dedup_key = ? AND created_at > ?",
                (dedup_key, (datetime.now() - timedelta(seconds=ttl_seconds)).isoformat()),
            ).fetchone()
            if row:
                return True
            c.execute(
                "INSERT INTO webhook_dedup (dedup_key) VALUES (?) "
                "ON CONFLICT(dedup_key) DO UPDATE SET created_at=CURRENT_TIMESTAMP",
                (dedup_key,),
            )
            # Cleanup old keys
            c.execute(
                "DELETE FROM webhook_dedup WHERE created_at <= ?",
                ((datetime.now() - timedelta(seconds=ttl_seconds * 2)).isoformat(),),
            )
            c.commit()
            return False
    except sqlite3.Error as exc:
        logging.warning("webhook_seen error: %s", exc)
        return False  # fail open


def webhook_cleanup(ttl_seconds: int = 600) -> None:
    try:
        with _write_lock, _conn() as c:
            c.execute(
                "DELETE FROM webhook_dedup WHERE created_at <= ?",
                ((datetime.now() - timedelta(seconds=ttl_seconds)).isoformat(),),
            )
            c.commit()
    except sqlite3.Error as exc:
        logging.warning("webhook_cleanup error: %s", exc)
