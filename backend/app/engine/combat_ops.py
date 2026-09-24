"""Combat operation handlers — same reversible-op contract as
engine/ops.py but operating on a Combat aggregate.

    handler(combat, payload, ctx) -> (inverse_op, [event_payloads])

ctx.content_db() gives read access to the rules DB so 'combatant.add'
can copy a monster stat block by content entity id.
"""
from __future__ import annotations

import json
import uuid
from typing import Callable

from ..domain.combat import Combat, Combatant, hp_state
from .dice import roll

Handler = Callable[[Combat, dict, object], tuple[dict, list[dict]]]
COMBAT_HANDLERS: dict[str, Handler] = {}


def op(name: str):
    def wrap(fn: Handler) -> Handler:
        COMBAT_HANDLERS[name] = fn
        return fn
    return wrap


def _find(combat: Combat, cid: str) -> Combatant:
    for c in combat.combatants:
        if c.id == cid:
            return c
    raise ValueError(f"combatant not found: {cid}")


def _hp_inverse(c: Combatant) -> dict:
    return {"operation_type": "combatant.hp.set",
            "payload": {"combatant_id": c.id, "current": c.hp_current,
                        "temp": c.hp_temp}}


@op("combat.next_turn")
def next_turn(combat: Combat, p: dict, ctx):
    order = combat.ordered()
    if not order:
        raise ValueError("no hay combatientes")
    inv = {"operation_type": "combat.prev_turn", "payload": {}}
    combat.turn_index += 1
    if combat.turn_index >= len(order):
        combat.turn_index = 0
        combat.round += 1
    active = combat.active
    return inv, [{"type": "combat.turn.advanced",
                  "payload": {"round": combat.round,
                              "active": active.name if active else None}}]


@op("combat.prev_turn")
def prev_turn(combat: Combat, p: dict, ctx):
    order = combat.ordered()
    if not order:
        raise ValueError("no hay combatientes")
    inv = {"operation_type": "combat.next_turn", "payload": {}}
    combat.turn_index -= 1
    if combat.turn_index < 0:
        combat.turn_index = len(order) - 1
        combat.round = max(1, combat.round - 1)
    return inv, [{"type": "combat.turn.advanced",
                  "payload": {"round": combat.round,
                              "active": combat.active.name}}]


@op("combat.end")
def combat_end(combat: Combat, p: dict, ctx):
    before = combat.model_dump()
    combat.status = "ended"
    return {"operation_type": "combat.state.restore",
            "payload": {"data": before}}, [{"type": "combat.ended",
                                           "payload": {"rounds": combat.round}}]


@op("combat.state.restore")
def combat_restore(combat: Combat, p: dict, ctx):
    current = combat.model_dump()
    restored = Combat(**p["data"])
    combat.__dict__.update(restored.__dict__)
    return {"operation_type": "combat.state.restore",
            "payload": {"data": current}}, []


@op("combatant.add")
def combatant_add(combat: Combat, p: dict, ctx):
    """Añade un combatiente. Con content_entity_id copia el stat block
    del bestiario (HP medio, CA, iniciativa = d20 + mod DES)."""
    data = {}
    if p.get("content_entity_id"):
        row = ctx.content_db().execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (p["content_entity_id"],)).fetchone()
        if row:
            data = json.loads(row["data"])
    dex = data.get("dexterity", 10)
    init = p.get("initiative")
    if init is None:
        init = roll("1d20").total + (dex - 10) // 2
    acs = data.get("armor_class") or []
    c = Combatant(
        id=uuid.uuid4().hex,
        kind=p.get("kind", "monster" if data else "npc"),
        name=p.get("name") or data.get("name", "?"),
        ref_id=p.get("ref_id") or p.get("content_entity_id"),
        initiative=int(init),
        hp_current=p.get("hp_max") or data.get("hit_points", 1),
        hp_max=p.get("hp_max") or data.get("hit_points", 1),
        ac=p.get("ac") or (acs[0].get("value", 10) if acs else 10),
        stat_block=data or None,
    )
    combat.combatants.append(c)
    inv = {"operation_type": "combatant.remove",
           "payload": {"combatant_id": c.id}}
    return inv, [{"type": "combat.turn.advanced",
                  "payload": {"added": c.name, "initiative": c.initiative}}]


@op("combatant.remove")
def combatant_remove(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    idx = combat.combatants.index(c)
    combat.combatants.remove(c)
    return {"operation_type": "combatant.add_raw",
            "payload": {"combatant": c.model_dump(), "index": idx}}, []


@op("combatant.add_raw")
def combatant_add_raw(combat: Combat, p: dict, ctx):
    """Undo helper: reinserta un combatiente con su id original."""
    c = Combatant(**p["combatant"])
    combat.combatants.insert(int(p.get("index", len(combat.combatants))), c)
    return {"operation_type": "combatant.remove",
            "payload": {"combatant_id": c.id}}, []


@op("combatant.damage")
def combatant_damage(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = _hp_inverse(c)
    amount = max(0, int(p["amount"]))
    absorbed = min(c.hp_temp, amount)
    c.hp_temp -= absorbed
    c.hp_current = max(0, c.hp_current - (amount - absorbed))
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name, "amount": amount,
                              "state": hp_state(c)}}]


@op("combatant.heal")
def combatant_heal(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = _hp_inverse(c)
    amount = max(0, int(p["amount"]))
    c.hp_current = min(c.hp_max, c.hp_current + amount)
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name, "healed": amount,
                              "state": hp_state(c)}}]


@op("combatant.hp.set")
def combatant_hp_set(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = _hp_inverse(c)
    c.hp_current = max(0, min(c.hp_max, int(p["current"])))
    c.hp_temp = max(0, int(p.get("temp", c.hp_temp)))
    return inv, []


@op("combatant.initiative")
def combatant_initiative(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = {"operation_type": "combatant.initiative",
           "payload": {"combatant_id": c.id, "value": c.initiative}}
    c.initiative = int(p["value"])
    return inv, []


@op("combatant.condition.apply")
def combatant_cond_apply(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = {"operation_type": "combatant.condition.remove",
           "payload": {"combatant_id": c.id, "condition": p["condition"]}}
    if p["condition"] not in c.conditions:
        c.conditions.append(p["condition"])
    return inv, [{"type": "character.condition.applied",
                  "payload": {"combatant": c.name,
                              "condition": p["condition"]}}]


@op("combatant.condition.remove")
def combatant_cond_remove(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = {"operation_type": "combatant.condition.apply",
           "payload": {"combatant_id": c.id, "condition": p["condition"]}}
    if p["condition"] in c.conditions:
        c.conditions.remove(p["condition"])
    return inv, [{"type": "character.condition.removed",
                  "payload": {"combatant": c.name,
                              "condition": p["condition"]}}]


def apply_combat_operation(combat: Combat, operation_type: str,
                           payload: dict, ctx) -> tuple[dict, list[dict]]:
    handler = COMBAT_HANDLERS.get(operation_type)
    if handler is None:
        raise KeyError(f"unknown combat operation: {operation_type}")
    return handler(combat, payload, ctx)
