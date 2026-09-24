"""Importer for a local clone of foundryvtt/dnd5e compendium packs.

    git clone https://github.com/foundryvtt/dnd5e
    python -m pipeline.cli import-foundry --path dnd5e/packs/_source

The repo ships the SRD 5.1 + 5.2 (CC-BY-4.0) as YAML source files under
``packs/_source/<pack>/**.yml``. The data is the Foundry modeling of the
SRD — enriched formulas, activities, effects — complementing the raw
5e-bits import. All content is redistributable (CC-BY-4.0).

Entity ids: ``foundry:{pack}:{_id}`` keeping the pack organization.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from .. import db

SOURCE_ID = "foundry-dnd5e"
LICENSE = "CC-BY-4.0"
ORIGIN = "https://github.com/foundryvtt/dnd5e"
ATTRIBUTION = (
    "Foundry VTT dnd5e compendium packs — material from the SRD 5.1/5.2 "
    "by Wizards of the Coast, CC-BY-4.0."
)

# pack folder -> entity_type (covers the main packs; unknown = folder name)
PACK_TYPES = {
    "monsters": "monster",
    "actors24": "monster",
    "heroes": "character",
    "spells": "spell",
    "spells24": "spell",
    "items": "equipment",
    "items24": "equipment",
    "classes": "class",
    "classes24": "class",
    "subclasses": "subclass",
    "origins": "background",
    "origins24": "background",
    "races": "race",
    "rules": "rule",
    "rules24": "rule",
    "tables": "table",
    "tables24": "table",
    "monsters24": "monster",
    "feats24": "feat",
    "classfeatures": "feature",
    "classfeatures24": "feature",
    "monsterfeatures": "feature",
    "monsterfeatures24": "feature",
    "backgrounds24": "background",
    "species24": "species",
}


def import_foundry(
    conn: sqlite3.Connection,
    source_dir: Path,
    ruleset: str = "mixed",
) -> int:
    """Walk packs/_source/**/*.yml and import each entry."""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(source_dir)

    db.upsert_source(
        conn, source_id=SOURCE_ID,
        name="Foundry VTT dnd5e compendium packs (local clone)",
        version=None, license=LICENSE, attribution_text=ATTRIBUTION,
        original_url=ORIGIN, distribution_allowed=True)

    count = 0
    for path in sorted(source_dir.rglob("*.yml")):
        pack = path.relative_to(source_dir).parts[0]
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            print(f"  skip {path.name}: {exc}")
            continue
        if not isinstance(doc, dict) or not doc.get("name"):
            continue
        etype = PACK_TYPES.get(pack, pack)
        fid = doc.get("_id") or path.stem
        db.insert_entity(
            conn, source_id=SOURCE_ID,
            index=f"{pack}:{fid}",
            entity_type=etype, name=str(doc["name"]),
            ruleset=ruleset, license=LICENSE, data=doc,
            source_document=pack,
            is_redistributable=True)
        count += 1
    print(f"  packs: {count}")
    db.rebuild_fts(conn)
    conn.commit()
    return count
