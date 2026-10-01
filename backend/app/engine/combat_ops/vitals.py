"""Handlers de combate — PG, salvaciones de muerte y condiciones del combatiente."""
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
    COMBAT_HANDLERS, op, _apply_dmg, _char_ref, _char_trigger, _char_typed_amount, _find, _hp_inverse, _sync_character, _typed_amount, op
)

@op("combatant.damage")
def combatant_damage(combat: Combat, p: dict, ctx):
    """Daño con tipo opcional: aplica resistencia (÷2), inmunidad (0)
    o vulnerabilidad (×2) del stat block si lo hay."""
    c = _find(combat, p["combatant_id"])
    inv = _hp_inverse(c)
    dtype = (p.get("damage_type") or "").strip().lower()
    if c.kind == "character" and c.ref_id:
        # PJ: res/imm/vul declarativas de SU ficha (efectos pasivos +
        # triggers de daño) — el tracker antes solo miraba stat_block
        # y un PJ con resistencia recibía daño íntegro en el mapa
        amount, note = _char_typed_amount(ctx, c,
                                          max(0, int(p["amount"])),
                                          dtype)
    else:
        amount, note = _typed_amount(c, max(0, int(p["amount"])), dtype)
    payload = _apply_dmg(c, amount, note)
    _sync_character(c, ctx)
    _char_trigger(ctx, c, Trigger.AFTER_DAMAGE,
                  {"damage": {"amount": payload["amount"],
                              "type": dtype}})
    return inv, [{"type": "character.hp.changed",
                  "payload": payload}]


@op("combatant.heal")
def combatant_heal(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = _hp_inverse(c)
    amount = max(0, int(p["amount"]))
    c.hp_current = min(c.hp_max, c.hp_current + amount)
    if c.hp_current > 0:                      # levantado: reset saves
        c.death_saves = {"success": 0, "fail": 0}
        for dead in ("muerto", "dead", "estable", "stable"):
            if dead in c.conditions:
                c.conditions.remove(dead)
    _sync_character(c, ctx)
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name, "healed": amount,
                              "state": hp_state(c), **_char_ref(c)}}]


@op("combatant.death_save")
def combatant_death_save(combat: Combat, p: dict, ctx):
    """Tirada de salvación de muerte: 3 éxitos → estable, 3 fallos →
    muerto. El resultado (success bool) lo pasa el cliente tras tirar."""
    c = _find(combat, p["combatant_id"])
    if c.hp_current > 0:
        raise ValueError("el combatiente no está a 0 PG")
    # la inversa debe cubrir también condiciones/hp: 3 éxitos añade
    # 'estable' y 3 fallos 'muerto' — undo sin esto dejaba el efecto
    inv = {"operation_type": "combatant.death_save.set",
           "payload": {"combatant_id": c.id,
                       "death_saves": dict(c.death_saves),
                       "hp": c.hp_current,
                       "conditions": list(c.conditions)}}
    key = "success" if p.get("success") else "fail"
    c.death_saves[key] += 1
    outcome = None
    if c.death_saves["success"] >= 3:
        if "estable" not in c.conditions:
            c.conditions.append("estable")
        c.death_saves = {"success": 0, "fail": 0}
        outcome = "estable"
    elif c.death_saves["fail"] >= 3:
        if "muerto" not in c.conditions:
            c.conditions.append("muerto")
        outcome = "muerto"
    _sync_character(c, ctx)   # la salvación manual desfasaba la ficha
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name,
                              "death_save": key,
                              "outcome": outcome, **_char_ref(c)}}]


@op("combatant.death_save_roll")
def combatant_death_save_roll(combat: Combat, p: dict, ctx):
    """El servidor tira el d20: >=10 éxito, 1 natural = 2 fallos,
    20 natural = recupera 1 PG (reglas SRD)."""
    c = _find(combat, p["combatant_id"])
    if c.hp_current > 0:
        raise ValueError("el combatiente no está a 0 PG")
    inv = {"operation_type": "combatant.death_save.set",
           "payload": {"combatant_id": c.id,
                       "death_saves": dict(c.death_saves),
                       "hp": c.hp_current,
                       "conditions": list(c.conditions)}}
    r = roll("1d20")
    outcome = None
    if r.total == 20:                     # pifia natural inversa: revive
        c.hp_current = 1
        c.death_saves = {"success": 0, "fail": 0}
        # levanta también el estado — como hp.heal y la save de la hoja
        c.conditions = [x for x in c.conditions
                        if x.lower() not in ("muerto", "dead", "estable")]
        # levanta también el estado — como hp.heal y la save de la hoja
        c.conditions = [x for x in c.conditions
                        if x.lower() not in ("muerto", "dead", "estable")]
        outcome = "recupera 1 PG"
    elif r.total == 1:
        c.death_saves["fail"] += 2
        outcome = "pifia (2 fallos)"
    elif r.total >= 10:
        c.death_saves["success"] += 1
    else:
        c.death_saves["fail"] += 1
    if c.death_saves["success"] >= 3:
        if "estable" not in c.conditions:
            c.conditions.append("estable")
        c.death_saves = {"success": 0, "fail": 0}
        outcome = "estable"
    elif c.death_saves["fail"] >= 3:
        if "muerto" not in c.conditions:
            c.conditions.append("muerto")
        outcome = "muerto"
    _sync_character(c, ctx)
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name, "death_save_roll": r.total,
                              "outcome": outcome, **_char_ref(c)}}]


