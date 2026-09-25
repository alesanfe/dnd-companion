"""Character model — the full sheet state. Serialized into
state DB `characters.data`. Derived values (AC, modifiers) are computed
by the effects engine, never stored."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .effects import Effect
from .ruleset import Ruleset

_ABILITY_ALIASES = {
    "str": "strength", "dex": "dexterity", "con": "constitution",
    "int": "intelligence", "wis": "wisdom", "cha": "charisma",
}


class AbilityScores(BaseModel):
    """Acepta claves cortas ('str') o largas ('strength') en JSON."""
    model_config = ConfigDict(populate_by_name=True)

    strength: int = Field(10, alias="str")
    dexterity: int = Field(10, alias="dex")
    constitution: int = Field(10, alias="con")
    intelligence: int = Field(10, alias="int")
    wisdom: int = Field(10, alias="wis")
    charisma: int = Field(10, alias="cha")

    def modifier(self, ability: str) -> int:
        attr = _ABILITY_ALIASES.get(ability, ability)
        return (getattr(self, attr) - 10) // 2


class HitPoints(BaseModel):
    current: int = 8
    max: int = 8
    temp: int = 0


class HitDicePool(BaseModel):
    """One pool per class for multiclass (e.g. d8 rogue + d10 fighter)."""
    die: str = "d8"
    total: int = 1
    remaining: int = 1


class Resource(BaseModel):
    """Rage, ki, sorcery points, action surge... reset_on: short|long|none."""
    id: str
    name: str
    current: int = 0
    max: int = 0
    reset_on: str = "long"


class ClassLevel(BaseModel):
    class_id: str              # content entity id, e.g. 'srd-2014:barbarian'
    subclass_id: str | None = None
    level: int = 1


class InventoryItem(BaseModel):
    id: str
    name: str
    quantity: int = 1
    equipped: bool = False
    attuned: bool = False
    source_id: str | None = None   # provenance si viene de content DB


class Narrative(BaseModel):
    """Estado narrativo: separado de los números."""
    personality: str = ""
    ideals: str = ""
    bonds: str = ""
    flaws: str = ""
    backstory: str = ""
    allies: str = ""
    goals: str = ""
    journal: list[str] = Field(default_factory=list)
    secrets: str = ""              # solo jugador + DM
    portrait_url: str | None = None


class Character(BaseModel):
    name: str = ""
    ruleset: Ruleset = Ruleset.DND5E_2014
    species_id: str | None = None  # content entity id
    background_id: str | None = None
    classes: list[ClassLevel] = Field(default_factory=list)
    abilities: AbilityScores = Field(default_factory=AbilityScores)
    hp: HitPoints = Field(default_factory=HitPoints)
    hit_dice: list[HitDicePool] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    spell_slots: dict[str, dict[str, int]] = Field(default_factory=dict)
    # {'1': {'total': 2, 'used': 0}, ...}
    spells_known: list[str] = Field(default_factory=list)   # entity ids
    feats_known: list[str] = Field(default_factory=list)    # entity ids
    features: list[str] = Field(default_factory=list)  # rasgos de clase
    languages: list[str] = Field(default_factory=list)
    rewards: list[str] = Field(default_factory=list)  # dones/boons (ids)
    skill_proficiencies: list[str] = Field(default_factory=list)
    save_proficiencies: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    condition_durations: dict[str, int] = Field(default_factory=dict)
    # {'poisoned': 3} → expira al pasar 3 rondas fuera de combate
    effects: list[Effect] = Field(default_factory=list)     # activos/pasivos
    inventory: list[InventoryItem] = Field(default_factory=list)
    purse: dict[str, int] = Field(
        default_factory=lambda: {"pp": 0, "gp": 0, "ep": 0, "sp": 0, "cp": 0})
    narrative: Narrative = Field(default_factory=Narrative)
    proficiency_bonus: int = 2
    xp: int = 0                             # puntos de experiencia
    concentrating_on: str | None = None     # conjuro en concentración
    inspiration: bool = False               # inspiración del DM
    death_saves: dict[str, int] = Field(
        default_factory=lambda: {"success": 0, "fail": 0})
    pinned: list[str] = Field(default_factory=list)
    # ids de inventario/spells fijados → salen en Resumen/modo partida

    @property
    def total_level(self) -> int:
        return sum(c.level for c in self.classes) or 1
