"""Operation handlers: damage absorbs temp first, rests restore, undo works."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.character import Character, HitDicePool, Resource
from app.engine.ops import apply_operation


def _char():
    return Character(
        name="Test",
        hp={"current": 10, "max": 10, "temp": 3},
        hit_dice=[HitDicePool(die="d8", total=2, remaining=2)],
        resources=[Resource(id="rage", name="Rage", current=1, max=3,
                            reset_on="long"),
                   Resource(id="ki", name="Ki", current=0, max=4,
                            reset_on="short")],
        spell_slots={"1": {"total": 4, "used": 2}},
        abilities={"con": 14},
    )


def test_damage_absorbs_temp_first():
    c = _char()
    inv, ev = apply_operation(c, "character.hp.damage", {"amount": 5})
    assert c.hp.temp == 0 and c.hp.current == 8
    assert inv["operation_type"] == "character.hp.set"


def test_heal_caps_at_max():
    c = _char()
    apply_operation(c, "character.hp.heal", {"amount": 100})
    assert c.hp.current == 10


def test_condition_round_trip():
    c = _char()
    apply_operation(c, "character.condition.apply", {"condition": "poisoned"})
    assert "poisoned" in c.conditions
    apply_operation(c, "character.condition.remove", {"condition": "poisoned"})
    assert "poisoned" not in c.conditions


def test_short_rest_only_resets_short_resources():
    c = _char()
    apply_operation(c, "character.rest.short", {})
    ki = next(r for r in c.resources if r.id == "ki")
    rage = next(r for r in c.resources if r.id == "rage")
    assert ki.current == 4            # reset_on short
    assert rage.current == 1          # reset_on long: intacto
    assert c.spell_slots["1"]["used"] == 2   # slots no se recuperan


def test_long_rest_restores_everything():
    c = _char()
    c.hp.current = 3
    apply_operation(c, "character.rest.long", {})
    assert c.hp.current == 10 and c.hp.temp == 0
    assert c.spell_slots["1"]["used"] == 0
    assert all(r.current == r.max for r in c.resources)
    # nivel 1 → recupera mín 1 dado; con pool lleno no pasa nada
    assert c.hit_dice[0].remaining <= c.hit_dice[0].total


def test_hit_die_spend_heals_and_consumes():
    c = _char()
    c.hp.current = 2
    inv, ev = apply_operation(c, "character.hit_die.spend", {"pool": 0})
    assert c.hit_dice[0].remaining == 1
    assert c.hp.current > 2           # 1d8 + 2 (con 14 → +2)
    # deshacer: devuelve el dado y quita la cura
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.hit_dice[0].remaining == 2
    assert c.hp.current == 2


def test_undo_rest_via_inverse():
    c = _char()
    c.hp.current = 4
    inv, _ = apply_operation(c, "character.rest.long", {})
    assert c.hp.current == 10
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.hp.current == 4          # snapshot restaurado
