"""Campaigns + invite codes. Skeleton — real-time sync lands via ws/rooms."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import member_role, optional_user
from ..db.connections import content_db, state_db
from ..domain.ruleset import Ruleset
from ..ws.rooms import manager

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    ruleset: Ruleset = Ruleset.DND5E_2014
    owner_id: str | None = None


@router.post("", status_code=201)
def create_campaign(body: CampaignCreate,
                    user: dict | None = Depends(optional_user)):
    conn = state_db()
    cid = uuid.uuid4().hex
    invite = secrets.token_urlsafe(6)
    now = datetime.now(timezone.utc).isoformat()
    owner = (user or {}).get("user_id") or body.owner_id
    conn.execute(
        """INSERT INTO campaigns
           (id, name, invite_code, ruleset, owner_id, data, created_at, updated_at)
           VALUES (?,?,?,?,?, '{}', ?, ?)""",
        (cid, body.name, invite, body.ruleset.value, owner, now, now),
    )
    if owner:
        conn.execute(
            "INSERT OR IGNORE INTO members "
            "(campaign_id, user_id, role, joined_at) VALUES (?,?,?,?)",
            (cid, owner, "owner", now))
    conn.commit()
    return {"id": cid, "invite_code": invite}


class JoinIn(BaseModel):
    invite_code: str
    user_id: str | None = None          # registra membresía si se pasa
    role: str = "player"


@router.post("/join")
def join_campaign(body: JoinIn,
                  user: dict | None = Depends(optional_user)):
    """Unirse a una campaña por código de invitación. Con token se
    registra como miembro con su rol (el token manda sobre user_id)."""
    conn = state_db()
    row = conn.execute(
        "SELECT id, name, ruleset FROM campaigns WHERE invite_code = ?",
        (body.invite_code,)).fetchone()
    if row is None:
        raise HTTPException(404, "campaign not found")
    uid = (user or {}).get("user_id") or body.user_id
    if uid:
        conn.execute(
            "INSERT OR IGNORE INTO members "
            "(campaign_id, user_id, role, joined_at) VALUES (?,?,?,?)",
            (row["id"], uid, body.role,
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
def create_entity(campaign_id: str, body: EntityIn,
                  user: dict | None = Depends(optional_user)):
    role = member_role(campaign_id, (user or {}).get("user_id"))
    if user is not None and role not in ("owner", "co_dm") \
            and body.visibility == "dm":
        raise HTTPException(
            403, "solo el DM puede crear entidades ocultas")
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
                  viewer: str | None = None,
                  user: dict | None = Depends(optional_user)):
    """Visibilidad por rol: owner/co_dm ven todo; el resto solo public
    + entidades donde su user_id está en known_to. Sin token, `viewer`
    controla la vista (modo local/anónimo)."""
    conn = state_db()
    uid = (user or {}).get("user_id")
    if user is not None:
        is_dm = member_role(campaign_id, uid) in ("owner", "co_dm")
        viewer_id = uid
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
async def reveal_entity(campaign_id: str, entity_id: str):
    """El DM revela la entidad a todos los jugadores — evento WS."""
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


class SessionPatch(BaseModel):
    status: str | None = None        # prep|active|done
    title: str | None = None


@router.patch("/{campaign_id}/sessions/{session_id}")
def patch_session(campaign_id: str, session_id: str, body: SessionPatch):
    conn = state_db()
    if body.status and body.status not in ("prep", "active", "done"):
        raise HTTPException(400, "status inválido")
    sets, params = [], []
    if body.status:
        sets.append("status = ?"); params.append(body.status)
    if body.title:
        sets.append("title = ?"); params.append(body.title)
    if not sets:
        return {"id": session_id, "changed": []}
    cur = conn.execute(
        f"UPDATE sessions SET {', '.join(sets)} "
        "WHERE id = ? AND campaign_id = ?",
        (*params, session_id, campaign_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "session not found")
    return {"id": session_id, "changed": sets}


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


@router.post("/{campaign_id}/scenes/{scene_id}/start", status_code=201)
def start_scene_combat(campaign_id: str, scene_id: str):
    """Inicia el combate preparado en una escena: crea el Combat con el
    nombre de la escena y añade los monstruos de data.monsters
    (content entity ids) como combatientes."""
    from ..domain.combat import Combat, Combatant
    conn = state_db()
    row = conn.execute(
        "SELECT data FROM campaign_entities WHERE id = ? AND campaign_id = ? "
        "AND kind = 'scene'", (scene_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "scene not found")
    scene = json.loads(row["data"])
    name = conn.execute(
        "SELECT name FROM campaign_entities WHERE id = ?",
        (scene_id,)).fetchone()["name"]
    combat = Combat(name=f"Escena: {name}", campaign_id=campaign_id)
    content = content_db()
    for mid in scene.get("monsters", []):
        crow = content.execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (mid,)).fetchone()
        data = json.loads(crow["data"]) if crow else {}
        dex = data.get("dexterity", 10)
        acs = data.get("armor_class") or []
        combat.combatants.append(Combatant(
            id=uuid.uuid4().hex, kind="monster",
            name=data.get("name", "?"), ref_id=mid,
            initiative=(dex - 10) // 2 + 10,
            hp_current=data.get("hit_points", 1),
            hp_max=data.get("hit_points", 1),
            ac=acs[0].get("value", 10) if acs else 10,
            stat_block=data or None))
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO combats (id, campaign_id, name, ruleset, version,
                                data, updated_at)
           VALUES (?,?,?,?,1,?,?)""",
        (cid, campaign_id, combat.name, "dnd5e-2014",
         json.dumps(combat.model_dump()), now))
    conn.commit()
    return {"combat_id": cid, "scene": name,
            "combatants": len(combat.combatants)}


@router.get("/{campaign_id}/events")
def campaign_events(campaign_id: str, limit: int = 100):
    """Feed de auditoría: todos los eventos de la campaña (tiradas,
    cambios de estado, revelaciones)."""
    conn = state_db()
    rows = conn.execute(
        """SELECT event_id, type, aggregate_id, actor_id, occurred_at,
                  payload FROM events WHERE campaign_id = ?
           ORDER BY occurred_at DESC LIMIT ?""",
        (campaign_id, limit)).fetchall()
    return {"events": [
        {**dict(r), "payload": json.loads(r["payload"])} for r in rows]}


@router.get("/{campaign_id}/export")
def export_campaign(campaign_id: str):
    """Backup completo de la campaña en JSON: entidades, miembros,
    sesiones, combates, personajes y eventos."""
    conn = state_db()
    def rows(table, where="campaign_id = ?"):
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE {where}",
            (campaign_id,)).fetchall()]
    camp = conn.execute("SELECT * FROM campaigns WHERE id = ?",
                        (campaign_id,)).fetchone()
    if camp is None:
        raise HTTPException(404, "campaign not found")
    return {
        "format": "dnd-companion-campaign",
        "format_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "campaign": dict(camp),
        "members": rows("members"),
        "entities": rows("campaign_entities"),
        "relationships": rows("relationships"),
        "sessions": rows("sessions"),
        "combats": rows("combats"),
        "characters": rows("characters"),
        "events": rows("events"),
    }


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
