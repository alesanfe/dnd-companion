"""Handlers de combate — ciclo de turno: next/prev, fin de combate y restore."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from ...domain import statblock
from ...domain.combat import Combat, Combatant, hp_state
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll
from ._base import (
    COMBAT_HANDLERS, op, _char_trigger, op
)

@op("combat.next_turn")
def next_turn(combat: Combat, p: dict, ctx):
    order = combat.ordered()
    if not order:
        raise ValueError("no hay combatientes")
    # snapshot: al cerrar ronda expiran condiciones — prev_turn no
    # podría restaurarlas (duración y lista ya mutadas)
    inv = {"operation_type": "combat.state.restore",
           "payload": {"data": combat.model_dump()}}
    # el combatiente que sale de turno dispara sus on_turn_end
    prev_active = combat.active
    combat.turn_index += 1
    expired: list[str] = []
    if combat.turn_index >= len(order):
        combat.turn_index = 0
        combat.round += 1
        # al cerrar la ronda, decrementan las duraciones de condiciones
        for c in combat.combatants:
            for cond in list(c.condition_durations):
                c.condition_durations[cond] -= 1
                if c.condition_durations[cond] <= 0:
                    del c.condition_durations[cond]
                    if cond in c.conditions:
                        c.conditions.remove(cond)
                        expired.append(f"{c.name}:{cond}")
            # efectos declarativos "al inicio de la ronda" (PJ)
            _char_trigger(ctx, c, Trigger.ON_ROUND_START)
    active = combat.active
    if prev_active is not None and prev_active is not active:
        _char_trigger(ctx, prev_active, Trigger.ON_TURN_END)
    if active is not None:
        _char_trigger(ctx, active, Trigger.ON_TURN_START)
    payload = {"round": combat.round,
               "active": active.name if active else None}
    if expired:
        payload["conditions_expired"] = expired
    return inv, [{"type": "combat.turn.advanced", "payload": payload}]


@op("combat.prev_turn")
def prev_turn(combat: Combat, p: dict, ctx):
    order = combat.ordered()
    if not order:
        raise ValueError("no hay combatientes")
    # snapshot como next_turn: deshacer un prev con next_turn volvería
    # a decrementar duraciones de condiciones — doble expiración
    inv = {"operation_type": "combat.state.restore",
           "payload": {"data": combat.model_dump()}}
    combat.turn_index -= 1
    if combat.turn_index < 0:
        combat.turn_index = len(order) - 1
        combat.round = max(1, combat.round - 1)
    # volver atrás no restaura las condiciones que expiraron al
    # cerrar la ronda — para eso está el snapshot de next_turn
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
    # evento pequeño de resync: sin él, un undo (p.ej. de combat.end)
    # dejaba a la sala viendo el estado viejo hasta el próximo refresh
    return {"operation_type": "combat.state.restore",
            "payload": {"data": current}}, [
                {"type": "combat.state.restored",
                 "payload": {"round": combat.round,
                             "status": combat.status}}]
