"""Regresión de los fixes de la revisión post-refactor:
inversas noop, doble-undo 409, muerte de PJ en combate, ASI gated
por asi_earned, adv antes del modificador, merge de inventario,
rest largo limpia muerto/estable."""
import asyncio
import json
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


def test_character_op_syncs_active_combat():
    """Espejo de _sync_character: una op vital sobre la FICHA (daño/
    cura del jugador desde su hoja, salvación de muerte) actualiza al
    combatiente vinculado en el combate activo de la campaña — antes
    el tracker del DM quedaba desfasado hasta tocar el combate."""
    camp = client.post("/api/campaigns", json={"name": "C"}).json()
    cid = _mkchar()
    client.patch(f"/api/characters/{cid}",
                 json={"campaign_id": camp["id"]})
    combat = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}).json()
    client.post(f"/api/combat/{combat['id']}/add-party")
    d = client.get(f"/api/combat/{combat['id']}").json()
    cbt = d["combat"]["combatants"][0]
    assert cbt["kind"] == "character" and cbt["ref_id"] == cid
    hp_max, cv = cbt["hp_max"], d["version"]
    # daño desde la hoja → el combatiente refleja el HP y el combate
    # bumpea versión (optimistic locking sigue funcionando)
    r = _op(cid, _version(cid), "character.hp.damage", {"amount": 3})
    assert r.status_code == 200
    d2 = client.get(f"/api/combat/{combat['id']}").json()
    cbt2 = d2["combat"]["combatants"][0]
    assert cbt2["hp_current"] == hp_max - 3
    assert d2["version"] == cv + 1
    # cura desde la hoja → también sincroniza
    r = _op(cid, _version(cid), "character.hp.heal", {"amount": 10})
    assert r.status_code == 200
    cbt3 = client.get(
        f"/api/combat/{combat['id']}").json()["combat"]["combatants"][0]
    assert cbt3["hp_current"] == hp_max
    # una op no vital NO toca el combate (sin bump de versión)
    cv2 = client.get(f"/api/combat/{combat['id']}").json()["version"]
    r = _op(cid, _version(cid), "character.inspiration.set",
            {"value": True})
    assert r.status_code == 200
    assert client.get(
        f"/api/combat/{combat['id']}").json()["version"] == cv2


def test_character_death_save_syncs_combat_death_state():
    """La salvación tirada en la hoja (3 fallos) marca al combatiente
    muerto en el tracker — el DM ve el desenlace sin recargar."""
    camp = client.post("/api/campaigns", json={"name": "C"}).json()
    cid = _mkchar()
    client.patch(f"/api/characters/{cid}",
                 json={"campaign_id": camp["id"]})
    combat = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}).json()
    client.post(f"/api/combat/{combat['id']}/add-party")
    # a 0 PG vía hoja
    mx = client.get(
        f"/api/combat/{combat['id']}").json()[
            "combat"]["combatants"][0]["hp_max"]
    _op(cid, _version(cid), "character.hp.set", {"current": 0})
    for _ in range(3):
        r = _op(cid, _version(cid), "character.death_save", {"roll": 1})
        assert r.status_code == 200
    d = client.get(f"/api/combat/{combat['id']}").json()["combat"]
    cbt = d["combatants"][0]
    assert "muerto" in cbt["conditions"]
    assert cbt["death_saves"]["fail"] >= 3
    assert cbt["hp_max"] == mx


# --- campañas con dueño: control de acceso por membresía --------------

def _auth_headers(username):
    r = client.post("/api/auth/register", json={
        "username": username, "password": "pw123456"})
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


def test_char_ownership_in_owned_campaign():
    """Un jugador solo muta SU ficha: player_id ligado al uid en el
    alta (spoof del body rebotado), patch/delete/op/transfer de la
    ficha de otro jugador = 403. El DM mueve todo."""
    def _account(tag):
        r = client.post("/api/auth/register", json={
            "username": f"{tag}{uuid.uuid4().hex[:8]}",
            "password": "pw123456"})
        return {"Authorization": f"Bearer {r.json()['token']}"}, \
            r.json()["user_id"]

    owner, _uid_o = _account("o")
    pa, uid_a = _account("a")
    pb, uid_b = _account("b")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    for h in (pa, pb):
        client.post("/api/campaigns/join",
                    json={"invite_code": code}, headers=h)
    # A crea su ficha intentando spoofear player_id=B → ligado a A
    r = client.post("/api/characters",
                    json={"name": "A", "campaign_id": camp["id"],
                          "player_id": uid_b}, headers=pa)
    assert r.status_code == 201
    cid = r.json()["id"]
    row = client.get(f"/api/characters/{cid}", headers=owner).json()
    assert row["player_id"] == uid_a
    # B: lectura sí (miembro), mutaciones no
    assert client.get(f"/api/characters/{cid}",
                      headers=pb).status_code == 200
    assert client.patch(f"/api/characters/{cid}", json={"name": "X"},
                        headers=pb).status_code == 403
    assert client.delete(f"/api/characters/{cid}",
                         headers=pb).status_code == 403
    assert client.post("/api/operations", json={
        "operation_id": uuid.uuid4().hex, "entity_id": cid,
        "entity_version": row["version"], "client_id": "c",
        "user_id": uid_b, "entity_kind": "character",
        "operation_type": "character.hp.damage",
        "payload": {"amount": 1}}, headers=pb).status_code == 403
    # ni tirar "como" la ficha de A — el evento firmaría su nombre
    assert client.post(f"/api/operations/character/{cid}/roll",
                       params={"expression": "1d20"},
                       headers=pb).status_code == 403
    # ni mover objetos de la ficha de A
    cb = client.post("/api/characters",
                     json={"name": "B", "campaign_id": camp["id"]},
                     headers=pb).json()
    assert client.post("/api/inventory/transfer", json={
        "transfer_id": uuid.uuid4().hex, "from_character": cid,
        "to_character": cb["id"], "item_id": "x", "quantity": 1},
        headers=pb).status_code == 403
    # A (dueña) y el DM sí pueden
    assert client.patch(f"/api/characters/{cid}",
                        json={"name": "A2"}, headers=pa).status_code == 200
    assert client.delete(f"/api/characters/{cid}",
                         headers=owner).status_code == 200


