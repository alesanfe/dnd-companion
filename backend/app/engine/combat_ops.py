"""Combat operation handlers — same reversible-op contract as
engine/ops.py but operating on a Combat aggregate.

    handler(combat, payload, ctx) -> (inverse_op, [event_payloads])

ctx.content_db() gives read access to the rules DB so 'combatant.add'
can copy a monster stat block by content entity id.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable

from ..domain import statblock
from ..domain.combat import Combat, Combatant, hp_state
from ..rules import rules
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
    from ..domain.character import Character
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


@op("combat.next_turn")
def next_turn(combat: Combat, p: dict, ctx):
    order = combat.ordered()
    if not order:
        raise ValueError("no hay combatientes")
    # snapshot: al cerrar ronda expiran condiciones — prev_turn no
    # podría restaurarlas (duración y lista ya mutadas)
    inv = {"operation_type": "combat.state.restore",
           "payload": {"data": combat.model_dump()}}
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


@op("combatant.add")
def combatant_add(combat: Combat, p: dict, ctx):
    """Añade un combatiente. Con content_entity_id copia el stat block
    del bestiario (HP medio, CA, iniciativa = d20 + mod DES)."""
    data = _entity_data(ctx, p.get("content_entity_id"))
    char_hp = _char_hp(ctx, p) if p.get("kind") == "character" else None
    # Normaliza cualquier schema de fuente (5e-bits, Open5e v1/v2,
    # 5etools, codexMUNDI, dnd-data) al bloque canónico.
    block = statblock.normalize(data) or p.get("stat_block")
    init = p.get("initiative")
    if init is None:
        init = roll("1d20").total + (
            (block or {}).get("initiative_mod", 0))
    hp_max = (p.get("hp_max") or (char_hp or {}).get("max")
              or (block or {}).get("hp", 1))
    c = Combatant(
        id=uuid.uuid4().hex,
        kind=p.get("kind", "monster" if data else "npc"),
        name=p.get("name") or data.get("name", "?"),
        ref_id=p.get("ref_id") or p.get("content_entity_id"),
        initiative=int(init),
        hp_current=(p.get("hp_max") or (char_hp or {}).get("current")
                    or hp_max),
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


def _entity_data(ctx, entity_id: str | None) -> dict:
    """JSON de la entidad de contenido (bestiario) — {} si falta."""
    if not entity_id:
        return {}
    row = ctx.content_db().execute(
        "SELECT data FROM content_entities WHERE id = ?",
        (entity_id,)).fetchone()
    return json.loads(row["data"]) if row else {}


def _char_hp(ctx, p: dict):
    """PG del personaje referenciado (kind=character) — None si no
    existe o el dato no es recuperable."""
    if not p.get("ref_id"):
        return None
    try:
        srow = ctx.state_db().execute(
            "SELECT data FROM characters WHERE id = ?",
            (p["ref_id"],)).fetchone()
        return json.loads(srow["data"]).get("hp") if srow else None
    except (AttributeError, Exception):
        return None


@op("combatant.remove")
def combatant_remove(combat: Combat, p: dict, ctx):
    c = _find(combat, p["combatant_id"])
    idx = combat.combatants.index(c)
    combat.combatants.remove(c)
    return {"operation_type": "combatant.add_raw",
            "payload": {"combatant": c.model_dump(), "index": idx}}, []


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
    return {"operation_type": "combatant.remove",
            "payload": {"combatant_id": c.id}}, []


@op("combatant.damage")
def combatant_damage(combat: Combat, p: dict, ctx):
    """Daño con tipo opcional: aplica resistencia (÷2), inmunidad (0)
    o vulnerabilidad (×2) del stat block si lo hay."""
    c = _find(combat, p["combatant_id"])
    inv = _hp_inverse(c)
    amount, note = _typed_amount(c, max(0, int(p["amount"])),
                               (p.get("damage_type") or "")
                               .strip().lower())
    payload = _apply_dmg(c, amount, note)
    _sync_character(c, ctx)
    return inv, [{"type": "character.hp.changed",
                  "payload": payload}]


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
        from ..domain.xp import cr_to_xp
        xp = cr_to_xp(c.stat_block.get("cr", 0))
        if xp:
            payload["xp_suggestion"] = xp
    return inv, [{"type": "character.condition.applied",
                  "payload": payload}]


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
    from ..domain.conditions import mods_for
    adv, dis, fail, notes = mods_for(c.conditions, f"save:{ability}")
    if fail:
        return {"operation_type": "noop", "payload": {}}, [
            {"type": "dice.roll.created",
             "payload": {"combatant": c.name, "save": ability,
                         "auto_fail": True, "notes": notes}}]
    r = roll("1d20adv" if adv and not dis else
             "1d20dis" if dis and not adv else "1d20")
    total = r.total + total_mod
    return {"operation_type": "noop", "payload": {}}, [
        {"type": "dice.roll.created",
         "payload": {"combatant": c.name, "save": ability,
                     "roll": r.total, "total": total,
                     **({"notes": notes} if notes else {})}}]


@op("combatant.action.roll")
def combatant_action_roll(combat: Combat, p: dict, ctx):
    """Rueda una acción del stat block del combatiente: parsea el texto
    normalizado buscando 'to hit' (+N) y dados de daño (NdM±K), y tira
    ambos. Acciones de salvación emiten la CD detectada."""
    import re
    c = _find(combat, p["combatant_id"])
    from ..domain.conditions import is_incapacitated, mods_for
    incap = is_incapacitated(c.conditions)
    if incap:
        raise ValueError(f"{c.name} está incapacitado ({incap})")
    actions = (c.stat_block or {}).get("actions") or []
    idx = int(p.get("action_index", -1))
    if not (0 <= idx < len(actions)):
        raise ValueError("acción fuera de rango")
    action = actions[idx]
    text = action.get("text", "")

    m_hit = re.search(r"([+-]?\d+)\s*to hit", text)
    m_dc = re.search(r"DC\s*(\d+)", text, re.IGNORECASE)
    m_dmg = re.search(r"(\d+d\d+(?:\s*[+-]\s*\d+)?)", text)

    adv, dis, _fail, notes = mods_for(c.conditions, "attack")
    # mode del cliente: el mapa pide desventaja cuando el objetivo
    # queda más allá del alcance normal del arma a distancia
    mode = str(p.get("mode", "normal"))
    if mode == "adv":
        adv = True
    elif mode == "dis":
        dis = True
    ev = {"type": "dice.roll.created", "payload": {
        "combatant": c.name, "action": action.get("name", "?"),
        **({"notes": notes} if notes else {})}}
    if m_hit:
        mod = int(m_hit.group(1))
        r = roll("1d20adv" if adv and not dis else
                 "1d20dis" if dis and not adv else "1d20")
        ev["payload"].update(
            attack_roll=r.total, attack_total=r.total + mod,
            attack_mod=mod)
    if m_dmg:
        expr = m_dmg.group(1).replace(" ", "")
        ev["payload"].update(
            damage_expr=expr, damage_total=roll(expr).total)
    if m_dc:
        ev["payload"]["save_dc"] = int(m_dc.group(1))
    # "Recharge 5–6"/"Recharge 6": tira 1d6, la acción vuelve si ≥X
    m_rech = re.search(r"[Rr]echarge\s*(\d+)", text)
    if m_rech:
        threshold = int(m_rech.group(1))
        rr = roll("1d6")
        ev["payload"].update(recharge_roll=rr.total,
                             recharge_needed=threshold,
                             recharges=rr.total >= threshold)
    return {"operation_type": "noop", "payload": {}}, [ev]


@op("combatant.check")
def combatant_check(combat: Combat, p: dict, ctx):
    """Tirada de habilidad del combatiente: total de stat_block.skills
    si existe (p.ej. Perception +12), si no mod de habilidad ligada."""
    c = _find(combat, p["combatant_id"])
    # normaliza 'sleight-of-hand' ≡ 'sleight of hand' — los schemas
    # de contenido usan ambas grafías
    skill = p["skill"].strip().lower().replace("-", " ")
    block = c.stat_block or {}
    skills = block.get("skills") or {}
    total_mod = skills.get(skill)
    if total_mod is None:
        total_mod = skills.get(skill.replace(" ", "-"))
    if total_mod is None:
        ability = SKILL_ABILITY.get(skill, "int")
        total_mod = (block.get("abilities") or {}).get(ability, 10)
        total_mod = (total_mod - 10) // 2
    from ..domain.conditions import mods_for
    adv, dis, _fail, notes = mods_for(c.conditions, "check")
    r = roll("1d20adv" if adv and not dis else
             "1d20dis" if dis and not adv else "1d20")
    return {"operation_type": "noop", "payload": {}}, [
        {"type": "dice.roll.created",
         "payload": {"combatant": c.name, "skill": skill,
                     "roll": r.total, "total": r.total + total_mod,
                     "mod": total_mod,
                     **({"notes": notes} if notes else {})}}]


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
    from .ops import _item_damage
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
    props = [p.get("index") for p in w.get("properties", [])]
    mod = char.abilities.modifier(
        "dex" if "finesse" in props or "ranged" in
        str(w.get("weapon_range", "")).lower() else "str")
    dtype = (((w.get("damage") or {}).get("damage_type") or {})
             .get("index") or w.get("dmgType") or None)
    return (item, mod, char.proficiency_bonus + mod,
            _item_damage(w) or "1d4", dtype)


def _double_dice(expr: str) -> str:
    """'2d6+3' → '4d6+3': crítico dobla los dados, no el bono."""
    import re
    return re.sub(r"(\d+)d(\d+)",
                  lambda m: f"{int(m.group(1)) * 2}d{m.group(2)}",
                  expr)


@op("combat.attack")
def combat_attack(combat: Combat, p: dict, ctx):
    """Un PJ ataca a otro combatiente: el servidor tira impacto con el
    arma de SU ficha (prof + mod + condiciones) contra la CA del
    objetivo — que nunca sale del servidor en la vista de jugador —
    y aplica el daño si impacta (res/imm/vul del stat block incluida).
    Reversible: restaura el estado vital del objetivo."""
    atk = _find(combat, p["attacker_combatant_id"])
    tgt = _find(combat, p["target_combatant_id"])
    if atk.id == tgt.id:
        raise ValueError("el atacante no puede ser su objetivo")
    if atk.kind != "character" or not atk.ref_id:
        raise ValueError("combat.attack lo ejecuta un personaje")
    from ..domain.conditions import is_incapacitated, mods_for
    incap = is_incapacitated(atk.conditions)
    if incap:
        raise ValueError(f"{atk.name} está incapacitado ({incap})")
    row = ctx.state_db().execute(
        "SELECT data FROM characters WHERE id = ?",
        (atk.ref_id,)).fetchone()
    if row is None:
        raise ValueError("ficha del atacante no encontrada")
    from ..domain.character import Character
    char = Character(**json.loads(row["data"]))
    item, mod, hit_bonus, dmg_dice, dtype = _weapon_attack(
        char, str(p.get("item_name", "")), ctx)
    dtype = (p.get("damage_type") or dtype or "")
    # mismas reglas de condición que /character/attack + modo manual
    adv, dis, fail, notes = mods_for(atk.conditions, "attack")
    mode = str(p.get("mode", "normal"))
    if mode == "adv":
        adv = True
    elif mode == "dis":
        dis = True
    hit = roll("1d20adv" if adv and not dis else
               "1d20dis" if dis and not adv else "1d20")
    hit_total = hit.total + hit_bonus
    crit = bool(hit.rolls) and max(hit.rolls) >= \
        rules()["combat"]["death_save_crit_success"]
    ac = tgt.ac or (tgt.stat_block or {}).get("ac", 10)
    hits = not fail and (crit or hit_total >= ac)
    ev = {"type": "dice.roll.created", "payload": {
        "combatant": atk.name, "attack": item.name, "target": tgt.name,
        "roll": hit.total, "total": hit_total, "hits": hits,
        **({"crit": True} if crit else {}),
        **({"notes": notes} if notes else {})}}
    if not hits:
        return {"operation_type": "noop", "payload": {}}, [ev]
    expr = _double_dice(dmg_dice) if crit else dmg_dice
    dmg_total = roll(f"{expr}{mod:+d}").total
    inv = _hp_inverse(tgt)
    amount, note = _typed_amount(tgt, dmg_total, dtype.strip().lower())
    dmg_payload = _apply_dmg(tgt, amount, note)
    ev["payload"]["damage"] = amount
    _sync_character(tgt, ctx)
    return inv, [ev, {"type": "character.hp.changed",
                      "payload": dmg_payload}]


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


def apply_combat_operation(combat: Combat, operation_type: str,
                           payload: dict, ctx) -> tuple[dict, list[dict]]:
    handler = COMBAT_HANDLERS.get(operation_type)
    if handler is None:
        raise KeyError(f"unknown combat operation: {operation_type}")
    return handler(combat, payload, ctx)
