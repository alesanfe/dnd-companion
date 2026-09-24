"""Importer for nick-aschenbach/dnd-data (npm 'dnd-data' package).

Six flat JSON files: backgrounds, classes, items, monsters, species,
spells — each a list of {name, description, properties, publisher,
book}. ~34k entries. The underlying data is scraped from D&D Beyond
(the "Expansion"/"properties" fields), so it is imported as
non-redistributable (local use) even though the package code is MIT.

  python -m pipeline.cli import-dnddata            # fetch from GitHub
  python -m pipeline.cli import-dnddata --path ./dnd-data/data
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.request
from pathlib import Path

from .. import db

SOURCE_ID = "dnd-data"
LICENSE = "non-free (scraped D&D Beyond data — local use only)"
ORIGIN = "https://github.com/nick-aschenbach/dnd-data"
RAW = "https://raw.githubusercontent.com/nick-aschenbach/dnd-data/main/data"

FILES = {
    "backgrounds.json": "background",
    "classes.json": "class",
    "items.json": "item",
    "monsters.json": "monster",
    "species.json": "species",
    "spells.json": "spell",
}


def _load(source_dir: Path | None, filename: str) -> list:
    if source_dir is not None:
        return json.loads(
            (source_dir / filename).read_text(encoding="utf-8"))
    req = urllib.request.Request(
        f"{RAW}/{filename}", headers={"User-Agent": "dnd-companion/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def _slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def import_dnddata(
    conn: sqlite3.Connection,
    source_dir: Path | None = None,
    ruleset: str = "dnd5e-2014",
) -> int:
    db.upsert_source(
        conn, source_id=SOURCE_ID,
        name="nick-aschenbach/dnd-data (npm package data)",
        version=None, license=LICENSE,
        attribution_text=(
            "Community dataset scraped from D&D Beyond. Content "
            "© Wizards of the Coast / respective publishers."),
        original_url=ORIGIN, distribution_allowed=False)

    count = 0
    for filename, etype in FILES.items():
        try:
            rows = _load(source_dir, filename)
        except (FileNotFoundError, urllib.error.URLError) as exc:
            print(f"  skip {filename}: {exc}")
            continue
        if not isinstance(rows, list):
            continue
        blob = hashlib.sha256(
            json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]
        ep = 0
        for row in rows:
            name = row.get("name")
            if not isinstance(row, dict) or not name:
                continue
            db.insert_entity(
                conn, source_id=SOURCE_ID,
                index=_slug(str(name)),
                entity_type=etype, name=str(name),
                ruleset=ruleset, license=LICENSE, data=row,
                source_document=row.get("book") or filename,
                source_version=blob,
                is_redistributable=False)
            count += 1
            ep += 1
        print(f"  {etype}: {ep}")
    db.rebuild_fts(conn)
    conn.commit()
    return count
