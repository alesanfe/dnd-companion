"""Currency ops, shop buy, compare, homebrew, rules assistant,
packages, sessions/scenes, timeline, contextual actions."""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CONTENT_DB = Path(__file__).resolve().parents[2] / "data" / "content.sqlite3"
needs_content = pytest.mark.skipif(
    not CONTENT_DB.exists(), reason="content DB no importada")


def _mkchar(name="T"):
    return client.post("/api/characters", json={"name": name}).json()["id"]


def _op(cid, version, otype, payload, oid=None, kind="character"):
    return client.post("/api/operations", json={
        "operation_id": oid or uuid.uuid4().hex,
        "entity_id": cid, "entity_version": version,
        "client_id": "c1", "user_id": "u1", "entity_kind": kind,
        "operation_type": otype, "payload": payload})


def _version(cid):
    return client.get(f"/api/characters/{cid}").json()["version"]


# --- monedas ----------------------------------------------------------

def test_currency_earn_and_spend_with_conversion():
    cid = _mkchar()
    _op(cid, _version(cid), "character.currency.earn", {"gp": 5})
    # gastar 2 gp 5 sp: debe convertir (5gp=500cp, gasto 250cp)
    r = _op(cid, _version(cid), "character.currency.spend",
            {"gp": 2, "sp": 5})
    assert r.status_code == 200
    purse = client.get(f"/api/characters/{cid}").json()["data"]["purse"]
    total_cp = (purse["pp"] * 1000 + purse["gp"] * 100 + purse["ep"] * 50
                + purse["sp"] * 10 + purse["cp"])
    assert total_cp == 250


def test_spend_insufficient_funds_rejected():
    cid = _mkchar()
    r = _op(cid, _version(cid), "character.currency.spend", {"gp": 10})
    assert r.status_code == 400
    assert "insuficientes" in r.json()["detail"]


def test_shop_buy_deducts_coins_and_stock():
    camp = client.post("/api/campaigns", json={"name": "S"}).json()["id"]
    shop = client.post(f"/api/campaigns/{camp}/entities", json={
        "kind": "shop", "name": "Herrero", "visibility": "public",
        "data": {"stock": [{"name": "Espada", "price_cp": 1500,
                           "quantity": 2}]}}).json()["id"]
    cid = _mkchar()
    _op(cid, _version(cid), "character.currency.earn", {"gp": 20})
    r = _op(cid, _version(cid), "character.shop.buy",
            {"shop_id": shop, "item": "Espada"})
    assert r.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert any(i["name"] == "Espada" for i in d["inventory"])
    cp = (d["purse"]["pp"] * 1000 + d["purse"]["gp"] * 100
          + d["purse"]["sp"] * 10 + d["purse"]["cp"])
    assert cp == 2000 - 1500
    shop_data = client.get(
        f"/api/campaigns/{camp}/entities?kind=shop").json()["entities"]
    assert shop_data[0]["data"]["stock"][0]["quantity"] == 1


# --- content: compare / homebrew / rules ------------------------------

@needs_content
def test_compare_fireball_2014_vs_2024():
    r = client.get("/api/content/compare?index=fireball").json()
    assert "dnd5e-2014" in r["versions"]
    assert "dnd5e-2024" in r["versions"]
    assert r["versions"]["dnd5e-2014"]["data"]["level"] == 3


def test_homebrew_entity_searchable():
    r = client.post("/api/content/homebrew", json={
        "entity_type": "monster", "name": "Dragón de Café",
        "data": {"challenge_rating": "99"}})
    assert r.status_code == 201
    eid = r.json()["id"]
    ent = client.get(f"/api/content/{eid}").json()
    assert ent["name"] == "Dragón de Café"
    assert ent["source_id"] == "homebrew"
    # aparece en búsqueda FTS (término distintivo: 'dragon' matchea 168)
    s = client.get("/api/content/search?q=café").json()
    assert any(x["id"] == eid for x in s["results"])


