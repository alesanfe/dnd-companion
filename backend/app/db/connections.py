"""DB connections. content = rules data (imported); state = game state."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import config

_STATE_SCHEMA = Path(__file__).parent / "state_schema.sql"


def content_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.CONTENT_DB))
    conn.row_factory = sqlite3.Row
    return conn


def state_db() -> sqlite3.Connection:
    config.STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.STATE_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # lectores + escritor
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_STATE_SCHEMA.read_text(encoding="utf-8"))
    return conn
