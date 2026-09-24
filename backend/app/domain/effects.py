"""Declarative effects model — game rules as data, not code.

Every condition, feat, class trait, magic item, aura or homebrew rule is an
Effect: a trigger + conditions + operations. The engine
(app/engine/) evaluates them; nothing in the codebase should hardcode
'if class == barbarian'.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .ruleset import Ruleset


class Trigger(str, Enum):
    ON_APPLY = "on_apply"
    ON_REMOVE = "on_remove"
    ON_TURN_START = "on_turn_start"
    ON_TURN_END = "on_turn_end"
    ON_ROUND_START = "on_round_start"
    BEFORE_ROLL = "before_roll"
    AFTER_ROLL = "after_roll"
    BEFORE_DAMAGE = "before_damage"
    AFTER_DAMAGE = "after_damage"
    ON_HIT = "on_hit"
    ON_MISS = "on_miss"
    ON_SAVE_SUCCESS = "on_save_success"
    ON_SAVE_FAILURE = "on_save_failure"
    ON_SHORT_REST = "on_short_rest"
    ON_LONG_REST = "on_long_rest"
    ON_LEVEL_UP = "on_level_up"


class Operation(str, Enum):
    ADD_MODIFIER = "add_modifier"
    SET_VALUE = "set_value"
    GRANT_ADVANTAGE = "grant_advantage"
    GRANT_DISADVANTAGE = "grant_disadvantage"
    ADD_DICE = "add_dice"
    REROLL = "reroll"
    REPLACE_ROLL = "replace_roll"
    MODIFY_DAMAGE = "modify_damage"
    GRANT_RESISTANCE = "grant_resistance"
    GRANT_VULNERABILITY = "grant_vulnerability"
    GRANT_IMMUNITY = "grant_immunity"
    APPLY_CONDITION = "apply_condition"
    REMOVE_CONDITION = "remove_condition"
    CONSUME_RESOURCE = "consume_resource"
    RESTORE_RESOURCE = "restore_resource"
    GRANT_ACTION = "grant_action"
    GRANT_REACTION = "grant_reaction"
    MODIFY_SPEED = "modify_speed"
    MODIFY_ARMOR_CLASS = "modify_armor_class"
    MODIFY_RANGE = "modify_range"


class StackingRule(str, Enum):
    STACK = "stack"               # suma con otras fuentes
    HIGHEST = "highest"           # solo el mayor aplica
    LOWEST = "lowest"
    REFRESH = "refresh"           # reemplaza duración
    UNIQUE = "unique"             # misma fuente no puede aplicarse 2 veces


class EffectOperation(BaseModel):
    op: Operation
    target: str = ""                         # 'armor_class', 'speed'... vacío = N/A
    value: int | float | str | bool | None = None
    dice: str | None = None                  # '1d4', '2d6'...
    extra: dict[str, Any] = Field(default_factory=dict)


class EffectCondition(BaseModel):
    """Declarative predicate, e.g. {field: 'attacker.visible', eq: false}."""
    field: str
    eq: Any = None
    ne: Any = None
    in_: list[Any] | None = Field(default=None, alias="in")
    gt: float | None = None
    lt: float | None = None


class Effect(BaseModel):
    id: str
    name: str
    trigger: Trigger | None = None           # None = pasivo permanente
    conditions: list[EffectCondition] = Field(default_factory=list)
    operations: list[EffectOperation] = Field(default_factory=list)
    duration: str | None = None              # '1 round', '10 minutes', 'concentration'
    stacking_rule: StackingRule = StackingRule.STACK
    priority: int = 0                        # mayor = se evalúa después
    source: str | None = None                # content entity id o 'homebrew:...'
    ruleset: Ruleset = Ruleset.DND5E_2014
