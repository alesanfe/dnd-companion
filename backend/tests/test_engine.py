"""Effects engine: traceable stat resolution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.effects import Effect, EffectOperation, Operation, StackingRule
from app.engine.engine import resolve_stat


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