@op("combatant.death_save.set")
def combatant_death_save_set(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = {"operation_type": "combatant.death_save.set",
           "payload": {"combatant_id": c.id,
                       "death_saves": dict(c.death_saves),
                       "hp": c.hp_current,
                       "conditions": list(c.conditions)}}
    c.death_saves = dict(p["death_saves"])
    if "hp" in p:
        c.hp_current = int(p["hp"])
    if "conditions" in p:
        c.conditions = list(p["conditions"])
    _sync_character(c, ctx)
    return inv, []


@op("combatant.hp.set")
def combatant_hp_set(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = _hp_inverse(c)
    c.hp_current = max(0, min(c.hp_max, int(p["current"])))
    c.hp_temp = max(0, int(p.get("temp", c.hp_temp)))
    # las inversas de _hp_inverse traen el snapshot completo; las
    # llamadas directas de la API solo fijan PG
    if "conditions" in p:
        c.conditions = list(p["conditions"])
    if "death_saves" in p:
        c.death_saves = dict(p["death_saves"])
    _sync_character(c, ctx)
    payload = {"combatant": c.name, "current": c.hp_current,
               "temp": c.hp_temp, "state": hp_state(c), **_char_ref(c)}
    # el PG exacto de un monstruo es info del DM — las PJs reciben el
    # estado difuso vía REST; el evento numérico solo va a la sala del DM
    if c.kind != "character":
        payload["visibility"] = "dm"
    return inv, [{"type": "character.hp.changed",
                  "payload": payload}]


@op("combatant.condition.apply")
def combatant_cond_apply(combat: Combat, p: dict, ctx):
    """`rounds` (opcional) fija duración: expira al cerrar esa ronda."""
    c = _find(combat, p["combatant_id"])
    if p["condition"] in c.conditions:
        # ya presente: solo cambia la duración — snapshot para que el
        # undo no elimine una condición preexistente
        inv = {"operation_type": "combat.state.restore",
               "payload": {"data": combat.model_dump()}}
    else:
        inv = {"operation_type": "combatant.condition.remove",
               "payload": {"combatant_id": c.id,
                           "condition": p["condition"]}}
    if p["condition"] not in c.conditions:
        c.conditions.append(p["condition"])
    if p.get("rounds"):
        c.condition_durations[p["condition"]] = int(p["rounds"])
    payload = {"combatant": c.name, "condition": p["condition"],
               "rounds": p.get("rounds")}
    # Muerte de un monstruo con CR → sugerencia de XP al DM
    if p["condition"].lower() in ("muerto", "dead", "muerta") \
            and c.stat_block:
        from ...domain.xp import cr_to_xp
        xp = cr_to_xp(c.stat_block.get("cr", 0))
        if xp:
            payload["xp_suggestion"] = xp
    return inv, [{"type": "character.condition.applied",
                  "payload": payload}]


@op("noop")
def noop(entity, p: dict, ctx):
    """Inversa de operaciones sin estado (tiradas puras)."""
    return {"operation_type": "noop", "payload": {}}, []


@op("combatant.condition.remove")
def combatant_cond_remove(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    cond = p["condition"]
    if cond not in c.conditions and cond not in c.condition_durations:
        # no-op: inversa noop para que deshacer no cree la condición
        return {"operation_type": "noop", "payload": {}}, []
    had_rounds = c.condition_durations.get(cond)
    inv = {"operation_type": "combatant.condition.apply",
           "payload": {"combatant_id": c.id, "condition": cond,
                       **({"rounds": had_rounds} if had_rounds else {})}}
    if cond in c.conditions:
        c.conditions.remove(cond)
    c.condition_durations.pop(cond, None)
    return inv, [{"type": "character.condition.removed",
                  "payload": {"combatant": c.name,
                              "condition": p["condition"]}}]
