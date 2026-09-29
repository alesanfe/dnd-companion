"""Combats — create/get. All mutations go through /api/operations
with entity_kind='combat'."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import member_role, optional_user
from .campaigns import _DM_ROLES, _has_owner, _require_role
from ..db.connections import state_db
from ..domain.combat import Combat, Combatant, hp_state
from ..domain.ruleset import Ruleset

router = APIRouter(prefix="/api/combat", tags=["combat"])


class CombatCreate(BaseModel):
    name: str = "Encuentro"
    campaign_id: str | None = None
    ruleset: Ruleset = Ruleset.DND5E_2014


@router.post("", status_code=201)
async def create_combat(body: CombatCreate,
                        user: dict | None = Depends(optional_user)):
    conn = state_db()
    # crear un encuentro en campaña con dueño es cosa del DM
    if body.campaign_id:
        _require_role(conn, body.campaign_id, user, _DM_ROLES)
    cid = uuid.uuid4().hex
    combat = Combat(name=body.name, campaign_id=body.campaign_id,
                    ruleset=body.ruleset.value)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO combats (id, campaign_id, name, ruleset, version,
                                data, updated_at)
           VALUES (?,?,?,?,1,?,?)""",
        (cid, body.campaign_id, body.name, body.ruleset.value,
         json.dumps(combat.model_dump()), now))
    conn.commit()
    # evento combat.started — declarado en EventType pero nunca se
    # emitía: los sockets de la sala refrescan al empezar el encuentro
    if body.campaign_id:
        from ..domain.events import Event, EventType
        from ..ws.rooms import manager
        ev = Event(event_id=uuid.uuid4().hex,
                   type=EventType.COMBAT_STARTED,
                   campaign_id=body.campaign_id, aggregate_id=cid,
                   aggregate_version=1,
                   actor_id=(user or {}).get("user_id") or "dm",
                   occurred_at=datetime.now(timezone.utc),
                   payload={"combat_id": cid, "name": body.name})
        conn.execute(
            """INSERT INTO events
               (event_id, campaign_id, aggregate_id, aggregate_version,
                actor_id, occurred_at, type, payload)
               VALUES (?,?,?,?,?,?,?,?)""",
            (ev.event_id, body.campaign_id, cid, 1, ev.actor_id,
             ev.occurred_at.isoformat(), ev.type.value,
             json.dumps(ev.payload)))
        conn.commit()
        await manager.broadcast(body.campaign_id, ev)
    return {"id": cid, "version": 1}


