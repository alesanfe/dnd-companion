"""Combat ops: initiative order, turn advance, damage states, undo."""
import json
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


def test_ordered_skips_downed_monster_and_stable():
    """Un monstruo a 0 PG aunque falte la marca 'muerto' y un PJ
    estabilizado no toman turno; el PJ caído sí — su turno es la
    salvación de muerte."""
    cm = Combat(combatants=[
        Combatant(id="m", kind="monster", name="Goblin",
                  initiative=20, hp_current=0, hp_max=7),
        Combatant(id="s", kind="character", name="Sara",
                  initiative=18, hp_current=0, hp_max=10,
                  ref_id="s", conditions=["estable"]),
        Combatant(id="a", kind="character", name="Aria",
                  initiative=15, hp_current=0, hp_max=20, ref_id="a"),
        Combatant(id="b", kind="character", name="Borin",
                  initiative=10, hp_current=12, hp_max=12, ref_id="b"),
    ])
    assert [c.id for c in cm.ordered()] == ["a", "b"]
    assert cm.active.id == "a"          # turno de salvación de Aria


def test_hp_set_event_dm_only_for_monsters():
    """hp.set emite el PG exacto — para un monstruo lleva
    visibility=dm (la ficha del PJ sigue recibiéndolo en claro)."""
    from app.engine.combat_ops import combatant_hp_set
    cm = Combat(combatants=[
        Combatant(id="m", kind="monster", name="Goblin",
                  initiative=20, hp_current=7, hp_max=7),
        Combatant(id="a", kind="character", name="Aria",
                  initiative=15, hp_current=20, hp_max=20,
                  ref_id="a"),
    ])
    _, evs = combatant_hp_set(
        cm, {"combatant_id": "m", "current": 4}, None)
    assert evs[0]["payload"]["visibility"] == "dm"
    _, evs2 = combatant_hp_set(
        cm, {"combatant_id": "a", "current": 3}, None)
    assert "visibility" not in evs2[0]["payload"]


def test_sync_character_preserves_sheet_conditions():
    """El daño/cura de combate sincroniza solo el estado vital: las
    condiciones persistentes de la ficha (agotamiento…) sobreviven y
    'muerto' del tracker se propaga. Antes la lista se copiaba entera
    y el tracker borraba las condiciones de la hoja."""
    from app.db.connections import state_db
    from app.api.operations import OpContext
    from app.domain.character import Character
    conn = state_db()
    ch = Character(name="Pj", conditions=["exhaustion"],
                   condition_stacks={"exhaustion": 2})
    conn.execute(
        "INSERT INTO characters (id, name, version, data, updated_at)"
        " VALUES (?,?,0,?,?)",
        ("pj-sync", "Pj", ch.model_dump_json(), "x"))
    conn.commit()
    ctx = OpContext(conn)
    cm = Combat(combatants=[
        Combatant(id="c", kind="character", name="Pj", initiative=10,
                  hp_current=10, hp_max=10, ref_id="pj-sync")])
    # daño masivo: muerte instantánea en el tracker
    apply_combat_operation(
        cm, "combatant.damage",
        {"combatant_id": "c", "amount": 30}, ctx)
    conn.commit()
    data = json.loads(conn.execute(
        "SELECT data FROM characters WHERE id = 'pj-sync'"
    ).fetchone()["data"])
    assert data["hp"]["current"] == 0
    assert "muerto" in data["conditions"]        # propagado
    assert "exhaustion" in data["conditions"]    # NO borrado
    assert data["condition_stacks"] == {"exhaustion": 2}
    # y la cura quita 'muerto' sin tocar el resto
    apply_combat_operation(
        cm, "combatant.heal",
        {"combatant_id": "c", "amount": 5}, ctx)
    conn.commit()
    data = json.loads(conn.execute(
        "SELECT data FROM characters WHERE id = 'pj-sync'"
    ).fetchone()["data"])
    assert data["hp"]["current"] == 5
    assert "muerto" not in data["conditions"]
    assert data["conditions"] == ["exhaustion"]


def test_death_save_roll_nat20_revives_and_clears_dead(monkeypatch):
    """Un 20 natural en la salvación de combate revive con 1 PG y
    limpia 'muerto'/'estable' — antes solo reiniciaba los contadores."""
    import app.engine.combat_ops as co

    class _R:
        total = 20

    # el handler que tira puede vivir en cualquier submódulo del
    # paquete combat_ops — patchear donde se usa
    for _m in (co.vitals, co.rolls, co.roster, co.turns):
        monkeypatch.setattr(_m, "roll", lambda _expr: _R())
    cm = Combat(combatants=[
        Combatant(id="c", kind="character", name="Pj", initiative=10,
                  hp_current=0, hp_max=10,
                  conditions=["muerto"],
                  death_saves={"success": 0, "fail": 2})])
    _, evs = apply_combat_operation(
        cm, "combatant.death_save_roll", {"combatant_id": "c"}, _Ctx())
    c = cm.combatants[0]
    assert c.hp_current == 1
    assert "muerto" not in c.conditions
    assert evs[0]["payload"]["outcome"] == "recupera 1 PG"


