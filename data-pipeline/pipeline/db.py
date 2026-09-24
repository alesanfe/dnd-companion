"""Content DB helpers: open/create schema, upsert sources and entities."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def upsert_source(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    name: str,
    version: str | None,
    license: str,
    attribution_text: str | None = None,
    original_url: str | None = None,
    content_hash: str | None = None,
    distribution_allowed: bool = False,
) -> None:
    conn.execute(
        """INSERT INTO content_sources
           (id, name, version, license, attribution_text, original_url,
            imported_at, content_hash, distribution_allowed)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name, version=excluded.version,
             license=excluded.license,
             attribution_text=excluded.attribution_text,
             original_url=excluded.original_url,
             imported_at=excluded.imported_at,
             content_hash=excluded.content_hash,
             distribution_allowed=excluded.distribution_allowed""",
        (
            source_id, name, version, license, attribution_text, original_url,
            datetime.now(timezone.utc).isoformat(), content_hash,
            int(distribution_allowed),
        ),
    )


def insert_entity(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    index: str,
    entity_type: str,
    name: str,
    ruleset: str,
    license: str,
    data: dict,
    source_document: str | None = None,
    source_version: str | None = None,
    source_page: str | None = None,
    is_redistributable: bool = False,
) -> str:
    entity_id = f"{source_id}:{index}"
    conn.execute(
        """INSERT OR REPLACE INTO content_entities
           (id, entity_type, name, ruleset, source_id, source_document,
            source_version, source_page, license, is_redistributable, data)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            entity_id, entity_type, name, ruleset, source_id, source_document,
            source_version, source_page, license, int(is_redistributable),
            json.dumps(data, ensure_ascii=False),
        ),
    )
    return entity_id


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM content_fts")
    conn.execute(
        """INSERT INTO content_fts (entity_id, name, body)
           SELECT id, name, data FROM content_entities"""
    )