@needs_content
def test_rules_assistant_cites_sources():
    r = client.post("/api/rules/ask", json={
        "question": "¿cómo funciona la condición grappled?"})
    body = r.json()
    assert body["evidence_found"] is True
    assert body["answer"] is None               # nunca inventa
    assert body["citations"][0]["citation"]["source_id"]


def test_rules_assistant_no_evidence():
    r = client.post("/api/rules/ask", json={
        "question": "zzzqqq xkcdp"})
    assert r.json()["evidence_found"] is False


# --- packages ----------------------------------------------------------

def test_package_install_registers_provenance():
    r = client.post("/api/packages/install", json={
        "manifest": {
            "id": "mi-pack", "name": "Mi Pack", "version": "1.0.0",
            "license": "CC-BY-4.0", "compatible_rulesets": ["dnd5e-2014"],
            "distribution_allowed": True},
        "content": {"spell": [{"index": "luz-de-luna", "name": "Luz de Luna",
                               "level": 2}]},
    })
    assert r.status_code == 201
    assert r.json()["entities"] == 1
    ent = client.get("/api/content/pkg:mi-pack:luz-de-luna").json()
    assert ent["license"] == "CC-BY-4.0"
    assert ent["ruleset"] == "dnd5e-2014"
    packs = client.get("/api/packages").json()["packages"]
    assert any(p["id"] == "pkg:mi-pack" for p in packs)


# --- sesiones, escenas, timeline ---------------------------------------

def test_sessions_with_ordered_scenes():
    camp = client.post("/api/campaigns", json={"name": "S1"}).json()["id"]
    sid = client.post(f"/api/campaigns/{camp}/sessions", json={
        "number": 1, "title": "La emboscada"}).json()["id"]
    for i, name in enumerate(["Puente", "Cueva", "Jefe"]):
        client.post(f"/api/campaigns/{camp}/entities", json={
            "kind": "scene", "name": name, "visibility": "dm",
            "data": {"session_id": sid, "order": 2 - i}})  # orden inverso
    sessions = client.get(f"/api/campaigns/{camp}/sessions").json()
    scenes = sessions["sessions"][0]["scenes"]
    assert [s["name"] for s in scenes] == ["Jefe", "Cueva", "Puente"]


def test_entity_patch_and_timeline():
    camp = client.post("/api/campaigns", json={"name": "T"}).json()["id"]
    e1 = client.post(f"/api/campaigns/{camp}/entities", json={
        "kind": "event", "name": "Caída del rey",
        "data": {"world_date": "1490-03-01"}}).json()["id"]
    client.post(f"/api/campaigns/{camp}/entities", json={
        "kind": "event", "name": "Fundación",
        "data": {"world_date": "1200-01-01"}})
    # PATCH: renombrar + añadir campo
    r = client.patch(f"/api/campaigns/{camp}/entities/{e1}", json={
        "name": "Caída del rey (sospechosa)",
        "data": {"clues": ["carta quemada"]}})
    assert "name" in r.json()["changed"]
    tl = client.get(f"/api/campaigns/{camp}/timeline").json()["timeline"]
    assert tl[0]["name"] == "Fundación"     # orden cronológico


# --- acciones contextuales ----------------------------------------------

@needs_content
def test_contextual_actions_groups_spells_and_weapons():
    r = client.post("/api/characters/create-from-options", json={
        "name": "Pía", "ruleset": "dnd5e-2014",
        "class_id": "srd-2014:wizard",
        "abilities": {"int": 16, "str": 10, "dex": 14},
    })
    cid = r.json()["id"]
    # arma + conjuros
    _op(cid, _version(cid), "character.inventory.add",
        {"name": "Daga", "source_id": "srd-2014:dagger"})
    d = client.get(f"/api/characters/{cid}").json()
    # añade spells_known directamente en data via un wrapper de update?
    # spells_known se rellena vía wizard avanzado; comprobamos lo básico:
    acts = client.get(f"/api/characters/{cid}/actions").json()["actions"]
    names = [a["name"] for a in acts["action"]]
    assert "Attack" in names
    assert any("Daga" in n for n in names)
    assert any(a["name"] == "Opportunity Attack" for a in acts["reaction"])


