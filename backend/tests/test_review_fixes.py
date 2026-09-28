"""Regresión de los fixes de la revisión post-refactor:
inversas noop, doble-undo 409, muerte de PJ en combate, ASI gated
por asi_earned, adv antes del modificador, merge de inventario,
rest largo limpia muerto/estable."""
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app                              # noqa: E402
from app.domain.character import Character, ClassLevel  # noqa: E402
from app.domain.effects import Effect, EffectOperation, Operation  # noqa: E402
from app.engine.ops import apply_operation            # noqa: E402
from app.engine.combat_ops import apply_combat_operation  # noqa: E402
from app.domain.combat import Combat, Combatant       # noqa: E402

client = TestClient(app)


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


def _mkchar(name="T"):
    return client.post("/api/characters", json={"name": name}).json()["id"]


def _op(cid, version, otype, payload, kind="character"):
    return client.post("/api/operations", json={
        "operation_id": uuid.uuid4().hex,
        "entity_id": cid, "entity_version": version,
        "client_id": "c1", "user_id": "u1", "entity_kind": kind,
        "operation_type": otype, "payload": payload})


def _version(cid):
    return client.get(f"/api/characters/{cid}").json()["version"]


def _history(entity_id):
    return client.get(
        f"/api/operations?entity_id={entity_id}").json()["operations"]


# --- adv antes del modificador -------------------------------------

def test_advantage_goes_before_modifier():
    from app.api.operations import _augment_expr
    c = Character(name="t", inspiration=True)
    expr, _ = _augment_expr(c, "1d20+5", "check", True, [])
    assert expr == "1d20adv+5"          # antes: 1d20+5adv → 400
    expr, _ = _augment_expr(c, "1d20", "check", True, [])
    assert expr == "1d20adv"


def test_adv_dis_rejects_multi_d20():
    from app.engine.dice import roll
    with pytest.raises(ValueError):
        roll("4d20adv")                 # tiraba 5 dados
    with pytest.raises(ValueError):
        roll("2d20dis")


# --- inversas noop --------------------------------------------------

def test_condition_remove_absent_is_noop():
    c = Character(name="t")
    inv, _ = apply_operation(c, "character.condition.remove",
                             {"condition": "prone"})
    assert inv["operation_type"] == "noop"
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.conditions == []           # no crea la condición


def test_immune_condition_apply_is_noop_inverse():
    c = Character(name="t", effects=[Effect(
        id="e1", name="Heroísmo",
        operations=[EffectOperation(op=Operation.GRANT_IMMUNITY,
                                    target="condition:*")])])
    c.conditions.append("asustado")     # ya la tenía de antes
    inv, ev = apply_operation(
        c, "character.condition.apply", {"condition": "asustado"})
    assert ev[0]["type"] == "character.condition.immune"
    assert inv["operation_type"] == "noop"
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.conditions == ["asustado"]  # el undo no la quita


def test_combat_condition_remove_absent_is_noop():
    cb = Combat(name="t", combatants=[
        Combatant(id="a", name="x", initiative=1)])
    inv, _ = apply_combat_operation(
        cb, "combatant.condition.remove",
        {"combatant_id": "a", "condition": "stunned"}, _Ctx())
    assert inv["operation_type"] == "noop"


# --- rest largo limpia estado de muerte ----------------------------

def test_long_rest_clears_death_state():
    c = Character(name="t", hp={"current": 0, "max": 10},
                  death_saves={"success": 2, "fail": 1},
                  conditions=["estable"])
    apply_operation(c, "character.rest.long", {})
    assert c.death_saves == {"success": 0, "fail": 0}
    assert "estable" not in c.conditions and "muerto" not in c.conditions


# --- muerte de PJ dentro de combate ---------------------------------

def test_combat_damage_on_character_uses_death_rules():
    cb = Combat(name="t", combatants=[
        Combatant(id="p", name="pj", initiative=1, kind="character",
                  hp_current=0, hp_max=10)])
    _, ev = apply_combat_operation(
        cb, "combatant.damage",
        {"combatant_id": "p", "amount": 2}, _Ctx())
    pj = cb.combatants[0]
    assert pj.death_saves["fail"] == 1
    assert ev[0]["payload"]["death_fail_at_zero"] == 1


def test_combat_massive_damage_kills_character():
    cb = Combat(name="t", combatants=[
        Combatant(id="p", name="pj", initiative=1, kind="character",
                  hp_current=5, hp_max=10)])
    apply_combat_operation(cb, "combatant.damage",
                           {"combatant_id": "p", "amount": 17}, _Ctx())
    pj = cb.combatants[0]
    assert pj.hp_current == 0 and "muerto" in pj.conditions
    assert pj.death_saves["fail"] >= 3


