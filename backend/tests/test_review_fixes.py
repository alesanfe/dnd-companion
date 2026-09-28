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


def test_char_ownership_in_owned_campaign():
    """Un jugador solo muta SU ficha: player_id ligado al uid en el
    alta (spoof del body rebotado), patch/delete/op/transfer de la
    ficha de otro jugador = 403. El DM mueve todo."""
    def _account(tag):
        r = client.post("/api/auth/register", json={
            "username": f"{tag}{uuid.uuid4().hex[:8]}",
            "password": "pw12345"})
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

    async def send_text(self, text):
        self.sent.append(json.loads(text))


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