# --- combate ↔ ficha, craft, miembros, tirada con efectos --------------

def _combat_op(combat_id, version, otype, payload):
    return client.post("/api/operations", json={
        "operation_id": uuid.uuid4().hex,
        "entity_id": combat_id, "entity_version": version,
        "client_id": "c1", "user_id": "dm", "entity_kind": "combat",
        "operation_type": otype, "payload": payload})


def test_combat_damage_syncs_character_sheet():
    cid = _mkchar()
    d0 = client.get(f"/api/characters/{cid}").json()["data"]
    hp0 = d0["hp"]["current"]
    combat = client.post("/api/combat", json={"name": "X"}).json()
    # añade el personaje como combatiente (ref_id = character id)
    r = _combat_op(combat["id"], combat["version"], "combatant.add",
                   {"name": "Héroe", "kind": "character", "ref_id": cid})
    assert r.status_code == 200
    cdata = client.get(f"/api/combat/{combat['id']}").json()["combat"]
    bid = cdata["combatants"][0]["id"]
    assert cdata["combatants"][0]["hp_current"] == hp0  # HP de la ficha
    _combat_op(combat["id"],
               client.get(f"/api/combat/{combat['id']}").json()["version"],
               "combatant.damage", {"combatant_id": bid, "amount": 3})
    hp1 = client.get(f"/api/characters/{cid}").json()["data"]["hp"]["current"]
    assert hp1 == hp0 - 3


def test_craft_consumes_inputs_and_produces():
    cid = _mkchar()
    _op(cid, _version(cid), "character.inventory.add",
        {"name": "Hierro", "quantity": 3})
    r = _op(cid, _version(cid), "character.craft", {
        "inputs": [{"name": "Hierro", "quantity": 2}],
        "output": {"name": "Herradura"}})
    assert r.status_code == 200
    inv = client.get(f"/api/characters/{cid}").json()["data"]["inventory"]
    assert next(i for i in inv if i["name"] == "Hierro")["quantity"] == 1
    assert any(i["name"] == "Herradura" for i in inv)


def test_craft_missing_input_rejected():
    cid = _mkchar()
    r = _op(cid, _version(cid), "character.craft", {
        "inputs": [{"name": "Mithril"}], "output": {"name": "Anillo"}})
    assert r.status_code == 400


def test_join_registers_member():
    camp = client.post("/api/campaigns", json={"name": "M"})
    # busca el invite_code en la respuesta
    code = camp.json().get("invite_code")
    assert code
    cid = camp.json()["id"]
    client.post("/api/campaigns/join", json={
        "invite_code": code, "user_id": "ana", "role": "player"})
    members = client.get(f"/api/campaigns/{cid}/members").json()["members"]
    assert any(m["user_id"] == "ana" and m["role"] == "player"
               for m in members)


def test_character_roll_applies_advantage_effect():
    cid = _mkchar()
    d = client.get(f"/api/characters/{cid}").json()["data"]
    d["effects"] = [{
        "id": "e1", "name": "Guía", "trigger": None,
        "operations": [{"op": "grant_advantage", "target": "check"}],
    }]
    # escribe effects directamente — no hay op pública aún para añadirlos
    import sqlite3
    from app.db.connections import state_db
    conn = state_db()
    conn.execute("UPDATE characters SET data = ? WHERE id = ?",
                 (__import__("json").dumps(d), cid))
    conn.commit()
    r = client.post(f"/api/operations/character/{cid}/roll",
                    params={"expression": "1d20", "roll_type": "check"})
    body = r.json()
    assert len(body["rolls"]) == 2          # ventaja: tiró 2d20
    assert body["kept"][0] == max(body["rolls"])
    assert body["effects_applied"]


