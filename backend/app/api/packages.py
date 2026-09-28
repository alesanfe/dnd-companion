"""Extension packages — declarative content packs with a validated
manifest. No arbitrary code execution: a package is manifest + data.
Install imports its entities into the content DB under source
'pkg:{id}' so provenance and licensing stay tracked."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config
from ..db.connections import content_db

router = APIRouter(prefix="/api/packages", tags=["packages"])

# capacidades que un pack puede declarar (ARCHITECTURE §12: solo
# declarativo, nada de código arbitrario). Vacío ≡ ['content'].
KNOWN_CAPABILITIES = {"content", "rules", "themes", "templates",
                      "locales", "importers", "exporters"}


def _ver_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


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


@router.post("/install", status_code=201)
def install_package(body: PackageIn):
    conn = content_db()
    m = body.manifest
    # dependencias del manifest: cada una debe existir como fuente
    # (paquete 'pkg:x' o fuente de pipeline 'srd:2014'…). Un pack
    # incompleto instalado "a medias" es peor que rechazar la install.
    if m.dependencies:
        have = {r[0] for r in conn.execute(
            "SELECT id FROM content_sources").fetchall()}
        missing = [d for d in m.dependencies
                   if d not in have and f"pkg:{d}" not in have]
        if missing:
            raise HTTPException(
                409, f"dependencias ausentes: {', '.join(missing)}")
    # enforcement real del manifest: capabilities desconocidas y
    # required_app_version > app instalada → rechazar, no instalar
    # algo que el runtime no puede satisfacer
    unknown = set(m.capabilities) - KNOWN_CAPABILITIES
    if unknown:
        raise HTTPException(
            400, f"capabilities desconocidas: {', '.join(unknown)}")
    caps = set(m.capabilities) or {"content"}
    if body.content and "content" not in caps:
        raise HTTPException(
            400, "el pack lleva contenido sin declarar 'content'")
    if m.required_app_version and \
            _ver_tuple(m.required_app_version) > \
            _ver_tuple(config.APP_VERSION):
        raise HTTPException(
            409, f"requiere app {m.required_app_version} "
                 f"(instalada {config.APP_VERSION})")
    source_id = f"pkg:{m.id}"
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    try:
        conn.execute(
            """INSERT OR REPLACE INTO content_sources
               (id, name, version, license, attribution_text, imported_at,
                distribution_allowed)
               VALUES (?,?,?,?,?,?,?)""",
            (source_id, m.name, m.version, m.license, m.attribution, now,
             int(m.distribution_allowed)))
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
                     m.version, m.license, int(m.distribution_allowed),
                     blob))
                conn.execute(
                    "DELETE FROM content_fts WHERE entity_id = ?", (eid,))
                conn.execute(
                    "INSERT INTO content_fts (entity_id, name, body) "
                    "VALUES (?,?,?)", (eid, str(name), blob))
                count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"package": m.id, "entities": count}


@router.get("")
def list_packages():
    conn = content_db()
    rows = conn.execute(
        """SELECT s.id, s.name, s.version, s.license,
                  s.distribution_allowed, s.attribution_text,
                  COUNT(e.id) AS entities
           FROM content_sources s
           LEFT JOIN content_entities e ON e.source_id = s.id
           WHERE s.id LIKE 'pkg:%'
           GROUP BY s.id ORDER BY s.name""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # desglose por tipo — '12 hechizos · 3 objetos' para la UI
        d["by_type"] = {r2[0]: r2[1] for r2 in conn.execute(
            """SELECT entity_type, COUNT(*) FROM content_entities
               WHERE source_id = ? GROUP BY entity_type""",
            (d["id"],)).fetchall()}
        out.append(d)
    return {"packages": out}


@router.delete("/{pkg_id}", status_code=200)
def uninstall_package(pkg_id: str):
    """Desinstala un pack: borra su fuente, entidades e índice FTS.
    Solo packs de usuario ('pkg:*') — las fuentes de pipeline (srd,
    open5e…) no se tocan por este endpoint."""
    conn = content_db()
    source_id = pkg_id if pkg_id.startswith("pkg:") else f"pkg:{pkg_id}"
    row = conn.execute(
        "SELECT id FROM content_sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "paquete no instalado")
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM content_entities WHERE source_id = ?",
        (source_id,)).fetchall()]
    try:
        # FTS primero — la fila de entities se va en el mismo commit
        for eid in ids:
            conn.execute(
                "DELETE FROM content_fts WHERE entity_id = ?", (eid,))
        conn.execute(
            "DELETE FROM content_entities WHERE source_id = ?",
            (source_id,))
        conn.execute(
            "DELETE FROM content_sources WHERE id = ?", (source_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"removed": source_id, "entities": len(ids)}
