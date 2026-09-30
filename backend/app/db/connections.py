"""DB connections. content = rules data (imported); state = game state."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import config

_STATE_SCHEMA = Path(__file__).parent / "state_schema.sql"
_SCHEMA_VERSION = 2


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
    # user_version actúa como marcador de migración: el schema es
    # idempotente (IF NOT EXISTS), así que una subida de versión solo
    # re-ejecuta el script — añadir tablas = subir SCHEMA_VERSION.
    # v1: baseline · v2: auth_throttle
    if conn.execute("PRAGMA user_version").fetchone()[0] \
            < _SCHEMA_VERSION:
        conn.executescript(_STATE_SCHEMA.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    return conn
