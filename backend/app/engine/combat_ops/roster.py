"""Handlers de combate — altas/bajas de combatientes y delegación."""
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
    COMBAT_HANDLERS, op, _char_sheet, _entity_data, _find, op
)

@op("combatant.add")
def combatant_add(combat: Combat, p: dict, ctx):
    """Añade un combatiente. Con content_entity_id copia el stat block
    del bestiario (HP medio, CA, iniciativa = d20 + mod DES)."""
    data = _entity_data(ctx, p.get("content_entity_id"))
    char_hp, char_dex = _char_sheet(ctx, p) \
        if p.get("kind") == "character" else (None, None)
    # Normaliza cualquier schema de fuente (5e-bits, Open5e v1/v2,
    # 5etools, codexMUNDI, dnd-data) al bloque canónico.
    block = statblock.normalize(data) or p.get("stat_block")
    init = p.get("initiative")
    if init is None:
        # un PJ sin stat block tiraba 1d20+0 — su iniciativa real es
        # 1d20 + mod DES de la ficha (como hace initiative_roll)
        init = roll("1d20").total + (
            char_dex if char_dex is not None
            else (block or {}).get("initiative_mod", 0))
    hp_max = (p.get("hp_max") or (char_hp or {}).get("max")
              or (block or {}).get("hp", 1))
    c = Combatant(
        id=uuid.uuid4().hex,
        kind=p.get("kind", "monster" if data else "npc"),
        name=p.get("name") or data.get("name", "?"),
        ref_id=p.get("ref_id") or p.get("content_entity_id"),
        initiative=int(init),
        # el hp.current vivo de la ficha manda sobre un hp_max del
        # payload — antes un payload con hp_max=20 entraba al tracker
        # con 20/20 aunque la ficha estuviera a 7/20
        hp_current=((char_hp or {}).get("current") or hp_max),
        hp_max=hp_max,
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
    # quitar un combatiente ANTERIOR al activo desplazaba el turno:
    # ordered() se recalcula y turn_index apuntaba al siguiente → el
    # que actuaba perdía el turno. Si el retirado era el activo, el
    # índice ya apunta al siguiente — correcto sin ajuste.
    orig_turn = combat.turn_index
    order = combat.ordered()
    if order:
        active_pos = combat.turn_index % len(order)
        rem_pos = next((i for i, x in enumerate(order)
                        if x.id == c.id), None)
        if rem_pos is not None and rem_pos < active_pos:
            combat.turn_index -= 1
    combat.combatants.remove(c)
    return {"operation_type": "combatant.add_raw",
            "payload": {"combatant": c.model_dump(), "index": idx,
                        "turn_index": orig_turn}}, []


@op("combatant.delegate")
def combatant_delegate(combat: Combat, p: dict, ctx):
    """El DM cede un NPC/monstruo a un jugador (`player_uid`, None lo
    retira). El delegado puede mover su token y atacar con él como
    si fuera su PJ — guard de auth en api/operations."""
    c = _find(combat, p["combatant_id"])
    prev = c.delegated_to
    c.delegated_to = p.get("player_uid")
    return {"operation_type": "combatant.delegate",
            "payload": {"combatant_id": c.id, "player_uid": prev}}, [
            {"type": "combatant.delegated",
             "payload": {"combatant": c.name,
                         "player_uid": c.delegated_to}}]


@op("combatant.add_raw")
def combatant_add_raw(combat: Combat, p: dict, ctx):
    """Undo helper: reinserta un combatiente con su id original."""
    c = Combatant(**p["combatant"])
    combat.combatants.insert(int(p.get("index", len(combat.combatants))), c)
    # remove ajustó turn_index; restaurarlo deshace ese ajuste también
    if p.get("turn_index") is not None:
        combat.turn_index = int(p["turn_index"])
    return {"operation_type": "combatant.remove",
            "payload": {"combatant_id": c.id}}, []
