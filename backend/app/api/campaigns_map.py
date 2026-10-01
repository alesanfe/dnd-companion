"""Mapa VTT: ping efímero, 'mostrar al grupo', token-move y PATCH de
entidad. Split de api/campaigns.py (AU-22) — mismo prefijo de router,
guards en _campaign_access."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ._campaign_access import (
    _DM_ROLES, _has_owner, _notify_entity, _require_role,
)
from .auth import member_role, optional_user
from ..db.connections import state_db
from ..ws.rooms import manager

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class PingIn(BaseModel):
    x: int
    y: int
    entity_id: str | None = None        # mapa donde se pulsó


@router.post("/{campaign_id}/ping")
async def map_ping(campaign_id: str, body: PingIn,
                   user: dict | None = Depends(optional_user)):
    """Ping efímero del mapa (botón derecho): señalar un punto a toda
    la mesa. Solo WS — no persiste en el feed de eventos."""
    from ..domain.events import Event, EventType
    conn = state_db()
    _require_role(conn, campaign_id, user)
    ev = Event(event_id=uuid.uuid4().hex, type=EventType.MAP_PING,
               campaign_id=campaign_id,
               aggregate_id=body.entity_id or campaign_id,
               aggregate_version=0,
               actor_id=(user or {}).get("user_id") or "?",
               occurred_at=datetime.now(timezone.utc),
               payload={"x": int(body.x), "y": int(body.y),
                        "entity_id": body.entity_id,
                        "by": (user or {}).get("username") or "?",
                        # el destinatario puede verificar que el ping
                        # es del mapa que está viendo
                        })
    await manager.broadcast(campaign_id, ev)
    return {"ok": True}


class PresentIn(BaseModel):
    entity_id: str | None = None   # None = cerrar la presentación


@router.post("/{campaign_id}/present")
async def present_entity(campaign_id: str, body: PresentIn,
                         user: dict | None = Depends(optional_user)):
    """'Mostrar al grupo' — el DM proyecta una entidad (nota, imagen de
    mapa, PNJ) en la pantalla de todos los jugadores (modal). La entidad
    debe ser visible para los jugadores: nada de filtrar secretos."""
    from ..domain.events import Event, EventType
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    payload: dict = {"entity_id": None}
    if body.entity_id:
        row = conn.execute(
            """SELECT id, kind, name, visibility, data
               FROM campaign_entities
               WHERE id = ? AND campaign_id = ?""",
            (body.entity_id, campaign_id)).fetchone()
        if row is None:
            raise HTTPException(404, "entity not found")
        # lo oculto al grupo no se puede proyectar — evita el leak de
        # proyectar una nota privada 'por error'
        if row["visibility"] != "public":
            raise HTTPException(
                400, "solo se proyectan entidades públicas")
        payload = {"entity_id": row["id"], "kind": row["kind"],
                   "name": row["name"], "data": json.loads(row["data"])}
    ev = Event(event_id=uuid.uuid4().hex, type=EventType.PRESENT,
               campaign_id=campaign_id,
               aggregate_id=body.entity_id or campaign_id,
               aggregate_version=0,
               actor_id=(user or {}).get("user_id") or "?",
               occurred_at=datetime.now(timezone.utc),
               payload=payload)
    await manager.broadcast(campaign_id, ev)
    return {"ok": True}


class TokenMove(BaseModel):
    token_id: str
    x: int
    y: int


@router.post("/{campaign_id}/entities/{entity_id}/token-move")
async def token_move(campaign_id: str, entity_id: str,
                     body: TokenMove,
                     user: dict | None = Depends(optional_user)):
    """Mueve un token del mapa. El DM mueve cualquiera; un jugador
    solo el suyo — el token vinculado a su ficha (`player_id` del
    token o del personaje referenciado por `ref_id`)."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    row = conn.execute(
        "SELECT * FROM campaign_entities WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "entity not found")
    data = json.loads(row["data"])
    tk = next((t for t in (data.get("tokens") or [])
               if t.get("id") == body.token_id), None)
    if tk is None:
        raise HTTPException(404, "token not found")
    uid = (user or {}).get("user_id")
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, uid) in _DM_ROLES

    def _player_check(tk_cur: dict, data_cur: dict) -> None:
        """Ownership + muros sobre UNA copia del mapa — se re-ejecuta
        sobre la copia fresca si el UPDATE pierde la carrera (el DM
        pudo desvincular el token o murar el borde entretanto)."""
        # solo el token cuya ficha pertenece al jugador — o un
        # combatiente que el DM le delegó (combatant.delegate)
        owner_uid = tk_cur.get("player_id")
        if owner_uid is None and tk_cur.get("ref_id"):
            prow = conn.execute(
                "SELECT player_id FROM characters WHERE id = ?",
                (tk_cur["ref_id"],)).fetchone()
            owner_uid = prow["player_id"] if prow else None
        if owner_uid is None and tk_cur.get("combatant_id") and uid:
            for crow in conn.execute(
                    "SELECT data FROM combats WHERE campaign_id = ?",
                    (campaign_id,)).fetchall():
                cd = json.loads(crow["data"])
                if cd.get("status") != "active":
                    continue
                for cb in cd.get("combatants", []):
                    if cb.get("id") == tk_cur["combatant_id"] \
                            and cb.get("delegated_to") == uid:
                        owner_uid = uid
        if uid is None or owner_uid != uid:
            raise HTTPException(403, "ese token no es tuyo")
        # muros: una casilla adyacente ortogonal no se cruza si el
        # borde está murado (saltos largos/diagonales = rodear, libre)
        walls = set(data_cur.get("walls") or [])
        dx, dy = int(body.x) - tk_cur["x"], int(body.y) - tk_cur["y"]
        if abs(dx) + abs(dy) == 1:
            edge = (f"{tk_cur['x']},{tk_cur['y']},S" if dy == 1 else
                    f"{tk_cur['x']},{tk_cur['y'] - 1},S" if dy == -1
                    else f"{tk_cur['x']},{tk_cur['y']},E" if dx == 1
                    else f"{tk_cur['x'] - 1},{tk_cur['y']},E")
            if edge in walls:
                raise HTTPException(400, "hay un muro en medio")

    if not is_dm:
        _player_check(tk, data)
    cols = int(data.get("cols") or 16)
    rows = int(data.get("rows") or 10)
    tk["x"] = max(0, min(cols - 1, int(body.x)))
    tk["y"] = max(0, min(rows - 1, int(body.y)))
    # bump de version/updated_at como patch_entity: sin él un resync
    # no notaba la posición nueva y un PATCH concurrente del DM (fog,
    # muros) podía pisar el movimiento con su copia de data
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "UPDATE campaign_entities SET data = ?, version = version+1, "
        "updated_at = ? WHERE id = ? AND version = ?",
        (json.dumps(data), now, entity_id, row["version"]))
    if cur.rowcount == 0:
        # otro escritor ganó entre el SELECT y el UPDATE: el movimiento
        # es un DELTA sobre un token — reaplicarlo sobre la copia
        # fresca no pisa los cambios del otro (fog, muros, marcas…)
        fresh = conn.execute(
            "SELECT data, version FROM campaign_entities WHERE id = ?",
            (entity_id,)).fetchone()
        data = json.loads(fresh["data"])
        tk2 = next((t for t in (data.get("tokens") or [])
                    if t.get("id") == body.token_id), None)
        if tk2 is None:
            conn.rollback()
            raise HTTPException(404, "token not found")
        if not is_dm:
            try:
                _player_check(tk2, data)   # revalidar sobre lo fresco
            except HTTPException:
                conn.rollback()
                raise
        tk2["x"], tk2["y"] = tk["x"], tk["y"]
        conn.execute(
            "UPDATE campaign_entities SET data = ?, version = version+1, "
            "updated_at = ? WHERE id = ? AND version = ?",
            (json.dumps(data), now, entity_id, fresh["version"]))
    conn.commit()
    await _notify_entity(campaign_id, entity_id, ["data"],
                         row["visibility"], "map", row["name"])
    return {"x": tk["x"], "y": tk["y"]}


