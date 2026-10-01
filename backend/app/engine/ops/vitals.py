"""Handlers vitals: PG, salvaciones de muerte, condiciones, descansos, recursos/ticks — estado vital de la ficha."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ...domain.character import Character, Narrative
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll
from ._base import (
    HANDLERS,
    _damage_mult,
    _death_rules,
    _immune_to,
    _restore_inverse,
    _restore_resources,
    _run_trigger,
    _set_inverse,
    _shrink_condition,
    op,
)

@op("character.hp.damage")
def hp_damage(char: Character, p: dict, ctx):
    inv = _set_inverse(char)
    amount = max(0, int(p["amount"]))
    # resistencia/vulnerabilidad/inmunidad declarativas por tipo de daño
    dtype = str(p.get("type", "")).lower()
    # ops mutantes "antes del daño" (p.ej. consumir carga para reducir)
    _run_trigger(char, Trigger.BEFORE_DAMAGE,
                 {"damage": {"amount": amount, "type": dtype}})
    mult, applied = _damage_mult(char, dtype)
    amount = int(amount * mult)
    absorbed = min(char.hp.temp, amount)
    char.hp.temp -= absorbed
    dmg = amount - absorbed
    was_zero = char.hp.current == 0
    overflow = dmg - char.hp.current      # daño que sobra tras llegar a 0
    char.hp.current = max(0, char.hp.current - dmg)
    payload = {"amount": amount, "temp_absorbed": absorbed,
               "current": char.hp.current}
    _death_rules(char, dmg, was_zero, overflow, payload)
    if applied:
        payload["damage_effects"] = applied
        payload["damage_type"] = dtype
    if char.concentrating_on:
        # recibir daño exige tirada de CON: CD máx(floor, daño/2)
        floor = rules()["combat"]["concentration_dc_floor"]
        payload["concentration_check"] = True
        payload["concentration_dc"] = max(floor, amount // 2)
        payload["spell"] = char.concentrating_on
    # "al recibir daño…" (furor, represalia) — ops mutantes tras aplicar
    _run_trigger(char, Trigger.AFTER_DAMAGE,
                 {"damage": {"amount": amount, "type": dtype,
                             "current": char.hp.current}})
    return inv, [{"type": "character.hp.changed", "payload": payload}]


@op("character.death_save")
def death_save(char: Character, p: dict, ctx):
    """Salvación de muerte (a 0 PG). El cliente pasa 'roll' (1d20 ya
    tirado): ≥10 éxito, <10 fallo, 1 = doble fallo, 20 = se recupera
    con 1 PG. Tres éxitos estabiliza, tres fallos es la muerte."""
    if char.hp.current > 0:
        raise ValueError("el personaje no está a 0 PG")
    inv = _set_inverse(char)
    cs = rules()["combat"]
    # 2024: la inspiración heroica repite el dado (el cliente ya hizo
    # el reroll y manda el resultado nuevo); aquí solo se consume —
    # va tras el snapshot de _set_inverse: el undo la restaura
    if p.get("heroic"):
        if getattr(char.ruleset, "value", char.ruleset) != "dnd5e-2024":
            raise ValueError("la inspiración heroica es una regla 2024")
        if not char.inspiration:
            raise ValueError("sin inspiración heroica")
        char.inspiration = False
    d20 = int(p["roll"])
    result = None
    if d20 >= cs["death_save_crit_success"]:
        char.hp.current = 1
        char.death_saves = {"success": 0, "fail": 0}
        # hp.heal ya lo hace; un 20 natural también levanta al PJ
        char.conditions = [c for c in char.conditions
                           if c.lower() not in ("muerto", "dead")]
        result = "20 natural — recupera 1 PG"
    elif d20 <= cs["death_save_crit_fail"]:
        char.death_saves["fail"] = min(
            cs["death_save_fails"], char.death_saves["fail"] + 2)
        result = "1 natural — doble fallo"
    elif d20 >= cs["death_save_dc"]:
        char.death_saves["success"] += 1
        result = "éxito"
    else:
        char.death_saves["fail"] += 1
        result = "fallo"
    if char.death_saves["fail"] >= cs["death_save_fails"]:
        result += " — muerte"
        if "muerto" not in char.conditions:
            char.conditions.append("muerto")
    return inv, [{"type": "character.hp.changed",
                  "payload": {"death_save": d20, "result": result,
                              **char.death_saves}}]


@op("character.hp.heal")
def hp_heal(char: Character, p: dict, ctx):
    inv = _set_inverse(char)
    amount = max(0, int(p["amount"]))
    char.hp.current = min(char.hp.max, char.hp.current + amount)
    if char.hp.current > 0:   # curarse estabiliza: reinicia muerte
        char.death_saves = {"success": 0, "fail": 0}
        # los cuatro estados vitales en ambos idiomas — quedarse
        # "estable" tras curar dejaba al PJ fuera del orden de
        # iniciativa (Combat.ordered lo sigue saltando)
        char.conditions = [c for c in char.conditions
                           if c.lower() not in
                           ("muerto", "dead", "estable", "stable")]
    return inv, [{"type": "character.hp.changed",
                  "payload": {"healed": amount, "current": char.hp.current}}]


@op("character.hp.set")
def hp_set(char: Character, p: dict, ctx):
    inv = _set_inverse(char)
    char.hp.current = max(0, min(char.hp.max, int(p["current"])))
    char.hp.temp = max(0, int(p.get("temp", char.hp.temp)))
    if "death_saves" in p:               # restauración de undo
        char.death_saves = dict(p["death_saves"])
    if "conditions" in p:
        char.conditions = list(p["conditions"])
    if "condition_stacks" in p:
        char.condition_stacks = dict(p["condition_stacks"])
    if "condition_durations" in p:
        char.condition_durations = dict(p["condition_durations"])
    return inv, [{"type": "character.hp.changed",
                  "payload": {"current": char.hp.current,
                              "temp": char.hp.temp}}]


@op("character.condition.apply")
def condition_apply(char: Character, p: dict, ctx):
    """Aplica una condición; `stacks` es un delta de niveles
    (agotamiento +1/-1). Re-aplicar una condición existente toma
    snapshot para no borrarla al deshacer."""
    cond = p["condition"]
    rounds = int(p["rounds"]) if p.get("rounds") else None
    delta = int(p["stacks"]) if p.get("stacks") is not None else None
    # inmunidad a condiciones declarativa: grant_immunity con
    # target 'condition:<nombre>' o 'condition:*' (la inversa de
    # condition.remove lleva force=True para que deshacer sea fiel)
    if not p.get("force") and _immune_to(char, cond):
        # inversa noop: deshacer un apply que no aplicó no debe
        # quitar una condición que ya estuviera
        return {"operation_type": "noop", "payload": {}}, [
            {"type": "character.condition.immune",
             "payload": {"condition": cond}}]
    if delta is not None and delta < 0 and \
            char.condition_stacks.get(cond, 0) <= 0:
        raise ValueError("condición sin niveles que quitar")
    if cond in char.conditions or delta is not None:
        inv = _set_inverse(char)
    else:
        inv = {"operation_type": "character.condition.remove",
               "payload": {"condition": cond}}
    if delta is not None and delta < 0:
        _shrink_condition(char, cond, delta)
    else:
        if cond not in char.conditions:
            char.conditions.append(cond)
        if delta:
            char.condition_stacks[cond] = \
                char.condition_stacks.get(cond, 0) + delta
    if rounds:
        char.condition_durations[cond] = rounds
    # agotamiento nivel 6 = muerte (2014 y 2024 comparten el umbral;
    # sólo cambia la mecánica de penalización)
    from ...domain.conditions import canon
    lvl = char.condition_stacks.get(cond, 0)
    died = canon(cond) == "exhaustion" \
        and lvl >= rules()["combat"]["exhaustion_death_level"]
    if died and "muerto" not in char.conditions \
            and "dead" not in char.conditions:
        char.conditions.append("muerto")
    return inv, [{"type": "character.condition.applied",
                  "payload": {"condition": cond, "rounds": rounds,
                              **({"died": True} if died else {}),
                              "stacks":
                              char.condition_stacks.get(cond, 0)}}]


@op("character.condition.remove")
def condition_remove(char: Character, p: dict, ctx):
    cond = p["condition"]
    if cond not in char.conditions \
            and cond not in char.condition_stacks \
            and cond not in char.condition_durations:
        # quitar una condición ausente es no-op; si la inversa fuese
        # condition.apply, deshacer crearía una condición fantasma
        return {"operation_type": "noop", "payload": {}}, []
    had_rounds = char.condition_durations.get(cond)
    had_stacks = char.condition_stacks.get(cond)
    inv = {"operation_type": "character.condition.apply",
           "payload": {"condition": cond, "force": True,
                       **({"rounds": had_rounds} if had_rounds else {}),
                       **({"stacks": had_stacks} if had_stacks else {})}}
    if cond in char.conditions:
        char.conditions.remove(cond)
    char.condition_durations.pop(cond, None)
    char.condition_stacks.pop(cond, None)
    return inv, [{"type": "character.condition.removed",
                  "payload": {"condition": cond}}]


@op("character.tick")
def character_tick(char: Character, p: dict, ctx):
    """Pasa una ronda fuera de combate: decrementa las duraciones de
    condiciones y expira las que lleguen a 0."""
    inv = _set_inverse(char)
    expired = []
    # rounds negativo INCREMENTABA las duraciones — el tiempo no
    # fluye hacia atrás
    rounds = max(0, int(p.get("rounds", 1)))
    for cond in list(char.condition_durations):
        char.condition_durations[cond] -= rounds
        if char.condition_durations[cond] <= 0:
            del char.condition_durations[cond]
            if cond in char.conditions:
                char.conditions.remove(cond)
            expired.append(cond)
    return inv, [{"type": "character.condition.removed",
                  "payload": {"expired": expired}}]


@op("character.hit_die.spend")
def hit_die_spend(char: Character, p: dict, ctx):
    """Gasta un dado de golpe en descanso corto: cura roll + mod CON."""
    idx = int(p.get("pool", 0))
    pool = char.hit_dice[idx]
    if pool.remaining <= 0:
        raise ValueError("no quedan dados de golpe en este pool")
    con_mod = char.abilities.modifier("con")
    r = roll(f"1{pool.die}")
    healed = max(1, r.total + con_mod)
    pool.remaining -= 1
    before = char.hp.current
    char.hp.current = min(char.hp.max, char.hp.current + healed)
    actual = char.hp.current - before
    inv = {"operation_type": "character.hit_die.unspend",
           "payload": {"pool": idx, "healed": actual}}
    return inv, [{"type": "character.hp.changed",
                  "payload": {"healed": actual, "roll": r.kept[0],
                              "current": char.hp.current}}]


@op("character.hit_die.unspend")
def hit_die_unspend(char: Character, p: dict, ctx):
    # snapshot: la inversa natural (hit_die.spend) volvería a TIRAR y
    # deshacer-el-deshacer podría curar una cantidad distinta
    inv = _restore_inverse(char.model_dump())
    pool = char.hit_dice[int(p.get("pool", 0))]
    pool.remaining = min(pool.total, pool.remaining + 1)
    # 'healed' solo lo lleva la inversa generada por spend; llamada
    # directa desde la UI (recuperar dado) no deshace curación
    char.hp.current = max(0, char.hp.current - int(p.get("healed", 0)))
    return inv, []


@op("character.rest.short")
def rest_short(char: Character, p: dict, ctx):
    before = char.model_dump()
    _restore_resources(char, {"short"})
    # magia de pacto (brujo): sus espacios se recuperan en descanso
    # corto — todas las demás tradiciones solo en largo
    for slot in char.pact_slots.values():
        slot["used"] = 0
    _run_trigger(char, Trigger.ON_SHORT_REST)
    return _restore_inverse(before), [{"type": "character.hp.changed",
                                       "payload": {"rest": "short"}}]


@op("character.rest.long")
def rest_long(char: Character, p: dict, ctx):
    before = char.model_dump()
    char.hp.current = char.hp.max
    char.hp.temp = 0
    # levantarse a PG máximos limpia el estado de muerte — como hp_heal
    char.death_saves = {"success": 0, "fail": 0}
    for dead in ("muerto", "estable"):
        if dead in char.conditions:
            char.conditions.remove(dead)
        char.condition_durations.pop(dead, None)
    for slot in char.spell_slots.values():
        slot["used"] = 0
    for slot in char.pact_slots.values():
        slot["used"] = 0
    # recupera la mitad de los dados de golpe (mín 1) por nivel total
    regain = max(1, char.total_level // 2)
    for pool in char.hit_dice:
        take = min(regain, pool.total - pool.remaining)
        pool.remaining += take
        regain -= take
    # amanecer también se recupera con el descanso largo
    _restore_resources(char, {"short", "long", "dawn"})
    # las condiciones apilables (agotamiento) bajan 1 nivel por
    # descanso largo; a 0 se retira la condición
    for cond in list(char.condition_stacks):
        char.condition_stacks[cond] -= 1
        if char.condition_stacks[cond] <= 0:
            del char.condition_stacks[cond]
            char.condition_durations.pop(cond, None)
            if cond in char.conditions:
                char.conditions.remove(cond)
    _run_trigger(char, Trigger.ON_LONG_REST)
    return _restore_inverse(before), [{"type": "character.hp.changed",
                                       "payload": {"rest": "long",
                                                   "current": char.hp.current}}]


@op("character.state.restore")
def state_restore(char: Character, p: dict, ctx):
    """Undo de operaciones complejas: restaura un snapshot previo."""
    current = char.model_dump()
    restored = Character(**p["data"])
    char.__dict__.update(restored.__dict__)
    # resync para la sala: sin evento, los otros sockets (otro
    # dispositivo del jugador, el tablero del DM) se quedan viendo el
    # estado previo al undo
    return {"operation_type": "character.state.restore",
            "payload": {"data": current}}, [
                {"type": "character.state.restored",
                 "payload": {"hp": char.hp.current}}]


@op("character.concentration.break")
def concentration_break(char: Character, p: dict, ctx):
    before = char.model_dump()
    spell = char.concentrating_on
    char.concentrating_on = None
    return _restore_inverse(before), [
        {"type": "resource.usage.changed",
         "payload": {"concentration_broken": spell}}]


@op("character.inspiration.set")
def inspiration_set(char: Character, p: dict, ctx):
    inv = {"operation_type": "character.inspiration.set",
           "payload": {"value": char.inspiration}}
    char.inspiration = bool(p.get("value", True))
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"inspiration": char.inspiration}}]


@op("noop")
def noop(entity, p: dict, ctx):
    """Inversa de operaciones sin efecto (condición inmune, remove
    sobre ausente, tiradas puras)."""
    return {"operation_type": "noop", "payload": {}}, []
