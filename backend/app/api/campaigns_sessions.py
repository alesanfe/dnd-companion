"""Sesiones, línea temporal, escenas y export — split de api/campaigns.py (AU-22)"""
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


@router.delete("/{campaign_id}/sessions/{session_id}")
def delete_session(campaign_id: str, session_id: str,
                   user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    cur = conn.execute(
        "DELETE FROM sessions WHERE id = ? AND campaign_id = ?",
        (session_id, campaign_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "session not found")
    return {"deleted": session_id}


class SessionIn(BaseModel):
    number: int | None = None
    title: str
    status: str = "prep"               # prep|active|done
    data: dict = {}


@router.post("/{campaign_id}/sessions", status_code=201)
def create_session(campaign_id: str, body: SessionIn,
                   user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
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
def list_sessions(campaign_id: str,
                  user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user)
    # escenas visibility=dm no se sirven a jugadores — el prep del DM
    # (notas, monstruos) no debe filtrarse a la mesa; en modo local
    # (sin owner) todo es visible
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, (user or {}).get("user_id")) \
        in _DM_ROLES
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
            [{**dict(x), "data": json.loads(x["data"])} for x in scenes
             if is_dm or x["visibility"] != "dm"],
            key=lambda x: x["data"].get("order", 0))
        out.append(s)
    return {"sessions": out}


class SessionPatch(BaseModel):
    status: str | None = None        # prep|active|done
    title: str | None = None


@router.patch("/{campaign_id}/sessions/{session_id}")
async def patch_session(campaign_id: str, session_id: str,
                        body: SessionPatch,
                        user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    if body.status and body.status not in ("prep", "active", "done"):
        raise HTTPException(400, "status inválido")
    sets, params = [], []
    if body.status:
        sets.append("status = ?")
        params.append(body.status)
    if body.title:
        sets.append("title = ?")
        params.append(body.title)
    if not sets:
        return {"id": session_id, "changed": []}
    sets.append("updated_at = ?")          # como toda escritura de estado
    params.append(datetime.now(timezone.utc).isoformat())
    cur = conn.execute(
        f"UPDATE sessions SET {', '.join(sets)} "
        "WHERE id = ? AND campaign_id = ?",
        (*params, session_id, campaign_id))
    # reveal_condition con evaluador real: 'session:<id>' o
    # 'session_active' se revelan cuando una sesión arranca —
    # sin esto el campo se guardaba y jamás se leía
    revealed: list[dict] = []
    if body.status == "active":
        rows = conn.execute(
            """SELECT id, name FROM campaign_entities
               WHERE campaign_id = ? AND visibility != 'public'
                 AND reveal_condition IN
                     ('session_active', ?)""",
            (campaign_id, f"session:{session_id}")).fetchall()
        if rows:
            now = datetime.now(timezone.utc).isoformat()
            ids = [r["id"] for r in rows]
            conn.execute(
                f"""UPDATE campaign_entities
                    SET visibility='public', revealed_at=?,
                        updated_at=?, version=version+1
                    WHERE id IN ({','.join('?' * len(ids))})""",
                (now, now, *ids))
            revealed = [dict(r) for r in rows]
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "session not found")
    for r in revealed:
        await _notify_reveal(conn, campaign_id, r["id"], r["name"])
    return {"id": session_id,
            "changed": [s.split(" = ")[0] for s in sets],
            "revealed": [r["id"] for r in revealed]}


@router.get("/{campaign_id}/timeline")
def timeline(campaign_id: str,
             user: dict | None = Depends(optional_user)):
    """Cronología del mundo: eventos + relaciones fechadas, ordenadas."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    # la línea temporal no filtra los eventos/relaciones del DM a
    # jugadores (misma regla que entities/relationships)
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, (user or {}).get("user_id")) \
        in _DM_ROLES
    events = conn.execute(
        "SELECT id, name, data, visibility FROM campaign_entities "
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
        if is_dm or e["visibility"] != "dm"
    ] + [
        {"kind": "relationship", "id": r["id"],
         "name": f"{r['from_id']} → {r['to_id']}",
         "world_date": r["world_date"], "data": dict(r)}
        for r in rels
        if is_dm or r["visibility"] != "dm"
    ]
    items.sort(key=lambda x: x["world_date"] or "")
    return {"timeline": items}


@router.post("/{campaign_id}/scenes/{scene_id}/start", status_code=201)
async def start_scene_combat(campaign_id: str, scene_id: str,
                             user: dict | None = Depends(optional_user)):
    """Inicia el combate preparado en una escena: crea el Combat con el
    nombre de la escena y añade los monstruos de data.monsters
    (content entity ids) como combatientes."""
    from ..domain.combat import Combat, Combatant
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
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
    from ..domain import statblock
    content = content_db()
    for mid in scene.get("monsters", []):
        crow = content.execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (mid,)).fetchone()
        data = json.loads(crow["data"]) if crow else {}
        block = statblock.normalize(data)
        combat.combatants.append(Combatant(
            id=uuid.uuid4().hex, kind="monster",
            name=data.get("name", "?"), ref_id=mid,
            initiative=(block or {}).get("initiative_mod", 0) + 10,
            hp_current=(block or {}).get("hp", 1),
            hp_max=(block or {}).get("hp", 1),
            ac=(block or {}).get("ac", 10),
            stat_block=block))
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO combats (id, campaign_id, name, ruleset, version,
                                data, updated_at)
           VALUES (?,?,?,?,1,?,?)""",
        (cid, campaign_id, combat.name, "dnd5e-2014",
         json.dumps(combat.model_dump()), now))
    conn.commit()
    # combat.started — mismo evento que POST /combat: sin él la sala
    # no se enteraba de que la escena arrancó un encuentro
    from ..domain.events import Event, EventType
    ev = Event(event_id=uuid.uuid4().hex,
               type=EventType.COMBAT_STARTED,
               campaign_id=campaign_id, aggregate_id=cid,
               aggregate_version=1,
               actor_id=(user or {}).get("user_id") or "dm",
               occurred_at=datetime.now(timezone.utc),
               payload={"combat_id": cid, "name": combat.name,
                        "scene_id": scene_id})
    conn.execute(
        """INSERT INTO events
           (event_id, campaign_id, aggregate_id, aggregate_version,
            actor_id, occurred_at, type, payload)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ev.event_id, campaign_id, cid, 1, ev.actor_id,
         ev.occurred_at.isoformat(), ev.type.value,
         json.dumps(ev.payload)))
    conn.commit()
    await manager.broadcast(campaign_id, ev)
    return {"combat_id": cid, "scene": name,
            "combatants": len(combat.combatants)}


@router.get("/{campaign_id}/events")
def campaign_events(campaign_id: str, limit: int = 100,
                    user: dict | None = Depends(optional_user)):
    """Feed de auditoría: todos los eventos de la campaña (tiradas,
    cambios de estado, revelaciones)."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    uid = (user or {}).get("user_id")
    # igual que en /state: las tiradas visibility=dm no se filtran a
    # jugadores por el feed de auditoría
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, uid) in _DM_ROLES
    # el filtrado de visibilidad es post-SQL: si los N últimos eventos
    # son dm-only, el jugador recibía menos de `limit` — sobre-muestrea
    # y recorta tras filtrar (mismo patrón que /operations/conflicts)
    rows = conn.execute(
        """SELECT event_id, type, aggregate_id, actor_id, occurred_at,
                  payload FROM events WHERE campaign_id = ?
           ORDER BY occurred_at DESC LIMIT ?""",
        (campaign_id, limit * 4)).fetchall()
    return {"events": [
        {**dict(r), "payload": json.loads(r["payload"])} for r in rows
        if _ev_visible(r, uid, is_dm)][:limit]}