class EntityPatch(BaseModel):
    name: str | None = None
    data: dict | None = None
    visibility: str | None = None
    known_to: list[str] | None = None
    reveal_condition: str | None = None
    expected_version: int | None = None   # optimistic lock → 409


@router.patch("/{campaign_id}/entities/{entity_id}")
async def patch_entity(campaign_id: str, entity_id: str,
                       body: EntityPatch,
                       user: dict | None = Depends(optional_user)):
    """Actualiza campos de una entidad (orden de escena, estado, notas…)."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    row = conn.execute(
        "SELECT * FROM campaign_entities WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "entity not found")
    if (body.visibility is not None or body.known_to is not None) \
            and _has_owner(conn, campaign_id) \
            and member_role(campaign_id, (user or {}).get("user_id")) \
            not in _DM_ROLES:
        # la visibilidad es del DM — un jugador podría revelar
        # entidades ocultas (dm→public) u ocultarlas (public→dm)
        raise HTTPException(
            403, "solo el DM puede cambiar la visibilidad")
    sets, params = [], []
    if body.name is not None:
        sets.append("name = ?")
        params.append(body.name)
    if body.data is not None:
        merged = {**json.loads(row["data"]), **body.data}
        sets.append("data = ?")
        params.append(json.dumps(merged))
    if body.visibility is not None:
        sets.append("visibility = ?")
        params.append(body.visibility)
    if body.known_to is not None:
        sets.append("known_to = ?")
        params.append(json.dumps(body.known_to))
    if body.reveal_condition is not None:
        sets.append("reveal_condition = ?")
        params.append(body.reveal_condition)
    if not sets:
        return {"id": entity_id, "changed": []}
    sets += ["updated_at = ?", "version = version + 1"]
    params.append(datetime.now(timezone.utc).isoformat())
    where = "id = ?"
    params.append(entity_id)
    if body.expected_version is not None:
        # optimistic lock: el cliente escribe sobre la versión que leyó —
        # un 409 obliga a recargar en vez de pisar el cambio de otro
        # (p. ej. un token-move del jugador mientras el DM pinta niebla)
        where += " AND version = ?"
        params.append(body.expected_version)
    cur = conn.execute(
        f"UPDATE campaign_entities SET {', '.join(sets)} WHERE {where}",
        params)
    if cur.rowcount == 0:
        # sin rollback el UPDATE fallido mantiene el candado de
        # escritura WAL abierto y el siguiente writer traga un
        # "database is locked"
        conn.rollback()
        raise HTTPException(409, "entity version conflict")
    conn.commit()
    changed = [s.split(" = ")[0] for s in sets[:-2]]
    await _notify_entity(campaign_id, entity_id, changed,
                         body.visibility or row["visibility"],
                         row["kind"], row["name"])
    return {"id": entity_id, "changed": changed}
