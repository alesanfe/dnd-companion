"""Wizard create-from-options + campaign join/state (necesita la
content DB real del SRD; se salta si no existe)."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CONTENT_DB = Path(__file__).resolve().parents[2] / "data" / "content.sqlite3"
needs_content = pytest.mark.skipif(
    not CONTENT_DB.exists(), reason="content DB no importada")


@needs_content
def test_wizard_builds_level1_barbarian():
    r = client.post("/api/characters/create-from-options", json={
        "name": "Grognak", "ruleset": "dnd5e-2014",
        "class_id": "srd-2014:barbarian",
        "abilities": {"str": 15, "dex": 14, "con": 14,
                      "int": 8, "wis": 12, "cha": 10},
    })
    assert r.status_code == 201, r.text
    char = client.get(f"/api/characters/{r.json()['id']}").json()
    d = char["data"]
    assert d["hp"]["max"] == 14                  # d12 + CON(+2)
    assert d["hit_dice"][0]["die"] == "d12"
    assert d["classes"][0]["class_id"] == "srd-2014:barbarian"


@needs_content
def test_wizard_spell_slots_for_caster():
    r = client.post("/api/characters/create-from-options", json={
        "name": "Merlin", "ruleset": "dnd5e-2014",
        "class_id": "srd-2014:wizard",
        "abilities": {"int": 15, "con": 12},
    })
    char = client.get(f"/api/characters/{r.json()['id']}").json()
    assert char["data"]["spell_slots"]["1"]["total"] == 2  # wizard niv 1


def test_campaign_create_join_state():
    r = client.post("/api/campaigns", json={"name": "Mina Perdida"})
    assert r.status_code == 201
    camp = r.json()
    j = client.post("/api/campaigns/join",
                    json={"invite_code": camp["invite_code"]})
    assert j.status_code == 200
    assert j.json()["name"] == "Mina Perdida"
    st = client.get(f"/api/campaigns/{camp['id']}/state")
    assert st.status_code == 200
    assert "characters" in st.json() and "combats" in st.json()


def test_combat_api_roundtrip():
    r = client.post("/api/combat", json={"name": "Emboscada"})
    cid = r.json()["id"]
    # añade un combatiente manual vía operación
    op = client.post("/api/operations", json={
        "operation_id": "add-1", "entity_id": cid, "entity_version": 1,
        "client_id": "c", "user_id": "dm", "entity_kind": "combat",
        "operation_type": "combatant.add",
        "payload": {"name": "Orco", "initiative": 12, "hp_max": 15},
    })
    assert op.status_code == 200
    got = client.get(f"/api/combat/{cid}").json()
    assert got["combat"]["combatants"][0]["name"] == "Orco"
    assert got["combat"]["combatants"][0]["hp_max"] == 15
    # vista jugador oculta HP
    pub = client.get(f"/api/combat/{cid}?reveal_hp=false").json()
    assert pub["combat"]["combatants"][0]["hp_current"] is None
    assert pub["combat"]["combatants"][0]["hp_state"] == "ileso"


def test_bad_invite_404():
    r = client.post("/api/campaigns/join", json={"invite_code": "nope"})
    assert r.status_code == 404
