"""Acceso y visibilidad de campaña — helpers compartidos por
api/campaigns.py, api/campaigns_map.py, api/operations.py y el
dispatcher WS (main.py). Un solo lugar para el modelo 'campaña sin
owner = local abierta / con owner = membresía obligatoria'.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from .auth import member_role
from ..ws.rooms import manager

_DM_ROLES = ("owner", "co_dm")


def _has_owner(conn, campaign_id: str) -> bool:
    row = conn.execute(
        "SELECT owner_id FROM campaigns WHERE id = ?",
        (campaign_id,)).fetchone()
    return bool(row and row["owner_id"])


def _require_role(conn, campaign_id: str, user: dict | None,
                  roles: tuple = _DM_ROLES + ("player", "guest")) -> None:
    """Si la campaña tiene dueño, exige membresía con el rol pedido;
    campañas locales (owner_id NULL, sin cuentas) quedan abiertas."""
    row = conn.execute(
        "SELECT owner_id FROM campaigns WHERE id = ?",
        (campaign_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "campaign not found")
    if row["owner_id"] is None:
        return                     # modo local: sin autenticación
    role = member_role(campaign_id, (user or {}).get("user_id"))
    if role not in roles:
        raise HTTPException(403, "sin permiso en esta campaña")


def _ev_is_dm(row) -> bool:
    """Evento marcado visibility=dm (tirada secreta del DM)."""
    try:
        return (json.loads(row["payload"]) or {}).get("visibility") \
            == "dm"
    except Exception:
        return False


def _ev_for_uid(row, uid: str | None) -> bool:
    """El evento es dm-only pero está dirigido a ESTE usuario — su
    destinatario (p.ej. el que tiró en secreto) sí lo lee en el feed."""
    if not uid:
        return False
    try:
        return (json.loads(row["payload"]) or {}).get("for_user") == uid
    except Exception:
        return False


def _ev_visible(row, uid: str | None, is_dm: bool) -> bool:
    return is_dm or not _ev_is_dm(row) or _ev_for_uid(row, uid)


async def _notify_entity(campaign_id: str, entity_id: str,
                         changed: list[str], visibility: str,
                         kind: str = "", name: str = "") -> None:
    """Broadcast ligero para refresco de clientes (pestaña Mapa del
    jugador, tablero del DM). visibility='dm' → solo sockets DM,
    así una entidad oculta no se delata a los jugadores."""
    from ..domain.events import Event, EventType
    ev = Event(event_id=uuid.uuid4().hex,
               type=EventType.ENTITY_UPDATED,
               campaign_id=campaign_id, aggregate_id=entity_id,
               aggregate_version=0, actor_id="dm",
               occurred_at=datetime.now(timezone.utc),
               payload={"kind": kind, "name": name,
                        "changed": changed, "visibility": visibility})
    await manager.broadcast(campaign_id, ev)