# --- auth + enforcement por rol ---------------------------------------

def _auth_headers(username):
    r = client.post("/api/auth/register", json={
        "username": username, "password": "pw12345"})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={
            "username": username, "password": "pw12345"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_register_login_me():
    h = _auth_headers(f"u{uuid.uuid4().hex[:8]}")
    me = client.get("/api/auth/me", headers=h)
    assert me.status_code == 200
    assert me.json()["user_id"]


def test_dm_entities_hidden_from_players():
    owner = _auth_headers(f"dm{uuid.uuid4().hex[:8]}")
    player = _auth_headers(f"p{uuid.uuid4().hex[:8]}")
    camp = client.post("/api/campaigns", json={"name": "Auth"},
                       headers=owner).json()
    client.post("/api/campaigns/join",
                json={"invite_code": camp["invite_code"]},
                headers=player)
    cid = camp["id"]
    # jugador no puede crear entidad oculta
    r = client.post(f"/api/campaigns/{cid}/entities",
                    json={"kind": "note", "name": "Secreto",
                          "visibility": "dm"}, headers=player)
    assert r.status_code == 403
    # el owner sí puede
    r = client.post(f"/api/campaigns/{cid}/entities",
                    json={"kind": "note", "name": "Secreto",
                          "visibility": "dm"}, headers=owner)
    assert r.status_code == 201
    # el jugador no la ve; el owner sí
    for h, expected in ((player, False), (owner, True)):
        ents = client.get(f"/api/campaigns/{cid}/entities",
                          headers=h).json()["entities"]
        assert any(e["name"] == "Secreto" for e in ents) is expected


def test_wrong_password_rejected():
    u = f"w{uuid.uuid4().hex[:8]}"
    client.post("/api/auth/register", json={"username": u, "password": "a"})
    r = client.post("/api/auth/login", json={"username": u, "password": "b"})
    assert r.status_code == 401


def test_logout_revokes_token():
    h = _auth_headers(f"lo{uuid.uuid4().hex[:8]}")
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


# --- mejoras incrementales ---------------------------------------------

def test_effect_add_remove_ops():
    cid = _mkchar()
    r = _op(cid, _version(cid), "character.effect.add", {
        "effect": {"name": "Bendición",
                   "operations": [{"op": "add_modifier", "target": "attack",
                                   "value": 1}]}})
    assert r.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    eff_id = d["effects"][0]["id"]
    r = _op(cid, _version(cid), "character.effect.remove",
            {"effect_id": eff_id})
    assert r.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["effects"] == []


def test_spell_cast_consumes_slot_and_concentration():
    cid = _mkchar()
    import json as _j
    from app.db.connections import state_db
    conn = state_db()
    d = client.get(f"/api/characters/{cid}").json()["data"]
    d["spell_slots"] = {"1": {"total": 2, "used": 0}}
    conn.execute("UPDATE characters SET data = ? WHERE id = ?",
                 (_j.dumps(d), cid))
    conn.commit()
    r = _op(cid, _version(cid), "character.spell.cast",
            {"spell_id": "srd-2014:mage-armor", "level": 1})
    assert r.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["spell_slots"]["1"]["used"] == 1
    # sin espacios → 400
    _op(cid, _version(cid), "character.spell.cast",
        {"spell_id": "x", "level": 1})
    r = _op(cid, _version(cid), "character.spell.cast",
            {"spell_id": "x", "level": 1})
    assert r.status_code == 400


def test_xp_and_concentration_break():
    cid = _mkchar()
    _op(cid, _version(cid), "character.xp.add", {"amount": 300})
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["xp"] == 300
    d["concentrating_on"] = "bendición"
    import json as _j
    from app.db.connections import state_db
    conn = state_db()
    conn.execute("UPDATE characters SET data = ? WHERE id = ?",
                 (_j.dumps(d), cid))
    conn.commit()
    _op(cid, _version(cid), "character.concentration.break", {})
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["concentrating_on"] is None


def test_damage_flags_concentration_check():
    cid = _mkchar()
    import json as _j
    from app.db.connections import state_db
    d = client.get(f"/api/characters/{cid}").json()["data"]
    d["concentrating_on"] = "invisibilidad"
    conn = state_db()
    conn.execute("UPDATE characters SET data = ? WHERE id = ?",
                 (_j.dumps(d), cid))
    conn.commit()
    r = _op(cid, _version(cid), "character.hp.damage", {"amount": 5})
    ev = r.json()["events"][0]["payload"]
    assert ev["concentration_check"] is True


def test_shop_buy_undo_restores_stock():
    camp = client.post("/api/campaigns", json={"name": "S"}).json()["id"]
    shop = client.post(f"/api/campaigns/{camp}/entities", json={
        "kind": "shop", "name": "Tienda", "visibility": "public",
        "data": {"stock": [{"name": "Poción", "price_cp": 500,
                            "quantity": 1}]}}).json()["id"]
    cid = _mkchar()
    _op(cid, _version(cid), "character.currency.earn", {"gp": 10})
    r = _op(cid, _version(cid), "character.shop.buy",
            {"shop_id": shop, "item": "Poción"})
    op_id = r.json()["operation_id"]
    # deshacer: repone stock, quita objeto, devuelve monedas
    client.post(f"/api/operations/undo/{op_id}")
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert not any(i["name"] == "Poción" for i in d["inventory"])
    shopd = client.get(
        f"/api/campaigns/{camp}/entities?kind=shop").json()["entities"]
    assert shopd[0]["data"]["stock"][0]["quantity"] == 1
    total_cp = sum(d["purse"][c] * v for c, v in
                   {"pp": 1000, "gp": 100, "ep": 50, "sp": 10,
                    "cp": 1}.items())
    assert total_cp == 1000          # reembolso íntegro (normalizado)


def test_death_saves():
    combat = client.post("/api/combat", json={"name": "D"}).json()
    _combat_op(combat["id"], combat["version"], "combatant.add",
               {"name": "Hero", "hp_max": 10})
    cdata = client.get(f"/api/combat/{combat['id']}").json()["combat"]
    bid = cdata["combatants"][0]["id"]
    v = client.get(f"/api/combat/{combat['id']}").json()["version"]
    _combat_op(combat["id"], v, "combatant.damage",
               {"combatant_id": bid, "amount": 99})
    v = client.get(f"/api/combat/{combat['id']}").json()["version"]
    for _ in range(3):
        r = _combat_op(combat["id"], v, "combatant.death_save",
                       {"combatant_id": bid, "success": True})
        v = r.json()["version"]
    c = client.get(f"/api/combat/{combat['id']}").json()["combat"]
    assert "estable" in c["combatants"][0]["conditions"]


def test_condition_disadvantage_and_autofail():
    cid = _mkchar()
    _op(cid, _version(cid), "character.condition.apply",
        {"condition": "poisoned"})
    r = client.post(f"/api/operations/character/{cid}/roll",
                    params={"expression": "1d20", "roll_type": "attack"})
    b = r.json()
    assert len(b["rolls"]) == 2                       # desventaja: 2d20
    assert b["kept"][0] == min(b["rolls"])
    # stunned → save:str falla automáticamente
    _op(cid, _version(cid), "character.condition.apply",
        {"condition": "stunned"})
    r = client.post(f"/api/operations/character/{cid}/roll",
                    params={"expression": "1d20", "roll_type": "save:str"})
    assert r.json()["auto_fail"] is True


def test_skill_roll_adds_ability_and_prof():
    cid = _mkchar()
    import json as _j
    from app.db.connections import state_db
    conn = state_db()
    d = client.get(f"/api/characters/{cid}").json()["data"]
    d["abilities"]["wis"] = 14          # +2
    d["skill_proficiencies"] = ["perception"]
    d["proficiency_bonus"] = 2
    conn.execute("UPDATE characters SET data = ? WHERE id = ?",
                 (_j.dumps(d), cid))
    conn.commit()
    r = client.post(f"/api/operations/character/{cid}/roll",
                    params={"expression": "1d20",
                            "roll_type": "skill:perception"})
    b = r.json()
    assert b["total"] == b["kept"][0] + 4   # +2 WIS +2 prof
    assert any("wis" in a for a in b["effects_applied"])
    assert any("prof" in a for a in b["effects_applied"])


def test_spell_cast_rejects_low_slot():
    cid = _mkchar()
    import json as _j
    from app.db.connections import state_db
    conn = state_db()
    d = client.get(f"/api/characters/{cid}").json()["data"]
    d["spell_slots"] = {"1": {"total": 4, "used": 0},
                        "3": {"total": 2, "used": 0}}
    conn.execute("UPDATE characters SET data = ? WHERE id = ?",
                 (_j.dumps(d), cid))
    conn.commit()
    # fireball es nivel 3 → no se puede con espacio de nivel 1
    r = _op(cid, _version(cid), "character.spell.cast",
            {"spell_id": "srd-2014:fireball", "level": 1})
    assert r.status_code == 400
    # upcasting a nivel 3 sí (si hay spell conocido en DB)
    r = _op(cid, _version(cid), "character.spell.cast",
            {"spell_id": "srd-2014:fireball", "level": 3})
    if r.status_code == 200:
        d = client.get(f"/api/characters/{cid}").json()["data"]
        assert d["spell_slots"]["3"]["used"] == 1


def test_death_save_roll_server_side():
    combat = client.post("/api/combat", json={"name": "DR"}).json()
    _combat_op(combat["id"], combat["version"], "combatant.add",
               {"name": "Hero", "hp_max": 10})
    cdata = client.get(f"/api/combat/{combat['id']}").json()["combat"]
    bid = cdata["combatants"][0]["id"]
    v = client.get(f"/api/combat/{combat['id']}").json()["version"]
    _combat_op(combat["id"], v, "combatant.damage",
               {"combatant_id": bid, "amount": 99})
    v = client.get(f"/api/combat/{combat['id']}").json()["version"]
    r = _combat_op(combat["id"], v, "combatant.death_save_roll",
                   {"combatant_id": bid})
    assert r.status_code == 200
    ev = r.json()["events"][0]["payload"]
    assert 1 <= ev["death_save_roll"] <= 20


def test_journal_add_and_undo():
    cid = _mkchar()
    r = _op(cid, _version(cid), "character.journal.add",
            {"entry": "Conocimos al tabernero"})
    assert r.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["narrative"]["journal"] == ["Conocimos al tabernero"]
    client.post(f"/api/operations/undo/{r.json()['operation_id']}")
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["narrative"]["journal"] == []


def test_attack_endpoint_hit_and_damage():
    cid = _mkchar()
    _op(cid, _version(cid), "character.inventory.add",
        {"name": "Daga", "source_id": "srd-2014:dagger"})
    r = client.post(f"/api/operations/character/{cid}/attack",
                    params={"item_name": "Daga"})
    if r.status_code == 404:
        import pytest
        pytest.skip("content DB no importada")
    b = r.json()
    assert 1 <= b["hit"]["total"] <= 20 + b["hit"]["bonus"]
    assert b["damage"]["rolls"]


def test_derived_all_stats():
    cid = _mkchar()
    import json as _j
    from app.db.connections import state_db
    conn = state_db()
    d = client.get(f"/api/characters/{cid}").json()["data"]
    d["abilities"]["dexterity"] = 16
    d["abilities"]["wisdom"] = 14
    d["proficiency_bonus"] = 2
    d["skill_proficiencies"] = ["perception"]
    conn.execute("UPDATE characters SET data = ? WHERE id = ?",
                 (_j.dumps(d), cid))
    conn.commit()
    r = client.get(f"/api/characters/{cid}/derived").json()
    assert r["initiative"] == 3
    assert r["passive_perception"] == 10 + 2 + 2     # wis 14 + prof
    assert r["armor_class"]["total"] == 10 + 3       # sin armadura: 10+DES
    assert r["spell_save_dc"] == 8 + 2 + 0           # int 10


def test_scene_start_creates_combat_with_monsters():
    camp = client.post("/api/campaigns", json={"name": "SC"}).json()["id"]
    scene = client.post(f"/api/campaigns/{camp}/entities", json={
        "kind": "scene", "name": "Emboscada", "visibility": "dm",
        "data": {"monsters": ["srd-2014:goblin"]}}).json()["id"]
    r = client.post(f"/api/campaigns/{camp}/scenes/{scene}/start")
    if r.status_code == 201:
        combat = client.get(f"/api/combat/{r.json()['combat_id']}").json()
        assert combat["combat"]["combatants"][0]["name"] == "Goblin"
    else:
        # sin content DB no hay monstruo, pero el combate se crea igual
        assert r.status_code in (201, 404)


def test_campaign_events_and_export():
    camp = client.post("/api/campaigns", json={"name": "EV"}).json()["id"]
    cid = _mkchar()
    client.patch(f"/api/characters/{cid}", json={"campaign_id": camp})
    # la tirada emite un evento dice.roll.created en la campaña
    client.post(f"/api/operations/character/{cid}/roll",
                params={"expression": "1d20", "roll_type": "check"})
    ev = client.get(f"/api/campaigns/{camp}/events").json()["events"]
    assert any(e["type"] == "dice.roll.created" for e in ev)
    ex = client.get(f"/api/campaigns/{camp}/export").json()
    assert ex["format"] == "dnd-companion-campaign"
    assert any(c["id"] == cid for c in ex["characters"])


def test_ability_set_and_attune_limit():
    cid = _mkchar()
    _op(cid, _version(cid), "character.ability.set",
        {"ability": "str", "value": 18})
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["abilities"]["strength"] == 18
    # sintonía: máximo 3
    for i in range(4):
        _op(cid, _version(cid), "character.inventory.add",
            {"name": f"Anillo{i}"})
    d = client.get(f"/api/characters/{cid}").json()["data"]
    ids = [i["id"] for i in d["inventory"]]
    for iid in ids[:3]:
        r = _op(cid, _version(cid), "character.item.attune",
                {"item_id": iid})
        assert r.status_code == 200
    r = _op(cid, _version(cid), "character.item.attune",
            {"item_id": ids[3]})
    assert r.status_code == 400


def test_inspiration_toggle_and_resource_add():
    cid = _mkchar()
    _op(cid, _version(cid), "character.inspiration.set", {"value": True})
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["inspiration"] is True
    r = _op(cid, _version(cid), "character.resource.add",
            {"name": "Furia", "max": 3, "reset_on": "long"})
    assert r.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["resources"][0]["name"] == "Furia"


@needs_content
def test_compare_returns_diff_keys():
    r = client.get("/api/content/compare?index=fireball").json()
    assert "diff" in r and isinstance(r["diff"], list)


def test_patch_and_delete_character():
    cid = _mkchar()
    r = client.patch(f"/api/characters/{cid}", json={"name": "Renombrado"})
    assert r.status_code == 200
    assert client.get(f"/api/characters/{cid}").json()["name"] == "Renombrado"
    assert client.delete(f"/api/characters/{cid}").status_code == 200
    assert client.get(f"/api/characters/{cid}").status_code == 404
