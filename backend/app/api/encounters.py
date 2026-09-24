"""Encounter difficulty calculator — XP thresholds + multipliers
(reglas 2014, DMG). Input: niveles del grupo + CRs de monstruos."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/encounters", tags=["encounters"])

# XP thresholds por nivel de personaje: easy, medium, hard, deadly
_THRESHOLDS = {
    1: (25, 50, 75, 100), 2: (50, 100, 150, 200), 3: (75, 150, 225, 400),
    4: (125, 250, 375, 500), 5: (250, 500, 750, 1100),
    6: (300, 600, 900, 1400), 7: (350, 750, 1100, 1700),
    8: (450, 900, 1400, 2100), 9: (550, 1100, 1600, 2400),
    10: (600, 1200, 1900, 2800), 11: (800, 1600, 2400, 3600),
    12: (1000, 2000, 3000, 4500), 13: (1100, 2200, 3400, 5100),
    14: (1250, 2500, 3800, 5700), 15: (1400, 2800, 4300, 6400),
    16: (1600, 3200, 4800, 7200), 17: (2000, 3900, 5900, 8800),
    18: (2100, 4200, 6300, 9500), 19: (2400, 4900, 7300, 10900),
    20: (2800, 5700, 8500, 12700),
}

_CR_XP = {
    "0": 10, "1/8": 25, "1/4": 50, "1/2": 100, "1": 200, "2": 450,
    "3": 700, "4": 1100, "5": 1800, "6": 2300, "7": 2900, "8": 3900,
    "9": 5000, "10": 5900, "11": 7200, "12": 8400, "13": 10000,
    "14": 11500, "15": 13000, "16": 15000, "17": 18000, "18": 20000,
    "19": 22000, "20": 25000, "21": 33000, "22": 41000, "23": 50000,
    "24": 62000, "30": 155000,
}


def _multiplier(n: int) -> float:
    if n <= 1:
        return 1.0
    if n == 2:
        return 1.5
    if n <= 6:
        return 2.0
    if n <= 10:
        return 2.5
    if n <= 14:
        return 3.0
    return 4.0


def cr_to_xp(cr) -> int:
    return _CR_XP.get(str(cr), 0)


class EncounterIn(BaseModel):
    party_levels: list[int]
    monster_crs: list[str]               # ["1/4", "1/2", "2"]


@router.post("/difficulty")
def difficulty(body: EncounterIn):
    budget = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for lvl in body.party_levels:
        t = _THRESHOLDS.get(min(20, max(1, lvl)))
        if t:
            for k, v in zip(budget, t):
                budget[k] += v

    raw_xp = sum(cr_to_xp(cr) for cr in body.monster_crs)
    adj_xp = int(raw_xp * _multiplier(len(body.monster_crs)))

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
