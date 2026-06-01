"""
TTS audio persistence layer for line-family-bot.
Stores audio BLOBs in SQLite so they survive Render free-tier restarts.
"""

import os
import sqlite3
import threading

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
        c.commit()


_init()


def save_tts_audio(filename: str, audio_bytes: bytes, mime_type: str = "audio/mpeg") -> None:
    try:
        with _write_lock, _conn() as c:
            c.execute(
                "INSERT INTO tts_audio (filename, audio_blob, mime_type) VALUES (?, ?, ?) "
                "ON CONFLICT(filename) DO UPDATE SET audio_blob=excluded.audio_blob, mime_type=excluded.mime_type",
                (filename, audio_bytes, mime_type),
            )
            # Keep only the latest 100 entries
            c.execute(
                "DELETE FROM tts_audio WHERE filename IN ("
                "SELECT filename FROM tts_audio ORDER BY created_at DESC LIMIT -1 OFFSET 100"
                ")"
            )
            c.commit()
    except sqlite3.Error as exc:
        import logging
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
        import logging
        logging.warning("tts_store get error: %s", exc)
    return None


def delete_tts_audio(filename: str) -> None:
    try:
        with _write_lock, _conn() as c:
            c.execute("DELETE FROM tts_audio WHERE filename = ?", (filename,))
            c.commit()
    except sqlite3.Error as exc:
        import logging
        logging.warning("tts_store delete error: %s", exc)
