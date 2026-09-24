"""combatant.action.roll — parser de ataques/daño/CD del stat block."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.combat import Combat, Combatant           # noqa: E402
from app.engine import combat_ops                         # noqa: E402


class _Ctx:
    content_db = state_db = lambda s: None


def _monster(actions):
    return Combat(name="t", combatants=[Combatant(
        id="m1", kind="monster", name="Beholder",
        stat_block={"abilities": {"str": 10, "dex": 14, "con": 18,
                                  "int": 17, "wis": 15, "cha": 17},
                    "saves": {}, "actions": actions})])


def test_attack_and_damage_parsed():
    c = _monster([{"name": "Bite", "text":
                   "+9 to hit, reach 5 ft. Hit: 21 (3d8+8) piercing."}])
    _, evs = combat_ops.combatant_action_roll(
        c, {"combatant_id": "m1", "action_index": 0}, _Ctx())
    p = evs[0]["payload"]
    assert p["attack_total"] - p["attack_mod"] == p["attack_roll"]
    assert p["attack_mod"] == 9
    assert p["damage_expr"] == "3d8+8"
    assert isinstance(p["damage_total"], int)


def test_save_action_dc():
    c = _monster([{"name": "Fear Ray", "text":
                   "DC 16 Wisdom saving throw or be Frightened."}])
    _, evs = combat_ops.combatant_action_roll(
        c, {"combatant_id": "m1", "action_index": 0}, _Ctx())
    assert evs[0]["payload"]["save_dc"] == 16
    assert "attack_total" not in evs[0]["payload"]


def test_out_of_range():
    c = _monster([{"name": "x", "text": ""}])
    with pytest.raises(ValueError):
        combat_ops.combatant_action_roll(
            c, {"combatant_id": "m1", "action_index": 5}, _Ctx())
