"""D&D Companion backend — FastAPI entrypoint."""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    auth, campaigns, campaigns_map, characters, combat, content, dice,
    encounters, inventory, operations, packages, push, rules,
)
from .api.operations import OperationIn, apply_to_store, \
    _entity_campaign
from .db.connections import state_db
from .ws.rooms import manager

app = FastAPI(title="D&D Companion", version="0.1.0")

# Orígenes CORS por env (despliegues LAN/dominio propio); dev por
# defecto solo el servidor de Vite.
_CORS_ORIGINS = [o.strip() for o in
                 os.environ.get(
                     "DND_CORS_ORIGINS",
                     "http://localhost:5173").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_headers(request, call_next):
    """Higiene básica si la app se expone fuera de localhost:
    sin esto un XSS en cualquier origen servido podía inyectar
    contenido sniffeado o embeber la app en un iframe ajeno."""
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp

app.include_router(content.router)
app.include_router(characters.router)
app.include_router(campaigns.router)
app.include_router(campaigns_map.router)
app.include_router(operations.router)
app.include_router(combat.router)
app.include_router(encounters.router)
app.include_router(inventory.router)
app.include_router(auth.router)
app.include_router(packages.router)
app.include_router(rules.router)
app.include_router(dice.router)
app.include_router(push.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/campaign/{campaign_id}")
async def campaign_ws(websocket: WebSocket, campaign_id: str,
                      user_id: str | None = None,
                      token: str | None = None):
    """Sala de campaña. Protocolo:
      → {"type": "operation", "operation": {...OperationIn}}
      → {"type": "ping"}
      ← {"type": "event", "event": {...}}  broadcast a la sala
      ← {"type": "ack", "operation_id", "version"} | {"type": "error", ...}

    Con `?token=` el rol se resuelve por el usuario autenticado — el
    parámetro user_id suelto solo vale en modo local (sin cuenta),
    porque es spoofable y daría rol 'dm' a cualquiera."""
    role, resolved, name, authed = _ws_identity(
        campaign_id, token, user_id)
    await manager.join(campaign_id, websocket, role=role, name=name,
                       uid=resolved)
    # presencia en vivo — estilo Discord: la sala se entera de
    # altas y bajas sin polling
    await _broadcast_presence(campaign_id)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps({"type": "error", "detail": "invalid json"}))
                continue
            await _dispatch_ws(websocket, campaign_id, msg, resolved,
                               name, role, authed)
    except WebSocketDisconnect:
        manager.leave(campaign_id, websocket)
        await _broadcast_presence(campaign_id)


def _ws_identity(campaign_id: str, token: str | None,
                 user_id: str | None
                 ) -> tuple[str, str | None, str | None, bool]:
    """Resuelve (rol, user_id, nombre visible, autenticado) de la
    conexión.

    Con `?token=` el rol se resuelve por el usuario autenticado — el
    parámetro user_id suelto solo vale en modo local (sin cuenta),
    porque es spoofable y daría rol 'dm' a cualquiera. `authed`
    distingue la identidad verificada por token de la spoofable —
    los guards de propiedad solo pueden confiar en la primera."""
    resolved = name = None
    authed = False
    if token:
        from .api.auth import user_from_token
        info = user_from_token(token)
        resolved = (info or {}).get("user_id")
        name = (info or {}).get("username")
        authed = resolved is not None
    elif user_id:
        # un ?user_id suelto solo acredita identidad en campañas SIN
        # dueño (modo local puro). Con owner es spoofable: antes
        # heredaba el rol real del uid suplantado — incluido owner/DM
        row = state_db().execute(
            "SELECT owner_id FROM campaigns WHERE id = ?",
            (campaign_id,)).fetchone()
        if not (row and row["owner_id"]):
            resolved = name = user_id   # el id local ya es el nombre
    role = "local"
    if resolved:
        from .api.auth import member_role
        # member_role también reconoce al owner aunque falte la fila
        role = member_role(campaign_id, resolved) or \
            ("player" if token else "local")
    else:
        # sin identidad resoluble: 'local' (rol privilegiado, recibe
        # eventos visibility=dm) solo en campañas sin dueño. Con owner,
        # un socket anónimo es espectador — no ve tiradas secretas
        row = state_db().execute(
            "SELECT owner_id FROM campaigns WHERE id = ?",
            (campaign_id,)).fetchone()
        if row and row["owner_id"]:
            role = "spectator"
    return role, resolved, name, authed


async def _broadcast_presence(campaign_id: str) -> None:
    await manager.broadcast(campaign_id, {
        "type": "campaign.presence",
        "payload": {"members": manager.present(campaign_id)}})


async def _dispatch_ws(websocket: WebSocket, campaign_id: str,
                       msg: dict, resolved: str | None = None,
                       name: str | None = None,
                       role: str = "local", authed: bool = False) -> None:
    """Un mensaje del protocolo de sala: ping / chat / operation."""
    if msg.get("type") == "ping":
        await websocket.send_text(json.dumps({"type": "pong"}))
        return
    # chat efímero de mesa — no persiste, solo se reparte. El remitente
    # es la identidad autenticada del socket — el `from` del cliente es
    # spoofable (un jugador podría firmar mensajes como "DM")
    if msg.get("type") == "chat":
        # un espectador anónimo mira pero no habla — antes podía
        # intervenir en el chat de una mesa ajena con token inválido
        if role == "spectator":
            await websocket.send_text(json.dumps(
                {"type": "error", "detail": "solo lectura"}))
            return
        text = str(msg.get("text", "")).strip()[:500]
        if text:
            await manager.broadcast(campaign_id, {
                "type": "chat",
                "from": name or str(msg.get("from", "?"))[:80],
                "text": text})
        return
    # "X está escribiendo" — efímero: se reparte a los DEMÁS sin
    # persistir ni encolar (el que escribe ya sabe que escribe)
    if msg.get("type") == "typing":
        if role == "spectator":
            return
        await manager.broadcast(campaign_id, {
            "type": "typing",
            "from": name or str(msg.get("from", "?"))[:80]},
            exclude=websocket)
        return
    # señalización WebRTC (voz de mesa): {to: uid, data: sdp/ice} —
    # relay dirigido; el servidor no toca el SDP
    if msg.get("type") == "rtc.signal":
        # el espectador es solo lectura — tampoco negocia audio
        if role == "spectator":
            return
        target = str(msg.get("to") or "")[:80]
        if target and resolved:
            await manager.send_to(campaign_id, target, {
                "type": "rtc.signal", "from": resolved,
                "from_name": name, "data": msg.get("data")})
        return
    if msg.get("type") != "operation":
        await websocket.send_text(
            json.dumps({"type": "error", "detail": "unknown message"}))
        return
    if role == "spectator":
        # mira pero no toca — ni operaciones sobre entidades de la sala
        # ni sobre fichas sin campaña (entity_camp None saltaba el guard)
        await websocket.send_text(json.dumps(
            {"type": "error", "detail": "solo lectura"}))
        return
    try:
        op = OperationIn(**msg["operation"])
        # la op debe tocar una entidad de ESTA sala — sin el check un
        # socket de la sala A podía mutar fichas de la campaña B; y en
        # campañas con dueño se exige membresía igual que en REST
        conn = state_db()
        entity_camp = _entity_campaign(conn, op)
        if entity_camp and entity_camp != campaign_id:
            raise HTTPException(400, "la entidad es de otra campaña")
        if entity_camp:
            from .api.campaigns import _require_role
            _require_role(conn, entity_camp,
                          {"user_id": resolved} if resolved else None)
            from .api.operations import _char_ownership
            from .api.auth import member_role
            from .api.campaigns import _DM_ROLES, _has_owner
            if op.entity_kind == "character":
                _char_ownership(conn, op.entity_id,
                                {"user_id": resolved}
                                if resolved else None)
            elif op.entity_kind == "combat" and \
                    _has_owner(conn, entity_camp):
                # mismo modelo que REST: el tracker es del DM — única
                # excepción, la salvación de muerte del propio PJ
                if member_role(entity_camp, resolved) not in _DM_ROLES:
                    from .api.operations import _player_combat_op
                    _player_combat_op(conn, op,
                                      {"user_id": resolved}
                                      if resolved else None)
        elif not entity_camp:
            # ficha sin campaña (None o "") con player_id: solo la
            # muta su dueño (mismo guard que REST — y solo vale la
            # identidad por token: un ?user_id suelto es spoofable)
            from .api.operations import (
                _campaignless_combat_guard, _personal_ownership)
            as_user = ({"user_id": resolved} if authed else None)
            _personal_ownership(conn, op, as_user)
            _campaignless_combat_guard(conn, op, as_user)
        if resolved:
            # el actor es la identidad de la conexión — el user_id del
            # payload es spoofable y envenenaría la auditoría
            op.user_id = resolved
        result = apply_to_store(op)
    except HTTPException as exc:
        detail = exc.detail
    except (KeyError, ValueError) as exc:
        detail = str(exc)
    except Exception as exc:      # noqa: BLE001
        # un handler defectuoso no debe tumbar el socket
        detail = f"internal error: {exc!r}"
    else:
        await websocket.send_text(json.dumps(
            {"type": "ack", "operation_id": result["operation_id"],
             "version": result["version"],
             "duplicate": result["duplicate"],
             # paridad con REST: el cliente necesita la inversa para
             # poder deshacer; los eventos ya llegan por broadcast
             "inverse": result.get("inverse")}))
        for event in result.pop("_event_objs", []):
            await manager.broadcast(campaign_id, event)
        return
    await websocket.send_text(json.dumps(
        {"type": "error", "detail": detail}))
