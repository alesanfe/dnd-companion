"""Acciones de grupo: roll-request del DM, reparto de tesoro y descanso de party — split de campaigns.py"""
from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ._campaign_access import (
    _DM_ROLES, _ev_for_uid, _ev_is_dm, _ev_visible, _has_owner,
    _notify_entity, _notify_reveal, _require_role,
)
from .auth import member_role, optional_user
from ..db.connections import content_db, state_db
from ..ws.rooms import manager

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class RollRequestIn(BaseModel):
    character_id: str
    expression: str = "1d20"
    reason: str = ""                   # 'tirada de percepción', 'save de SAB'
    secret: bool = False               # tirada oculta al resto


@router.post("/{campaign_id}/roll-request", status_code=202)
async def request_roll(campaign_id: str, body: RollRequestIn,
                       user: dict | None = Depends(optional_user)):
    """El DM pide una tirada; llega como evento a la sala WS."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    from ..domain.events import Event, EventType
    payload = {"expression": body.expression, "reason": body.reason,
               "secret": body.secret}
    if body.secret and _has_owner(conn, campaign_id):
        # petición secreta: solo el dueño de la ficha (y los DM) la ven
        # — antes se emitía a toda la sala y delataba la tirada oculta
        prow = conn.execute(
            "SELECT player_id FROM characters WHERE id = ?",
            (body.character_id,)).fetchone()
        payload["for_user"] = prow["player_id"] if prow else None
        payload["visibility"] = "dm"
    event = Event(
        event_id=uuid.uuid4().hex,
        type=EventType.ROLL_REQUESTED,
        campaign_id=campaign_id,
        aggregate_id=body.character_id,
        aggregate_version=0,
        actor_id="dm",
        occurred_at=datetime.now(timezone.utc),
        payload=payload,
    )
    conn.execute(
        """INSERT INTO events
           (event_id, campaign_id, aggregate_id, aggregate_version,
            actor_id, occurred_at, type, payload)
           VALUES (?,?,?,?,?,?,?,?)""",
        (event.event_id, campaign_id, event.aggregate_id,
         event.aggregate_version, event.actor_id,
         event.occurred_at.isoformat(), event.type.value,
         json.dumps(event.payload)))
    conn.commit()
    await manager.broadcast(campaign_id, event)
    # push PWA al dueño de la ficha — le llega aunque tenga la app
    # cerrada (móvil en bolsillo antes de la sesión)
    prow = conn.execute(
        "SELECT player_id FROM characters WHERE id = ?",
        (body.character_id,)).fetchone()
    if prow and prow["player_id"]:
        from .push import send_push
        # webpush es I/O bloqueante — sacarlo del event loop o cada
        # push congela la sala entera unos cientos de ms
        await asyncio.to_thread(
            send_push, prow["player_id"], "Tirada solicitada",
            body.reason or body.expression, f"/campaign/{campaign_id}")
    return {"event_id": event.event_id}


_COINS = ("pp", "gp", "ep", "sp", "cp")


class LootSplit(BaseModel):
    coin: str = "gp"
    amount: int = 0


@router.post("/{campaign_id}/split-loot")
async def split_loot(campaign_id: str, body: LootSplit,
                     user: dict | None = Depends(optional_user)):
    """Reparte el tesoro entre las fichas de la campaña — cada parte es
    una op `character.currency.earn` real: auditable, deshacible y con
    broadcast a la sala (el que esté conectado ve su bolsa crecer)."""
    from .operations import OperationIn, apply_to_store
    conn = state_db()
    if _has_owner(conn, campaign_id):
        _require_role(conn, campaign_id, user, _DM_ROLES)
    if body.coin not in _COINS or body.amount <= 0:
        raise HTTPException(400, "tesoro inválido")
    rows = conn.execute(
        "SELECT id, version FROM characters WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    if not rows:
        return {"share": 0, "awarded": 0}
    share, rem = divmod(body.amount, len(rows))
    uid = (user or {}).get("user_id") or "dm"
    awarded = 0
    for i, r in enumerate(rows):
        part = share + (1 if i < rem else 0)
        if part <= 0:
            continue
        result = apply_to_store(OperationIn(
            operation_id=uuid.uuid4().hex, entity_id=r["id"],
            entity_version=r["version"], client_id="api:split-loot",
            user_id=uid, operation_type="character.currency.earn",
            entity_kind="character", payload={body.coin: part}))
        for event in result.pop("_event_objs", []):
            await manager.broadcast(campaign_id, event)
        awarded += 1
    return {"share": share, "awarded": awarded}


@router.post("/{campaign_id}/rest")
async def party_rest(campaign_id: str, kind: str = "long",
                     user: dict | None = Depends(optional_user)):
    """Descanso del grupo: aplica `character.rest.<kind>` a cada ficha
    de la campaña como op real (auditable, deshacible, broadcast) —
    el DM declara el descanso y todas las fichas se recuperan a la vez."""
    from .operations import OperationIn, apply_to_store
    if kind not in ("short", "long"):
        raise HTTPException(400, "kind debe ser short|long")
    conn = state_db()
    if _has_owner(conn, campaign_id):
        _require_role(conn, campaign_id, user, _DM_ROLES)
    rows = conn.execute(
        "SELECT id, version FROM characters WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    uid = (user or {}).get("user_id") or "dm"
    for r in rows:
        result = apply_to_store(OperationIn(
            operation_id=uuid.uuid4().hex, entity_id=r["id"],
            entity_version=r["version"], client_id="api:party-rest",
            user_id=uid,
            operation_type=f"character.rest.{kind}",
            entity_kind="character", payload={}))
        for event in result.pop("_event_objs", []):
            await manager.broadcast(campaign_id, event)
    return {"rested": len(rows), "kind": kind}


@router.get("/{campaign_id}/roll-requests/pending")
def pending_roll_requests(campaign_id: str, character_ids: str = "",
                          user: dict | None = Depends(optional_user)):
    """Peticiones de tirada aún sin responder.

    Una petición dice.roll.requested cuenta pendiente si el último
    evento dice.* de ese personaje es la petición (la respuesta del
    jugador emite dice.roll.created sobre el mismo aggregate_id).
    """
    ids = [x for x in character_ids.split(",") if x]
    if not ids:
        return {"pending": []}
    conn = state_db()
    _require_role(conn, campaign_id, user)
    # un jugador solo consulta SUS fichas: una petición secreta a otro
    # PJ filtraría el motivo del DM ("percepción: te mienten")
    uid = (user or {}).get("user_id")
    if _has_owner(conn, campaign_id) \
            and member_role(campaign_id, uid) not in _DM_ROLES:
        allowed = {r["id"] for r in conn.execute(
            f"""SELECT id FROM characters
                WHERE id IN ({",".join("?" * len(ids))})
                  AND (player_id = ? OR player_id IS NULL
                       OR player_id = '')""",
            (*ids, uid)).fetchall()}
        ids = [i for i in ids if i in allowed]
        if not ids:
            return {"pending": []}
    rows = conn.execute(
        f"""SELECT aggregate_id, type, occurred_at, payload
            FROM events
            WHERE campaign_id = ?
              AND aggregate_id IN ({",".join("?" * len(ids))})
              AND type IN ('dice.roll.requested', 'dice.roll.created')
            ORDER BY occurred_at""",
        (campaign_id, *ids)).fetchall()
    latest: dict[str, dict | None] = {}
    for r in rows:
        latest[r["aggregate_id"]] = (
            {**json.loads(r["payload"]), "at": r["occurred_at"]}
            if r["type"] == "dice.roll.requested" else None)
    return {"pending": [
        {"character_id": k, **v} for k, v in latest.items() if v]}
