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

from ..domain import statblock
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


def _sync_character(c: Combatant, ctx) -> None:
    """Si el combatiente es una ficha de personaje, propaga el HP a la
    tabla characters dentro de la misma transacción."""
    if c.kind != "character" or not c.ref_id:
        return
    try:
        conn = ctx.state_db()
    except AttributeError:
        return
    if conn is None:
        return
    from ..domain.character import Character
    row = conn.execute("SELECT data FROM characters WHERE id = ?",
                       (c.ref_id,)).fetchone()
    if row is None:
        return
    ch = Character(**json.loads(row["data"]))
    ch.hp.current = c.hp_current
    ch.hp.temp = c.hp_temp
    conn.execute("UPDATE characters SET data = ? WHERE id = ?",
                 (ch.model_dump_json(), c.ref_id))


@op("combat.next_turn")
def next_turn(combat: Combat, p: dict, ctx):
    order = combat.ordered()
    if not order:
        raise ValueError("no hay combatientes")
    inv = {"operation_type": "combat.prev_turn", "payload": {}}
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
    active = combat.active
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
    char_hp = None
    if p.get("kind") == "character" and p.get("ref_id"):
        try:
            srow = ctx.state_db().execute(
                "SELECT data FROM characters WHERE id = ?",
                (p["ref_id"],)).fetchone()
            if srow:
                char_hp = json.loads(srow["data"]).get("hp")
        except (AttributeError, Exception):
            char_hp = None
    # Normaliza cualquier schema de fuente (5e-bits, Open5e v1/v2,
    # 5etools, codexMUNDI, dnd-data) al bloque canónico.
    block = statblock.normalize(data) or p.get("stat_block")
    init = p.get("initiative")
    if init is None:
        init = roll("1d20").total + (
            (block or {}).get("initiative_mod", 0))
    c = Combatant(
        id=uuid.uuid4().hex,
        kind=p.get("kind", "monster" if data else "npc"),
        name=p.get("name") or data.get("name", "?"),
        ref_id=p.get("ref_id") or p.get("content_entity_id"),
        initiative=int(init),
        hp_current=(p.get("hp_max") or (char_hp or {}).get("current")
                    or (block or {}).get("hp", 1)),
        hp_max=(p.get("hp_max") or (char_hp or {}).get("max")
                or (block or {}).get("hp", 1)),
        hp_temp=(char_hp or {}).get("temp", 0),
        ac=p.get("ac") or (block or {}).get("ac", 10),
        stat_block=block,
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
    _sync_character(c, ctx)
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name, "amount": amount,
                              "state": hp_state(c)}}]


@op("combatant.heal")
def combatant_heal(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = _hp_inverse(c)
    amount = max(0, int(p["amount"]))
    c.hp_current = min(c.hp_max, c.hp_current + amount)
    if c.hp_current > 0:                      # levantado: reset saves
        c.death_saves = {"success": 0, "fail": 0}
        for dead in ("muerto", "estable"):
            if dead in c.conditions:
                c.conditions.remove(dead)
    _sync_character(c, ctx)
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name, "healed": amount,
                              "state": hp_state(c)}}]


@op("combatant.death_save")
def combatant_death_save(combat: Combat, p: dict, ctx):
    """Tirada de salvación de muerte: 3 éxitos → estable, 3 fallos →
    muerto. El resultado (success bool) lo pasa el cliente tras tirar."""
    c = _find(combat, p["combatant_id"])
    if c.hp_current > 0:
        raise ValueError("el combatiente no está a 0 PG")
    inv = {"operation_type": "combatant.death_save.set",
           "payload": {"combatant_id": c.id,
                       "death_saves": dict(c.death_saves)}}
    key = "success" if p.get("success") else "fail"
    c.death_saves[key] += 1
    outcome = None
    if c.death_saves["success"] >= 3:
        c.conditions.append("estable")
        c.death_saves = {"success": 0, "fail": 0}
        outcome = "estable"
    elif c.death_saves["fail"] >= 3:
        c.conditions.append("muerto")
        outcome = "muerto"
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name,
                              "death_save": key,
                              "outcome": outcome}}]


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
        outcome = "recupera 1 PG"
    elif r.total == 1:
        c.death_saves["fail"] += 2
        outcome = "pifia (2 fallos)"
    elif r.total >= 10:
        c.death_saves["success"] += 1
    else:
        c.death_saves["fail"] += 1
    if c.death_saves["success"] >= 3:
        c.conditions.append("estable")
        c.death_saves = {"success": 0, "fail": 0}
        outcome = "estable"
    elif c.death_saves["fail"] >= 3:
        c.conditions.append("muerto")
        outcome = "muerto"
    _sync_character(c, ctx)
    return inv, [{"type": "character.hp.changed",
                  "payload": {"combatant": c.name, "death_save_roll": r.total,
                              "outcome": outcome}}]


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
    _sync_character(c, ctx)
    return inv, []


