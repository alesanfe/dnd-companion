"""Content search over the rules DB (FTS5). Each hit carries provenance."""
from __future__ import annotations

import json

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..db.connections import content_db

router = APIRouter(prefix="/api/content", tags=["content"])


def _spell_for_class(data: dict, cls_name: str) -> bool:
    """¿Este conjuro está en la lista de la clase? Multi-schema:
    5e-bits classes[].index · 5etools classes.fromClassList[].name ·
    open5e2 classes[].name · codexMUNDI 'Sorcerer, Wizard'."""
    cls = data.get("classes")
    want = cls_name.lower()
    if isinstance(cls, str):
        return want in cls.lower()
    names: list[str] = []
    if isinstance(cls, list):
        names = [(c.get("index") or c.get("name") or "")
                 for c in cls if isinstance(c, dict)]
    elif isinstance(cls, dict):
        for grp in ("fromClassList", "fromSubclass"):
            for c in cls.get(grp) or []:
                if isinstance(c, dict):
                    n = c.get("name") or (c.get("class") or {}).get("name")
                    if n:
                        names.append(n)
    if not names:
        # schema sin lista (dnd-data): match suelto por texto
        blob = json.dumps(data.get("desc") or data.get("entries")
                          or "", ensure_ascii=False).lower()
        return want in blob
    return any(want == str(n).lower() for n in names)


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    entity_type: str | None = None,
    ruleset: str | None = None,
    source: str | None = None,
    for_class: str | None = None,
    limit: int = Query(20, le=100),
):
    conn = content_db()
    sql = """
        SELECT e.id, e.entity_type, e.name, e.ruleset, e.license,
               e.is_redistributable, e.source_id, e.data,
               snippet(content_fts, 2, '[', ']', '…', 12) AS excerpt
        FROM content_fts f
        JOIN content_entities e ON e.id = f.entity_id
        WHERE content_fts MATCH ?
    """
    params: list = [q]
    if entity_type:
        sql += " AND e.entity_type = ?"
        params.append(entity_type)
    if ruleset:
        sql += " AND e.ruleset = ?"
        params.append(ruleset)
    if source:
        sql += " AND e.source_id = ?"
        params.append(source)
    # con for_class pedimos de más y filtramos en Python (las listas
    # de clases viven dentro del JSON, no en columnas)
    sql += " ORDER BY bm25(content_fts) LIMIT ?"
    params.append(limit * 4 if for_class else limit)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        if for_class and entity_type == "spell":
            if not _spell_for_class(json.loads(r.pop("data")),
                                    for_class):
                continue
        else:
            r.pop("data", None)
        out.append(r)
        if len(out) >= limit:
            break
    return {"results": out}


@router.get("/sources")
def list_sources():
    """Fuentes de contenido instaladas (con recuento) — para filtros UI."""
    conn = content_db()
    rows = conn.execute(
        """SELECT s.id, s.name, s.license, s.distribution_allowed,
                  COUNT(e.id) AS entities
           FROM content_sources s
           LEFT JOIN content_entities e ON e.source_id = s.id
           GROUP BY s.id ORDER BY entities DESC""").fetchall()
    return {"sources": [dict(r) for r in rows]}


