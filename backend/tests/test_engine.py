"""Effects engine: traceable stat resolution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.effects import (
    Effect, EffectCondition, EffectOperation, StackingRule, Trigger)
from app.domain.character import Character, Resource
from app.engine.engine import (
    apply_triggered, check_conditions, resolve_stat)


def _eff(name, ops, **kw):
    return Effect(id=name, name=name,
                  operations=[EffectOperation(**o) for o in ops], **kw)


def test_ac_breakdown_is_traceable():
    effects = [
        _eff("chain mail", [{"op": "set_value", "target": "armor_class", "value": 16}]),
        _eff("shield", [{"op": "add_modifier", "target": "armor_class", "value": 2}]),
    ]
    out = resolve_stat("armor_class", 10, effects)
    assert out.total == 18          # 16 (set) + 2 (shield)
    assert len(out.entries) == 2
    assert {e.source for e in out.entries} == {"chain mail", "shield"}


def test_advantage_and_resistance_flags():
    effects = [
        _eff("bless", [{"op": "grant_advantage", "target": "saving_throw"}]),
        _eff("ring", [{"op": "grant_resistance", "value": "fire"}]),
    ]
    out = resolve_stat("saving_throw", 2, effects)
    assert out.advantage and not out.disadvantage
    assert out.resistances == ["fire"]


def test_highest_stacking_rule_does_not_double():
    effects = [
        _eff("mage armor", [{"op": "add_modifier", "target": "armor_class", "value": 3}],
             stacking_rule=StackingRule.HIGHEST),
        _eff("mage armor", [{"op": "add_modifier", "target": "armor_class", "value": 5}],
             stacking_rule=StackingRule.HIGHEST),
    ]
    out = resolve_stat("armor_class", 10, effects)
    assert out.total == 15          # solo el mayor


def test_disadvantage_and_vulnerability_immunity_flags():
    effects = [
        _eff("poisoned", [{"op": "grant_disadvantage", "target": "attack"}]),
        _eff("curse", [{"op": "grant_vulnerability", "value": "necrotic"},
                       {"op": "grant_immunity", "value": "poison"}]),
    ]
    out = resolve_stat("attack", 0, effects)
    assert out.disadvantage and not out.advantage
    assert out.vulnerabilities == ["necrotic"]
    assert out.immunities == ["poison"]


def test_lowest_stacking_keeps_smallest():
    effects = [
        _eff("penal", [{"op": "add_modifier", "target": "speed", "value": -5}],
             stacking_rule=StackingRule.LOWEST),
        _eff("penal", [{"op": "add_modifier", "target": "speed", "value": -10}],
             stacking_rule=StackingRule.LOWEST),
    ]
    out = resolve_stat("speed", 30, effects)
    assert out.total == 20          # solo el menor (-10)


def test_check_conditions_operators():
    conds = [EffectCondition(field="level", gt=4),
             EffectCondition(field="hp", lt=10)]
    assert check_conditions(conds, {"level": 5, "hp": 3})
    assert not check_conditions(conds, {"level": 3, "hp": 3})
    assert not check_conditions(conds, {"level": 5, "hp": 99})
    eq = [EffectCondition(field="status", eq="active")]
    assert check_conditions(eq, {"status": "active"})
    assert not check_conditions(eq, {"status": "idle"})
    ne = [EffectCondition(field="status", ne="muerto")]
    assert not check_conditions(ne, {"status": "muerto"})
    in_ = [EffectCondition(**{"field": "size", "in": ["S", "M"]})]
    assert check_conditions(in_, {"size": "S"})
    assert not check_conditions(in_, {"size": "L"})
    assert check_conditions([], {})          # sin condiciones → aplica


def test_apply_triggered_resources_and_conditions():
    char = Character(name="t")
    char.resources.append(
        Resource(id="cls.ki", name="Ki", current=1, max=4))
    eff = _eff("disciplina", [
        {"op": "restore_resource", "target": "cls.ki", "value": 2},
        {"op": "apply_condition", "value": "ready"},
    ], trigger=Trigger.ON_SHORT_REST)
    char.effects.append(eff)
    apply_triggered(char, Trigger.ON_SHORT_REST)
    assert char.resources[0].current == 3
    assert "ready" in char.conditions

    # consume_resource + remove_condition
    char.effects = [_eff("fin", [
        {"op": "consume_resource", "target": "cls.ki", "value": 1},
        {"op": "remove_condition", "value": "ready"},
    ], trigger=Trigger.ON_LONG_REST)]
    apply_triggered(char, Trigger.ON_LONG_REST)
    assert char.resources[0].current == 2
    assert "ready" not in char.conditions

    # trigger distinto → no hace nada
    apply_triggered(char, Trigger.ON_HIT)
    assert char.resources[0].current == 2


def test_apply_triggered_respects_conditions():
    char = Character(name="t")
    char.xp = 100
    char.effects.append(_eff("nv5", [
        {"op": "apply_condition", "value": "buff"}],
        trigger=Trigger.ON_LEVEL_UP,
        conditions=[{"field": "xp", "gt": 300}]))
    apply_triggered(char, Trigger.ON_LEVEL_UP)
    assert "buff" not in char.conditions    # xp 100 < 300
