"""Campaign rooms — one WS hub per campaign. Clients resync on reconnect
by requesting full state; events are small and typed (domain/events.py)."""
from __future__ import annotations

import json

from fastapi import WebSocket

from ..domain.events import Event


class RoomManager:
    def __init__(self) -> None:
        # campaign_id → {socket: rol} — 'dm'|'owner'|'player'|'local'
        self._rooms: dict[str, dict[WebSocket, str]] = {}

    async def join(self, campaign_id: str, ws: WebSocket,
                   role: str = 'local') -> None:
        await ws.accept()
        self._rooms.setdefault(campaign_id, {})[ws] = role

    def leave(self, campaign_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(campaign_id)
        if room:
            room.pop(ws, None)
            if not room:
                del self._rooms[campaign_id]

    async def broadcast(self, campaign_id: str, event: Event) -> None:
        """Reparte el evento a la sala. Si el payload marca
        visibility=dm solo llega a sockets DM/owner/local — las
        tiradas secretas no se filtran a los jugadores."""
        room = self._rooms.get(campaign_id, {})
        dm_only = (event.payload or {}).get("visibility") == "dm"
        dead = []
        for ws, role in room.items():
            if dm_only and role not in ("dm", "owner", "local"):
                continue
            try:
                await ws.send_text(event.model_dump_json())
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(campaign_id, ws)


manager = RoomManager()