@router.get("/{entity_id}/render")
def render_entity(entity_id: str):
    """Vista canónica por tipo (spell/item/class/feature…) para la UI."""
    from ..domain import render
    conn = content_db()
    row = conn.execute(
        "SELECT id, name, entity_type, data FROM content_entities "
        "WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(404, "entity not found")
    return {"entity_id": entity_id, "name": row["name"],
            "entity_type": row["entity_type"],
            "render": render.render(row["entity_type"],
                                    json.loads(row["data"]))}


@router.get("/{entity_id}/statblock")
def statblock_preview(entity_id: str):
    """Stat block canónico normalizado — cualquier fuente soportada."""
    from ..domain import statblock
    conn = content_db()
    row = conn.execute(
        "SELECT name, data, source_id FROM content_entities WHERE id = ?",
        (entity_id,)).fetchone()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(404, "entity not found")
    block = statblock.normalize(json.loads(row["data"]))
    if block is None:
        raise HTTPException(422, "la entidad no es un stat block")
    block.pop("raw", None)                  # no reenviar el blob crudo
    return {"entity_id": entity_id, "source_id": row["source_id"],
            "statblock": block}


_TYPE_ALIASES = {
    "spell": "spell", "monster": "monster", "rule": "rule",
    "item": "magic-item", "magic-item": "magic-item", "class": "class",
    "race": "race", "species": "species",      # species = raza 2024
    "feat": "feat", "condition": "condition", "background": "background",
    "equipment": "equipment", "trait": "trait",
}

_CR_FLOAT = {"0": 0, "1/8": 0.125, "1/4": 0.25, "1/2": 0.5}


def _cr_float(cr) -> float:
    s = str(cr)
    if s in _CR_FLOAT:
        return _CR_FLOAT[s]
    try:
        return float(s)
    except ValueError:
        return -1


def _match_filters(data: dict, filters: dict[str, str]) -> bool:
    """Filtros key:value sobre el JSON de la entidad."""
    for key, val in filters.items():
        if key == "level":
            try:
                if data.get("level") != int(val):
                    return False
            except ValueError:
                return False
        elif key == "cr":
            cr = _cr_float(data.get("challenge_rating"))
            if ".." in val:
                lo, hi = val.split("..", 1)
                if not (_cr_float(lo) <= cr <= _cr_float(hi)):
                    return False
            elif cr != _cr_float(val):
                return False
        elif key == "school":
            school = data.get("school") or {}
            if val.lower() not in str(
                    school.get("index") or school.get("name", "")).lower():
                return False
        elif key == "concentration":
            if bool(data.get("concentration")) != (val == "true"):
                return False
        elif key == "type":
            if val.lower() not in str(data.get("type", "")).lower():
                return False
        elif key == "class":
            names = [str(c.get("name", "")).lower()
                     for c in data.get("classes", [])]
            if val.lower() not in names:
                return False
        elif key == "resistance":
            res = [str(r).lower() for r in
                   data.get("damage_resistances", [])]
            if val.lower() not in res:
                return False
        else:
            return False                      # filtro desconocido
    return True


@router.get("/command")
def command_search(q: str = Query(..., min_length=2),
                   limit: int = Query(20, le=100)):
    """Búsqueda por comandos:
      /spell fire level:3 concentration:true
      /monster undead cr:1..5 resistance:necrotic
      /rule grapple ruleset:2024
    """
    conn = content_db()
    tokens = q.strip().split()
    entity_type = None
    filters: dict[str, str] = {}
    terms: list[str] = []
    ruleset = None

    for tok in tokens:
        if tok.startswith("/") and entity_type is None:
            entity_type = _TYPE_ALIASES.get(tok[1:].lower())
        elif ":" in tok:
            k, v = tok.split(":", 1)
            if k == "ruleset":
                ruleset = "dnd5e-" + v if not v.startswith("dnd5e") else v
            else:
                filters[k] = v
        else:
            terms.append(tok)

    sql = ("SELECT e.id, e.entity_type, e.name, e.ruleset, e.data, "
           "e.source_id FROM content_entities e WHERE 1=1")
    params: list = []
    if entity_type:
        sql += " AND e.entity_type = ?"
        params.append(entity_type)
    if ruleset:
        sql += " AND e.ruleset = ?"
        params.append(ruleset)
    if terms:
        sql += (" AND e.id IN (SELECT entity_id FROM content_fts "
                "WHERE content_fts MATCH ?)")
        params.append(" ".join(terms))
    sql += " ORDER BY e.name LIMIT ?"
    params.append(limit * 4)                 # margen para filtrado Python

    results = []
    for row in conn.execute(sql, params).fetchall():
        data = json.loads(row["data"])
        if not _match_filters(data, filters):
            continue
        results.append({
            "id": row["id"], "entity_type": row["entity_type"],
            "name": row["name"], "ruleset": row["ruleset"],
            "source_id": row["source_id"],
            "summary": _summarize(data),
        })
        if len(results) >= limit:
            break
    return {"results": results, "parsed": {
        "type": entity_type, "terms": terms,
        "filters": filters, "ruleset": ruleset}}


def _summarize(data: dict) -> dict:
    """Campos clave según tipo para la lista de resultados."""
    out = {}
    for k in ("level", "school", "challenge_rating", "type", "rarity",
              "casting_time", "hit_points"):
        v = data.get(k)
        if isinstance(v, dict):
            v = v.get("name")
        if v is not None:
            out[k] = v
    return out


@router.get("/compare")
def compare(index: str):
    """Comparador de reglas: la misma entidad en 2014 vs 2024.

    El representante de cada ruleset es preferentemente la fuente
    redistribuible (SRD/Open5e); fuentes alternativas se listan en
    `alternates` para no mezclar schemas distintos en el diff."""
    conn = content_db()
    rows = conn.execute(
        "SELECT id, entity_type, name, ruleset, data, source_id, "
        "is_redistributable FROM content_entities WHERE id LIKE ? "
        "ORDER BY is_redistributable DESC, ruleset",
        (f"%:{index}",)).fetchall()
    versions = {}
    alternates = []
    for r in rows:
        entry = {
            "id": r["id"], "name": r["name"],
            "entity_type": r["entity_type"], "source_id": r["source_id"],
            "data": json.loads(r["data"]),
        }
        if r["ruleset"] not in versions:
            versions[r["ruleset"]] = entry
        else:
            alternates.append({k: entry[k] for k in
                               ("id", "name", "entity_type", "source_id")})
    # diff de primer nivel: claves que difieren entre ediciones
    diff = []
    if len(versions) > 1:
        datas = [v["data"] for v in versions.values()]
        for key in set().union(*(d.keys() for d in datas)):
            vals = {json.dumps(v["data"].get(key), sort_keys=True)
                    for v in versions.values()}
            if len(vals) > 1:
                diff.append(key)
    return {"index": index, "versions": versions,
            "alternates": alternates, "diff": sorted(diff)}


class HomebrewIn(BaseModel):
    entity_type: str
    name: str
    data: dict = {}
    ruleset: str = "dnd5e-2014"
    license: str = "user-created"
    redistributable: bool = True     # es contenido del propio usuario


@router.post("/homebrew", status_code=201)
def create_homebrew(body: HomebrewIn):
    """Contenido homebrew del usuario → content DB con su propia fuente."""
    import uuid
    from datetime import datetime, timezone
    conn = content_db()
    conn.execute(
        """INSERT OR IGNORE INTO content_sources
           (id, name, license, imported_at, distribution_allowed)
           VALUES ('homebrew', 'Contenido homebrew del usuario',
                   'user-created', ?, 1)""",
        (datetime.now(timezone.utc).isoformat(),))
    eid = f"homebrew:{uuid.uuid4().hex[:12]}"
    data = {**body.data, "name": body.name, "index": eid.split(":")[-1]}
    conn.execute(
        """INSERT INTO content_entities
           (id, entity_type, name, ruleset, source_id, license,
            is_redistributable, data)
           VALUES (?,?,?,?, 'homebrew', ?, ?, ?)""",
        (eid, body.entity_type, body.name, body.ruleset, body.license,
         int(body.redistributable), json.dumps(data, ensure_ascii=False)))
    conn.execute(
        "INSERT INTO content_fts (entity_id, name, body) VALUES (?,?,?)",
        (eid, body.name, json.dumps(data, ensure_ascii=False)))
    conn.commit()
    return {"id": eid}


@router.get("/options")
def options(entity_type: str, ruleset: str | None = None,
            source: str | None = None, all_sources: bool = False):
    """Opciones para el wizard: lista {id, name} de un tipo de entidad.
    'mixed' siempre incluido (contenido agnóstico de edición);
    por defecto solo fuentes redistribuibles (SRD/Open5e) para no
    saturar con ~130k entidades privadas — all_sources=true las incluye."""
    conn = content_db()
    sql = ("SELECT id, name, source_id FROM content_entities "
           "WHERE entity_type = ?")
    params: list = [entity_type]
    if ruleset:
        sql += " AND ruleset IN (?, 'mixed')"
        params.append(ruleset)
    if source:
        sql += " AND source_id = ?"
        params.append(source)
    if not all_sources:
        sql += " AND is_redistributable = 1"
    sql += " ORDER BY name"
    rows = conn.execute(sql, params).fetchall()
    return {"options": [dict(r) for r in rows]}


@router.get("/{entity_id:path}")
def get_entity(entity_id: str):
    conn = content_db()
    row = conn.execute(
        "SELECT * FROM content_entities WHERE id = ?", (entity_id,)
    ).fetchone()
    if row is None:
        return {"error": "not found"}
    out = dict(row)
    out["data"] = json.loads(out["data"])
    return out
