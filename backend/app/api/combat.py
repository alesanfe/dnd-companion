"""Combats — create/get. All mutations go through /api/operations
with entity_kind='combat'."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db
from ..domain.combat import Combat, Combatant, hp_state
from ..domain.ruleset import Ruleset

router = APIRouter(prefix="/api/combat", tags=["combat"])


class CombatCreate(BaseModel):
    name: str = "Encuentro"
    campaign_id: str | None = None
    ruleset: Ruleset = Ruleset.DND5E_2014


@router.post("", status_code=201)
def create_combat(body: CombatCreate):
    conn = state_db()
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
    return {"id": cid, "version": 1}


@router.delete("/{combat_id}")
def delete_combat(combat_id: str):
    conn = state_db()
    cur = conn.execute("DELETE FROM combats WHERE id = ?", (combat_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "combat not found")
    return {"deleted": combat_id}


@router.post("/{combat_id}/add-party")
def add_party(combat_id: str):
    """Añade todos los personajes de la campaña del combate como
    combatientes (con su HP real de ficha)."""
    conn = state_db()
    row = conn.execute("SELECT data, campaign_id FROM combats WHERE id = ?",
                       (combat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "combat not found")
    combat = Combat(**json.loads(row["data"]))
    if not row["campaign_id"]:
        raise HTTPException(400, "el combate no pertenece a una campaña")
    chars = conn.execute(
        "SELECT id, data FROM characters WHERE campaign_id = ?",
        (row["campaign_id"],)).fetchall()
    from ..domain.character import Character
    added = 0
    existing = {c.ref_id for c in combat.combatants}
    for cr in chars:
        if cr["id"] in existing:
            continue
        ch = Character(**json.loads(cr["data"]))
        combat.combatants.append(Combatant(
            id=uuid.uuid4().hex, kind="character", name=ch.name,
            ref_id=cr["id"], initiative=ch.abilities.modifier("dex"),
            hp_current=ch.hp.current, hp_max=ch.hp.max,
            hp_temp=ch.hp.temp))
        added += 1
    conn.execute(
        "UPDATE combats SET data = ?, version = version + 1, "
        "updated_at = ? WHERE id = ?",
        (json.dumps(combat.model_dump()),
         datetime.now(timezone.utc).isoformat(), combat_id))
    conn.commit()
    return {"added": added}


@router.get("")
def list_combats(campaign_id: str | None = None,
                 status: str | None = None):
    """Combates activos/pasados — el DM reabre el tracker desde aquí."""
    conn = state_db()
    sql = ("SELECT id, name, campaign_id, ruleset, version, updated_at "
           "FROM combats WHERE 1=1")
    params: list = []
    if campaign_id:
        sql += " AND campaign_id = ?"; params.append(campaign_id)
    if status:
        sql += " AND json_extract(data,'$.status') = ?"
        params.append(status)
    sql += " ORDER BY updated_at DESC"
    return {"combats": [dict(r) for r in
                        conn.execute(sql, params).fetchall()]}


@router.get("/{combat_id}")
def get_combat(combat_id: str, reveal_hp: bool = True):
    """reveal_hp=false devuelve la vista de jugador (estados, sin números)."""
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM combats WHERE id = ?", (combat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "combat not found")
    combat = Combat(**json.loads(row["data"]))
    out = combat.model_dump()
    if not reveal_hp:
        for i, c in enumerate(combat.combatants):
            out["combatants"][i]["hp_state"] = hp_state(c)
            for k in ("hp_current", "hp_max", "hp_temp", "stat_block"):
                out["combatants"][i][k] = None
    return {"id": combat_id, "version": row["version"], "combat": out}
