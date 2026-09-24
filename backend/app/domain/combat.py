"""Combat tracker — initiative order, per-combatant HP/conditions.
A combatant may reference a character (syncs to their sheet) or a
content entity (monster stat block copied in for the DM)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Combatant(BaseModel):
    id: str
    kind: str = "monster"                # character|monster|npc
    name: str
    ref_id: str | None = None            # character id o content entity id
    initiative: int = 0
    hp_current: int = 1
    hp_max: int = 1
    hp_temp: int = 0
    ac: int = 10
    conditions: list[str] = Field(default_factory=list)
    stat_block: dict | None = None       # monstruo completo (solo DM)
    hidden_hp: bool = True               # jugadores ven estado, no número


class Combat(BaseModel):
    name: str = "Encuentro"
    campaign_id: str | None = None
    ruleset: str = "dnd5e-2014"
    status: str = "active"               # active|ended
    round: int = 1
    turn_index: int = 0
    combatants: list[Combatant] = Field(default_factory=list)

    def ordered(self) -> list[Combatant]:
        return sorted(self.combatants,
                      key=lambda c: -c.initiative)

    @property
    def active(self) -> Combatant | None:
        order = self.ordered()
        if not order:
            return None
        return order[self.turn_index % len(order)]


def hp_state(c: Combatant) -> str:
    """Estado aproximado visible para jugadores (HP exactos ocultos)."""
    if c.hp_current <= 0:
        return "caído"
    ratio = c.hp_current / max(1, c.hp_max)
    if ratio >= 1.0:
        return "ileso"
    if ratio >= 0.5:
        return "herido"
    return "grave"