def test_combat_heal_undo_restores_death_state():
    cb = Combat(name="t", combatants=[
        Combatant(id="p", name="pj", initiative=1, kind="character",
                  hp_current=0, hp_max=10, conditions=["muerto"],
                  death_saves={"success": 0, "fail": 3})])
    inv, _ = apply_combat_operation(
        cb, "combatant.heal", {"combatant_id": "p", "amount": 5}, _Ctx())
    pj = cb.combatants[0]
    assert "muerto" not in pj.conditions      # la cura revivió
    apply_combat_operation(cb, inv["operation_type"], inv["payload"],
                           _Ctx())
    assert pj.conditions == ["muerto"]        # el undo la restaura
    assert pj.death_saves["fail"] == 3
    assert pj.hp_current == 0


def test_monster_damage_skips_death_rules():
    cb = Combat(name="t", combatants=[
        Combatant(id="m", name="goblin", initiative=1, kind="monster",
                  hp_current=0, hp_max=7)])
    _, ev = apply_combat_operation(
        cb, "combatant.damage", {"combatant_id": "m", "amount": 3},
        _Ctx())
    assert cb.combatants[0].death_saves["fail"] == 0
    assert "death_fail_at_zero" not in ev[0]["payload"]


def test_combatant_check_normalizes_skill_names():
    cb = Combat(name="t", combatants=[
        Combatant(id="p", name="pj", initiative=1, kind="character",
                  hp_current=10, hp_max=10,
                  stat_block={"abilities": {"dex": 16, "int": 10}})])
    _, ev = apply_combat_operation(
        cb, "combatant.check",
        {"combatant_id": "p", "skill": "sleight-of-hand"}, _Ctx())
    # sleight of hand = DEX (+3); sin normalizar caía a INT (+0)
    assert ev[0]["payload"]["mod"] == 3


# --- inventario: undo de un remove parcial fusiona ------------------

def test_inventory_remove_undo_merges_quantity():
    c = Character(name="t")
    apply_operation(c, "character.inventory.add",
                    {"id": "rope", "name": "Cuerda", "quantity": 5})
    inv, _ = apply_operation(c, "character.inventory.remove",
                             {"item_id": "rope", "quantity": 2})
    assert c.inventory[0].quantity == 3
    apply_operation(c, inv["operation_type"], inv["payload"])
    ropes = [i for i in c.inventory if i.id == "rope"]
    assert len(ropes) == 1 and ropes[0].quantity == 5


# --- ASI gated por tabla de clase (con ctx = content DB) -----------

def test_asi_apply_enforces_earned_pool():
    c = Character(
        name="t", abilities={"str": 10},
        classes=[ClassLevel(class_id="srd-2014:barbarian", level=4)])
    apply_operation(c, "character.asi.apply",
                    {"ability": "str", "amount": 2}, _Ctx())
    assert c.asi_used == 2
    with pytest.raises(ValueError):     # bárbaro 4 solo ganó una ASI
        apply_operation(c, "character.asi.apply",
                        {"ability": "str", "amount": 2}, _Ctx())


def test_asi_apply_without_earned_rejected():
    c = Character(
        name="t",
        classes=[ClassLevel(class_id="srd-2014:barbarian", level=3)])
    with pytest.raises(ValueError):     # nv.3 aún no tiene ASI
        apply_operation(c, "character.asi.apply",
                        {"ability": "str", "amount": 2}, _Ctx())


# --- API: doble-undo, patch campaign_id ------------------------------

def test_double_undo_rejected():
    cid = _mkchar()
    r = _op(cid, _version(cid), "character.condition.apply",
            {"condition": "prone"})
    assert r.status_code == 200
    op_id = r.json()["operation_id"]
    assert client.post(
        f"/api/operations/undo/{op_id}").status_code == 200
    r2 = client.post(f"/api/operations/undo/{op_id}")
    assert r2.status_code == 409        # ya revertida — no reaplicar


def test_undo_of_noop_condition_remove():
    cid = _mkchar()
    r = _op(cid, _version(cid), "character.condition.remove",
            {"condition": "prone"})
    assert r.status_code == 200
    client.post(f"/api/operations/undo/{r.json()['operation_id']}")
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["conditions"] == []        # no aparece "prone" fantasma


def test_patch_character_unsets_campaign():
    camp = client.post("/api/campaigns", json={"name": "C"}).json()
    cid = _mkchar()
    client.patch(f"/api/characters/{cid}",
                 json={"campaign_id": camp["id"]})
    r = client.patch(f"/api/characters/{cid}",
                     json={"campaign_id": None})
    assert "campaign_id" in r.json()["changed"]
    assert client.get(
        f"/api/characters/{cid}").json()["campaign_id"] is None


