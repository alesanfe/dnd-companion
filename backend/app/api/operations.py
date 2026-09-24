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
from ..engine.dice import roll as dice_roll
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
    """Acceso a las DBs desde handlers. state_conn es la conexión de la
    transacción actual: los handlers que tocan otras entidades (tiendas)
    quedan dentro de la misma transacción atómica."""
    def __init__(self, state_conn=None):
        self._state = state_conn

    def content_db(self):
        return content_db()

    def state_db(self):
        return self._state


# Reglas declarativas de condiciones (SRD): qué impone cada condición
# sobre tiradas. Es data, no condicionales por clase — igual que los
# Effect, pero para condiciones que no existen como entidad efecto.
# roll_type admite 'attack|check|save|damage' y 'save:dex', 'skill:x'.
_CONDITION_ROLLS = {
    "blinded":     {"dis": {"attack"}},
    "invisible":   {"adv": {"attack"}},
    "poisoned":    {"dis": {"attack", "check"}},
    "prone":       {"dis": {"attack"}},
    "restrained":  {"dis": {"attack", "save:dex"}},
    "frightened":  {"dis": {"check", "attack"}},
    "grappled":    {},
    "stunned":     {"fail": {"save:str", "save:dex"}},
    "paralyzed":   {"fail": {"save:str", "save:dex"}},
    "unconscious": {"fail": {"save:str", "save:dex"}},
    "exhaustion":  {"dis": {"check"}},
}


def _condition_mods(char: Character, roll_type: str):
    """Deriva ventaja/desventaja/autofallo desde char.conditions."""
    adv = dis = fail = False
    notes: list[str] = []
    base = roll_type.split(":")[0]
    for cond in char.conditions:
        rule = _CONDITION_ROLLS.get(cond.lower())
        if not rule:
            continue
        if any(roll_type == t or base == t for t in rule.get("adv", ())):
            adv = True; notes.append(f"{cond}: ventaja")
        if any(roll_type == t or base == t for t in rule.get("dis", ())):
            dis = True; notes.append(f"{cond}: desventaja")
        if roll_type in rule.get("fail", ()):
            fail = True; notes.append(f"{cond}: salvación automática fallida")
    return adv, dis, fail, notes


@router.post("/character/{character_id}/roll")
def character_roll(character_id: str, expression: str = "1d20",
                   roll_type: str = "check"):
    """Tirada a través del motor de efectos: ventaja/desventaja y mods
    declarativos (efectos pasivos o before_roll) + reglas de condición.
    roll_type: attack|check|save|damage|save:dex|skill:x."""
    conn = state_db()
    row = conn.execute(
        "SELECT data FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    char = Character(**json.loads(row["data"]))

    expr = expression.strip().lower()
    adv = dis = False
    extra_mod = 0
    applied = []
    for eff in char.effects:
        # solo efectos pasivos o con trigger before_roll
        if eff.trigger is not None and eff.trigger.value != "before_roll":
            continue
        for o in eff.operations:
            tgt = o.target or ""
            if tgt not in (roll_type, f"*.{roll_type}", "*", "roll"):
                continue
            if o.op.value == "grant_advantage":
                adv = True; applied.append(f"{eff.name}: ventaja")
            elif o.op.value == "grant_disadvantage":
                dis = True; applied.append(f"{eff.name}: desventaja")
            elif o.op.value == "add_modifier" and o.value is not None:
                extra_mod += int(o.value)
                applied.append(f"{eff.name}: {int(o.value):+d}")
    c_adv, c_dis, fail, c_notes = _condition_mods(char, roll_type)
    adv = adv or c_adv
    dis = dis or c_dis
    applied += c_notes
    if fail:
        return {"expression": expr, "rolls": [], "kept": [], "total": 0,
                "auto_fail": True, "effects_applied": applied}
    if adv and not dis and "adv" not in expr and "dis" not in expr \
            and "d20" in expr:
        expr += "adv"
    elif dis and not adv and "adv" not in expr and "dis" not in expr \
            and "d20" in expr:
        expr += "dis"
    if extra_mod:
        expr += f"{extra_mod:+d}"
    try:
        r = dice_roll(expr)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"expression": r.expression, "rolls": r.rolls, "kept": r.kept,
            "total": r.total, "auto_fail": False,
            "effects_applied": applied}


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
                entity, op.operation_type, op.payload, OpContext(conn))
        else:
            inverse, events = apply_operation(
                entity, op.operation_type, op.payload, OpContext(conn))
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


@router.get("")
def history(entity_id: str, limit: int = 50):
    """Historial de operaciones de una entidad (auditoría + deshacer)."""
    conn = state_db()
    rows = conn.execute(
        """SELECT operation_id, entity_version, user_id, timestamp,
                  operation_type, payload, status,
                  inverse IS NOT NULL AS reversible
           FROM operations WHERE entity_id = ?
           ORDER BY timestamp DESC LIMIT ?""",
        (entity_id, limit)).fetchall()
    return {"operations": [
        {**dict(r), "payload": json.loads(r["payload"])} for r in rows]}


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
