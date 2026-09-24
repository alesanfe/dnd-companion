"""Extension packages — declarative content packs with a validated
manifest. No arbitrary code execution: a package is manifest + data.
Install imports its entities into the content DB under source
'pkg:{id}' so provenance and licensing stay tracked."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db.connections import content_db

router = APIRouter(prefix="/api/packages", tags=["packages"])


class Manifest(BaseModel):
    """Manifest declarativo — ver ARCHITECTURE §12."""
    id: str
    name: str
    version: str
    compatible_rulesets: list[str] = Field(default_factory=list)
    required_app_version: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    license: str
    attribution: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    distribution_allowed: bool = False


class PackageIn(BaseModel):
    manifest: Manifest
    content: dict[str, list[dict]] = Field(default_factory=dict)
    # {'spell': [{...}], 'monster': [{...}]}


@router.post("/install", status_code=201)
def install_package(body: PackageIn):
    conn = content_db()
    m = body.manifest
    source_id = f"pkg:{m.id}"
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO content_sources
           (id, name, version, license, attribution_text, imported_at,
            distribution_allowed)
           VALUES (?,?,?,?,?,?,?)""",
        (source_id, m.name, m.version, m.license, m.attribution, now,
         int(m.distribution_allowed)))

    count = 0
    for entity_type, rows in body.content.items():
        for row in rows:
            index = row.get("index") or row.get("name")
            name = row.get("name") or index
            if not index or not name:
                continue
            eid = f"{source_id}:{index}"
            blob = json.dumps(row, ensure_ascii=False)
            ruleset = (m.compatible_rulesets[0]
                       if len(m.compatible_rulesets) == 1 else "mixed")
            conn.execute(
                """INSERT OR REPLACE INTO content_entities
                   (id, entity_type, name, ruleset, source_id,
                    source_version, license, is_redistributable, data)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (eid, entity_type, str(name), ruleset, source_id,
                 m.version, m.license, int(m.distribution_allowed), blob))
            conn.execute(
                "INSERT INTO content_fts (entity_id, name, body) "
                "VALUES (?,?,?)", (eid, str(name), blob))
            count += 1
    conn.commit()
    return {"package": m.id, "entities": count}


@router.get("")
def list_packages():
    conn = content_db()
    rows = conn.execute(
        "SELECT id, name, version, license, distribution_allowed "
        "FROM content_sources WHERE id LIKE 'pkg:%'").fetchall()
    return {"packages": [dict(r) for r in rows]}