@router.get("/{campaign_id}/export")
def export_campaign(campaign_id: str,
                    user: dict | None = Depends(optional_user)):
    """Backup completo de la campaña en JSON: entidades, miembros,
    sesiones, combates, personajes y eventos."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
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


@router.get("/{campaign_id}/export-vtt")
def export_vtt(campaign_id: str,
               user: dict | None = Depends(optional_user)):
    """Export neutral para VTTs (Foundry/Roll20/…): personajes y
    combatientes como actores genéricos {name, type, hp, ac, abilities,
    conditions, cr}. No es un schema propietario — cada VTT lo mapea
    con un importador."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    camp = conn.execute("SELECT id, name FROM campaigns WHERE id = ?",
                        (campaign_id,)).fetchone()
    if camp is None:
        raise HTTPException(404, "campaign not found")

    def actor(name, kind, d):
        ab = d.get("abilities") or {}
        return {
            "name": name,
            "type": "npc" if kind != "character" else "character",
            "hp": {"current": (d.get("hp") or {}).get("current",
                                d.get("hp_current", 1)),
                   "max": (d.get("hp") or {}).get("max",
                             d.get("hp_max", 1)),
                   "temp": (d.get("hp") or {}).get("temp",
                              d.get("hp_temp", 0))},
            "ac": (d.get("derived") or {}).get("ac") or
                  d.get("ac") or (d.get("stat_block") or {}).get("ac"),
            "abilities": ab,
            "level": sum(c.get("level", 1)
                         for c in d.get("classes", [])) or None,
            "conditions": d.get("conditions", []),
            "cr": (d.get("stat_block") or {}).get("cr"),
            "spells": d.get("spells_known") or None,
        }

    actors, combats_out = [], []
    for r in conn.execute(
            "SELECT name, data FROM characters WHERE campaign_id = ?",
            (campaign_id,)).fetchall():
        actors.append(actor(r["name"], "character", json.loads(r["data"])))
    for r in conn.execute(
            "SELECT name, data FROM combats WHERE campaign_id = ?",
            (campaign_id,)).fetchall():
        cb = json.loads(r["data"])
        cbt = {"name": cb.get("name"), "round": cb.get("round"),
               "combatants": [
                   {**actor(c.get("name"), c.get("kind", "monster"), c),
                    "initiative": c.get("initiative")}
                   for c in cb.get("combatants", [])]}
        combats_out.append(cbt)
        actors.extend(cbt["combatants"])

    # escenas/mapa: el estado táctico completo (grid, niebla, muros,
    # luz, plantillas) para que otro VTT reconstruya el tablero
    scenes = []
    for r in conn.execute(
            """SELECT name, data FROM campaign_entities
               WHERE campaign_id = ? AND kind = 'map'""",
            (campaign_id,)).fetchall():
        d = json.loads(r["data"])
        scenes.append({
            "name": r["name"],
            "cols": d.get("cols"), "rows": d.get("rows"),
            "cell_ft": d.get("cell_ft"),
            "background_image": d.get("image_url"),
            "ambient_music": d.get("music_url"),
            "fog": d.get("fog") or [],
            "walls": d.get("walls") or [],
            "marks": d.get("marks") or {},
            "pins": d.get("pins") or [],
            "tokens": [{
                "name": tk.get("name"), "x": tk.get("x"), "y": tk.get("y"),
                "size": tk.get("size", 1), "color": tk.get("color"),
                "hp": tk.get("hp"), "hp_max": tk.get("max_hp"),
                "vision_ft": tk.get("vision_ft"),
                "light_ft": tk.get("light_ft"),
                "image_url": tk.get("image_url"),
                "actor_ref": tk.get("ref_id"),
                "combatant_id": tk.get("combatant_id"),
                "player_id": tk.get("player_id"),
            } for tk in d.get("tokens", [])],
        })

    return {
        "format": "vtt-generic",
        "format_version": 2,
        "campaign": dict(camp),
        "actors": actors,
        "combats": combats_out,
        "scenes": scenes,
    }
