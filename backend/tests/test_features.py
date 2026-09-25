"""Level-up, export/import, inventory transfer, entities, encounters,
command search."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CONTENT_DB = Path(__file__).resolve().parents[2] / "data" / "content.sqlite3"
needs_content = pytest.mark.skipif(
    not CONTENT_DB.exists(), reason="content DB no importada")


def _mkchar(name="T"):
    r = client.post("/api/characters", json={"name": name})
    return r.json()["id"]


def _op(cid, version, otype, payload, oid=None):
    import uuid
    return client.post("/api/operations", json={
        "operation_id": oid or uuid.uuid4().hex,
        "entity_id": cid, "entity_version": version,
        "client_id": "c1", "user_id": "u1",
        "operation_type": otype, "payload": payload})


@needs_content
def test_level_up_barbarian_fixed_hp():
    r = client.post("/api/characters/create-from-options", json={
        "name": "Grog", "ruleset": "dnd5e-2014",
        "class_id": "srd-2014:barbarian",
        "abilities": {"str": 15, "con": 14},
    })
    cid = r.json()["id"]
    op = _op(cid, 1, "character.level_up",
             {"class_id": "srd-2014:barbarian", "hp_mode": "fixed"})
    assert op.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["classes"][0]["level"] == 2
    assert d["hp"]["max"] == 14 + 7 + 2     # 14 + (d12/2+1) + CON2
    assert d["hit_dice"][0]["total"] == 2


def test_inventory_add_remove_undo():
    cid = _mkchar()
    r = _op(cid, 1, "character.inventory.add",
            {"name": "Cuerda", "quantity": 2})
    item_id = None
    d = client.get(f"/api/characters/{cid}").json()["data"]
    item_id = d["inventory"][0]["id"]
    r2 = _op(cid, 2, "character.inventory.remove",
             {"item_id": item_id, "quantity": 1})
    assert r2.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["inventory"][0]["quantity"] == 1


def test_atomic_transfer_between_characters():
    a = _mkchar("A")
    b = _mkchar("B")
    _op(a, 1, "character.inventory.add", {"name": "Gema", "quantity": 3})
    d = client.get(f"/api/characters/{a}").json()["data"]
    iid = d["inventory"][0]["id"]
    r = client.post("/api/inventory/transfer", json={
        "transfer_id": "tx-1", "from_character": a, "to_character": b,
        "item_id": iid, "quantity": 2})
    assert r.status_code == 200
    da = client.get(f"/api/characters/{a}").json()["data"]
    db = client.get(f"/api/characters/{b}").json()["data"]
    assert da["inventory"][0]["quantity"] == 1
    assert db["inventory"][0]["quantity"] == 2
    # idempotente: repetir no duplica
    r2 = client.post("/api/inventory/transfer", json={
        "transfer_id": "tx-1", "from_character": a, "to_character": b,
        "item_id": iid, "quantity": 2})
    assert r2.json()["duplicate"] is True
    db = client.get(f"/api/characters/{b}").json()["data"]
    assert db["inventory"][0]["quantity"] == 2


def test_export_import_roundtrip():
    cid = _mkchar("Export")
    ex = client.get(f"/api/characters/{cid}/export").json()
    assert ex["format_version"] == 1
    r = client.post("/api/characters/import",
                    json={"character": ex["character"]})
    assert r.status_code == 201
    d = client.get(f"/api/characters/{r.json()['id']}").json()["data"]
    assert d["name"] == "Export"


def test_operations_history_and_reversible_flag():
    cid = _mkchar()
    _op(cid, 1, "character.hp.damage", {"amount": 2})
    h = client.get(f"/api/operations?entity_id={cid}").json()
    assert len(h["operations"]) == 1
    assert h["operations"][0]["reversible"] == 1


def test_entities_visibility_and_reveal():
    camp = client.post("/api/campaigns", json={"name": "C"}).json()
    cid = camp["id"]
    client.post(f"/api/campaigns/{cid}/entities", json={
        "kind": "npc", "name": "Traidor secreto",
        "visibility": "dm", "data": {"notes": "es un doppelganger"}})
    client.post(f"/api/campaigns/{cid}/entities", json={
        "kind": "location", "name": "Taberna", "visibility": "public"})
    dm_view = client.get(
        f"/api/campaigns/{cid}/entities?viewer=dm").json()["entities"]
    pl_view = client.get(
        f"/api/campaigns/{cid}/entities?viewer=player").json()["entities"]
    assert len(dm_view) == 2 and len(pl_view) == 1
    # revelar
    secret = next(e for e in dm_view if e["visibility"] == "dm")
    client.post(f"/api/campaigns/{cid}/entities/{secret['id']}/reveal")
    pl_view = client.get(
        f"/api/campaigns/{cid}/entities?viewer=player").json()["entities"]
    assert len(pl_view) == 2


def test_relationships_graph():
    camp = client.post("/api/campaigns", json={"name": "G"}).json()
    cid = camp["id"]
    e1 = client.post(f"/api/campaigns/{cid}/entities",
                     json={"kind": "npc", "name": "A"}).json()["id"]
    e2 = client.post(f"/api/campaigns/{cid}/entities",
                     json={"kind": "npc", "name": "B"}).json()["id"]
    client.post(f"/api/campaigns/{cid}/relationships", json={
        "from_id": e1, "to_id": e2, "type": "hates",
        "description": "A odia a B"})
    rels = client.get(
        f"/api/campaigns/{cid}/relationships?entity_id={e1}").json()
    assert len(rels["relationships"]) == 1
    assert rels["relationships"][0]["type"] == "hates"


def test_encounter_difficulty():
    r = client.post("/api/encounters/difficulty", json={
        "party_levels": [3, 3, 3, 3],
        "monster_crs": ["1", "1", "1"]})   # 600 raw → 1200 adj (x2)
    body = r.json()
    assert body["raw_xp"] == 600
    assert body["adjusted_xp"] == 1200
    # party 4x lvl3: easy 300, med 600, hard 900, deadly 1600 → hard
    assert body["rating"] == "hard"


@needs_content
def test_command_search_spell_level():
    r = client.get("/api/content/command?q=/spell level:3 fireball")
    body = r.json()
    assert body["parsed"]["type"] == "spell"
    assert body["parsed"]["filters"] == {"level": "3"}
    names = [x["name"] for x in body["results"]]
    assert "Fireball" in names


@needs_content
def test_command_search_monster_cr_range():
    r = client.get(
        "/api/content/command?q=/monster cr:1..2 type:undead")
    body = r.json()
    assert body["parsed"]["type"] == "monster"
    for x in body["results"]:
        assert "undead" in str(x["summary"].get("type", "")).lower()


def test_roll_request_broadcast():
    camp = client.post("/api/campaigns", json={"name": "RR"}).json()
    r = client.post(f"/api/campaigns/{camp['id']}/roll-request", json={
        "character_id": "char-1", "expression": "1d20",
        "reason": "percepción", "secret": True})
    assert r.status_code == 202


def test_pending_roll_requests():
    """La petición del DM queda pendiente hasta que el personaje tira."""
    camp = client.post("/api/campaigns", json={"name": "PR"}).json()
    cid = camp["id"]
    # crear personaje y asignarlo a la campaña
    char = client.post("/api/characters", json={"name": "Kael"}).json()
    client.patch(f"/api/characters/{char['id']}",
                 json={"campaign_id": cid})
    url = f"/api/campaigns/{cid}/roll-requests/pending"
    ids = f"character_ids={char['id']}"
    assert client.get(f"{url}?{ids}").json()["pending"] == []
    client.post(f"/api/campaigns/{cid}/roll-request", json={
        "character_id": char["id"], "expression": "1d20",
        "reason": "save de SAB"})
    pend = client.get(f"{url}?{ids}").json()["pending"]
    assert len(pend) == 1 and pend[0]["reason"] == "save de SAB"
    # el jugador responde → ya no está pendiente
    client.post(f"/api/operations/character/{char['id']}/roll",
                params={"expression": "1d20", "roll_type": "save"})
    assert client.get(f"{url}?{ids}").json()["pending"] == []


def test_condition_durations_tick():
    """Condición con rondas → tick la expira y la quita."""
    cid = _mkchar()
    ver = 1
    r = _op(cid, ver, "character.condition.apply",
            {"condition": "poisoned", "rounds": 2})
    ver = r.json()["version"]
    r = _op(cid, ver, "character.tick", {"rounds": 1})
    ver = r.json()["version"]
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["conditions"] == ["poisoned"]
    assert d["condition_durations"] == {"poisoned": 1}
    _op(cid, ver, "character.tick", {"rounds": 1})
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["conditions"] == [] and d["condition_durations"] == {}


def test_death_saves_lifecycle():
    """0 PG → salvaciones (1=2 fallos, 20=1PG); curar reinicia."""
    cid = _mkchar()
    ver = 1
    r = _op(cid, ver, "character.hp.set", {"current": 0})
    assert r.status_code == 200
    ver = r.json()["version"]
    # éxito (12) y fallo (8)
    for roll in (12, 8):
        r = _op(cid, ver, "character.death_save", {"roll": roll})
        assert r.status_code == 200, r.text
        ver = r.json()["version"]
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["death_saves"] == {"success": 1, "fail": 1}
    # 1 natural = doble fallo → 3 fallos → muerte
    r = _op(cid, ver, "character.death_save", {"roll": 1})
    ver = r.json()["version"]
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["death_saves"]["fail"] == 3
    assert "muerto" in [c.lower() for c in d["conditions"]]
    # curar saca de 0 PG, limpia muerte y reinicia las salvaciones
    r = _op(cid, ver, "character.hp.heal", {"amount": 5})
    assert r.status_code == 200
    d = client.get(f"/api/characters/{cid}").json()["data"]
    assert d["hp"]["current"] == 5
    assert d["death_saves"] == {"success": 0, "fail": 0}
    assert "muerto" not in [c.lower() for c in d["conditions"]]
