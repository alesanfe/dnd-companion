"""Encounter difficulty calculator — XP thresholds + multipliers
(reglas 2014, DMG). Input: niveles del grupo + CRs de monstruos.
`/suggest` va en sentido inverso: presupuesto + filtros → composición
de monstruos de la content DB."""
from __future__ import annotations

import json
import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import optional_user
from .campaigns import _DM_ROLES, _has_owner, _require_role
from ..db.connections import content_db, state_db
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
def combat_difficulty(combat_id: str,
                      user: dict | None = Depends(optional_user)):
    """Dificultad del combate real: CRs de los stat blocks de los
    monstruos vs niveles de los personajes de la campaña."""
    import json
    conn = state_db()
    row = conn.execute(
        "SELECT campaign_id, data FROM combats WHERE id = ?",
        (combat_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "combat not found")
    # CRs y stat blocks son información del DM — en campañas con
    # dueño un jugador no debe medir la dificultad del encuentro
    if row["campaign_id"] and _has_owner(conn, row["campaign_id"]):
        _require_role(conn, row["campaign_id"], user, _DM_ROLES)
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


_DIFFS = ("easy", "medium", "hard", "deadly")


class SuggestIn(BaseModel):
    party_levels: list[int]
    difficulty: str = "medium"
    monster_types: list[str] = []        # filtro: undead, beast…
    max_count: int = Field(6, ge=1, le=20)
    seed: int | None = None              # composición reproducible


@router.post("/suggest")
def suggest(body: SuggestIn):
    """Composición de encuentro dentro del presupuesto ajustado:
    greedy aleatorio (con semilla opcional) que solo mete monstruos
    que no pasen el presupuesto — el multiplicador sube con cada
    alta, así que reevalúa tras cada pick."""
    dif = body.difficulty
    if dif not in _DIFFS:
        raise HTTPException(400, f"difficulty debe ser {'|'.join(_DIFFS)}")
    budget = sum(encounter_threshold(l)[_DIFFS.index(dif)]
                 for l in body.party_levels)
    if budget <= 0:
        raise HTTPException(400, "party_levels requerido")
    want = {t.strip().lower() for t in body.monster_types if t.strip()}
    cands = []
    for r in content_db().execute(
            "SELECT id, name, data FROM content_entities "
            "WHERE entity_type = 'monster'").fetchall():
        try:
            d = json.loads(r["data"])
        except (TypeError, ValueError):
            continue
        cr = d.get("cr") or d.get("challenge_rating") \
            or d.get("challenge") or 0
        xp = cr_to_xp(cr)
        if xp <= 0:
            continue
        if want:
            hay = json.dumps(
                [d.get("type"), d.get("creature_type"),
                 d.get("monster_type")], ensure_ascii=False).lower()
            if not any(t in hay for t in want):
                continue
        cands.append({"id": r["id"], "name": r["name"],
                      "cr": str(cr), "xp": xp})
    if not cands:
        raise HTTPException(404, "sin monstruos en la content DB")
    rng = random.Random(body.seed)
    rng.shuffle(cands)
    picked, raw, adj = [], 0, 0
    for m in cands:
        if len(picked) >= body.max_count:
            break
        cand_raw = raw + m["xp"]
        cand_adj = int(cand_raw * encounter_multiplier(len(picked) + 1))
        if cand_adj <= budget:
            picked.append(m)
            raw, adj = cand_raw, cand_adj
    if not picked:
        # ni el más barato entra → devolver ese solo (el DM decide)
        cheapest = min(cands, key=lambda m: m["xp"])
        picked = [cheapest]
        raw = cheapest["xp"]
        adj = int(raw * encounter_multiplier(1))
    return {"budget": budget, "difficulty": dif,
            "raw_xp": raw, "adjusted_xp": adj,
            "monsters": picked}