@op("combatant.initiative.roll")
def combatant_initiative_roll(combat: Combat, p: dict, ctx):
    """El servidor tira iniciativa: 1d20 + mod DES del stat block o
    de la ficha vinculada."""
    c = _find(combat, p["combatant_id"])
    dex = 10
    if c.stat_block:
        # bloque canónico (abilities.dex) o crudo legacy (dexterity)
        dex = (c.stat_block.get("abilities", {}).get("dex")
               or c.stat_block.get("dexterity") or 10)
    elif c.kind == "character" and c.ref_id:
        try:
            row = ctx.state_db().execute(
                "SELECT data FROM characters WHERE id = ?",
                (c.ref_id,)).fetchone()
            if row:
                dex = json.loads(row["data"])["abilities"]["dexterity"]
        except Exception:
            pass
    inv = {"operation_type": "combatant.initiative",
           "payload": {"combatant_id": c.id, "value": c.initiative}}
    mod = (dex - 10) // 2
    c.initiative = roll("1d20").total + mod
    return inv, [{"type": "combat.turn.advanced",
                  "payload": {"initiative_rolled": c.name,
                              "value": c.initiative}}]


@op("combatant.initiative")
def combatant_initiative(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    inv = {"operation_type": "combatant.initiative",
           "payload": {"combatant_id": c.id, "value": c.initiative}}
    c.initiative = int(p["value"])
    return inv, []


@op("combatant.condition.apply")
def combatant_cond_apply(combat: Combat, p: dict, ctx):
    """`rounds` (opcional) fija duración: expira al cerrar esa ronda."""
    c = _find(combat, p["combatant_id"])
    inv = {"operation_type": "combatant.condition.remove",
           "payload": {"combatant_id": c.id, "condition": p["condition"]}}
    if p["condition"] not in c.conditions:
        c.conditions.append(p["condition"])
    if p.get("rounds"):
        c.condition_durations[p["condition"]] = int(p["rounds"])
    return inv, [{"type": "character.condition.applied",
                  "payload": {"combatant": c.name,
                              "condition": p["condition"],
                              "rounds": p.get("rounds")}}]


@op("combatant.save")
def combatant_save(combat: Combat, p: dict, ctx):
    """El servidor tira la salvación de un combatiente: 1d20 + mod de la
    característica del stat block. El total va en el evento."""
    c = _find(combat, p["combatant_id"])
    ability = p["ability"]
    block = c.stat_block or {}
    if "saves" in block:            # bloque canónico: totales ya dados
        total_mod = block["saves"].get(ability, 0)
    else:                           # bloque crudo (legacy): score→mod
        score = block.get(
            {"str": "strength", "dex": "dexterity", "con": "constitution",
             "int": "intelligence", "wis": "wisdom", "cha": "charisma"
             }.get(ability, ability), 10)
        total_mod = (score - 10) // 2
    r = roll("1d20")
    total = r.total + total_mod
    return {"operation_type": "noop", "payload": {}}, [
        {"type": "dice.roll.created",
         "payload": {"combatant": c.name, "save": ability,
                     "roll": r.total, "total": total}}]


@op("combatant.action.roll")
def combatant_action_roll(combat: Combat, p: dict, ctx):
    """Rueda una acción del stat block del combatiente: parsea el texto
    normalizado buscando 'to hit' (+N) y dados de daño (NdM±K), y tira
    ambos. Acciones de salvación emiten la CD detectada."""
    import re
    c = _find(combat, p["combatant_id"])
    actions = (c.stat_block or {}).get("actions") or []
    idx = int(p.get("action_index", -1))
    if not (0 <= idx < len(actions)):
        raise ValueError("acción fuera de rango")
    action = actions[idx]
    text = action.get("text", "")

    m_hit = re.search(r"([+-]?\d+)\s*to hit", text)
    m_dc = re.search(r"DC\s*(\d+)", text, re.IGNORECASE)
    m_dmg = re.search(r"(\d+d\d+(?:\s*[+-]\s*\d+)?)", text)

    ev = {"type": "dice.roll.created", "payload": {
        "combatant": c.name, "action": action.get("name", "?")}}
    if m_hit:
        mod = int(m_hit.group(1))
        r = roll("1d20")
        ev["payload"].update(
            attack_roll=r.total, attack_total=r.total + mod,
            attack_mod=mod)
    if m_dmg:
        expr = m_dmg.group(1).replace(" ", "")
        ev["payload"].update(
            damage_expr=expr, damage_total=roll(expr).total)
    if m_dc:
        ev["payload"]["save_dc"] = int(m_dc.group(1))
    return {"operation_type": "noop", "payload": {}}, [ev]


@op("noop")
def noop(entity, p: dict, ctx):
    """Inversa de operaciones sin estado (tiradas puras)."""
    return {"operation_type": "noop", "payload": {}}, []


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
