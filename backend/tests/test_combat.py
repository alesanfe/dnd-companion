"""Combat ops: initiative order, turn advance, damage states, undo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.combat import Combat, Combatant, hp_state
from app.engine.combat_ops import apply_combat_operation


class _Ctx:
    def content_db(self):
        return None          # tests sin content DB


def _combat():
    return Combat(name="Test", combatants=[
        Combatant(id="a", name="Aria", initiative=15, hp_current=20, hp_max=20),
        Combatant(id="g", name="Goblin", initiative=10, hp_current=7, hp_max=7),
    ])


def test_next_turn_advances_and_wraps_round():
    c = _combat()
    assert c.active.name == "Aria"
    apply_combat_operation(c, "combat.next_turn", {}, _Ctx())
    assert c.active.name == "Goblin"
    apply_combat_operation(c, "combat.next_turn", {}, _Ctx())
    assert c.active.name == "Aria" and c.round == 2


def test_combatant_damage_and_hp_state():
    c = _combat()
    g = next(x for x in c.combatants if x.id == "g")
    apply_combat_operation(c, "combatant.damage",
                           {"combatant_id": "g", "amount": 4}, _Ctx())
    assert g.hp_current == 3
    assert hp_state(g) == "grave"
    apply_combat_operation(c, "combatant.damage",
                           {"combatant_id": "g", "amount": 10}, _Ctx())
    assert g.hp_current == 0 and hp_state(g) == "caído"


def test_remove_and_undo_reinserts():
    c = _combat()
    inv, _ = apply_combat_operation(
        c, "combatant.remove", {"combatant_id": "g"}, _Ctx())
    assert len(c.combatants) == 1
    apply_combat_operation(c, inv["operation_type"], inv["payload"], _Ctx())
    assert len(c.combatants) == 2
    assert c.combatants[1].name == "Goblin"


def test_end_is_reversible():
    c = _combat()
    inv, _ = apply_combat_operation(c, "combat.end", {}, _Ctx())
    assert c.status == "ended"
    apply_combat_operation(c, inv["operation_type"], inv["payload"], _Ctx())
    assert c.status == "active"
