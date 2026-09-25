"""CR → XP (tabla oficial 2014/2024) — extraída del rules pack
``app/rules/srd_core.json`` (SRD, CC-BY-4.0)."""
from ..rules import rules


def _cr_str(cr) -> str:
    if isinstance(cr, float) and cr in (0.125, 0.25, 0.5):
        return {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}[cr]
    if isinstance(cr, float) and cr == int(cr):
        return str(int(cr))
    return str(cr)


def cr_to_xp(cr) -> int:
    return rules()["cr_xp"].get(_cr_str(cr), 0)


def encounter_threshold(level: int) -> tuple[int, int, int, int]:
    """(easy, medium, hard, deadly) para un nivel de PJ."""
    t = rules()["encounter_thresholds"][str(min(20, max(1, level)))]
    return tuple(t)


def encounter_multiplier(monster_count: int) -> float:
    """Multiplicador de XP por número de enemigos (DMG)."""
    mult = 1.0
    for min_count, m in rules()["encounter_multipliers"]["steps"]:
        if monster_count >= min_count:
            mult = m
    return mult


def level_xp_table() -> list[int]:
    return rules()["level_xp"]["values"]
