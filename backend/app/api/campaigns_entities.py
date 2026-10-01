"""Entidades de campaña (notas, mapas, PNJs…) y relaciones — split de api/campaigns.py (AU-22)"""
from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ._campaign_access import (
    _DM_ROLES, _ev_for_uid, _ev_is_dm, _ev_visible, _has_owner,
    _notify_entity, _notify_reveal, _require_role,
)
from .auth import member_role, optional_user
from ..db.connections import content_db, state_db
from ..ws.rooms import manager

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


@router.delete("/{campaign_id}/entities/{entity_id}")
async def delete_entity(campaign_id: str, entity_id: str,
                  user: dict | None = Depends(optional_user)):
    """Borra una entidad de campaña (y sus relaciones)."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    row = conn.execute(
        "SELECT name, kind, visibility FROM campaign_entities "
        "WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "entity not found")
    conn.execute(
        "DELETE FROM campaign_entities WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id))
    conn.execute(
        "DELETE FROM relationships WHERE campaign_id = ? "
        "AND (from_id = ? OR to_id = ?)",
        (campaign_id, entity_id, entity_id))
    conn.commit()
    await _notify_entity(campaign_id, entity_id, ["deleted"],
                         row["visibility"], row["kind"], row["name"])
    return {"deleted": entity_id}


class EntityIn(BaseModel):
    kind: str                          # npc|location|quest|faction|scene|note
    name: str
    data: dict = {}
    visibility: str = "public"         # public|dm
    known_to: list[str] = []           # player/user ids con info parcial
    reveal_condition: str | None = None


@router.post("/{campaign_id}/entities", status_code=201)
async def create_entity(campaign_id: str, body: EntityIn,
                  user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user)
    role = member_role(campaign_id, (user or {}).get("user_id"))
    if role is not None and role not in ("owner", "co_dm") \
            and body.visibility == "dm":
        raise HTTPException(
            403, "solo el DM puede crear entidades ocultas")
    eid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO campaign_entities
           (id, campaign_id, kind, name, data, visibility, known_to,
            reveal_condition, version, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
        (eid, campaign_id, body.kind, body.name, json.dumps(body.data),
         body.visibility, json.dumps(body.known_to),
         body.reveal_condition, now, now))
    conn.commit()
    await _notify_entity(campaign_id, eid, ["created"],
                         body.visibility, body.kind, body.name)
    return {"id": eid}


@router.get("/{campaign_id}/entities")
def list_entities(campaign_id: str, kind: str | None = None,
                  viewer: str | None = None,
                  user: dict | None = Depends(optional_user)):
    """Visibilidad por rol: owner/co_dm ven todo; el resto solo public
    + entidades donde su user_id está en known_to. Sin token, `viewer`
    controla la vista (modo local/anónimo)."""
    conn = state_db()
    # membresía primero: sin el guard un extraño veía al menos las
    # entidades públicas de una mesa ajena
    _require_role(conn, campaign_id, user)
    uid = (user or {}).get("user_id")
    if user is not None:
        is_dm = member_role(campaign_id, uid) in ("owner", "co_dm")
        viewer_id = uid
    elif _has_owner(conn, campaign_id):
        # con dueño, un anónimo nunca es DM — solo ve lo público
        is_dm, viewer_id = False, ""
    else:
        is_dm = (viewer or "dm") == "dm"  # compat modo local
        viewer_id = viewer or "dm"
    sql = "SELECT * FROM campaign_entities WHERE campaign_id = ?"
    params: list = [campaign_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        e = dict(r)
        e["data"] = json.loads(e["data"])
        e["known_to"] = json.loads(e["known_to"])
        if not is_dm and e["visibility"] == "dm" \
                and viewer_id not in e["known_to"]:
            continue
        out.append(e)
    return {"entities": out}


@router.post("/{campaign_id}/entities/{entity_id}/reveal")
async def reveal_entity(campaign_id: str, entity_id: str,
                        user: dict | None = Depends(optional_user)):
    """El DM revela la entidad a todos los jugadores — evento WS."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """UPDATE campaign_entities
           SET visibility='public', revealed_at=?, updated_at=?,
               version=version+1
           WHERE id=? AND campaign_id=?""",
        (now, now, entity_id, campaign_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "entity not found")
    name = conn.execute("SELECT name FROM campaign_entities WHERE id = ?",
                        (entity_id,)).fetchone()["name"]
    from ..domain.events import Event, EventType
    ev = Event(event_id=uuid.uuid4().hex,
               type=EventType.ENTITY_REVEALED,
               campaign_id=campaign_id, aggregate_id=entity_id,
               aggregate_version=0, actor_id="dm",
               occurred_at=datetime.now(timezone.utc),
               payload={"name": name})
    conn.execute(
        """INSERT INTO events
           (event_id, campaign_id, aggregate_id, aggregate_version,
            actor_id, occurred_at, type, payload)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ev.event_id, campaign_id, entity_id, 0, "dm",
         ev.occurred_at.isoformat(), ev.type.value,
         json.dumps(ev.payload)))
    conn.commit()
    await manager.broadcast(campaign_id, ev)
    return {"id": entity_id, "visibility": "public"}


class RelationshipIn(BaseModel):
    from_id: str
    to_id: str
    type: str                          # knows|works_for|hates|family|...
    description: str | None = None
    visibility: str = "dm"
    world_date: str | None = None


@router.post("/{campaign_id}/relationships", status_code=201)
def create_relationship(campaign_id: str, body: RelationshipIn,
                        user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    rid = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO relationships
           (id, campaign_id, from_id, to_id, type, description,
            visibility, world_date, status, created_at)
           VALUES (?,?,?,?,?,?,?,?, 'active', ?)""",
        (rid, campaign_id, body.from_id, body.to_id, body.type,
         body.description, body.visibility, body.world_date,
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return {"id": rid}


@router.get("/{campaign_id}/relationships")
def list_relationships(campaign_id: str, entity_id: str | None = None,
                       viewer: str | None = None,
                       user: dict | None = Depends(optional_user)):
    """Mismo filtro que las entidades: un jugador solo ve las
    relaciones públicas — las de DM no se filtran."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    uid = (user or {}).get("user_id")
    if user is not None:
        is_dm = member_role(campaign_id, uid) in ("owner", "co_dm")
    else:
        # ?viewer solo vale en modo local; con dueño, anónimo ≠ DM
        is_dm = not _has_owner(conn, campaign_id) \
            and (viewer or "dm") == "dm"
    sql = "SELECT * FROM relationships WHERE campaign_id = ?"
    params: list = [campaign_id]
    if entity_id:
        sql += " AND (from_id = ? OR to_id = ?)"
        params += [entity_id, entity_id]
    if not is_dm:
        sql += " AND visibility != 'dm'"
    rows = conn.execute(sql, params).fetchall()
    return {"relationships": [dict(r) for r in rows]}


@router.delete("/{campaign_id}/relationships/{rel_id}", status_code=204)
def delete_relationship(campaign_id: str, rel_id: str,
                        user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    cur = conn.execute(
        "DELETE FROM relationships WHERE id = ? AND campaign_id = ?",
        (rel_id, campaign_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "relationship not found")
