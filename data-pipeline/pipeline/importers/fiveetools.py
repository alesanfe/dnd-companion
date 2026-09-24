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

# Homebrew/UA files ("Author; Title.json") hold arbitrary mixes of keys —
# scan every known top-level key per file.
KEY_TYPES = {
    "monster": "monster", "spell": "spell", "item": "magic-item",
    "baseitem": "equipment", "magicvariant": "magic-item",
    "feat": "feat", "race": "race", "subrace": "subrace",
    "class": "class", "subclass": "subclass",
    "background": "background", "condition": "condition",
    "disease": "condition", "action": "action", "table": "table",
    "variantrule": "rule", "reward": "reward", "boon": "feat",
    "deity": "deity", "optionalfeature": "feature", "hazard": "hazard",
    "trap": "hazard", "object": "object", "language": "language",
    "vehicle": "vehicle", "charoption": "feature", "psionic": "spell",
    "card": "object", "deck": "table", "cult": "feature",
    "classFeature": "class-feature", "subclassFeature": "class-feature",
    "recipe": "item", "status": "condition", "itemProperty": "rule",
    "itemType": "rule", "itemEntry": "rule", "monsterFluff": None,
    "trait": "trait", "sense": "rule", "skill": "skill",
    "legendaryGroup": "rule", "optionalfeatureTypes": "rule",
    "bookData": None, "adventureData": None,
}


def _index_of(row: dict) -> str | None:
    name = row.get("name")
    src = row.get("source") or row.get("srd52") and "srd52" or "unknown"
    if not name:
        return None
    return f"{str(name).lower()}|{str(src).lower()}".replace(" ", "-")


def _pairs_from_file(path: Path) -> list[tuple[str, dict]]:
    """Return [(entity_type, row), ...] scanning all known keys."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  skip {path.name}: {exc}")
        return []
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, dict]] = []
    for key, etype in KEY_TYPES.items():
        rows = data.get(key)
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    out.append((etype or "misc", r))
    return out


def import_5etools(
    conn: sqlite3.Connection,
    data_dir: Path,
    ruleset: str = "mixed",
    source_id: str = SOURCE_ID,
    license: str = LICENSE,
    distribution_allowed: bool = False,
) -> int:
    """Import every recognized file under a 5etools-format dir tree.

    Works for the main data repo (data/bestiary-*.json etc.) and for
    homebrew/UA repos where each file mixes keys ("Author; Title.json").
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(data_dir)

    db.upsert_source(
        conn, source_id=source_id,
        name=f"5etools-format dataset: {source_id} (local clone)",
        version=None, license=license,
        attribution_text=(
            "5etools-format JSON. Content rights belong to the original "
            "authors/publishers. For personal use only."),
        original_url=ORIGIN,
        distribution_allowed=distribution_allowed,
    )

    count = 0
    for path in sorted(data_dir.rglob("*.json")):
        # skip generated/schema/meta dirs
        if any(part in ("generated", "schema", "zips", ".git")
               for part in path.parts):
            continue
        pairs = _pairs_from_file(path)
        ep = 0
        for etype, row in pairs:
            index = _index_of(row)
            name = row.get("name")
            if not index or not name:
                continue
            db.insert_entity(
                conn, source_id=source_id,
                index=f"{etype}:{index}",
                entity_type=etype, name=str(name),
                ruleset=ruleset, license=license, data=row,
                source_document=str(row.get("source") or path.stem),
                is_redistributable=distribution_allowed)
            count += 1
            ep += 1
        if ep:
            print(f"  {path.name}: {ep}")

    db.rebuild_fts(conn)
    conn.commit()
    return count
