"""Combats — create/get. All mutations go through /api/operations
with entity_kind='combat'."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db
from ..domain.combat import Combat, hp_state
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
