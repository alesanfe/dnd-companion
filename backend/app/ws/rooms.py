"""Campaign rooms — one WS hub per campaign. Clients resync on reconnect
by requesting full state; events are small and typed (domain/events.py)."""
from __future__ import annotations

import json

from fastapi import WebSocket

from ..domain.events import Event


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}

    async def join(self, campaign_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._rooms.setdefault(campaign_id, set()).add(ws)

    def leave(self, campaign_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(campaign_id)
        if room:
            room.discard(ws)
            if not room:
                del self._rooms[campaign_id]

    async def broadcast(self, campaign_id: str, event: Event) -> None:
        room = self._rooms.get(campaign_id, set())
        dead = []
        for ws in room:
            try:
                await ws.send_text(event.model_dump_json())
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(campaign_id, ws)


manager = RoomManager()
