"""Campaigns + invite codes. Skeleton — real-time sync lands via ws/rooms."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db
from ..domain.ruleset import Ruleset
from ..ws.rooms import manager

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    ruleset: Ruleset = Ruleset.DND5E_2014
    owner_id: str | None = None


@router.post("", status_code=201)
def create_campaign(body: CampaignCreate):
    conn = state_db()
    cid = uuid.uuid4().hex
    invite = secrets.token_urlsafe(6)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO campaigns
           (id, name, invite_code, ruleset, owner_id, data, created_at, updated_at)
           VALUES (?,?,?,?,?, '{}', ?, ?)""",
        (cid, body.name, invite, body.ruleset.value, body.owner_id, now, now),
    )
    conn.commit()
    return {"id": cid, "invite_code": invite}


class JoinIn(BaseModel):
    invite_code: str
    user_id: str | None = None          # registra membresía si se pasa
    role: str = "player"


@router.post("/join")
def join_campaign(body: JoinIn):
    """Unirse a una campaña por código de invitación. Si llega user_id,
    queda registrado como miembro con su rol."""
    conn = state_db()
    row = conn.execute(
        "SELECT id, name, ruleset FROM campaigns WHERE invite_code = ?",
        (body.invite_code,)).fetchone()
    if row is None:
        raise HTTPException(404, "campaign not found")
    if body.user_id:
        conn.execute(
            "INSERT OR IGNORE INTO members "
            "(campaign_id, user_id, role, joined_at) VALUES (?,?,?,?)",
            (row["id"], body.user_id, body.role,
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return {"id": row["id"], "name": row["name"], "ruleset": row["ruleset"]}


@router.get("/{campaign_id}/members")
def list_members(campaign_id: str):
    conn = state_db()
    rows = conn.execute(
        "SELECT user_id, role, joined_at FROM members "
        "WHERE campaign_id = ?", (campaign_id,)).fetchall()
    return {"members": [dict(r) for r in rows]}


@router.get("/{campaign_id}/state")
def campaign_state(campaign_id: str):
    """Snapshot para resync tras reconexión: personajes + combate activo
    + últimos eventos."""
    conn = state_db()
    chars = conn.execute(
        "SELECT id, name, ruleset, version, data FROM characters "
        "WHERE campaign_id = ?", (campaign_id,)).fetchall()
    combats = conn.execute(
        "SELECT id, name, version, data FROM combats WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    events = conn.execute(
        "SELECT * FROM events WHERE campaign_id = ? "
        "ORDER BY occurred_at DESC LIMIT 50", (campaign_id,)).fetchall()
    return {
        "characters": [{**dict(c), "data": json.loads(c["data"])}
                       for c in chars],
        "combats": [{**dict(c), "data": json.loads(c["data"])}
                    for c in combats],
        "events": [dict(e) for e in events],
    }


# --- Entidades de campaña: NPC, lugares, misiones, escenas, notas ----
# Visibilidad: 'public' (todos), 'dm' (solo DM) o parcial via known_to.

class EntityIn(BaseModel):
    kind: str                          # npc|location|quest|faction|scene|note
    name: str
    data: dict = {}
    visibility: str = "public"         # public|dm
    known_to: list[str] = []           # player/user ids con info parcial
    reveal_condition: str | None = None


@router.post("/{campaign_id}/entities", status_code=201)
def create_entity(campaign_id: str, body: EntityIn):
    conn = state_db()
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
    return {"id": eid}


@router.get("/{campaign_id}/entities")
def list_entities(campaign_id: str, kind: str | None = None,
                  viewer: str = "dm"):
    """viewer='dm' ve todo; viewer='player' solo public + known_to."""
    conn = state_db()
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
        if viewer != "dm" and e["visibility"] == "dm" \
                and viewer not in e["known_to"]:
            continue
        out.append(e)
    return {"entities": out}


@router.post("/{campaign_id}/entities/{entity_id}/reveal")
def reveal_entity(campaign_id: str, entity_id: str):
    """El DM revela la entidad a todos los jugadores."""
    conn = state_db()
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
    return {"id": entity_id, "visibility": "public"}


# --- Grafo de relaciones --------------------------------------------

class RelationshipIn(BaseModel):
    from_id: str
    to_id: str
    type: str                          # knows|works_for|hates|family|...
    description: str | None = None
    visibility: str = "dm"
    world_date: str | None = None


@router.post("/{campaign_id}/relationships", status_code=201)
def create_relationship(campaign_id: str, body: RelationshipIn):
    conn = state_db()
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
def list_relationships(campaign_id: str, entity_id: str | None = None):
    conn = state_db()
    sql = "SELECT * FROM relationships WHERE campaign_id = ?"
    params: list = [campaign_id]
    if entity_id:
        sql += " AND (from_id = ? OR to_id = ?)"
        params += [entity_id, entity_id]
    rows = conn.execute(sql, params).fetchall()
    return {"relationships": [dict(r) for r in rows]}


class EntityPatch(BaseModel):
    name: str | None = None
    data: dict | None = None
    visibility: str | None = None
    known_to: list[str] | None = None
    reveal_condition: str | None = None


@router.patch("/{campaign_id}/entities/{entity_id}")
def patch_entity(campaign_id: str, entity_id: str, body: EntityPatch):
    """Actualiza campos de una entidad (orden de escena, estado, notas…)."""
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM campaign_entities WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "entity not found")
    sets, params = [], []
    if body.name is not None:
        sets.append("name = ?"); params.append(body.name)
    if body.data is not None:
        merged = {**json.loads(row["data"]), **body.data}
        sets.append("data = ?"); params.append(json.dumps(merged))
    if body.visibility is not None:
        sets.append("visibility = ?"); params.append(body.visibility)
    if body.known_to is not None:
        sets.append("known_to = ?"); params.append(json.dumps(body.known_to))
    if body.reveal_condition is not None:
        sets.append("reveal_condition = ?")
        params.append(body.reveal_condition)
    if not sets:
        return {"id": entity_id, "changed": []}
    sets += ["updated_at = ?", "version = version + 1"]
    params += [datetime.now(timezone.utc).isoformat(), entity_id]
    conn.execute(
        f"UPDATE campaign_entities SET {', '.join(sets)} WHERE id = ?",
        params)
    conn.commit()
    return {"id": entity_id,
            "changed": [s.split(" = ")[0] for s in sets[:-2]]}


# --- Sesiones y línea temporal ---------------------------------------

class SessionIn(BaseModel):
    number: int | None = None
    title: str
    status: str = "prep"               # prep|active|done
    data: dict = {}


@router.post("/{campaign_id}/sessions", status_code=201)
def create_session(campaign_id: str, body: SessionIn):
    conn = state_db()
    sid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO sessions
           (id, campaign_id, number, title, status, data, created_at,
            updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (sid, campaign_id, body.number, body.title, body.status,
         json.dumps(body.data), now, now))
    conn.commit()
    return {"id": sid}


@router.get("/{campaign_id}/sessions")
def list_sessions(campaign_id: str):
    conn = state_db()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE campaign_id = ? ORDER BY number",
        (campaign_id,)).fetchall()
    out = []
    for r in rows:
        s = dict(r)
        s["data"] = json.loads(s["data"])
        # escenas vinculadas a esta sesión, ordenadas
        scenes = conn.execute(
            "SELECT id, name, data, visibility FROM campaign_entities "
            "WHERE campaign_id = ? AND kind = 'scene' "
            "AND json_extract(data, '$.session_id') = ?",
            (campaign_id, s["id"])).fetchall()
        s["scenes"] = sorted(
            [{**dict(x), "data": json.loads(x["data"])} for x in scenes],
            key=lambda x: x["data"].get("order", 0))
        out.append(s)
    return {"sessions": out}


