"""Content search over the rules DB (FTS5). Each hit carries provenance."""
from __future__ import annotations

import json

from fastapi import APIRouter, Query

from ..db.connections import content_db

router = APIRouter(prefix="/api/content", tags=["content"])


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    entity_type: str | None = None,
    ruleset: str | None = None,
    limit: int = Query(20, le=100),
):
    conn = content_db()
    sql = """
        SELECT e.id, e.entity_type, e.name, e.ruleset, e.license,
               e.is_redistributable, e.source_id,
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
    sql += " LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return {"results": [dict(r) for r in rows]}


@router.get("/options")
def options(entity_type: str, ruleset: str | None = None):
    """Opciones para el wizard: lista {id, name} de un tipo de entidad."""
    conn = content_db()
    sql = ("SELECT id, name FROM content_entities WHERE entity_type = ?")
    params: list = [entity_type]
    if ruleset:
        sql += " AND ruleset = ?"
        params.append(ruleset)
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
