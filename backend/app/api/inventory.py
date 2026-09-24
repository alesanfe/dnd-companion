"""Atomic inventory transfers between characters — one transaction,
two logged operations, no duplication on reconnect."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db
from ..domain.character import Character, InventoryItem

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


class TransferIn(BaseModel):
    transfer_id: str                 # idempotency key (client-generated)
    from_character: str
    to_character: str
    item_id: str
    quantity: int = 1
    user_id: str = "local"


@router.post("/transfer")
def transfer(body: TransferIn):
    conn = state_db()
    conn.execute("BEGIN IMMEDIATE")

    if conn.execute("SELECT 1 FROM operations WHERE operation_id = ?",
                    (f"{body.transfer_id}:out",)).fetchone():
        conn.commit()
        return {"duplicate": True, "transfer_id": body.transfer_id}

    rows = {
        r["id"]: r for r in conn.execute(
            "SELECT * FROM characters WHERE id IN (?,?)",
            (body.from_character, body.to_character)).fetchall()
    }
    src_row, dst_row = rows.get(body.from_character), rows.get(body.to_character)
    if not src_row or not dst_row:
        conn.rollback()
        raise HTTPException(404, "character not found")

    src = Character(**json.loads(src_row["data"]))
    dst = Character(**json.loads(dst_row["data"]))

    item = next((i for i in src.inventory if i.id == body.item_id), None)
    qty = min(body.quantity, item.quantity) if item else 0
    if qty <= 0:
        conn.rollback()
        raise HTTPException(400, "item not found or quantity is 0")

    now = datetime.now(timezone.utc).isoformat()
    item.quantity -= qty
    moved = item.model_copy(update={"quantity": qty})
    if item.quantity <= 0:
        src.inventory.remove(item)
    # merge si el destino ya tiene el mismo item (mismo id de contenido)
    existing = next((i for i in dst.inventory
                     if i.source_id and i.source_id == moved.source_id
                     and i.source_id is not None
                     and i.name == moved.name), None)
    if existing:
        existing.quantity += qty
    else:
        dst.inventory.append(
            InventoryItem(**{**moved.model_dump(), "id": uuid.uuid4().hex}))

    for row, char in ((src_row, src), (dst_row, dst)):
        conn.execute(
            "UPDATE characters SET data=?, version=?, updated_at=? WHERE id=?",
            (json.dumps(char.model_dump()), row["version"] + 1, now,
             row["id"]))
        conn.execute(
            """INSERT INTO operations
               (operation_id, entity_id, entity_version, client_id, user_id,
                timestamp, operation_type, payload, status, inverse)
               VALUES (?,?,?,?,?,?,?,?, 'synced', NULL)""",
            (f"{body.transfer_id}:{'out' if row is src_row else 'in'}",
             row["id"], row["version"] + 1, "transfer", body.user_id, now,
             "inventory.transfer",
             json.dumps({"item": moved.name, "quantity": qty,
                         "peer": dst_row["id"] if row is src_row
                         else src_row["id"]})))
    conn.commit()
    return {"duplicate": False, "transfer_id": body.transfer_id,
            "moved": {"name": moved.name, "quantity": qty}}