@router.get("/{campaign_id}/timeline")
def timeline(campaign_id: str):
    """Cronología del mundo: eventos + relaciones fechadas, ordenadas."""
    conn = state_db()
    events = conn.execute(
        "SELECT id, name, data FROM campaign_entities "
        "WHERE campaign_id = ? AND kind = 'event'", (campaign_id,)
    ).fetchall()
    rels = conn.execute(
        "SELECT * FROM relationships WHERE campaign_id = ? "
        "AND world_date IS NOT NULL", (campaign_id,)).fetchall()
    items = [
        {"kind": "event", "id": e["id"], "name": e["name"],
         "world_date": json.loads(e["data"]).get("world_date"),
         "data": json.loads(e["data"])}
        for e in events
    ] + [
        {"kind": "relationship", "id": r["id"],
         "name": f"{r['from_id']} → {r['to_id']}",
         "world_date": r["world_date"], "data": dict(r)}
        for r in rels
    ]
    items.sort(key=lambda x: x["world_date"] or "")
    return {"timeline": items}


# --- Solicitud de tirada (DM -> jugador) -----------------------------

class RollRequestIn(BaseModel):
    character_id: str
    expression: str = "1d20"
    reason: str = ""                   # 'tirada de percepción', 'save de SAB'
    secret: bool = False               # tirada oculta al resto


@router.post("/{campaign_id}/roll-request", status_code=202)
async def request_roll(campaign_id: str, body: RollRequestIn):
    """El DM pide una tirada; llega como evento a la sala WS."""
    from ..domain.events import Event, EventType
    event = Event(
        event_id=uuid.uuid4().hex,
        type=EventType.ROLL_REQUESTED,
        campaign_id=campaign_id,
        aggregate_id=body.character_id,
        aggregate_version=0,
        actor_id="dm",
        occurred_at=datetime.now(timezone.utc),
        payload={"expression": body.expression, "reason": body.reason,
                 "secret": body.secret},
    )
    conn = state_db()
    conn.execute(
        """INSERT INTO events
           (event_id, campaign_id, aggregate_id, aggregate_version,
            actor_id, occurred_at, type, payload)
           VALUES (?,?,?,?,?,?,?,?)""",
        (event.event_id, campaign_id, event.aggregate_id,
         event.aggregate_version, event.actor_id,
         event.occurred_at.isoformat(), event.type.value,
         json.dumps(event.payload)))
    conn.commit()
    await manager.broadcast(campaign_id, event)
    return {"event_id": event.event_id}