def test_death_save_stable_not_duplicated():
    """3 éxitos marca 'estable' — si ya estaba no se duplica."""
    cm = Combat(combatants=[
        Combatant(id="c", kind="character", name="Pj", initiative=10,
                  hp_current=0, hp_max=10,
                  conditions=["estable"],
                  death_saves={"success": 2, "fail": 0})])
    apply_combat_operation(
        cm, "combatant.death_save",
        {"combatant_id": "c", "success": True}, _Ctx())
    c = cm.combatants[0]
    assert c.conditions.count("estable") == 1


def test_sync_character_preserves_sheet_conditions():
    """El daño/cura de combate sincroniza solo el estado vital: las
    condiciones persistentes de la ficha (agotamiento…) sobreviven y
    'muerto' del tracker se propaga. Antes la lista se copiaba entera
    y el tracker borraba las condiciones de la hoja."""
    from app.db.connections import state_db
    from app.api.operations import OpContext
    from app.domain.character import Character
    conn = state_db()
    ch = Character(name="Pj", conditions=["exhaustion"],
                   condition_stacks={"exhaustion": 2})
    conn.execute(
        "INSERT INTO characters (id, name, version, data, updated_at)"
        " VALUES (?,?,0,?,?)",
        ("pj-sync", "Pj", ch.model_dump_json(), "x"))
    conn.commit()
    ctx = OpContext(conn)
    cm = Combat(combatants=[
        Combatant(id="c", kind="character", name="Pj", initiative=10,
                  hp_current=10, hp_max=10, ref_id="pj-sync")])
    # daño masivo: muerte instantánea en el tracker
    apply_combat_operation(
        cm, "combatant.damage",
        {"combatant_id": "c", "amount": 30}, ctx)
    conn.commit()
    data = json.loads(conn.execute(
        "SELECT data FROM characters WHERE id = 'pj-sync'"
    ).fetchone()["data"])
    assert data["hp"]["current"] == 0
    assert "muerto" in data["conditions"]        # propagado
    assert "exhaustion" in data["conditions"]    # NO borrado
    assert data["condition_stacks"] == {"exhaustion": 2}
    # y la cura quita 'muerto' sin tocar el resto
    apply_combat_operation(
        cm, "combatant.heal",
        {"combatant_id": "c", "amount": 5}, ctx)
    conn.commit()
    data = json.loads(conn.execute(
        "SELECT data FROM characters WHERE id = 'pj-sync'"
    ).fetchone()["data"])
    assert data["hp"]["current"] == 5
    assert "muerto" not in data["conditions"]
    assert data["conditions"] == ["exhaustion"]


def test_death_save_roll_nat20_revives_and_clears_dead(monkeypatch):
    """Un 20 natural en la salvación de combate revive con 1 PG y
    limpia 'muerto'/'estable' — antes solo reiniciaba los contadores."""
    import app.engine.combat_ops as co

    class _R:
        total = 20

    # el handler que tira puede vivir en cualquier submódulo del
    # paquete combat_ops — patchear donde se usa
    for _m in (co.vitals, co.rolls, co.roster, co.turns):
        monkeypatch.setattr(_m, "roll", lambda _expr: _R())
    cm = Combat(combatants=[
        Combatant(id="c", kind="character", name="Pj", initiative=10,
                  hp_current=0, hp_max=10,
                  conditions=["muerto"],
                  death_saves={"success": 0, "fail": 2})])
    _, evs = apply_combat_operation(
        cm, "combatant.death_save_roll", {"combatant_id": "c"}, _Ctx())
    c = cm.combatants[0]
    assert c.hp_current == 1
    assert "muerto" not in c.conditions
    assert evs[0]["payload"]["outcome"] == "recupera 1 PG"


def test_death_save_stable_not_duplicated():
    """3 éxitos marca 'estable' — si ya estaba no se duplica."""
    cm = Combat(combatants=[
        Combatant(id="c", kind="character", name="Pj", initiative=10,
                  hp_current=0, hp_max=10,
                  conditions=["estable"],
                  death_saves={"success": 2, "fail": 0})])
    apply_combat_operation(
        cm, "combatant.death_save",
        {"combatant_id": "c", "success": True}, _Ctx())
    c = cm.combatants[0]
    assert c.conditions.count("estable") == 1


