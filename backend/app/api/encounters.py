"""Encounter difficulty calculator — XP thresholds + multipliers
(reglas 2014, DMG). Input: niveles del grupo + CRs de monstruos."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db
from ..domain.xp import (cr_to_xp, encounter_multiplier,
                         encounter_threshold)

router = APIRouter(prefix="/api/encounters", tags=["encounters"])


class EncounterIn(BaseModel):
    party_levels: list[int]
    monster_crs: list[str]               # ["1/4", "1/2", "2"]


@router.post("/difficulty")
def difficulty(body: EncounterIn):
    budget = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for lvl in body.party_levels:
        for k, v in zip(budget, encounter_threshold(lvl)):
            budget[k] += v

    raw_xp = sum(cr_to_xp(cr) for cr in body.monster_crs)
    adj_xp = int(raw_xp * encounter_multiplier(len(body.monster_crs)))

    if adj_xp >= budget["deadly"]:
        rating = "deadly"
    elif adj_xp >= budget["hard"]:
        rating = "hard"
    elif adj_xp >= budget["medium"]:
        rating = "medium"
    elif adj_xp >= budget["easy"]:
        rating = "easy"
    else:
        rating = "trivial"

    warnings = []
    if len(body.monster_crs) > len(body.party_levels) * 2:
        warnings.append("economía de acciones: muchos enemigos por personaje")
    if body.party_levels and max(body.party_levels) - min(body.party_levels) > 3:
        warnings.append("gran dispersión de niveles en el grupo")

    return {"raw_xp": raw_xp, "adjusted_xp": adj_xp, "budget": budget,
            "rating": rating, "warnings": warnings}


@router.get("/for-combat/{combat_id}")
def combat_difficulty(combat_id: str):
    """Dificultad del combate real: CRs de los stat blocks de los
    monstruos vs niveles de los personajes de la campaña."""
    import json
    conn = state_db()
    row = conn.execute(
        "SELECT campaign_id, data FROM combats WHERE id = ?",
        (combat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "combat not found")
    combat = json.loads(row["data"])
    crs = [str((c.get("stat_block") or {}).get("cr", 0))
           for c in combat.get("combatants", [])
           if c.get("kind") == "monster"]
    levels = []
    if row["campaign_id"]:
        for r in conn.execute(
                "SELECT data FROM characters WHERE campaign_id = ?",
                (row["campaign_id"],)).fetchall():
            classes = (json.loads(r["data"]).get("classes") or [])
            levels.append(max(1, sum(c.get("level", 1)
                                     for c in classes)))
    return difficulty(EncounterIn(party_levels=levels or [1],
                                  monster_crs=crs))
