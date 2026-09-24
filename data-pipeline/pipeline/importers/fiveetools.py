"""Importer for a local clone of the 5etools data repo.

    git clone https://github.com/5etools-mirror-3/5etools-src
    python -m pipeline.cli import-5etools --path 5etools-src/data

The 5etools dataset contains the full WotC catalogue (all books, not
just the SRD). That content is NOT redistributable: every entity is
imported with ``is_redistributable=False`` and license "non-free", so
it stays in the user's local DB — consistent with AGENTS.md.

Entity ids keep the 5etools natural key: ``5etools:{type}:{name}|{src}``
(e.g. ``5etools:monster:adult red dragon|mm``).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .. import db

SOURCE_ID = "5etools"
LICENSE = "non-free (WotC fan content — local use only)"
ORIGIN = "https://github.com/5etools-mirror-3/5etools-src"

# filename prefix -> (json key, entity_type). Files under data/.
FILE_MAP = {
    "bestiary-": ("monster", "monster"),
    "spells-": ("spell", "spell"),
    "class-": ("class", "class"),
    "subclass-": ("subclass", "subclass"),
    "race": ("race", "race"),
}
# top-level files: (filename, json key, entity_type)
SINGLE_FILES = {
    "items.json": ("item", "magic-item"),
    "items-base.json": ("baseitem", "equipment"),
    "conditionsdiseases.json": ("condition", "condition"),
    "actions.json": ("action", "action"),
    "backgrounds.json": ("background", "background"),
    "feats.json": ("feat", "feat"),
    "optionalfeatures.json": ("optionalfeature", "feature"),
    "rewards.json": ("reward", "reward"),
    "boons.json": ("boon", "feat"),
    "deities.json": ("deity", "deity"),
    "traps.json": ("trap", "hazard"),
    "hazards.json": ("hazard", "hazard"),
    "objects.json": ("object", "object"),
    "variantrules.json": ("variantrule", "rule"),
    "tables.json": ("table", "table"),
    "languages.json": ("language", "language"),
    "skills.json": ("skill", "skill"),
    "senses.json": ("sense", "rule"),
}


def _index_of(row: dict) -> str | None:
    name = row.get("name")
    src = row.get("source") or row.get("srd52") and "srd52" or "unknown"
    if not name:
        return None
    return f"{str(name).lower()}|{str(src).lower()}".replace(" ", "-")


def _rows_from_file(path: Path, key: str) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  skip {path.name}: {exc}")
        return []
    rows = data.get(key)
    if not isinstance(rows, list):
        # some files nest under _copy-friendly wrappers; try any list
        rows = next((v for v in data.values()
                     if isinstance(v, list) and v
                     and isinstance(v[0], dict) and "name" in v[0]), [])
    return [r for r in rows if isinstance(r, dict)]


def import_5etools(
    conn: sqlite3.Connection,
    data_dir: Path,
    ruleset: str = "mixed",
) -> int:
    """Import every recognized file under <clone>/data. Returns count."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(data_dir)

    db.upsert_source(
        conn, source_id=SOURCE_ID, name="5etools dataset (local clone)",
        version=None, license=LICENSE,
        attribution_text=(
            "Unofficial fan dataset — content © Wizards of the Coast. "
            "For personal use only; do not redistribute."),
        original_url=ORIGIN,
        distribution_allowed=False,
    )

    count = 0
    for path in sorted(data_dir.rglob("*.json")):
        # skip generated/schema/meta dirs
        if any(part in ("generated", "schema", "zips")
               for part in path.parts):
            continue
        key = etype = None
        for prefix, (k, t) in FILE_MAP.items():
            if path.name.startswith(prefix):
                key, etype = k, t
                break
        if key is None and path.name in SINGLE_FILES:
            key, etype = SINGLE_FILES[path.name]
        if key is None:
            continue
        rows = _rows_from_file(path, key)
        ep = 0
        for row in rows:
            index = _index_of(row)
            name = row.get("name")
            if not index or not name:
                continue
            db.insert_entity(
                conn, source_id=SOURCE_ID,
                index=f"{etype}:{index}",
                entity_type=etype, name=str(name),
                ruleset=ruleset, license=LICENSE, data=row,
                source_document=str(row.get("source") or path.stem),
                is_redistributable=False)
            count += 1
            ep += 1
        if ep:
            print(f"  {path.name}: {ep}")

    db.rebuild_fts(conn)
    conn.commit()
    return count