def _atk_ctx(monkeypatch, roll_seq):
    """Ctx con state_db real + tiradas scripted (impacto, daño…)."""
    import app.engine.combat_ops as co
    from app.db.connections import state_db
    from app.api.operations import OpContext
    seq = iter(roll_seq)

    class _R:
        def __init__(self, rs):
            self.rolls = rs
            self.total = sum(rs)

    for _m in (co.vitals, co.rolls, co.roster, co.turns):
        monkeypatch.setattr(_m, "roll", lambda _e: _R(next(seq)))
    conn = state_db()
    ctx = OpContext(conn)
    return conn, ctx


def test_combat_attack_hit_damages_target_and_inverse_restores(
        monkeypatch):
    """El PJ ataca desde el mapa: impacto vs CA del objetivo y daño
    aplicado por la op — la CA no sale del servidor. Reversible."""
    from app.domain.character import Character, InventoryItem
    conn, ctx = _atk_ctx(monkeypatch, [[15], [6]])
    ch = Character(name="Aria")
    ch.inventory.append(InventoryItem(id="i1", name="Espada"))
    conn.execute(
        "INSERT INTO characters (id, name, version, data, updated_at)"
        " VALUES (?,?,0,?,?)",
        ("atk-pj", "Aria", ch.model_dump_json(), "x"))
    conn.commit()
    cm = Combat(combatants=[
        Combatant(id="a", kind="character", name="Aria", initiative=15,
                  hp_current=10, hp_max=10, ref_id="atk-pj"),
        Combatant(id="m", kind="monster", name="Goblin", initiative=10,
                  hp_current=10, hp_max=10, ac=12)])
    inv, evs = apply_combat_operation(
        cm, "combat.attack",
        {"attacker_combatant_id": "a", "target_combatant_id": "m",
         "item_name": "Espada"}, ctx)
    m = cm.combatants[1]
    # 15 + 2 prof + 0 mod = 17 ≥ CA 12 → impacto; daño = 6
    assert evs[0]["payload"]["hits"] is True
    assert evs[0]["payload"]["damage"] == 6
    assert m.hp_current == 4
    apply_combat_operation(cm, inv["operation_type"], inv["payload"],
                           ctx)
    assert m.hp_current == 10


def test_combat_attack_miss_noop_inverse(monkeypatch):
    conn, ctx = _atk_ctx(monkeypatch, [[3]])
    from app.domain.character import Character, InventoryItem
    ch = Character(name="Aria")
    ch.inventory.append(InventoryItem(id="i1", name="Espada"))
    conn.execute(
        "INSERT INTO characters (id, name, version, data, updated_at)"
        " VALUES (?,?,0,?,?)",
        ("atk-miss", "Aria", ch.model_dump_json(), "x"))
    conn.commit()
    cm = Combat(combatants=[
        Combatant(id="a", kind="character", name="Aria", initiative=15,
                  hp_current=10, hp_max=10, ref_id="atk-miss"),
        Combatant(id="m", kind="monster", name="Goblin", initiative=10,
                  hp_current=10, hp_max=10, ac=12)])
    inv, evs = apply_combat_operation(
        cm, "combat.attack",
        {"attacker_combatant_id": "a", "target_combatant_id": "m",
         "item_name": "Espada"}, ctx)
    assert evs[0]["payload"]["hits"] is False
    assert cm.combatants[1].hp_current == 10     # sin daño
    assert inv["operation_type"] == "noop"


def test_combat_attack_rejects_monster_attacker_and_missing_weapon(
        monkeypatch):
    """El atacante debe ser un combatiente-PJ y el arma existir en su
    inventario — los ids del payload no dan privilegios extra."""
    import pytest
    conn, ctx = _atk_ctx(monkeypatch, [])
    cm = Combat(combatants=[
        Combatant(id="m1", kind="monster", name="Orco", initiative=15,
                  hp_current=10, hp_max=10, ref_id="fake-pj"),
        Combatant(id="m2", kind="monster", name="Goblin", initiative=10,
                  hp_current=10, hp_max=10)])
    with pytest.raises(Exception, match="personaje|atacante"):
        apply_combat_operation(
            cm, "combat.attack",
            {"attacker_combatant_id": "m1", "target_combatant_id": "m2",
             "item_name": "Espada"}, ctx)
    from app.domain.character import Character
    ch = Character(name="Sara")
    conn.execute(
        "INSERT INTO characters (id, name, version, data, updated_at)"
        " VALUES (?,?,0,?,?)",
        ("atk-nw", "Sara", ch.model_dump_json(), "x"))
    conn.commit()
    cm.combatants[0] = Combatant(
        id="a", kind="character", name="Sara", initiative=15,
        hp_current=10, hp_max=10, ref_id="atk-nw")
    with pytest.raises(Exception, match="inventario"):
        apply_combat_operation(
            cm, "combat.attack",
            {"attacker_combatant_id": "a", "target_combatant_id": "m2",
             "item_name": "Espada"}, ctx)
