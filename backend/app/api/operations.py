"""POST /api/operations — única puerta de entrada a cambios de estado.

- Idempotente: operation_id repetido devuelve el resultado guardado.
- Optimistic locking: entity_version debe coincidir o es 'conflict'.
- Auditable + reversible: guarda la operación inversa.
- Broadcast: emite events pequeños a la sala WS de la campaña.

Dispatch por entity_kind: 'character' (default) o 'combat'.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import content_db, state_db
from ..domain.character import Character
from ..domain.combat import Combat
from ..domain.events import Event, EventType, OperationStatus
from ..engine.combat_ops import apply_combat_operation
from ..engine.ops import apply_operation
from ..ws.rooms import manager

router = APIRouter(prefix="/api/operations", tags=["operations"])


class OperationIn(BaseModel):
    operation_id: str
    entity_id: str          # character id o combat id
    entity_version: int
    client_id: str
    user_id: str
    operation_type: str
    entity_kind: str = "character"   # character|combat
    payload: dict = {}


class OpContext:
    """Acceso a la content DB desde handlers (stat blocks, etc.)."""
    def content_db(self):
        return content_db()


_MODELS = {"character": Character, "combat": Combat}
_TABLES = {"character": "characters", "combat": "combats"}


def apply_to_store(op: OperationIn) -> dict:
    """Núcleo compartido por REST y WS: aplica la operación, persiste
    estado + operación + eventos, devuelve resultado para broadcast."""
    conn = state_db()

    seen = conn.execute(
        "SELECT entity_version, status FROM operations WHERE operation_id = ?",
        (op.operation_id,)).fetchone()
    if seen:
        return {"operation_id": op.operation_id, "duplicate": True,
                "version": seen["entity_version"], "status": seen["status"]}

    table = _TABLES.get(op.entity_kind)
    model = _MODELS.get(op.entity_kind)
    if table is None:
        raise HTTPException(400, f"unknown entity_kind: {op.entity_kind}")

    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?", (op.entity_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"{op.entity_kind} not found")

    if row["version"] != op.entity_version:
        _store_op(conn, op, row["version"], OperationStatus.CONFLICT, None)
        conn.commit()
        raise HTTPException(409, {
            "error": "version conflict",
            "expected": row["version"], "got": op.entity_version})

    entity = model(**json.loads(row["data"]))
    try:
        if op.entity_kind == "combat":
            inverse, events = apply_combat_operation(
                entity, op.operation_type, op.payload, OpContext())
        else:
            inverse, events = apply_operation(
                entity, op.operation_type, op.payload)
    except (KeyError, ValueError, IndexError) as exc:
        _store_op(conn, op, row["version"], OperationStatus.REJECTED, None)
        conn.commit()
        raise HTTPException(400, str(exc)) from exc

    new_version = row["version"] + 1
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        f"UPDATE {table} SET data = ?, version = ?, updated_at = ? WHERE id = ?",
        (json.dumps(entity.model_dump()), new_version, now, op.entity_id))
    _store_op(conn, op, new_version, OperationStatus.SYNCED, inverse)

    campaign_id = row["campaign_id"] or ""
    out_events = []
    for ev in events:
        event = Event(
            event_id=uuid.uuid4().hex,
            type=EventType(ev["type"]),
            campaign_id=campaign_id,
            aggregate_id=op.entity_id,
            aggregate_version=new_version,
            actor_id=op.user_id,
            occurred_at=datetime.now(timezone.utc),
            payload=ev["payload"],
        )
        conn.execute(
            """INSERT INTO events
               (event_id, campaign_id, aggregate_id, aggregate_version,
                actor_id, occurred_at, type, payload)
               VALUES (?,?,?,?,?,?,?,?)""",
            (event.event_id, event.campaign_id, event.aggregate_id,
             event.aggregate_version, event.actor_id,
             event.occurred_at.isoformat(), event.type.value,
             json.dumps(event.payload)))
        out_events.append(event)
    conn.commit()

    return {"operation_id": op.operation_id, "duplicate": False,
            "version": new_version, "status": "synced",
            "campaign_id": campaign_id, "inverse": inverse,
            "events": [e.model_dump(mode="json") for e in out_events],
            "_event_objs": out_events}


def _store_op(conn, op: OperationIn, version: int,
              status: OperationStatus, inverse: dict | None) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO operations
           (operation_id, entity_id, entity_version, client_id, user_id,
            timestamp, operation_type, payload, status, inverse)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (op.operation_id, op.entity_id, version, op.client_id, op.user_id,
         datetime.now(timezone.utc).isoformat(), op.operation_type,
         json.dumps(op.payload), status.value,
         json.dumps(inverse) if inverse else None),
    )


@router.post("")
async def apply(op: OperationIn):
    result = apply_to_store(op)
    events = result.pop("_event_objs", [])
    if result.get("campaign_id") and not result.get("duplicate"):
        for event in events:
            await manager.broadcast(result["campaign_id"], event)
    return result


@router.post("/undo/{operation_id}")
async def undo(operation_id: str):
    """Revierte una operación aplicando su inversa registrada."""
    conn = state_db()
    op_row = conn.execute(
        "SELECT * FROM operations WHERE operation_id = ?",
        (operation_id,)).fetchone()
    if op_row is None or not op_row["inverse"]:
        raise HTTPException(404, "operation not found or not reversible")
    inv = json.loads(op_row["inverse"])
    entity_kind = "combat" if conn.execute(
        "SELECT 1 FROM combats WHERE id = ?",
        (op_row["entity_id"],)).fetchone() else "character"
    inverse_op = OperationIn(
        operation_id=uuid.uuid4().hex,
        entity_id=op_row["entity_id"],
        entity_version=_current_version(conn, op_row["entity_id"],
                                        entity_kind),
        client_id=op_row["client_id"],
        user_id=op_row["user_id"],
        operation_type=inv["operation_type"],
        entity_kind=entity_kind,
        payload=inv["payload"],
    )
    return await apply(inverse_op)


def _current_version(conn, entity_id: str, kind: str = "character") -> int:
    table = _TABLES[kind]
    row = conn.execute(f"SELECT version FROM {table} WHERE id = ?",
                       (entity_id,)).fetchone()
    return row["version"] if row else 0
