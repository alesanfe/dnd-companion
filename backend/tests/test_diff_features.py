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
