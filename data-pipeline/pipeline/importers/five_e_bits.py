"""Importer for 5e-bits/5e-database (D&D SRD, CC-BY-4.0 content).

Source layout: src/{edition}/en/5e-SRD-<Collection>.json where each file is a
JSON array of entities with at least `index` and `name` keys.

Usage: python -m pipeline.cli import-srd --edition 2014
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.request
from pathlib import Path

from .. import db

RAW_BASE = (
    "https://raw.githubusercontent.com/5e-bits/5e-database/main/src"
)

# filename -> entity_type (2014 layout; 2024 renames a few files)
FILE_TYPES_2024_ONLY = {
    "5e-SRD-Species.json": "species",
    "5e-SRD-Subspecies.json": "subspecies",
    "5e-SRD-Poisons.json": "poison",
    "5e-SRD-Weapon-Mastery-Properties.json": "weapon-mastery",
}
FILE_TYPES_2014_ONLY = {
    "5e-SRD-Races.json": "race",
    "5e-SRD-Subraces.json": "subrace",
    "5e-SRD-Rule-Sections.json": "rule-section",
    "5e-SRD-Rules.json": "rule",
}
FILE_TYPES = {
    "5e-SRD-Ability-Scores.json": "ability-score",
    "5e-SRD-Alignments.json": "alignment",
    "5e-SRD-Backgrounds.json": "background",
    "5e-SRD-Classes.json": "class",
    "5e-SRD-Conditions.json": "condition",
    "5e-SRD-Damage-Types.json": "damage-type",
    "5e-SRD-Equipment-Categories.json": "equipment-category",
    "5e-SRD-Equipment.json": "equipment",
    "5e-SRD-Feats.json": "feat",
    "5e-SRD-Features.json": "feature",
    "5e-SRD-Languages.json": "language",
    "5e-SRD-Levels.json": "level",
    "5e-SRD-Magic-Items.json": "magic-item",
    "5e-SRD-Magic-Schools.json": "magic-school",
    "5e-SRD-Monsters.json": "monster",
    "5e-SRD-Proficiencies.json": "proficiency",
    "5e-SRD-Skills.json": "skill",
    "5e-SRD-Spells.json": "spell",
    "5e-SRD-Subclasses.json": "subclass",
    "5e-SRD-Traits.json": "trait",
    "5e-SRD-Weapon-Properties.json": "weapon-property",
}

LICENSE_CC_BY_4 = "CC-BY-4.0"
ATTRIBUTION = (
    "This work includes material from the System Reference Document by "
    "Wizards of the Coast LLC, licensed under CC-BY-4.0."
)


def _edition_dirs(edition: str) -> tuple[str, str]:
    """Map CLI edition to (repo dir, ruleset id)."""
    if edition == "2014":
        return "2014", "dnd5e-2014"
    if edition == "2024":
        return "2024", "dnd5e-2024"
    raise ValueError(f"edition must be 2014 or 2024, got {edition!r}")


def _load_file(source_dir: Path | None, url_path: str) -> list[dict]:
    if source_dir is not None:
        return json.loads((source_dir / url_path).read_text(encoding="utf-8"))
    with urllib.request.urlopen(f"{RAW_BASE}/{url_path}", timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def import_srd(
    conn: sqlite3.Connection,
    edition: str,
    source_dir: Path | None = None,
) -> int:
    """Import one SRD edition. Returns number of entities inserted."""
    repo_dir, ruleset = _edition_dirs(edition)
    source_id = f"srd-{edition}"
    # Local mode: source_dir is the repo's `src/` dir; files live in
    # {edition}/en/. Remote mode: fetch raw files from GitHub.
    local_dir = Path(source_dir) / repo_dir / "en" if source_dir else None

    db.upsert_source(
        conn,
        source_id=source_id,
        name=f"D&D System Reference Document ({edition} rules)",
        version=edition,
        license=LICENSE_CC_BY_4,
        attribution_text=ATTRIBUTION,
        original_url="https://github.com/5e-bits/5e-database",
        distribution_allowed=True,
    )

    file_types = dict(FILE_TYPES)
    file_types.update(
        FILE_TYPES_2024_ONLY if edition == "2024" else FILE_TYPES_2014_ONLY)

    count = 0
    for filename, entity_type in file_types.items():
        path = filename if local_dir else f"{repo_dir}/en/{filename}"
        try:
            rows = _load_file(local_dir, path)
        except (FileNotFoundError, urllib.error.URLError) as exc:
            print(f"  skip {filename}: {exc}")
            continue
        blob_hash = hashlib.sha256(
            json.dumps(rows, sort_keys=True).encode()
        ).hexdigest()[:16]
        for row in rows:
            index = row.get("index") or row.get("slug") or row.get("name")
            name = row.get("name") or index
            if not index or not name:
                continue
            db.insert_entity(
                conn,
                source_id=source_id,
                index=str(index),
                entity_type=entity_type,
                name=str(name),
                ruleset=ruleset,
                license=LICENSE_CC_BY_4,
                data=row,
                source_document=f"5e-SRD-{edition}",
                source_version=blob_hash,
                is_redistributable=True,
            )
            count += 1
        print(f"  {entity_type}: {len(rows)}")

    db.rebuild_fts(conn)
    conn.commit()
    return count
