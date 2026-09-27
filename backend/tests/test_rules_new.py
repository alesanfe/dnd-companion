"""Reglas 5e añadidas: daño a 0 PG, daño masivo, ASI, recursos de clase."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.character import Character, ClassLevel
from app.engine.ops import apply_operation


class _Ctx:
    """Content DB real (data/content.sqlite3 via conftest env)."""
    _conn = None

    def content_db(self):
        if self._conn is None:
            import os
            import sqlite3
            self._conn = sqlite3.connect(os.environ["DND_CONTENT_DB"])
            self._conn.row_factory = sqlite3.Row
        return self._conn


# --- daño a 0 PG y daño masivo (SRD) ---

def test_damage_at_zero_hp_is_death_save_failure():
    c = Character(name="t", hp={"current": 0, "max": 10})
    inv, ev = apply_operation(c, "character.hp.damage", {"amount": 4})
    assert c.death_saves["fail"] == 1
    assert ev[0]["payload"]["death_fail_at_zero"] == 1


def test_massive_damage_kills_instantly():
    # daño restante tras llegar a 0 ≥ PG máximos → muerte directa
    c = Character(name="t", hp={"current": 5, "max": 10})
    apply_operation(c, "character.hp.damage", {"amount": 17})
    assert c.hp.current == 0
    assert c.death_saves["fail"] >= 3
    assert "muerto" in c.conditions


def test_damage_at_zero_three_hits_kill():
    c = Character(name="t", hp={"current": 0, "max": 10})
    for _ in range(3):
        apply_operation(c, "character.hp.damage", {"amount": 2})
    assert "muerto" in c.conditions


def test_undo_restores_death_state():
    c = Character(name="t", hp={"current": 0, "max": 10})
    inv, _ = apply_operation(c, "character.hp.damage", {"amount": 4})
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.death_saves["fail"] == 0


# --- ASI (mejora de característica por nivel) ---

def test_asi_plus_two_and_undoes_cleanly():
    c = Character(name="t", abilities={"str": 15})
    inv, _ = apply_operation(c, "character.asi.apply",
                             {"ability": "str", "amount": 2})
    assert c.abilities.strength == 17 and c.asi_used == 2
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.abilities.strength == 15 and c.asi_used == 0


def test_asi_split_one_and_one():
    c = Character(name="t", abilities={"dex": 14, "wis": 12})
    apply_operation(c, "character.asi.apply",
                    {"ability": "dex", "ability2": "wis", "amount": 1})
    assert c.abilities.dexterity == 15 and c.abilities.wisdom == 13
    assert c.asi_used == 2


def test_asi_caps_at_30_and_feat_spends():
    c = Character(name="t", abilities={"cha": 30})
    apply_operation(c, "character.asi.apply",
                    {"ability": "cha", "amount": 2})
    assert c.abilities.charisma == 30     # tope 30
    apply_operation(c, "character.asi.spent", {})
    assert c.asi_used == 4                # +2 pts + dote (2)


# --- recursos de clase desde la tabla de nivel (content DB real) ---

def test_level_up_grants_class_specific_resources():
    c = Character(
        name="t",
        classes=[ClassLevel(class_id="srd-2014:barbarian", level=2)],
        abilities={"con": 12},
    )
    inv, ev = apply_operation(c, "character.level_up",
                              {"class_id": "srd-2014:barbarian"},
                              _Ctx())
    payload = ev[0]["payload"]
    # bárbaro nv.3: rage_count = 3 → recurso "Rage Count"
    rage = next((r for r in c.resources if r.id == "cls.rage_count"), None)
    assert rage is not None and rage.max == 3
    assert "rage_count" in payload["resources_updated"]
    # brutal_critical_dice = 0 → no se crea; nv.3 no da ASI
    assert not payload["asi_available"]
    assert "cls.brutal_critical_dice" not in [r.id for r in c.resources]
    # undo limpio: ni el recurso ni el nivel quedan
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.classes[0].level == 2
    assert all(r.id != "cls.rage_count" for r in c.resources)


def test_asi_level_flags_new_improvement():
    c = Character(
        name="t",
        classes=[ClassLevel(class_id="srd-2014:barbarian", level=3)],
        abilities={"con": 12},
    )
    _, ev = apply_operation(c, "character.level_up",
                            {"class_id": "srd-2014:barbarian"}, _Ctx())
    assert ev[0]["payload"]["asi_available"] is True   # nv.4 = ASI


# --- regresión: diario, monedas, condiciones ---


def test_journal_add_pop_roundtrip():
    c = Character(name="t")
    inv, _ = apply_operation(c, "character.journal.add",
                             {"entry": "día 1: taberna"})
    assert c.narrative.journal == ["día 1: taberna"]
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.narrative.journal == []


def test_journal_pop_empty_raises():
    import pytest as _pt
    with _pt.raises(ValueError):
        apply_operation(Character(name="t"), "character.journal.pop", {})


def test_currency_convert_roundtrip():
    c = Character(name="t", purse={"sp": 25, "gp": 0})
    inv, _ = apply_operation(c, "character.currency.convert",
                             {"from": "sp", "to": "gp", "amount": 20})
    assert c.purse["gp"] == 2 and c.purse["sp"] == 5
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.purse == {"sp": 25, "gp": 0}


def test_currency_convert_rejects_bad_change():
    c = Character(name="t", purse={"cp": 5})
    with pytest.raises(ValueError):          # 5cp no llega a 1pp
        apply_operation(c, "character.currency.convert",
                        {"from": "cp", "to": "pp", "amount": 5})


def test_condition_stack_delta_and_undo():
    c = Character(name="t", conditions=["exhaustion"],
                  condition_stacks={"exhaustion": 2})
    inv, _ = apply_operation(c, "character.condition.apply",
                             {"condition": "exhaustion", "stacks": 1})
    assert c.condition_stacks["exhaustion"] == 3
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.condition_stacks["exhaustion"] == 2


def test_condition_remove_restores_stacks_on_undo():
    c = Character(name="t", conditions=["exhaustion"],
                  condition_stacks={"exhaustion": 4},
                  condition_durations={"exhaustion": 3})
    inv, _ = apply_operation(c, "character.condition.remove",
                             {"condition": "exhaustion"})
    assert "exhaustion" not in c.conditions
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.condition_stacks["exhaustion"] == 4
    assert c.condition_durations["exhaustion"] == 3


def test_long_rest_drops_one_exhaustion_level():
    c = Character(name="t", hp={"current": 5, "max": 10},
                  conditions=["exhaustion"],
                  condition_stacks={"exhaustion": 1})
    apply_operation(c, "character.rest.long", {})
    assert "exhaustion" not in c.conditions
    assert c.condition_stacks == {}


# --- regresión: dados kh/kl acotados ---

def test_dice_keep_cannot_exceed_pool():
    from app.engine.dice import roll
    with pytest.raises(ValueError):
        roll("2d6kh5")
    with pytest.raises(ValueError):
        roll("2d6kl3")
    assert roll("4d6kh3").total > 0          # válido


# --- regresión: combate — muertos sin turno ---

def test_dead_combatants_skip_turn_order():
    from app.domain.combat import Combat, Combatant
    cb = Combat(name="t", combatants=[
        Combatant(id="a", name="viva", initiative=20),
        Combatant(id="b", name="dead", initiative=30,
                  conditions=["muerto"]),
    ])
    order = cb.ordered()
    assert [x.id for x in order] == ["a"]
    assert cb.active.id == "a"


# --- regresión: sanitizador FTS5 ---

def test_fts_query_quotes_terms():
    from app.api.content import _fts_query
    assert _fts_query('fire"ball OR *') == '"fire" "ball" "OR"'
    assert _fts_query('a(b)c') == '"a" "b" "c"'
    assert _fts_query('  ') is None
    assert _fts_query('') is None
