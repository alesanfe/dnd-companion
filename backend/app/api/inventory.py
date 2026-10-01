"""Atomic inventory transfers between characters — one transaction,
two logged operations, no duplication on reconnect."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import member_role, optional_user
from .campaigns import _DM_ROLES, _has_owner
from ..db.connections import state_db
from ..domain.character import Character, InventoryItem
from ..domain.events import Event, EventType

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


class TransferIn(BaseModel):
    transfer_id: str                 # idempotency key (client-generated)
    from_character: str
    to_character: str
    item_id: str
    quantity: int = 1
    user_id: str = "local"


@router.post("/transfer")
async def transfer(body: TransferIn,
                   user: dict | None = Depends(optional_user)):
    conn = state_db()
    conn.execute("BEGIN IMMEDIATE")

    if conn.execute("SELECT 1 FROM operations WHERE operation_id = ?",
                    (f"{body.transfer_id}:out",)).fetchone():
        conn.commit()
        return {"duplicate": True, "transfer_id": body.transfer_id}

    if body.from_character == body.to_character:
        conn.rollback()
        raise HTTPException(400, "origen y destino son la misma ficha")
    if body.quantity <= 0:
        conn.rollback()
        raise HTTPException(400, "quantity debe ser positiva")

    rows = {
        r["id"]: r for r in conn.execute(
            "SELECT * FROM characters WHERE id IN (?,?)",
            (body.from_character, body.to_character)).fetchall()
    }
    src_row, dst_row = rows.get(body.from_character), rows.get(body.to_character)
    if not src_row or not dst_row:
        conn.rollback()
        raise HTTPException(404, "character not found")

    # mover objetos de fichas en campañas con dueño exige ser miembro
    # (cualquiera con los ids podía robar el inventario de otra mesa)
    uid = (user or {}).get("user_id")
    for r in (src_row, dst_row):
        camp = r["campaign_id"]
        if camp and _has_owner(conn, camp) and member_role(
                camp, uid) not in _DM_ROLES + ("player", "guest"):
            conn.rollback()
            raise HTTPException(403, "sin permiso en esta campaña")
    if user:
        body.user_id = uid

    # y un jugador solo saca objetos de SU ficha — mover cosas del
    # inventario del vecino es del DM (en local queda libre)
    src_camp = src_row["campaign_id"]
    if src_camp and src_row["player_id"] and _has_owner(
            conn, src_camp) \
            and member_role(src_camp, uid) not in _DM_ROLES \
            and src_row["player_id"] != uid:
        conn.rollback()
        raise HTTPException(
            403, "solo puedes mover objetos de tu propia ficha")
    # ficha PERSONAL (sin campaña) con dueño: el check de campaña no
    # la cubre — cualquiera podía vaciar su inventario
    if not src_camp and src_row["player_id"] and src_row[
            "player_id"] != uid \
            and conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        conn.rollback()
        raise HTTPException(
            403, "solo puedes mover objetos de tu propia ficha")

    try:
        src = Character(**json.loads(src_row["data"]))
        dst = Character(**json.loads(dst_row["data"]))

        item = next((i for i in src.inventory if i.id == body.item_id), None)
        if item is None or item.quantity < body.quantity:
            raise HTTPException(400, "item not found or not enough")
        qty = body.quantity

        now = datetime.now(timezone.utc).isoformat()
        moved, dst_item_id = _move_item(src, dst, item, qty)
        # inversas reales por mitad — el undo compuesto (operations.undo
        # detecta el par ':out'/':in') revierte AMBAS fichas en una txn;
        # revertir solo una duplicaba los objetos
        inverses = {
            src_row["id"]: json.dumps({
                # add con el id original → se fusiona con el stack
                # restante o recrea el objeto íntegro
                "operation_type": "character.inventory.add",
                "payload": {**item.model_dump(mode="json"),
                            "id": item.id, "quantity": qty}}),
            dst_row["id"]: json.dumps({
                "operation_type": "character.inventory.remove",
                "payload": {"item_id": dst_item_id, "quantity": qty}}),
        }

        out_events = []
        for row, char in ((src_row, src), (dst_row, dst)):
            cur = conn.execute(
                "UPDATE characters SET data=?, version=?, updated_at=?"
                " WHERE id=? AND version=?",
                (json.dumps(char.model_dump()), row["version"] + 1, now,
                 row["id"], row["version"]))
            if cur.rowcount == 0:
                raise HTTPException(409, "version conflict")
            conn.execute(
                """INSERT INTO operations
                   (operation_id, entity_id, entity_version, client_id,
                    user_id, timestamp, operation_type, payload, status,
                    inverse)
                   VALUES (?,?,?,?,?,?,?,?, 'synced', ?)""",
                (f"{body.transfer_id}:{'out' if row is src_row else 'in'}",
                 row["id"], row["version"] + 1, "transfer", body.user_id,
                 now, "inventory.transfer",
                 json.dumps({"item": moved.name, "quantity": qty,
                             "peer": dst_row["id"] if row is src_row
                             else src_row["id"]}),
                 inverses[row["id"]]))
            # evento por ficha: la hoja abierta del otro jugador se
            # refresca vía WS — sin él solo el que hizo clic veía el
            # inventario actualizado
            ev = Event(
                event_id=uuid.uuid4().hex,
                type=EventType.INVENTORY_ITEM_TRANSFERRED,
                campaign_id=row["campaign_id"] or "",
                aggregate_id=row["id"],
                aggregate_version=row["version"] + 1,
                actor_id=body.user_id,
                occurred_at=datetime.now(timezone.utc),
                payload={"item": moved.name, "quantity": qty,
                         "peer": dst_row["id"] if row is src_row
                         else src_row["id"],
                         "direction": "out" if row is src_row else "in"})
            conn.execute(
                """INSERT INTO events
                   (event_id, campaign_id, aggregate_id, aggregate_version,
                    actor_id, occurred_at, type, payload)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ev.event_id, ev.campaign_id, ev.aggregate_id,
                 ev.aggregate_version, ev.actor_id,
                 ev.occurred_at.isoformat(), ev.type.value,
                 json.dumps(ev.payload)))
            out_events.append(ev)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    from ..ws.rooms import manager
    for ev in out_events:
        if ev.campaign_id:
            await manager.broadcast(ev.campaign_id, ev)
    return {"duplicate": False, "transfer_id": body.transfer_id,
            "moved": {"name": moved.name, "quantity": qty}}


def _move_item(src: Character, dst: Character, item,
               qty: int):
    """Descuenta del origen y añade al destino — merge si el destino
    ya tiene el mismo item (mismo source_id + nombre). Devuelve
    (item_movido, id_del_item_en_destino) para la inversa."""
    item.quantity -= qty
    moved = item.model_copy(update={"quantity": qty})
    if item.quantity <= 0:
        src.inventory.remove(item)
    existing = next((i for i in dst.inventory
                     if i.source_id and i.source_id == moved.source_id
                     and i.source_id is not None
                     and i.name == moved.name), None)
    if existing:
        existing.quantity += qty
        dst_id = existing.id
    else:
        dst_id = uuid.uuid4().hex
        dst.inventory.append(
            InventoryItem(**{**moved.model_dump(), "id": dst_id}))
    return moved, dst_id