def test_personal_char_ops_guard():
    """Ficha SIN campaña con player_id: solo la muta su dueño. Antes
    el guard de campaña saltaba entero (camp_id=None) y cualquier
    autenticado — o anónimo — la editaba por /api/operations."""
    owner = _auth_headers(f"po{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"ps{uuid.uuid4().hex[:8]}")
    uid = client.get("/api/auth/me", headers=owner).json()["user_id"]
    cid = client.post("/api/characters",
                      json={"name": "personal", "player_id": uid},
                      headers=owner).json()["id"]
    body = {"operation_id": uuid.uuid4().hex, "entity_id": cid,
            "entity_version": 1, "client_id": "t", "user_id": "x",
            "entity_kind": "character",
            "operation_type": "character.hp.set",
            "payload": {"current": 5}}
    assert client.post("/api/operations", json=body,
                       headers=stranger).status_code == 403
    # anónimo tampoco — hay usuarios registrados, el player_id vale
    assert client.post("/api/operations", json=body).status_code == 403
    # el dueño sí
    body["operation_id"] = uuid.uuid4().hex
    assert client.post("/api/operations", json=body,
                       headers=owner).status_code == 200
    # ficha libre (player_id NULL) sigue abierta en modo local
    free = _mkchar("free")
    assert client.post("/api/operations", json={
        **body, "operation_id": uuid.uuid4().hex,
        "entity_id": free}).status_code == 200


def test_personal_char_hidden_from_stranger_listing():
    """GET /api/characters no enumera fichas personales ajenas —
    ese listado era la fuente de ids para el bypass anterior."""
    owner = _auth_headers(f"pl{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"pm{uuid.uuid4().hex[:8]}")
    uid = client.get("/api/auth/me", headers=owner).json()["user_id"]
    cid = client.post("/api/characters",
                      json={"name": "privada", "player_id": uid},
                      headers=owner).json()["id"]
    ids = [c["id"] for c in client.get(
        "/api/characters", headers=stranger).json()["characters"]]
    assert cid not in ids
    # el dueño sí la ve en su listado
    ids = [c["id"] for c in client.get(
        "/api/characters", headers=owner).json()["characters"]]
    assert cid in ids
    # fichas libres siguen visibles para todos (modo local)
    free = _mkchar("libre")
    ids = [c["id"] for c in client.get(
        "/api/characters", headers=stranger).json()["characters"]]
    assert free in ids


def test_personal_char_ws_op_guard():
    """El mismo guard por WS: un socket de campaña no puede mutar
    fichas personales ajenas vía op con entity_camp=None."""
    owner = _auth_headers(f"wo{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"ws{uuid.uuid4().hex[:8]}")
    uid = client.get("/api/auth/me", headers=owner).json()["user_id"]
    cid = client.post("/api/characters",
                      json={"name": "persws", "player_id": uid},
                      headers=owner).json()["id"]
    camp = client.post("/api/campaigns", json={"name": "W"},
                       headers=stranger).json()
    tok = stranger["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(
            f"/ws/campaign/{camp['id']}?token={tok}") as ws:
        ws.send_json({"type": "operation", "operation": {
            "operation_id": uuid.uuid4().hex, "entity_id": cid,
            "entity_version": 1, "client_id": "t",
            "user_id": "x", "entity_kind": "character",
            "operation_type": "character.hp.set",
            "payload": {"current": 1}}})
        d = {}
        for _ in range(6):               # salta presence broadcast
            d = ws.receive_json()
            if d.get("type") in ("error", "ack"):
                break
        assert d.get("type") == "error"


def test_auth_throttle_persists_in_db(monkeypatch):
    """El rate-limit vive en state DB (no en memoria): un reinicio
    ya no regala 5 intentos gratis."""
    from app.api.auth import _throttle
    from fastapi import HTTPException
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    key = f"login:{uuid.uuid4().hex[:8]}"
    for _ in range(5):
        _throttle(key)
    with pytest.raises(HTTPException) as exc:
        _throttle(key)
    assert exc.value.status_code == 429
    _throttle(f"login:{uuid.uuid4().hex[:8]}")  # otra clave pasa


def test_char_claim_and_release():
    """Reclamar una ficha sin dueño en campaña con owner: player_id
    pasa a ser el uid del que la reclama; otro jugador ya no puede
    mutarla; el dueño puede soltarla."""
    owner = _auth_headers(f"cl{uuid.uuid4().hex[:8]}")
    pa, pb = _auth_headers(f"cA{uuid.uuid4().hex[:8]}"), \
             _auth_headers(f"cB{uuid.uuid4().hex[:8]}")
    uid_a = client.get("/api/auth/me", headers=pa).json()["user_id"]
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    for h in (pa, pb):
        client.post("/api/campaigns/join",
                    json={"invite_code": code}, headers=h)
    # el DM crea una ficha sin asignar
    r = client.post("/api/characters",
                    json={"name": "Free", "campaign_id": camp["id"]},
                    headers=owner)
    cid = r.json()["id"]
    # B intenta reclamarla para OTRO usuario → 403
    assert client.patch(f"/api/characters/{cid}",
                        json={"player_id": "otro"},
                        headers=pb).status_code == 403
    # A la reclama para sí misma
    assert client.patch(f"/api/characters/{cid}",
                        json={"player_id": uid_a},
                        headers=pa).status_code == 200
    # ya es de A: B no puede tocarla ni reasignarla
    assert client.patch(f"/api/characters/{cid}",
                        json={"player_id": None},
                        headers=pb).status_code == 403
    # A la suelta y vuelve a ser libre
    assert client.patch(f"/api/characters/{cid}",
                        json={"player_id": None},
                        headers=pa).status_code == 200


class _FakeWS:
    """Socket stub para probar _dispatch_ws sin WebSocket real."""

    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(json.loads(text))


def test_ws_spectator_is_read_only():
    """Un socket espectador (anónimo en mesa con dueño) mira pero no
    habla ni opera — ni siquiera sobre fichas sin campaña."""
    import asyncio
    from app.main import _dispatch_ws
    ws = _FakeWS()

    async def run():
        await _dispatch_ws(
            ws, "camp-x", {"type": "chat", "text": "hola"},
            role="spectator")
        await _dispatch_ws(ws, "camp-x", {"type": "typing"},
                           role="spectator")
        await _dispatch_ws(ws, "camp-x", {
            "type": "operation",
            "operation": {"operation_id": uuid.uuid4().hex,
                          "entity_id": "x", "entity_version": 1,
                          "client_id": "c",
                          "operation_type": "character.hp.damage",
                          "entity_kind": "character",
                          "payload": {"amount": 1}}},
            role="spectator")

    asyncio.run(run())
    errs = [m for m in ws.sent if m.get("type") == "error"]
    # chat rechazado + op rechazada; typing se descarta en silencio
    assert len(errs) == 2 and all("solo lectura" in e["detail"]
                                  for e in errs)


def test_ws_chat_uses_authenticated_name():
    """El `from` del mensaje WS es spoofable — el servidor firma con la
    identidad autenticada del socket."""
    import asyncio
    from app.main import _dispatch_ws
    from app.ws.rooms import manager
    listener = _FakeWS()

    async def run():
        await manager.join("camp-chat", listener, role="player",
                           name="otro")
        await _dispatch_ws(_FakeWS(), "camp-chat",
                           {"type": "chat", "from": "DM",
                            "text": "mensaje"}, resolved="u1",
                           name="pepito")
        manager.leave("camp-chat", listener)

    asyncio.run(run())
    assert listener.sent and listener.sent[0]["from"] == "pepito"


def test_ws_op_auth_parity_with_rest():
    """El path WS de operaciones aplica el mismo modelo que REST:
    la entidad debe ser de esta sala, en campaña con dueño se exige
    miembro, el jugador solo toca su ficha y el combate es del DM."""
    from app.main import _dispatch_ws
    owner = _auth_headers(f"we{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"wf{uuid.uuid4().hex[:8]}")
    uid_p = client.get("/api/auth/me", headers=player).json()["user_id"]
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    ch = client.post("/api/characters",
                     json={"name": "P", "campaign_id": camp["id"]},
                     headers=player).json()
    comb = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}, headers=owner).json()
    ws = _FakeWS()

    def _op(entity_id, version, kind, otype, payload=None):
        return {"type": "operation", "operation": {
            "operation_id": uuid.uuid4().hex, "entity_id": entity_id,
            "entity_version": version, "client_id": "c",
            "user_id": "spoofable", "entity_kind": kind,
            "operation_type": otype, "payload": payload or {}}}

    # jugador dirigiendo el combate por WS → error (como en REST)
    asyncio.run(_dispatch_ws(ws, camp["id"],
                             _op(comb["id"], comb["version"],
                                 "combat", "combat.end"),
                             resolved=uid_p))
    assert ws.sent[-1]["type"] == "error"
    assert "DM" in ws.sent[-1]["detail"]
    # jugador mutando SU ficha → ack, y el user_id queda sellado
    v = client.get(f"/api/characters/{ch['id']}",
                   headers=player).json()["version"]
    asyncio.run(_dispatch_ws(ws, camp["id"],
                             _op(ch["id"], v, "character",
                                 "character.hp.damage", {"amount": 1}),
                             resolved=uid_p))
    assert ws.sent[-1]["type"] == "ack"
    # socket sin identidad en campaña con dueño → error
    asyncio.run(_dispatch_ws(ws, camp["id"],
                             _op(ch["id"], v + 1, "character",
                                 "character.hp.damage", {"amount": 1}),
                             resolved=None))
    assert ws.sent[-1]["type"] == "error"
    # op sobre entidad de OTRA campaña → error (aislamiento de sala)
    camp2 = client.post("/api/campaigns", json={"name": "Otra"},
                        headers=owner).json()
    other = client.post("/api/characters",
                        json={"name": "X", "campaign_id": camp2["id"]},
                        headers=owner).json()
    asyncio.run(_dispatch_ws(ws, camp["id"],
                             _op(other["id"], other["version"],
                                 "character", "character.hp.damage",
                                 {"amount": 1}), resolved=uid_p))
    assert ws.sent[-1]["type"] == "error"


def test_combat_ops_dm_only_in_owned_campaign():
    """El tracker es del DM: un jugador no puede avanzar turnos ni
    terminar el combate via /api/operations (vigía, no jugador)."""
    owner = _auth_headers(f"cm{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"cn{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    comb = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}, headers=owner).json()
    op = {"operation_id": uuid.uuid4().hex, "entity_id": comb["id"],
          "entity_version": comb["version"], "client_id": "c",
          "user_id": "u", "entity_kind": "combat",
          "operation_type": "combat.end", "payload": {}}
    assert client.post("/api/operations", json=op,
                       headers=player).status_code == 403
    # el DM sí cierra el encuentro
    assert client.post("/api/operations", json=op,
                       headers=owner).status_code == 200


def test_secret_roll_request_marked_targeted():
    """Una petición secreta se marca visibility=dm + for_user — los
    demás jugadores no la ven ni por feed ni por socket."""
    owner = _auth_headers(f"sr{uuid.uuid4().hex[:8]}")
    pa = _auth_headers(f"st{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=pa)
    cha = client.post("/api/characters",
                      json={"name": "A", "campaign_id": camp["id"]},
                      headers=pa).json()
    uid_a = client.get("/api/auth/me", headers=pa).json()["user_id"]
    client.post(f"/api/campaigns/{camp['id']}/roll-request",
                json={"character_id": cha["id"], "secret": True,
                      "reason": "escucha"}, headers=owner)
    ev_dm = client.get(f"/api/campaigns/{camp['id']}/events",
                       headers=owner).json()["events"]
    req = [e for e in ev_dm if e["type"] == "dice.roll.requested"]
    assert req and req[0]["payload"]["for_user"] == uid_a
    assert req[0]["payload"]["visibility"] == "dm"
    # el destinatario SÍ la ve en su feed (le va dirigida) — cualquier
    # otro jugador no
    ev_pa = client.get(f"/api/campaigns/{camp['id']}/events",
                       headers=pa).json()["events"]
    assert any(e["type"] == "dice.roll.requested" for e in ev_pa)
    pb = _auth_headers(f"sy{uuid.uuid4().hex[:8]}")
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=pb)
    ev_pb = client.get(f"/api/campaigns/{camp['id']}/events",
                       headers=pb).json()["events"]
    assert not [e for e in ev_pb if e["type"] == "dice.roll.requested"]


def test_secret_player_roll_visible_to_roller_in_feed():
    """La tirada secreta del jugador lleva for_user=uid — en el feed la
    ven el DM y el propio autor (otros jugadores no)."""
    owner = _auth_headers(f"sv{uuid.uuid4().hex[:8]}")
    pa = _auth_headers(f"sw{uuid.uuid4().hex[:8]}")
    pb = _auth_headers(f"sx{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    for h in (pa, pb):
        client.post("/api/campaigns/join",
                    json={"invite_code": code}, headers=h)
    cha = client.post("/api/characters",
                      json={"name": "A", "campaign_id": camp["id"]},
                      headers=pa).json()
    r = client.post(
        f"/api/operations/character/{cha['id']}/roll",
        params={"expression": "1d20", "secret": "true"}, headers=pa)
    assert r.status_code == 200
    feed = lambda h: client.get(
        f"/api/campaigns/{camp['id']}/events", headers=h
        ).json()["events"]
    assert any(e["type"] == "dice.roll.created"
               for e in feed(pa))      # el autor la ve en su feed
    assert any(e["type"] == "dice.roll.created"
               for e in feed(owner))   # el DM también
    assert not any(e["type"] == "dice.roll.created"
                   for e in feed(pb))  # otro jugador no


def test_entities_and_relationships_require_membership():
    """Sin el guard un extraño listaba al menos las entidades y
    relaciones públicas de una mesa ajena. Ahora 403."""
    owner = _auth_headers(f"en{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"ex{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    client.post(f"/api/campaigns/{camp['id']}/entities",
                json={"kind": "npc", "name": "Tabernera"},
                headers=owner)
    for path in ("entities", "relationships", "timeline"):
        assert client.get(f"/api/campaigns/{camp['id']}/{path}",
                          headers=stranger).status_code == 403
        assert client.get(f"/api/campaigns/{camp['id']}/{path}",
                          headers=owner).status_code == 200


def test_pending_roll_requests_scoped_to_own_chars():
    """Un jugador no consulta peticiones pendientes de fichas ajenas —
    las secretas del DM filtrarían el motivo de la tirada."""
    owner = _auth_headers(f"rp{uuid.uuid4().hex[:8]}")
    pa = _auth_headers(f"rq{uuid.uuid4().hex[:8]}")
    pb = _auth_headers(f"rr{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    for h in (pa, pb):
        client.post("/api/campaigns/join",
                    json={"invite_code": code}, headers=h)
    cha = client.post("/api/characters",
                      json={"name": "A", "campaign_id": camp["id"]},
                      headers=pa).json()
    chb = client.post("/api/characters",
                      json={"name": "B", "campaign_id": camp["id"]},
                      headers=pb).json()
    client.post(f"/api/campaigns/{camp['id']}/roll-request",
                json={"character_id": cha["id"], "expression": "1d20",
                      "reason": "percepción", "secret": True},
                headers=owner)
    both = f"{cha['id']},{chb['id']}"
    # B no ve la petición dirigida a la ficha de A
    r = client.get(
        f"/api/campaigns/{camp['id']}/roll-requests/pending",
        params={"character_ids": both}, headers=pb).json()
    assert all(p["character_id"] != cha["id"] for p in r["pending"])
    # A sí ve la suya; el DM ve ambas
    ra = client.get(
        f"/api/campaigns/{camp['id']}/roll-requests/pending",
        params={"character_ids": both}, headers=pa).json()
    assert any(p["character_id"] == cha["id"] for p in ra["pending"])
    rm = client.get(
        f"/api/campaigns/{camp['id']}/roll-requests/pending",
        params={"character_ids": both}, headers=owner).json()
    assert any(p["character_id"] == cha["id"] for p in rm["pending"])


def test_secret_rolls_not_served_by_rest_state():
    """La tirada secreta va visibility=dm por WS, pero el resync REST
    (/state, /events) la servía con el total a cualquier miembro.
    Ahora un jugador no la recibe ni en el feed ni en el snapshot."""
    owner = _auth_headers(f"sr{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"sq{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    ch = client.post("/api/characters",
                     json={"name": "S", "campaign_id": camp["id"]},
                     headers=owner).json()
    client.post(f"/api/operations/character/{ch['id']}/roll",
                params={"expression": "1d20", "secret": "true"},
                headers=owner)
    # el jugador no la ve ni en state ni en el feed de eventos
    st = client.get(f"/api/campaigns/{camp['id']}/state",
                    headers=player).json()
    assert not [
        e for e in st["events"]
        if (json.loads(e["payload"]) or {}).get("visibility") == "dm"]
    ev = client.get(f"/api/campaigns/{camp['id']}/events",
                    headers=player).json()
    assert all(e["payload"].get("visibility") != "dm"
               for e in ev["events"])
    # el DM sí la recibe
    ev_dm = client.get(f"/api/campaigns/{camp['id']}/events",
                       headers=owner).json()
    assert any(e["payload"].get("visibility") == "dm"
               for e in ev_dm["events"])


def test_player_rolls_own_death_save_in_combat():
    """Excepción al tracker DM-only: la salvación de muerte la tira
    el jugador sobre SU combatiente-PJ. Sobre otro combatiente o
    cualquier otra op de combate sigue siendo 403."""
    owner = _auth_headers(f"ds{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"dt{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    ch = client.post("/api/characters",
                     json={"name": "P", "campaign_id": camp["id"]},
                     headers=player).json()
    comb = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}, headers=owner).json()
    client.post(f"/api/combat/{comb['id']}/add-party", headers=owner)
    cj = client.get(f"/api/combat/{comb['id']}", headers=owner).json()
    cb = next(c for c in cj["combat"]["combatants"]
              if c.get("ref_id") == ch["id"])

    def _cop(otype, payload, h, ver):
        return client.post("/api/operations", json={
            "operation_id": uuid.uuid4().hex, "entity_id": comb["id"],
            "entity_version": ver, "client_id": "c", "user_id": "u",
            "entity_kind": "combat", "operation_type": otype,
            "payload": payload}, headers=h)

    # DM deja al PJ a 0 PG
    r = _cop("combatant.hp.set",
             {"combatant_id": cb["id"], "current": 0},
             owner, cj["version"])
    assert r.status_code == 200
    v = r.json()["version"]
    # el jugador tira SU salvación de muerte — la única op de combate
    # permitida a un no-DM
    r2 = _cop("combatant.death_save_roll",
              {"combatant_id": cb["id"]}, player, v)
    assert r2.status_code == 200
    op_id = r2.json()["operation_id"]
    # un click erróneo se deshace — la inversa solo es legal para el
    # propio autor: otro jugador sigue recibiendo 403
    other = _auth_headers(f"du{uuid.uuid4().hex[:8]}")
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=other)
    assert client.post(f"/api/operations/undo/{op_id}",
                       headers=other).status_code == 403
    r3 = client.post(f"/api/operations/undo/{op_id}", headers=player)
    assert r3.status_code == 200
    # …pero nada más: turnos y combatientes ajenos siguen siendo del DM
    v2 = client.get(f"/api/combat/{comb['id']}",
                    headers=owner).json()["version"]
    assert _cop("combat.next_turn", {}, player, v2).status_code == 403


def test_combat_difficulty_is_dm_only():
    """Los CRs/stat_blocks son info del DM — for-combat exige rol DM
    cuando la campaña tiene dueño; en local queda abierto."""
    owner = _auth_headers(f"d{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"e{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    comb = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]},
        headers=owner).json()
    assert client.get(
        f"/api/encounters/for-combat/{comb['id']}",
        headers=stranger).status_code == 403
    assert client.get(
        f"/api/encounters/for-combat/{comb['id']}",
        headers=owner).status_code == 200


def test_get_campaign_owned_requires_membership():
    owner = _auth_headers(f"g{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"h{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    assert client.get(f"/api/campaigns/{camp['id']}",
                      headers=stranger).status_code == 403
    assert client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).status_code == 200


# --- resolución asistida de conflictos ---------------------------------

def test_conflict_retry_applies_at_fresh_version():
    cid = _mkchar()
    before = client.get(
        f"/api/characters/{cid}").json()["data"]["hp"]["current"]
    assert _op(cid, 1, "character.hp.damage",
               {"amount": 5}).status_code == 200
    # op con versión stale → 409 y queda registrada como 'conflict'
    stale = uuid.uuid4().hex
    r = client.post("/api/operations", json={
        "operation_id": stale, "entity_id": cid, "entity_version": 1,
        "client_id": "c", "user_id": "u", "entity_kind": "character",
        "operation_type": "character.hp.heal", "payload": {"amount": 3}})
    assert r.status_code == 409
    # reintentar: se aplica con la versión actual y se marca resolved
    assert client.post(
        f"/api/operations/conflicts/{stale}/retry").status_code == 200
    hp = client.get(
        f"/api/characters/{cid}").json()["data"]["hp"]["current"]
    assert hp == before - 5 + 3
    confs = client.get("/api/operations/conflicts").json()["conflicts"]
    assert all(c["operation_id"] != stale for c in confs)
    # reintentar dos veces → ya resuelto, 404
    assert client.post(
        f"/api/operations/conflicts/{stale}/retry").status_code == 404


def test_conflict_dismiss_marks_resolved():
    cid = _mkchar()
    assert _op(cid, 1, "character.condition.apply",
               {"condition": "prone"}).status_code == 200
    stale = uuid.uuid4().hex
    r = client.post("/api/operations", json={
        "operation_id": stale, "entity_id": cid, "entity_version": 1,
        "client_id": "c", "user_id": "u", "entity_kind": "character",
        "operation_type": "character.hp.damage", "payload": {"amount": 2}})
    assert r.status_code == 409
    assert client.post(
        f"/api/operations/conflicts/{stale}/dismiss").status_code == 200
    confs = client.get("/api/operations/conflicts").json()["conflicts"]
    assert all(c["operation_id"] != stale for c in confs)
    # descartado → ya no es conflict (404), y el daño NUNCA se aplicó
    assert client.post(
        f"/api/operations/conflicts/{stale}/dismiss").status_code == 404
    hp = client.get(
        f"/api/characters/{cid}").json()["data"]["hp"]["current"]
    assert hp == 8                      # default 8, sin el daño stale


# --- rules assistant: FTS seguro ------------------------------------

def test_rules_ask_survives_fts_operators():
    r = client.post("/api/rules/ask",
                    json={"question": "fire*ball OR NEAR(x y)"})
    assert r.status_code == 200          # antes: OperationalError 500
    r2 = client.post("/api/rules/ask", json={"question": "*"})
    assert r2.status_code == 200


# --- reparto de XP al cerrar el encuentro ------------------------------

def test_award_xp_splits_fallen_monsters_between_pcs():
    """award-xp: CR de monstruos caídos entre los PJs, como ops
    character.xp.add reales (auditable, deshacible). DM-only con owner;
    monstruos vivos no cuentan."""
    owner = _auth_headers(f"ax{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"ay{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    ch = client.post("/api/characters",
                     json={"name": "P", "campaign_id": camp["id"]},
                     headers=player).json()
    comb = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}, headers=owner).json()
    client.post(f"/api/combat/{comb['id']}/add-party", headers=owner)

    def _cop(otype, payload, h):
        cur = client.get(f"/api/combat/{comb['id']}",
                         headers=owner).json()["version"]
        return client.post("/api/operations", json={
            "operation_id": uuid.uuid4().hex, "entity_id": comb["id"],
            "entity_version": cur, "client_id": "c", "user_id": "u",
            "entity_kind": "combat", "operation_type": otype,
            "payload": payload}, headers=h)

    # un orco caído (CR 1/4 = 50 XP) y un ogro vivo (CR 2 = 450 XP)
    m1 = _cop("combatant.add", {
        "kind": "monster", "name": "orco", "hp_max": 15,
        "stat_block": {"cr": 0.25, "hp": 15, "ac": 13}}, owner)
    assert m1.status_code == 200
    mid = client.get(f"/api/combat/{comb['id']}",
                     headers=owner).json()["combat"]["combatants"]
    orco = next(c for c in mid if c["name"] == "orco")
    _cop("combatant.add", {
        "kind": "monster", "name": "ogro", "hp_max": 59,
        "stat_block": {"cr": 2, "hp": 59, "ac": 11}}, owner)
    _cop("combatant.hp.set",
         {"combatant_id": orco["id"], "current": 0}, owner)

    # jugador no reparte XP; el DM sí — 50 XP al único PJ
    assert client.post(f"/api/combat/{comb['id']}/award-xp",
                       headers=player).status_code == 403
    r = client.post(f"/api/combat/{comb['id']}/award-xp", headers=owner)
    assert r.status_code == 200
    assert r.json() == {"total_xp": 50, "per_player": 50, "awarded": 1}
    xp = client.get(f"/api/characters/{ch['id']}",
                    headers=player).json()["data"]["xp"]
    assert xp == 50


def test_campaign_state_redacts_combat_hp_for_players():
    """El resync /state servía el combate crudo: PG exactos y stat
    blocks de monstruos. Para jugadores se redacta igual que la vista
    reveal_hp=0; para el DM queda íntegro."""
    owner = _auth_headers(f"cs{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"ct{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    comb = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}, headers=owner).json()
    ver = client.get(f"/api/combat/{comb['id']}",
                     headers=owner).json()["version"]
    client.post("/api/operations", json={
        "operation_id": uuid.uuid4().hex, "entity_id": comb["id"],
        "entity_version": ver, "client_id": "c", "user_id": "u",
        "entity_kind": "combat", "operation_type": "combatant.add",
        "payload": {"kind": "monster", "name": "orco", "hp_max": 15,
                    "stat_block": {"cr": 0.25, "hp": 15, "ac": 13}}},
        headers=owner)
    st_p = client.get(f"/api/campaigns/{camp['id']}/state",
                      headers=player).json()
    cmb_p = st_p["combats"][0]["data"]["combatants"][0]
    assert cmb_p["hp_current"] is None and cmb_p["stat_block"] is None
    assert cmb_p["hp_state"] is not None
    st_o = client.get(f"/api/campaigns/{camp['id']}/state",
                      headers=owner).json()
    cmb_o = st_o["combats"][0]["data"]["combatants"][0]
    assert cmb_o["hp_current"] == 15 and cmb_o["stat_block"]["cr"] == 0.25


def test_split_loot_shares_treasure_dm_only():
    """split-loot reparte el tesoro entre las fichas como ops
    currency.earn; resto redondeado a las primeras. DM-only con owner."""
    owner = _auth_headers(f"sl{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"sm{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    a = client.post("/api/characters",
                    json={"name": "A", "campaign_id": camp["id"]},
                    headers=player).json()
    b = client.post("/api/characters",
                    json={"name": "B", "campaign_id": camp["id"]},
                    headers=owner).json()
    assert client.post(f"/api/campaigns/{camp['id']}/split-loot",
                       json={"coin": "gp", "amount": 10},
                       headers=player).status_code == 403
    r = client.post(f"/api/campaigns/{camp['id']}/split-loot",
                    json={"coin": "gp", "amount": 11}, headers=owner)
    assert r.status_code == 200 and r.json()["awarded"] == 2
    purses = [client.get(f"/api/characters/{cid}",
                         headers=owner).json()["data"]["purse"]
              for cid in (a["id"], b["id"])]
    # 11 gp / 2 fichas → 6 y 5, sin resto perdido
    assert sorted(p["gp"] for p in purses) == [5, 6]


def test_token_move_only_own_token():
    """token-move: el DM mueve cualquiera; el jugador solo el token
    vinculado a su ficha (ref_id o player_id). Fuera de la rejilla se
    clampa, no error."""
    owner = _auth_headers(f"tm{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"tn{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    ch = client.post("/api/characters",
                     json={"name": "P", "campaign_id": camp["id"]},
                     headers=player).json()
    ent = client.post(f"/api/campaigns/{camp['id']}/entities", json={
        "kind": "map", "name": "Mapa", "visibility": "public",
        "data": {"cols": 8, "rows": 6, "tokens": [
            {"id": "mio", "name": "Yo", "x": 0, "y": 0,
             "ref_id": ch["id"]},
            {"id": "ajeno", "name": "Otro", "x": 1, "y": 1}]}},
        headers=owner).json()

    def _mv(tok, x, y, h):
        return client.post(
            f"/api/campaigns/{camp['id']}/entities/{ent['id']}/token-move",
            json={"token_id": tok, "x": x, "y": y}, headers=h)

    assert _mv("ajeno", 3, 3, player).status_code == 403
    r = _mv("mio", 99, -3, player)             # fuera → clamp
    assert r.status_code == 200
    assert r.json() == {"x": 7, "y": 0}
    # el DM mueve el token ajeno sin problema
    assert _mv("ajeno", 4, 4, owner).status_code == 200
    # el movimiento persiste en la entidad
    data = client.get(
        f"/api/campaigns/{camp['id']}/entities",
        headers=owner).json()["entities"]
    toks = {t["id"]: t for t in
            next(e for e in data if e["id"] == ent["id"])["data"]["tokens"]}
    assert toks["mio"]["x"] == 7 and toks["ajeno"]["x"] == 4


def test_token_move_blocked_by_wall():
    """Un jugador no puede cruzar un muro adyacente ortogonal; el DM
    sí (reubica tokens libremente). Diagonal/salto largo = libre."""
    owner = _auth_headers(f"w{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"x{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    ch = client.post("/api/characters",
                     json={"name": "P", "campaign_id": camp["id"]},
                     headers=player).json()
    ent = client.post(f"/api/campaigns/{camp['id']}/entities", json={
        "kind": "map", "name": "Mapa", "visibility": "public",
        "data": {"cols": 8, "rows": 6,
                 "walls": ["3,3,E"],       # muro E de (3,3)
                 "tokens": [{"id": "mio", "name": "Yo", "x": 3, "y": 3,
                             "ref_id": ch["id"]}]}},
        headers=owner).json()

    def _mv(x, y, h):
        return client.post(
            f"/api/campaigns/{camp['id']}/entities/{ent['id']}/token-move",
            json={"token_id": "mio", "x": x, "y": y}, headers=h)

    # el jugador no cruza el muro (3,3)→(4,3); sí puede ir a (3,4)
    assert _mv(4, 3, player).status_code == 400
    assert _mv(3, 4, player).status_code == 200
    # el DM sí cruza el muro (reubica tokens libremente)
    assert _mv(4, 3, owner).status_code == 200


def test_delegated_npc_control():
    """Delegación: el DM cede un NPC a un jugador → puede mover su
    token; otro jugador no; al revocar vuelve a 403. Delegar sigue
    siendo op DM-only y el delegado no gana ops de dirección."""
    owner = _auth_headers(f"dg{uuid.uuid4().hex[:8]}")
    pr = client.post("/api/auth/register", json={
        "username": f"dp{uuid.uuid4().hex[:8]}",
        "password": "pw123456"})
    player = {"Authorization": f"Bearer {pr.json()['token']}"}
    puid = pr.json()["user_id"]          # el uid exacto del delegado
    other = _auth_headers(f"do{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    for h in (player, other):
        client.post("/api/campaigns/join",
                    json={"invite_code": code}, headers=h)

    comb = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}, headers=owner).json()

    def _cop(otype, payload, h):
        v = client.get(f"/api/combat/{comb['id']}",
                       headers=h).json()["version"]
        return client.post("/api/operations", json={
            "operation_id": uuid.uuid4().hex, "entity_id": comb["id"],
            "entity_version": v, "client_id": "t", "user_id": "x",
            "entity_kind": "combat", "operation_type": otype,
            "payload": payload}, headers=h)

    _cop("combatant.add", {"name": "Lobo", "kind": "npc",
                           "hp_max": 11, "initiative": 5}, owner)
    cdata = client.get(f"/api/combat/{comb['id']}",
                       headers=owner).json()["combat"]
    npc = next(c for c in cdata["combatants"] if c["name"] == "Lobo")

    ent = client.post(f"/api/campaigns/{camp['id']}/entities", json={
        "kind": "map", "name": "M", "visibility": "public",
        "data": {"cols": 8, "rows": 6, "tokens": [
            {"id": "lobo", "name": "Lobo", "x": 0, "y": 0,
             "combatant_id": npc["id"]}]}}, headers=owner).json()

    def _mv(h):
        return client.post(
            f"/api/campaigns/{camp['id']}/entities/{ent['id']}/"
            "token-move",
            json={"token_id": "lobo", "x": 2, "y": 0}, headers=h)

    # sin delegar: el jugador no mueve el token del NPC
    assert _mv(player).status_code == 403
    # un jugador no puede delegarse a sí mismo (op DM-only)
    assert _cop("combatant.delegate",
                {"combatant_id": npc["id"], "player_uid": puid},
                player).status_code == 403
    # el DM delega → el jugador mueve el token del NPC
    assert _cop("combatant.delegate",
                {"combatant_id": npc["id"], "player_uid": puid},
                owner).status_code == 200
    assert _mv(player).status_code == 200
    # otro jugador sigue fuera
    assert _mv(other).status_code == 403
    # pero el delegado no dirige el combate (next_turn sigue siendo DM)
    assert _cop("combat.next_turn", {}, player).status_code == 403
    # revocar → vuelve a 403
    assert _cop("combatant.delegate",
                {"combatant_id": npc["id"], "player_uid": None},
                owner).status_code == 200
    assert _mv(player).status_code == 403


def test_packages_install_deps_and_uninstall():
    """Packs: dependencias obligatorias, conteo por tipo y
    desinstalación limpia (fuente + entidades + FTS)."""
    sfx = uuid.uuid4().hex[:8]          # la content DB persiste
    base_id, child_id = f"base-{sfx}", f"child-{sfx}"
    base = {"id": base_id, "name": "Base", "version": "1.0",
            "license": "CC-BY-4.0"}
    r = client.post("/api/packages/install", json={
        "manifest": {**base, "id": child_id,
                     "dependencies": [base_id]},
        "content": {"spell": [{"index": "bolt", "name": "Bolt"}]}})
    assert r.status_code == 409  # falta la base

    client.post("/api/packages/install", json={
        "manifest": base,
        "content": {"spell": [{"index": "a", "name": "A"},
                              {"index": "b", "name": "B"}]}})
    r = client.post("/api/packages/install", json={
        "manifest": {**base, "id": child_id,
                     "dependencies": [base_id]},
        "content": {"item": [{"index": "x", "name": "X"}]}})
    assert r.status_code == 201

    pkgs = client.get("/api/packages").json()["packages"]
    child = next(p for p in pkgs if p["id"] == f"pkg:{child_id}")
    assert child["by_type"] == {"item": 1}
    assert child["entities"] == 1

    # tras desinstalar no queda ni entidad ni FTS
    r = client.delete(f"/api/packages/{child_id}")
    assert r.status_code == 200
    hits = client.get("/api/content/search?q=X"
                      "&entity_type=item").json()["results"]
    assert not any(h["id"] == f"pkg:{child_id}:x" for h in hits)
    # solo packs — una fuente de pipeline no se borra por aquí
    assert client.delete("/api/packages/srd:2014").status_code == 404
    # limpieza: sin esto cada pytest dejaba un 'pkg:base-*' huérfano
    assert client.delete(f"/api/packages/{base_id}").status_code == 200


def test_export_vtt_includes_scenes():
    """El export VTT lleva el estado táctico: grid, muros, niebla,
    tokens con visión/luz — no solo actores y combates."""
    owner = _auth_headers(f"v{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    client.post(f"/api/campaigns/{camp['id']}/entities", json={
        "kind": "map", "name": "Mazmorra", "visibility": "public",
        "data": {"cols": 8, "rows": 6, "cell_ft": 5,
                 "walls": ["3,3,E"], "fog": ["1,1"],
                 "tokens": [{"id": "t1", "name": "Mago", "x": 2, "y": 2,
                             "size": 1, "vision_ft": 60,
                             "light_ft": 20}]}}, headers=owner)
    r = client.get(f"/api/campaigns/{camp['id']}/export-vtt",
                   headers=owner)
    assert r.status_code == 200
    sc = r.json()["scenes"]
    assert len(sc) == 1
    m = sc[0]
    assert m["walls"] == ["3,3,E"] and m["fog"] == ["1,1"]
    tk = m["tokens"][0]
    assert tk["vision_ft"] == 60 and tk["light_ft"] == 20


def test_present_only_dm_and_public():
    """'Mostrar al grupo': solo el DM proyecta, solo entidades
    públicas — una nota oculta no debe llegar al modal de nadie."""
    owner = _auth_headers(f"p{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"q{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)

    pub = client.post(f"/api/campaigns/{camp['id']}/entities", json={
        "kind": "note", "name": "Pública",
        "visibility": "public", "data": {"notes": "texto"}},
        headers=owner).json()
    dm_only = client.post(f"/api/campaigns/{camp['id']}/entities", json={
        "kind": "note", "name": "Oculta", "visibility": "dm"},
        headers=owner).json()

    url = f"/api/campaigns/{camp['id']}/present"
    assert client.post(url, json={"entity_id": pub["id"]},
                       headers=player).status_code == 403
    assert client.post(url, json={"entity_id": dm_only["id"]},
                       headers=owner).status_code == 400
    r = client.post(url, json={"entity_id": pub["id"]}, headers=owner)
    assert r.status_code == 200
    # cerrar la presentación (entity_id null)
    assert client.post(url, json={"entity_id": None},
                       headers=owner).status_code == 200
    assert client.post(url, json={"entity_id": "no-existe"},
                       headers=owner).status_code == 404


def test_party_rest_applies_to_all_sheets_dm_only():
    """POST /campaigns/{id}/rest?kind=long aplica character.rest.long a
    cada ficha como op real — PG al máximo, deshacible. DM-only."""
    owner = _auth_headers(f"pr{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"ps{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=player)
    a = client.post("/api/characters",
                    json={"name": "A", "campaign_id": camp["id"]},
                    headers=player).json()
    # daña al PJ: hp 8 → 3
    ver = client.get(f"/api/characters/{a['id']}",
                     headers=player).json()["version"]
    client.post("/api/operations", json={
        "operation_id": uuid.uuid4().hex, "entity_id": a["id"],
        "entity_version": ver, "client_id": "c", "user_id": "u",
        "entity_kind": "character",
        "operation_type": "character.hp.damage",
        "payload": {"amount": 5}}, headers=player)
    assert client.post(f"/api/campaigns/{camp['id']}/rest?kind=long",
                       headers=player).status_code == 403
    r = client.post(f"/api/campaigns/{camp['id']}/rest?kind=long",
                    headers=owner)
    assert r.status_code == 200 and r.json()["rested"] == 1
    hp = client.get(f"/api/characters/{a['id']}",
                    headers=player).json()["data"]["hp"]
    assert hp["current"] == hp["max"]

# --- eventos faltantes en EventType: emitirlos daba 500 tras rollback ---

def test_item_charge_ops_via_rest():
    """character.item.charge.set|use emitían 'inventory.item.charged' —
    el tipo no estaba en EventType y apply_to_store hacía 500."""
    cid = _mkchar()
    assert _op(cid, _version(cid), "character.inventory.add",
               {"id": "wand", "name": "Varita", "quantity": 1}
               ).status_code == 200
    r = _op(cid, _version(cid), "character.item.charge.set",
            {"item_id": "wand", "max": 7})
    assert r.status_code == 200
    r = _op(cid, _version(cid), "character.item.charge.use",
            {"item_id": "wand", "amount": 2})
    assert r.status_code == 200


def test_undo_rest_doesnt_500():
    """undo de rest.long aplica character.state.restore — su evento
    'character.state.restored' no estaba en EventType → 500."""
    cid = _mkchar()
    _op(cid, _version(cid), "character.hp.damage", {"amount": 5})
    r = _op(cid, _version(cid), "character.rest.long", {})
    assert r.status_code == 200
    # localizar la op rest.long y deshacerla por REST
    ops = _history(cid)
    rest_op = next(o for o in ops
                   if o["operation_type"] == "character.rest.long")
    r = client.post(f"/api/operations/undo/{rest_op['operation_id']}")
    assert r.status_code == 200
    data = client.get(f"/api/characters/{cid}").json()["data"]
    assert data["hp"]["current"] == data["hp"]["max"] - 5


def test_death_save_undo_restores_conditions():
    """Deshacer combatant.death_save debe quitar 'estable'/'muerto' —
    la inversa no guardaba conditions."""
    from app.domain.combat import Combatant as Cbt
    cb = Combat(name="c", combatants=[
        Cbt(id="x", name="Heroe", kind="character",
            hp_current=0, hp_max=10, death_saves={"success": 0,
                                                  "fail": 0})])
    apply_combat_operation(cb, "combatant.death_save",
                           {"combatant_id": "x", "success": True}, None)
    apply_combat_operation(cb, "combatant.death_save",
                           {"combatant_id": "x", "success": True}, None)
    inv, _ = apply_combat_operation(
        cb, "combatant.death_save", {"combatant_id": "x",
                                     "success": True}, None)
    assert "estable" in cb.combatants[0].conditions
    apply_combat_operation(cb, inv["operation_type"],
                           inv["payload"], None)
    c = cb.combatants[0]
    assert "estable" not in c.conditions
    assert c.death_saves == {"success": 2, "fail": 0}


def test_reveal_condition_session_active():
    """reveal_condition='session_active' se evaluaba nunca: activar la
    sesión debe revelar la entidad automáticamente."""
    owner = _auth_headers(f"rv{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    e = client.post(f"/api/campaigns/{camp['id']}/entities", json={
        "kind": "npc", "name": "Villano", "visibility": "dm",
        "reveal_condition": "session_active"}, headers=owner).json()
    s = client.post(f"/api/campaigns/{camp['id']}/sessions",
                    json={"title": "S1"}, headers=owner).json()
    r = client.patch(f"/api/campaigns/{camp['id']}/sessions/{s['id']}",
                     json={"status": "active"}, headers=owner)
    assert r.status_code == 200
    assert e["id"] in (r.json().get("revealed") or [])
    ents = client.get(f"/api/campaigns/{camp['id']}/entities",
                      headers=owner).json()["entities"]
    ent = next(x for x in ents if x["id"] == e["id"])
    assert ent["visibility"] == "public" and ent["revealed_at"]


def test_package_capabilities_and_app_version_enforced():
    """capabilities desconocidas / contenido sin 'content' /
    required_app_version futura → rechazo, no install a medias."""
    pid = f"cap-{uuid.uuid4().hex[:8]}"
    bad = {"manifest": {"id": pid, "name": "P", "version": "1",
                        "license": "CC0",
                        "capabilities": ["run_arbitrary_js"]},
           "content": {}}
    assert client.post("/api/packages/install", json=bad
                       ).status_code == 400
    bad2 = {"manifest": {"id": pid, "name": "P", "version": "1",
                         "license": "CC0", "capabilities": ["themes"]},
            "content": {"spells": [{"index": "x", "name": "X"}]}}
    assert client.post("/api/packages/install", json=bad2
                       ).status_code == 400
    fut = {"manifest": {"id": pid, "name": "P", "version": "1",
                        "license": "CC0",
                        "required_app_version": "999.0.0"},
           "content": {}}
    assert client.post("/api/packages/install", json=fut
                       ).status_code == 409

# --- inversas exactas (auditoria de reversibilidad) --------------------

def test_xp_add_inverse_restores_exact_value():
    """xp.add con clamp a 0: la inversa -amount inflaba el XP
    (5 - 10 -> 0, undo +10 -> 10 != 5). Ahora restaura el valor previo."""
    c = Character(name="t", xp=5)
    inv, _ = apply_operation(c, "character.xp.add", {"amount": -10})
    assert c.xp == 0
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.xp == 5
    inv2, _ = apply_operation(c, "character.xp.add", {"amount": 300})
    assert c.xp == 305
    apply_operation(c, inv2["operation_type"], inv2["payload"])
    assert c.xp == 5


def test_inventory_add_merge_inverse_only_removes_added():
    """add sobre stack existente: undo quitaba el total fusionado."""
    c = Character(name="t")
    apply_operation(c, "character.inventory.add",
                    {"id": "i1", "name": "Flecha", "quantity": 5})
    inv, _ = apply_operation(c, "character.inventory.add",
                             {"id": "i1", "name": "Flecha",
                              "quantity": 2})
    assert c.inventory[0].quantity == 7
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.inventory[0].quantity == 5


def test_attune_redo_noop_inverse_keeps_attunement():
    """attune sobre objeto ya sintonizado: su inversa unattune
    borraba la sintonia legitima."""
    c = Character(name="t")
    apply_operation(c, "character.inventory.add",
                    {"id": "i1", "name": "Anillo"})
    apply_operation(c, "character.item.attune", {"item_id": "i1"})
    inv, _ = apply_operation(c, "character.item.attune",
                             {"item_id": "i1"})
    assert inv["operation_type"] == "character.item.noop"
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.inventory[0].attuned is True


def test_equip_redo_noop_inverse_keeps_state():
    """equip sobre objeto ya equipado: su inversa unequip lo
    desequipaba Y borraba la sintonia."""
    c = Character(name="t")
    apply_operation(c, "character.inventory.add",
                    {"id": "i1", "name": "Espada"})
    apply_operation(c, "character.item.equip", {"item_id": "i1"})
    apply_operation(c, "character.item.attune", {"item_id": "i1"})
    inv, _ = apply_operation(c, "character.item.equip",
                             {"item_id": "i1"})
    assert inv["operation_type"] == "character.item.noop"
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.inventory[0].equipped is True
    assert c.inventory[0].attuned is True


def test_journal_add_inverse_removes_exact_entry():
    """El undo no es LIFO: con otra entrada intermedia, journal.pop
    borraba la ultima en vez de la anadida."""
    c = Character(name="t")
    inv_a, _ = apply_operation(c, "character.journal.add",
                               {"entry": "entrada A"})
    apply_operation(c, "character.journal.add", {"entry": "entrada B"})
    apply_operation(c, inv_a["operation_type"], inv_a["payload"])
    assert c.narrative.journal == ["entrada B"]


def test_spell_slot_use_rejects_missing_and_overdraw():
    """setdefault creaba un nivel fantasma {total:0} y una inversa
    count=0 que explotaba en restore."""
    c = Character(name="t", spell_slots={"1": {"total": 2, "used": 0}})
    with pytest.raises(ValueError):
        apply_operation(c, "character.spell_slot.use", {"level": 3})
    assert "3" not in c.spell_slots
    apply_operation(c, "character.spell_slot.use",
                    {"level": 1, "count": 2})
    with pytest.raises(ValueError):
        apply_operation(c, "character.spell_slot.use", {"level": 1})
    assert c.spell_slots["1"] == {"total": 2, "used": 2}
    # el undo del uso doble sigue restaurando los 2
    hist_inv = {"operation_type": "character.spell_slot.restore",
                "payload": {"level": 1, "pool": "regular", "count": 2}}
    apply_operation(c, hist_inv["operation_type"], hist_inv["payload"])
    assert c.spell_slots["1"]["used"] == 0


def test_combat_prev_turn_inverse_restores_exact_state():
    """prev_turn invertido con next_turn volvia a expirar duraciones.
    Ambos usan snapshot ahora."""
    from app.engine.combat_ops import apply_combat_operation
    cb = Combat(name="t", combatants=[
        Combatant(id="a", name="x", initiative=20,
                  conditions=["prone"],
                  condition_durations={"prone": 1}),
        Combatant(id="b", name="y", initiative=10)],
        turn_index=1, round=1)
    before = cb.model_dump()
    inv, _ = apply_combat_operation(cb, "combat.prev_turn", {}, _Ctx())
    assert cb.turn_index == 0
    apply_combat_operation(cb, inv["operation_type"], inv["payload"],
                           _Ctx())
    assert cb.model_dump() == before    # turno y duraciones intactas
    inv2, _ = apply_combat_operation(cb, "combat.next_turn", {}, _Ctx())
    assert cb.round == 2 and cb.turn_index == 0
    assert cb.combatants[0].conditions == []      # prone expiró
    apply_combat_operation(cb, inv2["operation_type"],
                           inv2["payload"], _Ctx())
    assert cb.model_dump() == before    # snapshot exacto


def test_death_save_manual_syncs_character_sheet():
    """combatant.death_save (manual) no llamaba _sync_character —
    la ficha quedaba desfasada. Y el bump de version/updated_at."""
    cid = _mkchar()
    comb = client.post("/api/combat", json={"name": "X"}).json()
    v = client.get(f"/api/combat/{comb['id']}").json()["version"]
    _op(comb["id"], v, "combatant.add",
        {"kind": "character", "name": "P", "ref_id": cid},
        kind="combat")
    cj = client.get(f"/api/combat/{comb['id']}").json()
    cbid = cj["combat"]["combatants"][0]["id"]
    v = cj["version"]
    _op(comb["id"], v, "combatant.hp.set",
        {"combatant_id": cbid, "current": 0}, kind="combat")
    cv = client.get(f"/api/characters/{cid}").json()["version"]
    v = client.get(f"/api/combat/{comb['id']}").json()["version"]
    r = _op(comb["id"], v, "combatant.death_save",
            {"combatant_id": cbid, "success": True}, kind="combat")
    assert r.status_code == 200
    ch = client.get(f"/api/characters/{cid}").json()
    assert ch["data"]["death_saves"]["success"] == 1
    assert ch["version"] > cv           # bump: la hoja nota el cambio


def test_operation_id_reuse_with_different_payload_conflicts():
    """Mismo operation_id + distinto payload devolvia el resultado
    anterior en silencio — ahora 409."""
    cid = _mkchar()
    oid = uuid.uuid4().hex
    body = {"operation_id": oid, "entity_id": cid,
            "entity_version": 1, "client_id": "c", "user_id": "u",
            "entity_kind": "character",
            "operation_type": "character.hp.damage",
            "payload": {"amount": 2}}
    assert client.post("/api/operations", json=body).status_code == 200
    # mismo id, otro contenido -> conflicto, no eco del viejo
    body2 = {**body, "payload": {"amount": 99}}
    assert client.post(
        "/api/operations", json=body2).status_code == 409
    # mismo id, mismo contenido -> duplicado idempotente
    r = client.post("/api/operations", json=body)
    assert r.status_code == 200 and r.json()["duplicate"] is True


def test_death_save_undo_rejects_crafted_other_combatant():
    """Un _undoes de la propia death_save_roll solo autoriza la
    inversa EXACTA guardada: ni otro combatiente ni valores a medida."""
    owner = _auth_headers(f"ds{uuid.uuid4().hex[:8]}")
    pa = _auth_headers(f"pa{uuid.uuid4().hex[:8]}")
    pb = _auth_headers(f"pb{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=pa)
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=pb)
    cha = client.post("/api/characters",
                      json={"name": "A", "campaign_id": camp["id"]},
                      headers=pa).json()
    chb = client.post("/api/characters",
                      json={"name": "B", "campaign_id": camp["id"]},
                      headers=pb).json()
    comb = client.post("/api/combat", json={
        "name": "X", "campaign_id": camp["id"]}, headers=owner).json()
    client.post(f"/api/combat/{comb['id']}/add-party", headers=owner)
    cj = client.get(f"/api/combat/{comb['id']}", headers=owner).json()
    cba = next(c for c in cj["combat"]["combatants"]
               if c.get("ref_id") == cha["id"])
    cbb = next(c for c in cj["combat"]["combatants"]
               if c.get("ref_id") == chb["id"])

    def _cop(otype, payload, h):
        cur = client.get(f"/api/combat/{comb['id']}",
                         headers=owner).json()["version"]
        return client.post("/api/operations", json={
            "operation_id": uuid.uuid4().hex, "entity_id": comb["id"],
            "entity_version": cur, "client_id": "c", "user_id": "u",
            "entity_kind": "combat", "operation_type": otype,
            "payload": payload}, headers=h)

    # ambos a 0 PG, A tira su salvacion legitima
    _cop("combatant.hp.set", {"combatant_id": cba["id"], "current": 0},
         owner)
    _cop("combatant.hp.set", {"combatant_id": cbb["id"], "current": 0},
         owner)
    r = _cop("combatant.death_save_roll",
             {"combatant_id": cba["id"]}, pa)
    assert r.status_code == 200
    roll_op = r.json()["operation_id"]

    # 1) _undoes propio + combatiente AJENO -> 403
    crafted = {"_undoes": roll_op, "combatant_id": cbb["id"],
               "death_saves": {"success": 0, "fail": 0},
               "hp": 100, "conditions": []}
    assert _cop("combatant.death_save.set", crafted,
                pa).status_code == 403
    # 2) _undoes propio + combatiente propio pero valores a medida
    #    (curarse a 100 PG) -> 403: no es la inversa guardada
    crafted2 = {"_undoes": roll_op, "combatant_id": cba["id"],
                "death_saves": {"success": 0, "fail": 0},
                "hp": 100, "conditions": []}
    assert _cop("combatant.death_save.set", crafted2,
                pa).status_code == 403
    # el combatiente B sigue a 0 PG, intocado
    cj2 = client.get(f"/api/combat/{comb['id']}",
                     headers=owner).json()["combat"]
    bb = next(c for c in cj2["combatants"] if c["id"] == cbb["id"])
    assert bb["hp_current"] == 0
    # 3) el undo legitimo (endpoint /undo) sigue funcionando
    assert client.post(f"/api/operations/undo/{roll_op}",
                       headers=pa).status_code == 200

# --- privacidad: secrets solo PJ + DM -----------------------------------

def test_character_secrets_redacted_for_other_members():
    """narrative.secrets es 'solo PJ + DM': cualquier miembro leía la
    ficha íntegra (GET /characters/{id}, /export y /campaigns/state)."""
    owner = _auth_headers(f"sc{uuid.uuid4().hex[:8]}")
    pa = _auth_headers(f"sa{uuid.uuid4().hex[:8]}")
    pb = _auth_headers(f"sb{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "C"},
                       headers=owner).json()
    code = client.get(f"/api/campaigns/{camp['id']}",
                      headers=owner).json()["invite_code"]
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=pa)
    client.post("/api/campaigns/join",
                json={"invite_code": code}, headers=pb)
    ch = client.post("/api/characters",
                     json={"name": "A", "campaign_id": camp["id"]},
                     headers=pa).json()
    # el jugador A escribe su secreto via op narrativa
    ver = client.get(f"/api/characters/{ch['id']}",
                     headers=pa).json()["version"]
    client.post("/api/operations", json={
        "operation_id": uuid.uuid4().hex, "entity_id": ch["id"],
        "entity_version": ver, "client_id": "c", "user_id": "x",
        "entity_kind": "character",
        "operation_type": "character.narrative.set",
        "payload": {"field": "secrets",
                    "value": "soy un doble agente"}}, headers=pa)

    # otro jugador: ni la ficha, ni el export, ni el resync lo revelan
    d = client.get(f"/api/characters/{ch['id']}",
                   headers=pb).json()["data"]
    assert d["narrative"]["secrets"] == ""
    ex = client.get(f"/api/characters/{ch['id']}/export",
                    headers=pb).json()["character"]
    assert ex["narrative"]["secrets"] == ""
    st = client.get(f"/api/campaigns/{camp['id']}/state",
                    headers=pb).json()
    sc = next(c for c in st["characters"] if c["id"] == ch["id"])
    assert sc["data"]["narrative"]["secrets"] == ""
    # el dueño y el DM sí lo leen
    assert client.get(f"/api/characters/{ch['id']}",
                      headers=pa).json()["data"]["narrative"]["secrets"]
    assert client.get(f"/api/characters/{ch['id']}",
                      headers=owner).json()["data"]["narrative"]["secrets"]

def test_ws_dm_visibility_reaches_co_dm():
    """broadcast() solo dejaba pasar visibility=dm a ('dm','owner',
    'local') — un co_dm autenticado no veía tiradas secretas ni
    eventos dm-only aunque REST sí se los sirve (_DM_ROLES)."""
    import asyncio
    from app.ws.rooms import manager
    co = _FakeWS()
    ply = _FakeWS()

    async def run():
        await manager.join("camp-cd", co, role="co_dm", name="c")
        await manager.join("camp-cd", ply, role="player", name="p")
        await manager.broadcast("camp-cd", {
            "type": "character.hp.changed",
            "payload": {"visibility": "dm", "amount": 7}})
        manager.leave("camp-cd", co)
        manager.leave("camp-cd", ply)

    asyncio.run(run())
    assert co.sent and co.sent[0]["payload"]["amount"] == 7
    assert not ply.sent


def test_currency_earn_undo_restores_exact_purse():
    """earn invertido con spend: si ya se había gastado, el undo daba
    'fondos insuficientes' — ahora es snapshot de la bolsa."""
    c = Character(name="t", purse={"gp": 2, "sp": 5, "cp": 3})
    inv, _ = apply_operation(c, "character.currency.earn", {"gp": 10})
    assert c.purse["gp"] == 12
    # gasta justo lo ganado: con la inversa vieja (spend 10gp) el undo
    # daba 'fondos insuficientes' — solo quedan 253cp en la bolsa
    apply_operation(c, "character.currency.spend", {"gp": 10})
    assert c.purse["gp"] == 2
    apply_operation(c, inv["operation_type"], inv["payload"])
    assert c.purse == {"gp": 2, "sp": 5, "cp": 3}


def test_shop_refund_removes_the_exact_item_bought():
    """refund por nombre podía descontar un stack homónimo distinto al
    objeto comprado — ahora la inversa viaja con el item_id real."""
    c = Character(name="t", purse={"gp": 100})
    apply_operation(c, "character.inventory.add",
                    {"id": "vieja", "name": "Poción", "quantity": 5})
    from app.db.connections import state_db
    camp_id = client.post(
        "/api/campaigns", json={"name": "tienda"}).json()["id"]
    shop_id = client.post(f"/api/campaigns/{camp_id}/entities",
                          json={"name": "Tienda", "kind": "shop",
                                "data": {"stock": [
                                    {"name": "Poción",
                                     "price_cp": 5000,
                                     "quantity": 3}]}}).json()["id"]

    # OpContext con UNA conexión — como en producción: si state_db()
    # abre una conexión por llamada, el UPDATE sin commit deja una txn
    # de escritura abierta y bloquea al siguiente escritor
    from app.api.operations import OpContext
    ctx = OpContext(state_db())
    inv, _ = apply_operation(c, "character.shop.buy",
                             {"shop_id": shop_id, "item": "Poción"},
                             ctx)
    assert any(i.name == "Poción" and i.id != "vieja"
               for i in c.inventory)
    old = next(i for i in c.inventory if i.id == "vieja")
    apply_operation(c, inv["operation_type"], inv["payload"], ctx)
    assert old.quantity == 5            # el stack viejo intacto
    assert all(i.name != "Poción" or i.id == "vieja"
               for i in c.inventory)    # la comprada se devolvió
    # sin este commit la txn de escritura de la tienda quedaba abierta
    # y el GC la cerraba a mitad de OTRO test → 'database is locked'
    ctx.state_db().commit()


# --- auditoría 2ª ronda: bordes de autorización -------------------------

def test_anonymous_listing_only_local_campaigns():
    """GET /api/campaigns sin token: solo campañas sin owner. Antes
    listaba TODAS (role=dm) — enumeración de mesas privadas."""
    owner = _auth_headers(f"lo{uuid.uuid4().hex[:8]}")
    own = client.post("/api/campaigns", json={"name": "Privada"},
                      headers=owner).json()["id"]
    local = client.post("/api/campaigns",
                        json={"name": "Local"}).json()["id"]
    ids = [c["id"] for c in client.get("/api/campaigns")
           .json()["campaigns"]]
    assert local in ids
    assert own not in ids
    # el owner la sigue viendo en SU lista
    ids2 = [c["id"] for c in client.get(
        "/api/campaigns", headers=owner).json()["campaigns"]]
    assert own in ids2


def test_campaign_id_empty_string_does_not_disarm_guards():
    """PATCH campaign_id=\"\" quedaba guardado tal cual: ni truthy ni
    None → saltaban AMBOS guards de ops y la ficha quedaba libre."""
    owner = _auth_headers(f"em{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"es{uuid.uuid4().hex[:8]}")
    uid = client.get("/api/auth/me", headers=owner).json()["user_id"]
    cid = client.post("/api/characters",
                      json={"name": "P", "player_id": uid},
                      headers=owner).json()["id"]
    r = client.patch(f"/api/characters/{cid}",
                     json={"campaign_id": ""}, headers=owner)
    assert r.status_code == 200
    row = client.get(f"/api/characters/{cid}", headers=owner).json()
    assert row["campaign_id"] is None          # normalizado a NULL
    # y las ops siguen pidiendo ser el dueño
    assert _op(cid, row["version"], "character.hp.damage",
               {"amount": 1}, ).status_code in (403, 409)
    v = client.get(f"/api/characters/{cid}").json()["version"]
    r = client.post("/api/operations", json={
        "operation_id": uuid.uuid4().hex, "entity_id": cid,
        "entity_version": v, "client_id": "c", "user_id": "x",
        "entity_kind": "character",
        "operation_type": "character.hp.damage",
        "payload": {"amount": 1}}, headers=stranger)
    assert r.status_code == 403


def test_campaignless_combat_cannot_touch_foreign_char():
    """Combate sin campaña + combatant.add con ref_id de una ficha
    personal ajena → 403. Antes _sync_character escribía hp/muerto
    en la hoja de otro usuario."""
    owner = _auth_headers(f"cc{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"cs{uuid.uuid4().hex[:8]}")
    uid = client.get("/api/auth/me", headers=owner).json()["user_id"]
    victim = client.post("/api/characters",
                         json={"name": "V", "player_id": uid},
                         headers=owner).json()["id"]
    comb = client.post("/api/combat", json={"name": "X"},
                       headers=stranger).json()

    def _cop(otype, payload, h):
        v = client.get(f"/api/combat/{comb['id']}",
                       headers=h).json()["version"]
        return client.post("/api/operations", json={
            "operation_id": uuid.uuid4().hex, "entity_id": comb["id"],
            "entity_version": v, "client_id": "t", "user_id": "x",
            "entity_kind": "combat", "operation_type": otype,
            "payload": payload}, headers=h)

    assert _cop("combatant.add", {"kind": "character",
                                  "ref_id": victim,
                                  "name": "V", "hp_max": 5,
                                  "initiative": 1},
                stranger).status_code == 403
    # ni por award-xp con el PJ metido por el propio dueño... el
    # dueño sí puede usar el combate sobre SU ficha
    assert _cop("combatant.add", {"kind": "character",
                                  "ref_id": victim, "name": "V",
                                  "hp_max": 5, "initiative": 1},
                owner).status_code == 200
    # pero award-xp del extraño NO toca la ficha del dueño
    assert client.post(f"/api/combat/{comb['id']}/award-xp",
                       headers=stranger).status_code == 403


def test_transfer_undo_disabled_and_personal_char_guard():
    """El undo de transfer es COMPUESTO (revierte ambas fichas en una
    txn — la mitad suelta duplicaba objetos) y una ficha personal
    ajena no se vacía."""
    owner = _auth_headers(f"to{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"ts{uuid.uuid4().hex[:8]}")
    uid = client.get("/api/auth/me", headers=owner).json()["user_id"]
    a = client.post("/api/characters", json={
        "name": "A", "player_id": uid}, headers=owner).json()["id"]
    b = client.post("/api/characters", json={
        "name": "B", "player_id": uid}, headers=owner).json()["id"]
    # el extraño no saca objetos de la ficha personal de A
    assert client.post("/api/inventory/transfer", json={
        "transfer_id": uuid.uuid4().hex, "from_character": a,
        "to_character": b, "item_id": "x", "quantity": 1},
        headers=stranger).status_code == 403
    # self-transfer y quantity 0 son 400 limpios
    assert client.post("/api/inventory/transfer", json={
        "transfer_id": uuid.uuid4().hex, "from_character": a,
        "to_character": a, "item_id": "x", "quantity": 1},
        headers=owner).status_code == 400
    # transfer real entre sus fichas → las ops existen pero no se
    # pueden deshacer (no-reversible)
    r = client.post("/api/operations", json={
        "operation_id": uuid.uuid4().hex, "entity_id": a,
        "entity_version": client.get(f"/api/characters/{a}",
                                     headers=owner).json()["version"],
        "client_id": "c", "user_id": "x", "entity_kind": "character",
        "operation_type": "character.inventory.add",
        "payload": {"id": "poc", "name": "Poción",
                    "quantity": 2}}, headers=owner)
    assert r.status_code == 200
    r = client.post("/api/inventory/transfer", json={
        "transfer_id": "tx-audit", "from_character": a,
        "to_character": b, "item_id": "poc", "quantity": 1},
        headers=owner)
    assert r.status_code == 200
    # el undo compuesto revierte las DOS mitades en una txn
    assert client.post("/api/operations/undo/tx-audit:out",
                       headers=owner).status_code == 200
    inv_a = client.get(f"/api/characters/{a}", headers=owner
                       ).json()["data"]["inventory"]
    inv_b = client.get(f"/api/characters/{b}", headers=owner
                       ).json()["data"]["inventory"]
    assert next(i for i in inv_a
                if i["name"] == "Poción")["quantity"] == 2
    assert not [i for i in inv_b if i["name"] == "Poción"]
    # y un segundo undo es 409, no un segundo traspaso
    assert client.post("/api/operations/undo/tx-audit:out",
                       headers=owner).status_code == 409


def test_register_trims_username_and_blocks_short():
    """\"  a\" pasaba min_length en bruto y quedaba un username de 1
    char; ahora el trim ocurre antes de validar."""
    r = client.post("/api/auth/register", json={
        "username": "  a", "password": "pw123456"})
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={
        "username": "  valido  ", "password": "pw123456"})
    assert r.status_code == 201
    # y se guarda recortado
    me = client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {r.json()['token']}"}).json()
    assert me["username"] == "valido"
    # login con espacios funciona (mismo normalizado)
    r = client.post("/api/auth/login", json={
        "username": " valido", "password": "pw123456"})
    assert r.status_code == 200


# --- Fase A de la auditoría -------------------------------------------

def test_statblock_5etools_skill_dict_and_v2_scores():
    """skill:{perception:"+4"} (5etools), ability_scores con claves
    cortas (open5e v2) y '30 ft.' en speed ya se normalizan bien."""
    from app.domain.statblock import normalize
    b = normalize({"name": "x", "hp": {"average": 20},
                   "skill": {"perception": "+4", "stealth": "+2"},
                   "ability_scores": {"str": 18},
                   "speed": {"walk": "30 ft."}})
    assert b["skills"]["perception"] == 4
    assert b["skills"]["stealth"] == 2
    assert b["abilities"]["str"] == 18
    assert b["speed"] == "walk 30 ft."      # no "30 ft. ft."


def test_remove_before_active_keeps_turn():
    """Quitar un combatiente anterior al activo reajusta turn_index —
    el que actuaba no pierde el turno."""
    c = Combat(combatants=[
        Combatant(id="ta", name="A", initiative=30),
        Combatant(id="tb", name="B", initiative=20),
        Combatant(id="tc", name="C", initiative=10)])
    c.turn_index = 1                                  # activo = B
    removed_id = c.combatants[0].id
    apply_combat_operation(c, "combatant.remove",
                           {"combatant_id": removed_id}, _Ctx())
    assert c.active.name == "B"                       # sigue siendo B
    # retirar al propio activo: pasa el turno al siguiente
    apply_combat_operation(c, "combatant.remove",
                           {"combatant_id": c.active.id}, _Ctx())
    assert c.active.name == "C"


def test_slot_use_rejects_overdraw():
    """count > disponibles es 400, no un clamp silencioso."""
    c = Character(name="t", spell_slots={"1": {"total": 2, "used": 0}})
    with pytest.raises(Exception):
        apply_operation(c, "character.spell_slot.use",
                        {"level": 1, "count": 3}, _Ctx())
    assert c.spell_slots["1"]["used"] == 0


def test_tick_negative_rounds_does_not_extend():
    """rounds=-5 INCREMENTABA las duraciones — el tiempo no va atrás."""
    c = Character(name="t", conditions=["x"],
                  condition_durations={"x": 2})
    apply_operation(c, "character.tick", {"rounds": -5}, _Ctx())
    assert c.condition_durations["x"] == 2


def test_warlock_level_row_targets_pact_slots():
    """'warlock|phb' (5etools) y similares llenan pact_slots, no
    spell_slots — la recarga en descanso corto depende de ello."""
    from app.engine.ops import _apply_level_row
    for cid in ("warlock|phb", "class:warlock", "warlock"):
        c = Character(name="w",
                      classes=[ClassLevel(class_id=cid, level=1)])
        _apply_level_row(c, cid,
                         {"spellcasting": {"spell_slots_level_2": 2}})
        assert c.pact_slots["2"]["total"] == 2, cid
        assert "2" not in c.spell_slots, cid


def test_combatant_add_character_uses_dex_and_live_hp(monkeypatch):
    """Un PJ entra al tracker con 1d20+DEX (su iniciativa real) y su
    hp.current vivo — antes 1d20+0 y un hp_max de payload ganaba."""
    import app.engine.combat_ops as co
    from app.db.connections import state_db
    from app.api.operations import OpContext
    from app.domain.character import AbilityScores

    class _R:
        total = 10
        rolls = [10]
    monkeypatch.setattr(co, "roll", lambda _e: _R())
    conn = state_db()
    ctx = OpContext(conn)
    ch = Character(name="Dex",
                   abilities=AbilityScores(dexterity=16))   # +3
    ch.hp.current = 7
    ch.hp.max = 20
    conn.execute(
        "INSERT INTO characters (id, name, version, data, updated_at)"
        " VALUES (?,?,0,?,?)",
        ("dex-pj", "Dex", ch.model_dump_json(), "x"))
    conn.commit()
    cm = Combat()
    apply_combat_operation(
        cm, "combatant.add",
        {"kind": "character", "ref_id": "dex-pj", "hp_max": 20}, ctx)
    c = cm.combatants[0]
    assert c.initiative == 13          # 10 + mod DEX 3, no +0
    assert c.hp_current == 7           # vivo de la ficha, no 20


def test_content_get_entity_404():
    """200 + {"error"} rompía el manejo estándar (res.ok -> .data)."""
    assert client.get("/api/content/no-existe").status_code == 404


def test_unsubscribe_needs_only_endpoint():
    """La baja push no exige 'keys' (no se usan en unsubscribe)."""
    r = client.post("/api/push/unsubscribe",
                    json={"endpoint": "https://x/" + uuid.uuid4().hex})
    assert r.status_code == 200


def test_conflict_retry_rejects_second_retry():
    """El retry de un conflicto es CAS atómico: el segundo intento
    sobre la misma op es 404, no un doble-apply."""
    cid = _mkchar()
    v = _version(cid)
    client.post("/api/operations", json={
        "operation_id": "c-flush", "entity_id": cid,
        "entity_version": v, "client_id": "x", "user_id": "x",
        "entity_kind": "character",
        "operation_type": "character.hp.set",
        "payload": {"current": 5}})
    client.post("/api/operations", json={
        "operation_id": "c-stale", "entity_id": cid,
        "entity_version": v, "client_id": "y", "user_id": "y",
        "entity_kind": "character",
        "operation_type": "character.hp.set",
        "payload": {"current": 8}})          # -> conflict
    r = client.post("/api/operations/conflicts/c-stale/retry")
    assert r.status_code == 200
    # la op ya está 'resolved': un segundo retry no vuelve a aplicar
    r2 = client.post("/api/operations/conflicts/c-stale/retry")
    assert r2.status_code == 404
    assert client.get(f"/api/characters/{cid}").json(
        )["data"]["hp"]["current"] == 8      # una sola aplicación


# --- Fase B de la auditoría -------------------------------------------

def test_push_subscribe_cannot_hijack_endpoint():
    """Re-suscribir un endpoint registrado por otro usuario no le
    quita el user_id (antes INSERT OR REPLACE lo pisaba)."""
    owner = _auth_headers(f"po{uuid.uuid4().hex[:8]}")
    stranger = _auth_headers(f"ps{uuid.uuid4().hex[:8]}")
    ep = "https://push.example/" + uuid.uuid4().hex
    keys = {"p256dh": "k", "auth": "a"}
    r = client.post("/api/push/subscribe", headers=owner,
                    json={"endpoint": ep, "keys": keys})
    assert r.status_code == 201
    # extraño: ni se adueña ni la desvincula
    r = client.post("/api/push/subscribe", headers=stranger,
                    json={"endpoint": ep, "keys": keys})
    assert r.status_code == 403
    # el dueño sí actualiza sus claves
    r = client.post("/api/push/subscribe", headers=owner,
                    json={"endpoint": ep, "keys": keys})
    assert r.status_code == 201


def test_insert_entity_cross_type_collision_disambiguates():
    """monster 'goblin' y spell 'goblin' de la misma fuente ya no se
    sobrescriben — el tipo desambigua el id solo en colisión real."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                           / "data-pipeline"))
    from pipeline import db as pdb  # noqa: E402
    conn = pdb.connect(":memory:")
    pdb.upsert_source(conn, source_id="s", name="S", version=None,
                      license="OGL")
    common = dict(source_id="s", index="goblin", name="Goblin",
                  ruleset="dnd5e-2014", license="OGL", data={})
    a = pdb.insert_entity(conn, entity_type="monster", **common)
    b = pdb.insert_entity(conn, entity_type="spell", **common)
    assert a == "s:goblin"                    # el primero, id corto
    assert b == "s:spell:goblin"              # el segundo, ambiguo
    assert conn.execute(
        "SELECT COUNT(*) n FROM content_entities").fetchone()[0] == 2
    # mismo tipo+mismo índice sigue siendo upsert (semántica deseada)
    pdb.insert_entity(conn, entity_type="monster", **common)
    assert conn.execute(
        "SELECT COUNT(*) n FROM content_entities").fetchone()[0] == 2


# --- Fase C de la auditoría: triggers declarativos --------------------

def test_triggered_effect_not_passive():
    """Un Effect con trigger NO aplica a resolve_stat — antes una
    inmunidad 'al recibir daño' quedaba permanente."""
    from app.engine.engine import resolve_stat
    from app.domain.effects import Trigger
    eff = Effect(id="e1", name="escudo de emergencia",
                 trigger=Trigger.BEFORE_DAMAGE,
                 operations=[EffectOperation(
                     op=Operation.ADD_MODIFIER,
                     target="armor_class", value=5)])
    bd = resolve_stat("armor_class", 10, [eff])
    assert bd.total == 10          # no +5 permanente
    # el mismo efecto como pasivo sí suma
    eff2 = eff.model_copy(update={"trigger": None})
    assert resolve_stat("armor_class", 10, [eff2]).total == 15


def test_effect_conditions_resolve_nested_ctx():
    """{field:'hp.pct'} resolvía contra ctx plano y moría — ahora _dig
    navega el model_dump anidado."""
    from app.engine.engine import check_conditions
    from app.domain.effects import EffectCondition
    ctx = {"hp": {"current": 3, "max": 10}}
    c_lt = EffectCondition(field="hp.current", lt=5)
    c_gt = EffectCondition(field="hp.current", gt=5)
    assert check_conditions([c_lt], ctx) is True
    assert check_conditions([c_gt], ctx) is False


def test_before_after_damage_triggers_run():
    """hp.damage ejecuta triggers de daño: restaurar recurso al
    recibir daño muta la ficha dentro de la misma op."""
    from app.domain.effects import Trigger
    from app.domain.character import Resource
    c = Character(name="t")
    c.resources.append(Resource(id="rabia", name="Rabia",
                                current=0, max=2))
    c.effects.append(Effect(
        id="e", name="grito", trigger=Trigger.AFTER_DAMAGE,
        operations=[EffectOperation(op=Operation.RESTORE_RESOURCE,
                                    target="rabia", value=1)]))
    apply_operation(c, "character.hp.damage",
                    {"amount": 3, "type": "fire"}, _Ctx())
    assert c.resources[0].current == 1     # el trigger disparó


def test_damage_grant_with_damage_trigger_applies():
    """grant_resistance bajo before_damage SÍ cuenta en el daño —
    solo los triggers ajenos al contexto se ignoran."""
    from app.domain.effects import Trigger
    c = Character(name="t", hp={"current": 10, "max": 10, "temp": 0})
    c.effects.append(Effect(
        id="e", name="amorfo", trigger=Trigger.BEFORE_DAMAGE,
        operations=[EffectOperation(op=Operation.GRANT_RESISTANCE,
                                    target="fire")]))
    apply_operation(c, "character.hp.damage",
                    {"amount": 8, "type": "fire"}, _Ctx())
    assert c.hp.current == 6               # 8÷2, no 8 ni 0
    # pero el mismo grant con trigger de descanso NO aplica al daño
    c2 = Character(name="t", hp={"current": 10, "max": 10, "temp": 0})
    c2.effects.append(c.effects[0].model_copy(
        update={"trigger": Trigger.ON_SHORT_REST}))
    apply_operation(c2, "character.hp.damage",
                    {"amount": 8, "type": "fire"}, _Ctx())
    assert c2.hp.current == 2              # daño íntegro


def test_on_apply_on_remove_triggers():
    """effect.add/remove disparan los triggers de ciclo de vida."""
    from app.domain.effects import Trigger
    from app.domain.character import Resource
    c = Character(name="t")
    c.resources.append(Resource(id="carga", name="Carga",
                                current=1, max=3))
    apply_operation(c, "character.effect.add", {"effect": {
        "id": "furia", "name": "Furia", "trigger": "on_apply",
        "operations": [{"op": "consume_resource", "target": "carga",
                        "value": 1}]}}, _Ctx())
    assert c.resources[0].current == 0     # on_apply consumió
    c2 = Character(name="t", conditions=["furia-x"])
    c2.effects.append(Effect(
        id="f", name="F", trigger=Trigger.ON_REMOVE,
        operations=[EffectOperation(op=Operation.REMOVE_CONDITION,
                                    value="furia-x")]))
    apply_operation(c2, "character.effect.remove",
                    {"effect_id": "f"}, _Ctx())
    assert "furia-x" not in c2.conditions  # on_remove disparó


def test_turn_triggers_fire_on_linked_char():
    """next_turn dispara on_turn_end/on_turn_start sobre las fichas
    vinculadas — el efecto declarativo muta resources del PJ."""
    from app.domain.character import Resource
    from app.db.connections import state_db
    from app.api.operations import OpContext
    conn = state_db()
    ctx = OpContext(conn)
    ch = Character(name="Ki")
    ch.resources.append(Resource(id="ki", name="Ki", current=0, max=3))
    ch.effects.append(Effect(
        id="med", name="Meditación", trigger="on_turn_start",
        operations=[EffectOperation(op=Operation.RESTORE_RESOURCE,
                                    target="ki", value=1)]))
    conn.execute("INSERT INTO characters (id, name, version, data,"
                 " updated_at) VALUES (?,?,0,?,?)",
                 ("ki-pj", "Ki", ch.model_dump_json(), "x"))
    conn.commit()
    cm = Combat(combatants=[
        Combatant(id="k", kind="character", name="Ki", initiative=20,
                  hp_current=5, hp_max=5, ref_id="ki-pj"),
        Combatant(id="g", name="Goblin", initiative=10)])
    apply_combat_operation(cm, "combat.next_turn", {}, ctx)  # Ki→Goblin
    # cierra ronda (on_round_start de todos) y vuelve a Ki (turn_start)
    apply_combat_operation(cm, "combat.next_turn", {}, ctx)
    conn.commit()   # el UPDATE del trigger abrió txn de escritura —
                    # sin commit dejaba la DB bloqueada a tests ajenos
    row = conn.execute("SELECT data FROM characters WHERE id='ki-pj'"
                       ).fetchone()
    assert Character(**json.loads(row["data"])
                     ).resources[0].current == 1              # +1 ki
