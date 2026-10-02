"""Campaign rooms — one WS hub per campaign. Clients resync on reconnect
by requesting full state; events are small and typed (domain/events.py)."""
from __future__ import annotations

import json

from fastapi import WebSocket

from ..domain.events import Event


class RoomManager:
    def __init__(self) -> None:
        # campaign_id → {socket: (rol, nombre, user_id)}
        # rol: 'dm'|'owner'|'player'|'local'|'spectator'
        self._rooms: dict[str, dict[WebSocket, tuple]] = {}

    async def join(self, campaign_id: str, ws: WebSocket,
                   role: str = 'local', name: str | None = None,
                   uid: str | None = None,
                   subprotocol: str | None = None) -> None:
        await ws.accept(subprotocol=subprotocol)
        self._rooms.setdefault(campaign_id, {})[ws] = (role, name, uid)

    def leave(self, campaign_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(campaign_id)
        if room:
            room.pop(ws, None)
            if not room:
                del self._rooms[campaign_id]

    async def broadcast(self, campaign_id: str,
                        event: Event | dict,
                        exclude: WebSocket | None = None) -> None:
        """Reparte el evento a la sala. Si el payload marca
        visibility=dm solo llega a sockets DM/owner/local — las
        tiradas secretas no se filtran a los jugadores.
        Acepta Event de dominio o dicts efímeros (chat).
        `exclude` omite un socket (p.ej. el emisor del typing)."""
        room = self._rooms.get(campaign_id, {})
        payload = getattr(event, "payload", None)
        if payload is None and isinstance(event, dict):
            payload = event.get("payload")
        payload = payload or {}
        dm_only = payload.get("visibility") == "dm"
        # for_user: entrega dirigida (petición secreta del DM) — solo el
        # socket de ese usuario + los DM; el resto de la mesa ni la ve.
        # co_dm estaba fuera: su rol real es 'co_dm', no 'dm' — un
        # subdirector autenticado no veía tiradas secretas ni eventos
        # dm-only aunque REST sí se los sirve (_DM_ROLES).
        target = payload.get("for_user")
        data = (event.model_dump_json()
                if hasattr(event, "model_dump_json")
                else json.dumps(event))
        dead = []
        for ws, info in room.items():
            if ws is exclude:
                continue
            role, uid = (info[0], info[2] if len(info) > 2 else None) \
                if isinstance(info, tuple) else (info, None)
            priv = role in ("dm", "owner", "co_dm", "local")
            if dm_only and not priv and not (uid and uid == target):
                continue
            if target and not dm_only and not (uid and uid == target) \
                    and not priv:
                continue
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(campaign_id, ws)

    async def send_to(self, campaign_id: str, uid: str,
                      data: dict) -> None:
        """Entrega dirigida exacta (señalización WebRTC) — solo el
        socket(s) de ese uid; ni broadcast ni DMs."""
        room = self._rooms.get(campaign_id, {})
        text = json.dumps(data)
        for ws, info in room.items():
            if isinstance(info, tuple) and len(info) > 2 and \
                    info[2] == uid:
                try:
                    await ws.send_text(text)
                except Exception:
                    self.leave(campaign_id, ws)

    def present(self, campaign_id: str) -> list[dict]:
        """Miembros conectados ahora mismo — lista estilo Discord:
        nombres únicos con su rol + nº de invitados sin cuenta."""
        room = self._rooms.get(campaign_id, {})
        seen: dict[str, tuple[str, str | None]] = {}
        guests = 0
        for info in room.values():
            role, name, uid = (info[0], info[1], info[2]) \
                if isinstance(info, tuple) else (info, None, None)
            if name:
                seen.setdefault(name, (role, uid))
            else:
                guests += 1
        out = [{"name": n, "role": r, "uid": u}
               for n, (r, u) in seen.items()]
        if guests:
            out.append({"name": "local", "role": "local",
                        "count": guests})
        return out


manager = RoomManager()
