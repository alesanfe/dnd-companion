"""Operations endpoint: idempotency, optimistic locking, undo."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["DND_STATE_DB"] = str(Path(tempfile.mkdtemp()) / "state.sqlite3")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _mkchar():
    r = client.post("/api/characters", json={"name": "Aria"})
    return r.json()["id"]


def _op(char_id, version, otype, payload, oid="op-1"):
    return client.post("/api/operations", json={
        "operation_id": oid, "entity_id": char_id, "entity_version": version,
        "client_id": "c1", "user_id": "u1",
        "operation_type": otype, "payload": payload,
    })


def test_operation_applies_and_updates_version():
    cid = _mkchar()
    r = _op(cid, 1, "character.hp.damage", {"amount": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 2
    char = client.get(f"/api/characters/{cid}").json()
    assert char["data"]["hp"]["current"] == 5  # 8 - 3


def test_same_operation_id_is_idempotent():
    cid = _mkchar()
    _op(cid, 1, "character.hp.damage", {"amount": 3}, oid="dup")
    r = _op(cid, 1, "character.hp.damage", {"amount": 3}, oid="dup")
    assert r.json()["duplicate"] is True
    char = client.get(f"/api/characters/{cid}").json()
    assert char["data"]["hp"]["current"] == 5  # no se aplicó dos veces


def test_stale_version_conflicts():
    cid = _mkchar()
    _op(cid, 1, "character.hp.damage", {"amount": 1}, oid="a")
    r = _op(cid, 1, "character.hp.damage", {"amount": 1}, oid="b")
    assert r.status_code == 409


def test_undo_restores_hp():
    cid = _mkchar()
    r = _op(cid, 1, "character.hp.damage", {"amount": 4}, oid="dmg")
    u = client.post(f"/api/operations/undo/{r.json()['operation_id']}")
    assert u.status_code == 200
    char = client.get(f"/api/characters/{cid}").json()
    assert char["data"]["hp"]["current"] == 8


def test_derived_stat_breakdown():
    cid = _mkchar()
    r = client.get(f"/api/characters/{cid}/derived/armor_class?base=10")
    assert r.status_code == 200
    assert r.json()["total"] == 10
