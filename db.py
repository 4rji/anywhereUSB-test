import sqlite3
import threading
from datetime import datetime

DB_PATH = "camera_monitor.db"
_lock = threading.Lock()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS metrics_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                camera_id INTEGER NOT NULL,
                fps REAL,
                bitrate_kbps REAL,
                status TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                camera_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                detail TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics_history(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
        """)
        conn.commit()
        conn.close()


def save_metrics(camera_id: int, fps: float, bitrate_kbps: float, status: str):
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO metrics_history (timestamp, camera_id, fps, bitrate_kbps, status) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), camera_id, fps, bitrate_kbps, status),
        )
        conn.commit()
        conn.close()


def save_event(camera_id: int, event_type: str, detail: str = ""):
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO events (timestamp, camera_id, event_type, detail) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), camera_id, event_type, detail),
        )
        conn.commit()
        conn.close()


def get_recent_events(limit: int = 50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_metrics_history(camera_id: int, limit: int = 100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM metrics_history WHERE camera_id=? ORDER BY timestamp DESC LIMIT ?",
        (camera_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
