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
                   role: str = 'local', name: str | None = None) -> None:
        await ws.accept()
        self._rooms.setdefault(campaign_id, {})[ws] = (role, name)

    def leave(self, campaign_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(campaign_id)
        if room:
            room.pop(ws, None)
            if not room:
                del self._rooms[campaign_id]

    async def broadcast(self, campaign_id: str,
                        event: Event | dict) -> None:
        """Reparte el evento a la sala. Si el payload marca
        visibility=dm solo llega a sockets DM/owner/local — las
        tiradas secretas no se filtran a los jugadores.
        Acepta Event de dominio o dicts efímeros (chat)."""
        room = self._rooms.get(campaign_id, {})
        payload = getattr(event, "payload", None)
        if payload is None and isinstance(event, dict):
            payload = event.get("payload")
        dm_only = (payload or {}).get("visibility") == "dm"
        data = (event.model_dump_json()
                if hasattr(event, "model_dump_json")
                else json.dumps(event))
        dead = []
        for ws, info in room.items():
            role = info[0] if isinstance(info, tuple) else info
            if dm_only and role not in ("dm", "owner", "local"):
                continue
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(campaign_id, ws)

    def present(self, campaign_id: str) -> list[dict]:
        """Miembros conectados ahora mismo — lista estilo Discord:
        nombres únicos con su rol + nº de invitados sin cuenta."""
        room = self._rooms.get(campaign_id, {})
        seen: dict[str, str] = {}
        guests = 0
        for info in room.values():
            role, name = info if isinstance(info, tuple) else (info, None)
            if name:
                seen.setdefault(name, role)
            else:
                guests += 1
        out = [{"name": n, "role": r} for n, r in seen.items()]
        if guests:
            out.append({"name": "local", "role": "local",
                        "count": guests})
        return out


manager = RoomManager()