def test_add_party_emits_operations_and_rolls_init():
    camp = client.post("/api/campaigns", json={"name": "C"}).json()
    cid = _mkchar()
    client.patch(f"/api/characters/{cid}",
                 json={"campaign_id": camp["id"]})
    combat = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}).json()
    r = client.post(f"/api/combat/{combat['id']}/add-party")
    assert r.status_code == 200 and r.json()["added"] == 1
    ops = _history(combat["id"])
    assert any(o["operation_type"] == "combatant.add"
               for o in ops)             # auditable + deshacible
    d = client.get(f"/api/combat/{combat['id']}").json()["combat"]
    init = d["combatants"][0]["initiative"]
    dex_mod = 0                          # PJ por defecto: DEX 10
    assert 1 + dex_mod <= init <= 20 + dex_mod  # d20 tirado, no el mod


# --- campañas con dueño: control de acceso por membresía --------------

def _auth_headers(username):
    r = client.post("/api/auth/register", json={
        "username": username, "password": "pw12345"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _owned_camp_char():
    """(owner, stranger, camp_id, char_id) — char asignado a una
    campaña con dueño."""
    owner = _auth_headers(f"o{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"s{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    cid = _mkchar()
    client.patch(f"/api/characters/{cid}",
                 json={"campaign_id": camp["id"]}, headers=owner)
    return owner, stranger, camp["id"], cid


def test_owned_campaign_character_guarded():
    owner, stranger, _camp, cid = _owned_camp_char()
    assert client.get(f"/api/characters/{cid}",
                      headers=stranger).status_code == 403
    assert client.delete(f"/api/characters/{cid}",
                         headers=stranger).status_code == 403
    assert client.post(
        f"/api/operations/character/{cid}/roll?expression=1d20",
        headers=stranger).status_code == 403
    # el owner sigue pudiendo leerla
    assert client.get(f"/api/characters/{cid}",
                      headers=owner).status_code == 200
    # la lista del extraño no la filtra
    lst = client.get("/api/characters", headers=stranger).json()
    assert all(c["id"] != cid for c in lst["characters"])
    # ni puede adjuntar fichas a la campaña ajena
    other = _mkchar()
    assert client.patch(f"/api/characters/{other}",
                        json={"campaign_id": _camp},
                        headers=stranger).status_code == 403


def test_owned_campaign_ops_and_history_guarded():
    owner, stranger, _camp, cid = _owned_camp_char()
    v = client.get(f"/api/characters/{cid}",
                   headers=owner).json()["version"]
    op_body = {
        "operation_id": uuid.uuid4().hex, "entity_id": cid,
        "entity_version": v, "client_id": "c1", "user_id": "x",
        "entity_kind": "character",
        "operation_type": "character.condition.apply",
        "payload": {"condition": "prone"}}
    assert client.post("/api/operations", json=op_body,
                       headers=stranger).status_code == 403
    assert client.post("/api/operations", json=op_body,
                       headers=owner).status_code == 200
    assert client.get(f"/api/operations?entity_id={cid}",
                      headers=stranger).status_code == 403
    # op con user_id del autenticado (no el spoofable del body)
    h = client.get(f"/api/operations?entity_id={cid}",
                   headers=owner).json()["operations"]
    assert h[0]["user_id"] != "x"


def test_delete_campaign_detaches_characters():
    camp = client.post("/api/campaigns", json={"name": "C"}).json()
    cid = _mkchar()
    client.patch(f"/api/characters/{cid}",
                 json={"campaign_id": camp["id"]})
    assert client.delete(f"/api/campaigns/{camp['id']}").status_code == 200
    d = client.get(f"/api/characters/{cid}").json()
    assert d["campaign_id"] is None                    # ficha sobrevive
    assert client.get(f"/api/campaigns/{camp['id']}").status_code == 404


def test_get_campaign_owned_requires_membership():
    owner = _auth_headers(f"g{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"h{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    assert client.get(f"/api/campaigns/{camp['id']}",
                      headers=stranger).status_code == 403
    assert client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).status_code == 200


# --- rules assistant: FTS seguro ------------------------------------

def test_rules_ask_survives_fts_operators():
    r = client.post("/api/rules/ask",
                    json={"question": "fire*ball OR NEAR(x y)"})
    assert r.status_code == 200          # antes: OperationalError 500
    r2 = client.post("/api/rules/ask", json={"question": "*"})
    assert r2.status_code == 200
