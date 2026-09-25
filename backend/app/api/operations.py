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


# Las reglas de condición viven en domain/conditions.py (compartidas
# con los combatientes); aquí solo se consultan para el personaje.
from ..domain.conditions import mods_for as _condition_mods_raw


def _condition_mods(char: Character, roll_type: str):
    """Deriva ventaja/desventaja/autofallo desde char.conditions."""
    return _condition_mods_raw(char.conditions, roll_type)


@router.post("/character/{character_id}/roll")
async def character_roll(character_id: str, expression: str = "1d20",
                         roll_type: str = "check",
                         use_inspiration: bool = False,
                         secret: bool = False):
    """Tirada a través del motor de efectos: ventaja/desventaja y mods
    declarativos (efectos pasivos o before_roll) + reglas de condición.
    roll_type: attack|check|save|damage|save:dex|skill:x."""
    conn = state_db()
    row = conn.execute(
        "SELECT data, campaign_id FROM characters WHERE id = ?",
        (character_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    char = Character(**json.loads(row["data"]))

    expr = expression.strip().lower()
    adv = dis = False
    extra_mod = 0
    applied = []
    if use_inspiration and char.inspiration:
        adv = True
        applied.append("inspiración: ventaja")   # el cliente la consume
        # via la op inspiration.set{value:false} tras la tirada

    # modificador automático según tipo: check:dex, save:wis, skill:x
    base_type, _, detail = roll_type.partition(":")
    if base_type in ("check", "save") and detail:
        extra_mod += char.abilities.modifier(detail)
        applied.append(f"{detail}: {char.abilities.modifier(detail):+d}")
        if base_type == "save" and detail in char.save_proficiencies:
            extra_mod += char.proficiency_bonus
            applied.append(f"prof: +{char.proficiency_bonus}")
    elif base_type == "skill" and detail:
        ability = _SKILL_ABILITIES.get(detail, "int")
        extra_mod += char.abilities.modifier(ability)
        applied.append(f"{ability}({detail}): "
                       f"{char.abilities.modifier(ability):+d}")
        if detail in char.skill_proficiencies:
            extra_mod += char.proficiency_bonus
            applied.append(f"prof: +{char.proficiency_bonus}")

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
    result = {"expression": r.expression, "rolls": r.rolls,
              "kept": r.kept, "total": r.total, "auto_fail": False,
              "effects_applied": applied}
    # si el PJ está en campaña, la tirada se anuncia a la sala WS
    if row["campaign_id"]:
        await _broadcast_roll(conn, row["campaign_id"], character_id,
                              char.name, roll_type, result, secret)
    return result


async def _broadcast_roll(conn, campaign_id: str, character_id: str,
                          char_name: str, roll_type: str,
                          result: dict, secret: bool = False) -> None:
    now = datetime.now(timezone.utc)
    ev = Event(event_id=uuid.uuid4().hex, type=EventType.DICE_ROLL_CREATED,
               campaign_id=campaign_id, aggregate_id=character_id,
               aggregate_version=0, actor_id=character_id,
               occurred_at=now,
               payload={"character": char_name, "roll_type": roll_type,
                        "expression": result["expression"],
                        "total": result["total"],
                        "secret": secret,
                        # el DM filtra; los clientes de jugador no
                        # deben renderizar el total si secret=true
                        "visibility": "dm" if secret else "all"})
    conn.execute(
        """INSERT INTO events
           (event_id, campaign_id, aggregate_id, aggregate_version,
            actor_id, occurred_at, type, payload)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ev.event_id, campaign_id, character_id, 0, character_id,
         now.isoformat(), ev.type.value, json.dumps(ev.payload)))
    conn.commit()
    await manager.broadcast(campaign_id, ev)


# SRD 2014: habilidad → característica (nombre de habilidad en inglés)
_SKILL_ABILITIES = {
    "athletics": "str",
    "acrobatics": "dex", "sleight-of-hand": "dex", "stealth": "dex",
    "arcana": "int", "history": "int", "investigation": "int",
    "nature": "int", "religion": "int",
    "animal-handling": "wis", "insight": "wis", "medicine": "wis",
    "perception": "wis", "survival": "wis",
    "deception": "cha", "intimidation": "cha", "performance": "cha",
    "persuasion": "cha",
}


@router.post("/character/{character_id}/attack")
def character_attack(character_id: str, item_name: str,
                     mode: str = "normal",
                     target_ac: int | None = None):
    """Ataque completo con un arma del inventario: tirada de impacto
    (d20 + mod + prof, con condiciones/efectos) + tirada de daño.

    mode: normal|adv|dis — ventaja/desventaja explícita del jugador;
    las condiciones mecánicas del personaje se aplican encima.
    target_ac: si se informa, el resultado indica impacto/fallo."""
    conn = state_db()
    row = conn.execute(
        "SELECT data FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    char = Character(**json.loads(row["data"]))
    item = next((i for i in char.inventory
                 if i.name.lower() == item_name.lower()), None)
    if item is None:
        raise HTTPException(404, "arma no en inventario")
    w = {}
    if item.source_id:
        r = content_db().execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (item.source_id,)).fetchone()
        w = json.loads(r["data"]) if r else {}
    props = [p.get("index") for p in w.get("properties", [])]
    mod = char.abilities.modifier(
        "dex" if "finesse" in props or "ranged" in
        str(w.get("weapon_range", "")).lower() else "str")
    hit_bonus = char.proficiency_bonus + mod
    dmg_dice = (w.get("damage") or {}).get("damage_dice", "1d4")

    # condiciones: la mecánica es idéntica a /roll
    c_adv, c_dis, fail, c_notes = _condition_mods(char, "attack")
    if mode == "adv":
        c_adv = True
    elif mode == "dis":
        c_dis = True
    suffix = ("adv" if c_adv and not c_dis
              else "dis" if c_dis and not c_adv else "")
    hit = dice_roll(f"1d20{suffix}{hit_bonus:+d}")
    dmg = dice_roll(f"{dmg_dice}{mod:+d}")
    result = {"weapon": item.name,
              "auto_fail": fail,
              "notes": c_notes,
              "hit": {"rolls": hit.rolls, "total": hit.total,
                      "bonus": hit_bonus,
                      "mode": suffix or "normal"},
              "damage": {"expression": dmg.expression,
                         "rolls": dmg.rolls, "total": dmg.total}}
    if target_ac is not None and not fail:
        result["hit"]["hits"] = hit.total >= target_ac
        result["hit"]["target_ac"] = target_ac
    return result


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


@router.get("/conflicts")
def conflicts(limit: int = 20):
    """Operaciones en conflicto (optimistic locking) pendientes de
    revisión manual — PG/recursos modificados en dos dispositivos."""
    conn = state_db()
    rows = conn.execute(
        """SELECT operation_id, entity_id, entity_version, user_id,
                  timestamp, operation_type, payload
           FROM operations WHERE status = 'conflict'
           ORDER BY timestamp DESC LIMIT ?""",
        (limit,)).fetchall()
    return {"conflicts": [
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
