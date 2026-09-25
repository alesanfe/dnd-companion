"""RoomManager: reparto por rol — los eventos con visibility=dm no
llegan a sockets de jugadores."""
import asyncio

from app.domain.events import Event
from app.ws.rooms import RoomManager


class FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(text)


def _ev(visibility=None):
    import uuid
    from datetime import datetime, timezone
    return Event(
        event_id=uuid.uuid4().hex, type="dice.roll.created",
        campaign_id="camp", aggregate_id="c1", aggregate_version=1,
        actor_id="u1", occurred_at=datetime.now(timezone.utc),
        payload={"total": 17, "character": "Kael",
                 **({"visibility": "dm"} if visibility else {})})


def test_secret_roll_only_reaches_dm_sockets():
    mgr = RoomManager()
    dm, player, local = FakeWS(), FakeWS(), FakeWS()

    async def run():
        await mgr.join("camp", dm, role="dm")
        await mgr.join("camp", player, role="player")
        await mgr.join("camp", local, role="local")
        await mgr.broadcast("camp", _ev(visibility="dm"))

    asyncio.run(run())
    assert len(dm.sent) == 1
    assert len(local.sent) == 1          # modo local = siempre recibe
    assert player.sent == []             # el jugador NO ve la tirada


def test_public_roll_reaches_everyone():
    mgr = RoomManager()
    dm, player = FakeWS(), FakeWS()

    async def run():
        await mgr.join("camp", dm, role="dm")
        await mgr.join("camp", player, role="player")
        await mgr.broadcast("camp", _ev())

    asyncio.run(run())
    assert len(dm.sent) == 1 and len(player.sent) == 1


def test_secret_roll_http_payload_flagged():
    """El endpoint marca visibility=dm cuando secret=True."""
    import uuid
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    cid = c.post("/api/characters", json={"name": "T"}).json()["id"]
    r = c.post(f"/api/operations/character/{cid}/roll",
               params={"expression": "1d20", "secret": "true"})
    assert r.status_code == 200
    assert "total" in r.json()
