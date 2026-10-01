"""Handlers magic: conjuros: preparar/lanzar, libro, pacto, concentración."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ...domain.character import Character, Narrative
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll
from ._base import (
    HANDLERS,
    _cast_level,
    _content,
    _needs_conc,
    _restore_inverse,
    _slots_for,
    _spell_cast_payload,
    op,
)

@op("character.spell_slot.use")
def slot_use(char: Character, p: dict, ctx):
    lvl = str(p["level"])
    count = int(p.get("count", 1))
    pool = _slots_for(char, lvl, p.get("pool"))
    slot = pool.get(lvl)
    # sin setdefault: usar un nivel inexistente creaba un slot
    # fantasma {total:0} y una inversa con count=0 que luego
    # explotaba en restore ("nada que recuperar")
    if not slot or slot["total"] - slot["used"] <= 0:
        raise ValueError("no quedan espacios de conjuro de ese nivel")
    # pedir más de lo disponible era un clamp silencioso: el usuario
    # veía "gasté 3 de 2" — rechazar como toda validación del motor
    if count > slot["total"] - slot["used"]:
        raise ValueError(
            f"quedan {slot['total'] - slot['used']} espacios de ese nivel")
    # la inversa guarda el pool RESUELTO — si pact_slots cambia entre
    # la op y su undo, re-resolver 'None' podría caer en otro pool
    resolved_pool = "pact" if pool is char.pact_slots else "regular"
    inv = {"operation_type": "character.spell_slot.restore",
           "payload": {"level": int(lvl), "pool": resolved_pool,
                       "count": count}}
    slot["used"] += count
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"spell_slot": lvl, "used": slot["used"],
                              "pool": "pact" if pool is char.pact_slots
                                      else "regular"}}]


@op("character.spell_slot.restore")
def slot_restore(char: Character, p: dict, ctx):
    """Recupera `count` espacios de conjuro gastados (recuperación
    arcana, descanso, corrección manual). Reversible."""
    lvl = str(p["level"])
    count = int(p.get("count", 1))
    pool = _slots_for(char, lvl, p.get("pool"))
    slot = pool.get(lvl)
    if not slot or slot["used"] <= 0:
        raise ValueError("nada que recuperar")
    inv = {"operation_type": "character.spell_slot.use",
           "payload": {"level": int(lvl),
                       "pool": "pact" if pool is char.pact_slots
                               else "regular",
                       "count": min(count, slot["used"])}}
    slot["used"] = max(0, slot["used"] - count)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"spell_slot": lvl, "used": slot["used"]}}]


@op("character.spell.prepare")
def spell_prepare(char: Character, p: dict, ctx):
    """Marca un conjuro conocido como preparado (clases que
    preparan tras descanso largo). Los trucos no se preparan."""
    sid = p["spell_id"]
    if sid not in char.spells_known:
        raise ValueError("conjuro desconocido")
    sp = _content(ctx, sid) or {}
    lvl = int(sp.get("level")
              or (sp.get("properties") or {}).get("Level") or 0)
    if lvl == 0:
        raise ValueError("los trucos siempre están listos — no se preparan")
    if sid in char.spells_prepared:
        raise ValueError("conjuro ya preparado")
    char.spells_prepared.append(sid)
    return {"operation_type": "character.spell.unprepare",
            "payload": {"spell_id": sid}}, [
        {"type": "resource.usage.changed",
         "payload": {"spell_prepared": sid}}]


@op("character.spell.unprepare")
def spell_unprepare(char: Character, p: dict, ctx):
    sid = p["spell_id"]
    if sid not in char.spells_prepared:
        raise ValueError("conjuro no preparado")
    char.spells_prepared.remove(sid)
    return {"operation_type": "character.spell.prepare",
            "payload": {"spell_id": sid}}, [
        {"type": "resource.usage.changed",
         "payload": {"spell_unprepared": sid}}]


@op("character.spell.cast")
def spell_cast(char: Character, p: dict, ctx):
    """Lanza un conjuro: consume espacio (si level>0), marca
    concentración si el conjuro la requiere. Reversible via snapshot."""
    spell_id = p["spell_id"]
    sp = _content(ctx, spell_id) or {}
    level, spell_level = _cast_level(sp, int(p.get("level", 0)))
    # si el PJ tiene lista de conjuros conocidos, se lanza de ahí
    # (la lista vacía = permisivo: fuentes externas, dm fiat…)
    if char.spells_known and spell_id not in char.spells_known:
        raise ValueError("conjuro no conocido")
    # clases que preparan: solo se lanzan conjuros preparados
    # (la lista vacía = lanzador "conocido" como brujo/hechicero)
    if (spell_level > 0 and char.spells_prepared
            and spell_id not in char.spells_prepared):
        raise ValueError("conjuro no preparado — prepáralo tras un "
                         "descanso largo")
    before = char.model_dump()
    if level > 0:
        pool = _slots_for(char, str(level), p.get("pool"))
        # sin setdefault: lanzar sin espacios de ese nivel no debe
        # crear un slot fantasma {total:0,used:0} en la ficha
        slot = pool.get(str(level))
        if not slot or slot["used"] >= slot["total"]:
            raise ValueError(f"sin espacios de nivel {level}")
        slot["used"] += 1
    if _needs_conc(sp):
        char.concentrating_on = sp.get("name", spell_id)

    return _restore_inverse(before), [
        {"type": "resource.usage.changed",
         "payload": _spell_cast_payload(char, sp, spell_id, level,
                                        spell_level, ctx)}]


@op("character.spellbook.add")
def spellbook_add(char: Character, p: dict, ctx):
    """Añade un conjuro a un libro organizativo (dominio, dones…).
    Crea el libro si no existe. Reversible."""
    name = p["name"].strip()
    sid = p["spell_id"]
    book = char.spellbooks.setdefault(name, [])
    if sid in book:
        raise ValueError("conjuro ya en el libro")
    book.append(sid)
    return {"operation_type": "character.spellbook.remove",
            "payload": {"name": name, "spell_id": sid}}, [
        {"type": "resource.usage.changed",
         "payload": {"spellbook": name, "added": sid}}]


@op("character.spellbook.remove")
def spellbook_remove(char: Character, p: dict, ctx):
    name = p["name"]
    book = char.spellbooks.get(name)
    sid = p["spell_id"]
    if not book or sid not in book:
        raise ValueError("conjuro no está en el libro")
    book.remove(sid)
    if not book:
        del char.spellbooks[name]
    return {"operation_type": "character.spellbook.add",
            "payload": {"name": name, "spell_id": sid}}, [
        {"type": "resource.usage.changed",
         "payload": {"spellbook": name, "removed": sid}}]


@op("character.spellbook.delete")
def spellbook_delete(char: Character, p: dict, ctx):
    name = p["name"]
    book = char.spellbooks.pop(name, None)
    if book is None:
        raise ValueError("libro no encontrado")
    inv = {"operation_type": "character.spellbook.restore",
           "payload": {"name": name, "spells": book}}
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"spellbook_deleted": name}}]


@op("character.spellbook.restore")
def spellbook_restore(char: Character, p: dict, ctx):
    name = p["name"]
    prev = char.spellbooks.get(name, [])
    char.spellbooks[name] = list(p.get("spells") or [])
    return {"operation_type": "character.spellbook.restore",
            "payload": {"name": name, "spells": prev}}, [
        {"type": "resource.usage.changed",
         "payload": {"spellbook_restored": name}}]


@op("character.spell.learn")
def spell_learn(char: Character, p: dict, ctx):
    sid = p["spell_id"]
    if sid in char.spells_known:
        raise ValueError("conjuro ya conocido")
    char.spells_known.append(sid)
    # restauración desde undo de forget conserva "preparado"
    if p.get("prepared") and sid not in char.spells_prepared:
        char.spells_prepared.append(sid)
    return {"operation_type": "character.spell.forget",
            "payload": {"spell_id": sid}}, [
        {"type": "resource.usage.changed",
         "payload": {"spell_learned": sid}}]


@op("character.spell.forget")
def spell_forget(char: Character, p: dict, ctx):
    sid = p["spell_id"]
    if sid not in char.spells_known:
        raise ValueError("conjuro no conocido")
    was_prepared = sid in char.spells_prepared
    char.spells_known.remove(sid)
    if was_prepared:
        char.spells_prepared.remove(sid)
    # deshacer restaura también el estado "preparado"
    return {"operation_type": "character.spell.learn",
            "payload": {"spell_id": sid,
                        **({"prepared": True}
                           if was_prepared else {})}}, []


@op("character.craft")
def craft(char: Character, p: dict, ctx):
    """Fabricación/downtime: consume ingredientes del inventario y
    produce el objeto. Reversible via snapshot."""
    inputs = p.get("inputs", [])
    output = p.get("output", {})
    if not inputs or not output.get("name"):
        raise ValueError("craft requiere inputs y output.name")
    for need in inputs:
        have = next((i for i in char.inventory
                     if i.name == need["name"]), None)
        if not have or have.quantity < int(need.get("quantity", 1)):
            raise ValueError(f"falta ingrediente: {need['name']}")
    before = char.model_dump()
    for need in inputs:
        for _ in range(int(need.get("quantity", 1))):
            item = next(i for i in char.inventory
                        if i.name == need["name"])
            item.quantity -= 1
            if item.quantity <= 0:
                char.inventory.remove(item)
    from ...domain.character import InventoryItem
    import uuid as _uuid
    char.inventory.append(InventoryItem(
        id=_uuid.uuid4().hex, name=output["name"],
        quantity=int(output.get("quantity", 1))))
    return _restore_inverse(before), [
        {"type": "inventory.item.transferred",
         "payload": {"crafted": output["name"],
                     "consumed": [i["name"] for i in inputs]}}]