@router.delete("/{combat_id}")
def delete_combat(combat_id: str,
                  user: dict | None = Depends(optional_user)):
    conn = state_db()
    row = conn.execute("SELECT campaign_id FROM combats WHERE id = ?",
                       (combat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "combat not found")
    if row["campaign_id"]:
        _require_role(conn, row["campaign_id"], user, _DM_ROLES)
    conn.execute("DELETE FROM combats WHERE id = ?", (combat_id,))
    conn.commit()
    return {"deleted": combat_id}


@router.post("/{combat_id}/add-party")
async def add_party(combat_id: str,
                    user: dict | None = Depends(optional_user)):
    """Añade todos los personajes de la campaña del combate como
    combatientes — cada alta es una op combatant.add real:
    iniciativa tirada (d20+DES), PG de ficha, auditable, deshacible
    y con broadcast a la sala."""
    from ..domain.character import Character
    from ..engine.dice import roll
    from ..ws.rooms import manager
    from .operations import OperationIn, apply_to_store
    conn = state_db()
    row = conn.execute("SELECT data, campaign_id FROM combats WHERE id = ?",
                       (combat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "combat not found")
    if not row["campaign_id"]:
        raise HTTPException(400, "el combate no pertenece a una campaña")
    campaign_id = row["campaign_id"]
    _require_role(conn, campaign_id, user, _DM_ROLES)
    uid = (user or {}).get("user_id") or "dm"
    combat = Combat(**json.loads(row["data"]))
    existing = {c.ref_id for c in combat.combatants}
    chars = conn.execute(
        "SELECT id, data FROM characters WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    added = 0
    for cr in chars:
        if cr["id"] in existing:
            continue
        ch = Character(**json.loads(cr["data"]))
        cur = conn.execute(
            "SELECT version FROM combats WHERE id = ?",
            (combat_id,)).fetchone()["version"]
        result = apply_to_store(OperationIn(
            operation_id=uuid.uuid4().hex, entity_id=combat_id,
            entity_version=cur, client_id="api:add-party",
            user_id=uid, operation_type="combatant.add",
            entity_kind="combat",
            payload={
                "kind": "character", "ref_id": cr["id"],
                "name": ch.name,
                # combatant.add tira 1d20+initiative_mod del bloque;
                # para PJs el mod es DES de la ficha
                "initiative":
                    roll("1d20").total + ch.abilities.modifier("dex"),
            }))
        for event in result.pop("_event_objs", []):
            await manager.broadcast(campaign_id, event)
        added += 1
    return {"added": added}


@router.post("/{combat_id}/award-xp")
async def award_xp(combat_id: str,
                   user: dict | None = Depends(optional_user)):
    """Reparto de XP al cerrar el encuentro: suma el CR de los monstruos
    caídos (a 0 PG o marcados muertos) y lo divide entre los PJs — cada
    parte es una op `character.xp.add` real: auditable, deshacible y con
    broadcast a la sala."""
    from ..domain.xp import cr_to_xp
    from ..ws.rooms import manager
    from .operations import OperationIn, apply_to_store
    conn = state_db()
    row = conn.execute("SELECT data, campaign_id FROM combats WHERE id = ?",
                       (combat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "combat not found")
    if row["campaign_id"]:
        _require_role(conn, row["campaign_id"], user, _DM_ROLES)
    combat = Combat(**json.loads(row["data"]))
    total = 0
    for c in combat.combatants:
        if c.kind == "character" or not c.stat_block:
            continue
        dead = c.hp_current <= 0 or any(
            x.strip().lower() in ("muerto", "muerta", "dead")
            for x in c.conditions)
        if dead:
            total += cr_to_xp(c.stat_block.get("cr", 0))
    pjs = [c for c in combat.combatants
           if c.kind == "character" and c.ref_id]
    if total <= 0 or not pjs:
        return {"total_xp": total, "per_player": 0, "awarded": 0}
    share = total // len(pjs)
    awarded = 0
    for c in pjs:
        vrow = conn.execute("SELECT version FROM characters WHERE id = ?",
                            (c.ref_id,)).fetchone()
        if not vrow:
            continue
        result = apply_to_store(OperationIn(
            operation_id=uuid.uuid4().hex, entity_id=c.ref_id,
            entity_version=vrow["version"], client_id="api:award-xp",
            user_id=(user or {}).get("user_id") or "dm",
            operation_type="character.xp.add",
            entity_kind="character", payload={"amount": share}))
        for event in result.pop("_event_objs", []):
            if row["campaign_id"]:
                await manager.broadcast(row["campaign_id"], event)
        awarded += 1
    return {"total_xp": total, "per_player": share, "awarded": awarded}


@router.get("")
def list_combats(campaign_id: str | None = None,
                 status: str | None = None,
                 user: dict | None = Depends(optional_user)):
    """Combates activos/pasados — el DM reabre el tracker desde aquí."""
    conn = state_db()
    if campaign_id:
        _require_role(conn, campaign_id, user)
    sql = ("SELECT id, name, campaign_id, ruleset, version, updated_at "
           "FROM combats WHERE 1=1")
    params: list = []
    if campaign_id:
        sql += " AND campaign_id = ?"
        params.append(campaign_id)
    else:
        # sin filtro: solo combates locales o de campañas donde el
        # usuario es miembro — no listar los de mesas ajenas
        uid = (user or {}).get("user_id")
        if uid:
            sql += """ AND (campaign_id IS NULL OR campaign_id IN
                       (SELECT campaign_id FROM members
                        WHERE user_id = ?))"""
            params.append(uid)
        else:
            sql += " AND campaign_id IS NULL"
    if status:
        sql += " AND json_extract(data,'$.status') = ?"
        params.append(status)
    sql += " ORDER BY updated_at DESC"
    return {"combats": [dict(r) for r in
                        conn.execute(sql, params).fetchall()]}


@router.get("/{combat_id}")
def get_combat(combat_id: str, reveal_hp: bool = True,
               user: dict | None = Depends(optional_user)):
    """reveal_hp=false devuelve la vista de jugador (estados, sin números)."""
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM combats WHERE id = ?", (combat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "combat not found")
    if row["campaign_id"] and _has_owner(conn, row["campaign_id"]):
        _require_role(conn, row["campaign_id"], user)
        # los PG son información del DM — la vista de jugador los
        # oculta (solo en campañas con dueño; modo local queda abierto)
        if member_role(row["campaign_id"],
                       (user or {}).get("user_id")) not in _DM_ROLES:
            reveal_hp = False
    combat = Combat(**json.loads(row["data"]))
    out = combat.model_dump()
    if not reveal_hp:
        for i, c in enumerate(combat.combatants):
            out["combatants"][i]["hp_state"] = hp_state(c)
            for k in ("hp_current", "hp_max", "hp_temp", "stat_block"):
                out["combatants"][i][k] = None
    return {"id": combat_id, "version": row["version"], "combat": out}
