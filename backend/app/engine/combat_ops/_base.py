"""Handlers de combate — núcleo compartido.

    handler(combat, payload, ctx) -> (inverse_op, [event_payloads])

ctx.content_db() da acceso a la DB de reglas para que 'combatant.add'
copie el stat block por entity id.

Split de combat_ops.py (AU-22): registro (COMBAT_HANDLERS,
apply_combat_operation), helpers compartidos y sincronía con la ficha
(_sync_character); los handlers viven en turns/roster/vitals/rolls."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable

from ...domain import statblock
from ...domain.combat import Combat, Combatant, hp_state
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll

Handler = Callable[[Combat, dict, object], tuple[dict, list[dict]]]
COMBAT_HANDLERS: dict[str, Handler] = {}


def op(name: str):
    def wrap(fn: Handler) -> Handler:
        COMBAT_HANDLERS[name] = fn
        return fn
    return wrap


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
    """Snapshot completo del estado vital: curar/dañar también toca
    death_saves y las condiciones muerto/estable — la inversa debe
    restaurarlo todo o un undo dejaría el estado inconsistente."""
    return {"operation_type": "combatant.hp.set",
            "payload": {"combatant_id": c.id, "current": c.hp_current,
                        "temp": c.hp_temp,
                        "conditions": list(c.conditions),
                        "death_saves": dict(c.death_saves)}}


def _char_ref(c: Combatant) -> dict:
    """Marca los eventos de combate que tocan una ficha de personaje:
    la UI de la hoja filtra por aggregate_id=character_id para
    recargar cuando el DM daña/cura al PJ desde el tablero."""
    if c.kind == "character" and c.ref_id:
        return {"character_id": c.ref_id}
    return {}


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
    from ...domain.character import Character
    row = conn.execute("SELECT data, version FROM characters"
                       " WHERE id = ?", (c.ref_id,)).fetchone()
    if row is None:
        return
    ch = Character(**json.loads(row["data"]))
    ch.hp.current = c.hp_current
    ch.hp.temp = c.hp_temp
    # solo el estado vital se sincroniza: el tracker no conoce las
    # condiciones persistentes de la ficha (agotamiento, envenenado
    # de un efecto largo…) — copiar la lista entera las borraba y
    # dejaba condition_stacks huérfano
    for cond in ("muerto", "dead", "estable"):
        if cond in c.conditions and cond not in ch.conditions:
            ch.conditions.append(cond)
        elif cond not in c.conditions and cond in ch.conditions:
            ch.conditions.remove(cond)
    ch.death_saves = dict(c.death_saves)
    # el bump es imprescindible: sin él una op posterior de la ficha
    # (con la versión que tenía abierta) pisaba el HP del combate sin
    # conflicto — lost update silencioso entre tablero y hoja.
    # La guardia de versión evita pisar una escritura concurrente.
    cur = conn.execute(
        "UPDATE characters SET data = ?, version = ?, updated_at = ?"
        " WHERE id = ? AND version = ?",
        (ch.model_dump_json(), row["version"] + 1,
         datetime.now(timezone.utc).isoformat(),
         c.ref_id, row["version"]))
    if cur.rowcount == 0:
        raise ValueError("la ficha vinculada cambió durante la op de"
                         " combate — reintenta")


def _load_char(ctx, c: Combatant):
    """Ficha vinculada al combatiente-PJ, o None (monstruos/tokens
    sueltos). Punto único de lectura — _spend_heroic, concentración,
    shove_grapple la usan."""
    if c.kind != "character" or not c.ref_id:
        return None
    try:
        conn = ctx.state_db()
    except AttributeError:
        return None
    if conn is None:
        return None
    row = conn.execute("SELECT data FROM characters WHERE id = ?",
                       (c.ref_id,)).fetchone()
    if row is None:
        return None
    from ...domain.character import Character
    return Character(**json.loads(row["data"]))


def _spend_heroic(ctx, c: Combatant) -> bool:
    """Gasta la inspiración heroica de la ficha vinculada (2024).
    True si se gastó; False si el combatiente no es ficha o no la
    tiene. Mismo patrón que _sync_character (guardia de versión);
    el consumo queda fuera de la inversa del combate — como los
    triggers de la ficha (_char_trigger)."""
    if c.kind != "character" or not c.ref_id:
        return False
    try:
        conn = ctx.state_db()
    except AttributeError:
        return False
    if conn is None:
        return False
    row = conn.execute("SELECT data, version FROM characters"
                       " WHERE id = ?", (c.ref_id,)).fetchone()
    if row is None:
        return False
    from ...domain.character import Character
    ch = Character(**json.loads(row["data"]))
    if not ch.inspiration:
        return False
    ch.inspiration = False
    cur = conn.execute(
        "UPDATE characters SET data = ?, version = ?, updated_at = ?"
        " WHERE id = ? AND version = ?",
        (ch.model_dump_json(), row["version"] + 1,
         datetime.now(timezone.utc).isoformat(),
         c.ref_id, row["version"]))
    if cur.rowcount == 0:
        raise ValueError("la ficha vinculada cambió durante la op de"
                         " combate — reintenta")
    return True


def _char_trigger(ctx, c: Combatant, trigger, extra: dict | None = None):
    """Dispara los Effect de la ficha vinculada con este trigger y
    persiste (recursos/condiciones mutados por _trigger_op).
    Sin ficha/DB = no-op. Devuelve True si el estado cambió."""
    if c.kind != "character" or not c.ref_id:
        return False
    try:
        conn = ctx.state_db()
    except AttributeError:
        return False
    if conn is None:
        return False
    row = conn.execute("SELECT data, version FROM characters"
                       " WHERE id = ?", (c.ref_id,)).fetchone()
    if row is None:
        return False
    from ...domain.character import Character
    from ..engine import apply_triggered
    ch = Character(**json.loads(row["data"]))
    snap = ch.model_dump_json()
    apply_triggered(ch, trigger, extra)
    if ch.model_dump_json() == snap:
        return False                          # nada mutó → no bump
    cur = conn.execute(
        "UPDATE characters SET data = ?, version = ?, updated_at = ?"
        " WHERE id = ? AND version = ?",
        (ch.model_dump_json(), row["version"] + 1,
         datetime.now(timezone.utc).isoformat(),
         c.ref_id, row["version"]))
    if cur.rowcount == 0:
        raise ValueError("la ficha vinculada cambió durante la op de"
                         " combate — reintenta")
    return True


def _entity_data(ctx, entity_id: str | None) -> dict:
    """JSON de la entidad de contenido (bestiario) — {} si falta."""
    if not entity_id:
        return {}
    row = ctx.content_db().execute(
        "SELECT data FROM content_entities WHERE id = ?",
        (entity_id,)).fetchone()
    return json.loads(row["data"]) if row else {}


def _char_sheet(ctx, p: dict) -> tuple[dict | None, int | None]:
    """(hp, mod DES) del personaje referenciado (kind=character) —
    (None, None) si no existe o el dato no es recuperable."""
    if not p.get("ref_id"):
        return None, None
    try:
        srow = ctx.state_db().execute(
            "SELECT data FROM characters WHERE id = ?",
            (p["ref_id"],)).fetchone()
        if not srow:
            return None, None
        d = json.loads(srow["data"])
        ab = d.get("abilities") or {}
        score = ab.get("dex") or ab.get("dexterity")
        dex_mod = (score - 10) // 2 if isinstance(score, int) else None
        return d.get("hp"), dex_mod
    except (AttributeError, Exception):
        return None, None


def _char_typed_amount(ctx, c: Combatant, amount: int, dtype: str):
    """(daño final, nota) usando los Effect declarativos de la ficha
    del PJ — la misma regla que character.hp.damage en la hoja."""
    try:
        conn = ctx.state_db()
    except AttributeError:
        return _typed_amount(c, amount, dtype)
    if conn is None:
        return _typed_amount(c, amount, dtype)
    row = conn.execute("SELECT data FROM characters WHERE id = ?",
                       (c.ref_id,)).fetchone()
    if row is None:
        return _typed_amount(c, amount, dtype)
    from ...domain.character import Character
    from ..ops import _damage_mult
    ch = Character(**json.loads(row["data"]))
    mult, applied = _damage_mult(ch, dtype)
    amount = int(amount * mult)
    return amount, "; ".join(applied) if applied else None


def _typed_amount(c: Combatant, amount: int, dtype: str):
    """(daño final, nota) — res/imm/vul del stat block si lo hay."""
    note = None
    if dtype and c.stat_block:
        res = [str(x).lower() for x in c.stat_block.get("resistances", [])]
        imm = [str(x).lower() for x in c.stat_block.get("immunities", [])]
        vul = [str(x).lower() for x in
               c.stat_block.get("vulnerabilities", [])]
        if any(dtype in x for x in imm):
            amount, note = 0, f"inmune a {dtype}"
        elif any(dtype in x for x in res):
            amount, note = amount // 2, f"resistente a {dtype} (÷2)"
        elif any(dtype in x for x in vul):
            amount, note = amount * 2, f"vulnerable a {dtype} (×2)"
    return amount, note


def _apply_dmg(c: Combatant, amount: int, note: str | None) -> dict:
    """Aplica daño al combatiente (absorción por temp + reglas de
    muerte para PJ) y devuelve el payload del evento hp.changed."""
    absorbed = min(c.hp_temp, amount)
    c.hp_temp -= absorbed
    dmg = amount - absorbed
    was_zero = c.hp_current == 0
    overflow = dmg - c.hp_current    # daño que sobra tras llegar a 0
    c.hp_current = max(0, c.hp_current - dmg)
    payload = {"combatant": c.name, "amount": amount,
               "state": hp_state(c), **_char_ref(c),
               **({"note": note} if note else {})}
    _death_rules_cbt(c, dmg, was_zero, overflow, payload)
    return payload


def _death_rules_cbt(c: Combatant, dmg: int, was_zero: bool,
                     overflow: int, payload: dict) -> None:
    """Reglas de muerte SRD para combatientes PJ (misma lógica que
    ops._death_rules de la ficha): daño masivo (resto ≥ PG máx) mata
    al instante; un golpe estando a 0 PG es un fallo de salvación."""
    if c.kind != "character" or dmg <= 0 or c.hp_max <= 0:
        return
    cs = rules()["combat"]
    if overflow >= c.hp_max:
        c.death_saves["fail"] = cs["death_save_fails"]
        if "muerto" not in c.conditions:
            c.conditions.append("muerto")
        payload["instant_death"] = True
    elif was_zero:
        c.death_saves["fail"] = min(
            cs["death_save_fails"], c.death_saves["fail"] + 1)
        payload["death_fail_at_zero"] = c.death_saves["fail"]
        if c.death_saves["fail"] >= cs["death_save_fails"] and \
                "muerto" not in c.conditions:
            c.conditions.append("muerto")
            payload["instant_death"] = True


SKILL_ABILITY = {
    "athletics": "str", "acrobatics": "dex", "sleight of hand": "dex",
    "stealth": "dex", "arcana": "int", "history": "int",
    "investigation": "int", "nature": "int", "religion": "int",
    "animal handling": "wis", "insight": "wis", "medicine": "wis",
    "perception": "wis", "survival": "wis", "deception": "cha",
    "intimidation": "cha", "performance": "cha", "persuasion": "cha",
}


def _weapon_attack(char, item_name: str, ctx):
    """(item, mod, hit_bonus, dmg_dice, damage_type) del arma de la
    ficha — misma lógica que character.attack: finesse/ranged → DES,
    resto → FUE; prof siempre suma al impacto."""
    from ..ops import _is_finesse, _item_damage
    item = next((i for i in char.inventory
                 if i.name.lower() == item_name.lower()), None)
    if item is None:
        raise ValueError("arma no en inventario")
    w = {}
    if item.source_id:
        r = ctx.content_db().execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (item.source_id,)).fetchone()
        w = json.loads(r["data"]) if r else {}
    mod = char.abilities.modifier(
        "dex" if _is_finesse(w) else "str")
    dtype = (((w.get("damage") or {}).get("damage_type") or {})
             .get("index") or w.get("dmgType") or None)
    return (item, mod, char.proficiency_bonus + mod,
            _item_damage(w) or "1d4", dtype, w)


def _double_dice(expr: str) -> str:
    """'2d6+3' → '4d6+3': crítico dobla los dados, no el bono."""
    import re
    return re.sub(r"(\d+)d(\d+)",
                  lambda m: f"{int(m.group(1)) * 2}d{m.group(2)}",
                  expr)


def apply_combat_operation(combat: Combat, operation_type: str,
                           payload: dict, ctx) -> tuple[dict, list[dict]]:
    handler = COMBAT_HANDLERS.get(operation_type)
    if handler is None:
        raise KeyError(f"unknown combat operation: {operation_type}")
    return handler(combat, payload, ctx)
