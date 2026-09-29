"""Operation handlers — every state change is applied here and returns
the inverse operation so it can be undone. Signature:

    handler(char, payload) -> (inverse_op, [event_payloads])

inverse_op = {"operation_type": ..., "payload": ...} that would undo the
change. Events describe what happened for WS broadcast + log.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable

from ..domain.character import Character, Narrative
from ..domain.effects import Trigger
from ..rules import rules
from .dice import roll

Handler = Callable[[Character, dict, object], tuple[dict, list[dict]]]
HANDLERS: dict[str, Handler] = {}


def op(name: str):
    def wrap(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn
    return wrap


def _set_inverse(char: Character) -> dict:
    # snapshot de salvaciones/condiciones: el daño puede generar
    # fallos de muerte o "muerto" — el undo debe restaurarlos
    return {"operation_type": "character.hp.set",
            "payload": {"current": char.hp.current,
                        "temp": char.hp.temp,
                        "death_saves": dict(char.death_saves),
                        "conditions": list(char.conditions),
                        "condition_stacks": dict(char.condition_stacks),
                        "condition_durations":
                        dict(char.condition_durations)}}


@op("character.hp.damage")
def hp_damage(char: Character, p: dict, ctx):
    inv = _set_inverse(char)
    amount = max(0, int(p["amount"]))
    # resistencia/vulnerabilidad/inmunidad declarativas por tipo de daño
    dtype = str(p.get("type", "")).lower()
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
    return inv, [{"type": "character.hp.changed", "payload": payload}]


def _damage_mult(char: Character, dtype: str) -> tuple[float, list]:
    """Multiplicador por inmunidad/resistencia/vulnerabilidad
    declarativas (grant_*) filtradas por tipo de daño o '*' →
    (mult, [notas])."""
    mult, applied = 1.0, []
    for eff in char.effects:
        for o in eff.operations:
            tgt = (o.target or "").lower()
            if dtype and tgt not in (dtype, "*"):
                continue
            if o.op.value == "grant_immunity":
                mult = 0.0
                applied.append(f"{eff.name}: inmunidad")
            elif o.op.value == "grant_resistance" and mult > 0.5:
                mult = 0.5
                applied.append(f"{eff.name}: resistencia")
            elif o.op.value == "grant_vulnerability":
                mult *= 2.0
                applied.append(f"{eff.name}: vulnerabilidad")
    return mult, applied


def _death_rules(char: Character, dmg: int, was_zero: bool,
                 overflow: int, payload: dict) -> None:
    """Daño masivo (restante ≥ PG máx) → muerte instantánea; golpeado
    estando a 0 PG → un fallo de salvación de muerte."""
    if dmg <= 0 or char.hp.max <= 0:
        return
    cs = rules()["combat"]
    if overflow >= char.hp.max:
        char.death_saves["fail"] = cs["death_save_fails"]
        if "muerto" not in char.conditions:
            char.conditions.append("muerto")
        payload["instant_death"] = True
    elif was_zero:
        char.death_saves["fail"] = min(
            cs["death_save_fails"], char.death_saves["fail"] + 1)
        payload["death_fail_at_zero"] = char.death_saves["fail"]
        if char.death_saves["fail"] >= cs["death_save_fails"] and \
                "muerto" not in char.conditions:
            char.conditions.append("muerto")
            payload["instant_death"] = True


@op("character.death_save")
def death_save(char: Character, p: dict, ctx):
    """Salvación de muerte (a 0 PG). El cliente pasa 'roll' (1d20 ya
    tirado): ≥10 éxito, <10 fallo, 1 = doble fallo, 20 = se recupera
    con 1 PG. Tres éxitos estabiliza, tres fallos es la muerte."""
    if char.hp.current > 0:
        raise ValueError("el personaje no está a 0 PG")
    inv = _set_inverse(char)
    cs = rules()["combat"]
    d20 = int(p["roll"])
    result = None
    if d20 >= cs["death_save_crit_success"]:
        char.hp.current = 1
        char.death_saves = {"success": 0, "fail": 0}
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
        char.conditions = [c for c in char.conditions
                           if c.lower() not in ("muerto", "dead")]
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


_COIN_CP = {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}


@op("character.currency.convert")
def currency_convert(char: Character, p: dict, ctx):
    """Cambia monedas entre tipos (10sp→1gp, 50cp→5sp). La vuelta
    se queda en la moneda de origen. Reversible por snapshot."""
    src, dst = p["from"], p["to"]
    if src not in _COIN_CP or dst not in _COIN_CP or src == dst:
        raise ValueError("conversión de moneda inválida")
    amount = int(p["amount"])
    if amount <= 0 or char.purse.get(src, 0) < amount:
        raise ValueError("monedas insuficientes")
    inv = {"operation_type": "character.currency.set",
           "payload": {"purse": dict(char.purse)}}
    total_cp = amount * _COIN_CP[src]
    gained = total_cp // _COIN_CP[dst]
    if gained <= 0:
        raise ValueError("conversión vacía — no llega a una moneda")
    change_cp = total_cp - gained * _COIN_CP[dst]
    char.purse[src] -= amount
    char.purse[src] += change_cp // _COIN_CP[src]
    char.purse[dst] = char.purse.get(dst, 0) + gained
    return inv, [{"type": "inventory.item.transferred",
                  "payload": {"converted": f"{amount}{src} → "
                                          f"{gained}{dst}"}}]


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
    return inv, [{"type": "character.condition.applied",
                  "payload": {"condition": cond, "rounds": rounds,
                              "stacks":
                              char.condition_stacks.get(cond, 0)}}]


def _immune_to(char: Character, cond: str) -> bool:
    """grant_immunity con target 'condition:<nombre>' o
    'condition:*' — p.ej. heroísmo contra asustado."""
    immune = {str(o.target or "").lower()
              for eff in char.effects for o in eff.operations
              if o.op.value == "grant_immunity"}
    return f"condition:{cond}".lower() in immune or \
        "condition:*" in immune


def _shrink_condition(char: Character, cond: str, delta: int) -> None:
    """Quita niveles de condición (agotamiento -1); a 0 se limpia
    del todo — duración y lista de condiciones incluidas."""
    new = char.condition_stacks.get(cond, 0) + delta
    if new <= 0:
        char.condition_stacks.pop(cond, None)
        char.condition_durations.pop(cond, None)
        if cond in char.conditions:
            char.conditions.remove(cond)
    else:
        char.condition_stacks[cond] = new


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
    for cond in list(char.condition_durations):
        char.condition_durations[cond] -= int(p.get("rounds", 1))
        if char.condition_durations[cond] <= 0:
            del char.condition_durations[cond]
            if cond in char.conditions:
                char.conditions.remove(cond)
            expired.append(cond)
    return inv, [{"type": "character.condition.removed",
                  "payload": {"expired": expired}}]


@op("character.resource.consume")
def resource_consume(char: Character, p: dict, ctx):
    res = _resource(char, p["resource_id"])
    amount = max(0, int(p.get("amount", 1)))
    inv = {"operation_type": "character.resource.restore",
           "payload": {"resource_id": res.id, "amount": min(amount, res.current)}}
    res.current = max(0, res.current - amount)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"resource_id": res.id, "current": res.current}}]


@op("character.resource.restore")
def resource_restore(char: Character, p: dict, ctx):
    res = _resource(char, p["resource_id"])
    amount = max(0, int(p.get("amount", res.max)))
    inv = {"operation_type": "character.resource.consume",
           "payload": {"resource_id": res.id,
                       "amount": min(amount, res.max - res.current)}}
    res.current = min(res.max, res.current + amount)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"resource_id": res.id, "current": res.current}}]


def _slots_for(char: Character, lvl: str, pool: str | None):
    """El pool de espacios a usar: 'pact' = pacto del brujo,
    'regular' = normal; sin pool → pacto si existe ese nivel."""
    if pool == "pact":
        return char.pact_slots
    if pool == "regular" or not char.pact_slots:
        return char.spell_slots
    return char.pact_slots if lvl in char.pact_slots else char.spell_slots


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
    # la inversa guarda el pool RESUELTO — si pact_slots cambia entre
    # la op y su undo, re-resolver 'None' podría caer en otro pool
    resolved_pool = "pact" if pool is char.pact_slots else "regular"
    inv = {"operation_type": "character.spell_slot.restore",
           "payload": {"level": int(lvl), "pool": resolved_pool,
                       "count": min(count, slot["total"] - slot["used"])}}
    slot["used"] = min(slot["total"], slot["used"] + count)
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
    char.hp.current = max(0, char.hp.current - int(p["healed"]))
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


def _restore_inverse(before: dict) -> dict:
    return {"operation_type": "character.state.restore",
            "payload": {"data": before}}


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


@op("character.level_up")
def level_up(char: Character, p: dict, ctx):
    """Subida de nivel reversible. hp_mode: 'fixed' (media+1) o 'roll'
    (el cliente pasa 'rolled'). Soporta multiclase vía class_id."""
    class_id = p.get("class_id") or (
        char.classes[0].class_id if char.classes else None)
    if not class_id:
        raise ValueError("class_id requerido")

    before = char.model_dump()

    # ¿clase existente o multiclase nueva?
    from ..domain.classinfo import hit_die as _class_hit_die
    cls_data = _content(ctx, class_id)
    hit_die = _class_hit_die(cls_data or {})
    new_level = _bump_class(char, class_id, hit_die)

    con_mod = char.abilities.modifier("con")
    if p.get("hp_mode") == "roll" and p.get("rolled"):
        gain = int(p["rolled"]) + con_mod
    else:
        gain = hit_die // 2 + 1 + con_mod
    char.hp.max += max(1, gain)
    char.hp.current += max(1, gain)

    # prof bonus + spell slots del nuevo nivel (si la content DB lo tiene)
    source, class_index = class_id.split(":", 1)
    lvl = _content(ctx, f"{source}:{class_index}-{new_level}")
    _apply_level_row(char, class_id, lvl)

    # Rasgos ganados en este nivel (clase + subclase) → char.features
    gained = _level_features(ctx, char, lvl, cls_data, class_id,
                             new_level)
    for name in gained:
        if name and name not in char.features:
            char.features.append(name)

    res_gained = _level_resources(char, lvl)

    _run_trigger(char, Trigger.ON_LEVEL_UP)
    return _restore_inverse(before), [
        {"type": "character.hp.changed",
         "payload": {"level_up": class_id, "level": new_level,
                     "hp_max": char.hp.max,
                     "features_gained": gained,
                     "resources_updated": res_gained,
                     # mejora de característica NUEVA en este nivel:
                     # ability_score_bonuses es acumulado — sube solo
                     # en niveles de ASI (4, 8, 12, 16, 19)
                     "asi_available": _asi_gained(ctx, class_id,
                                                  new_level)}}]


def _bump_class(char: Character, class_id: str, hit_die: int) -> int:
    """+1 nivel en la clase (o entrada nueva en multiclase) y su dado
    de golpe. Devuelve el nivel resultante."""
    from ..domain.character import ClassLevel, HitDicePool
    entry = next((c for c in char.classes if c.class_id == class_id),
                 None)
    if entry is None:
        char.classes.append(ClassLevel(class_id=class_id, level=1))
        pool = None
        new_level = 1
    else:
        entry.level += 1
        new_level = entry.level
        pool = next((hd for hd in char.hit_dice
                     if hd.die == f"d{hit_die}"), None)
    if pool:
        pool.total += 1
        pool.remaining += 1
    else:
        char.hit_dice.append(HitDicePool(die=f"d{hit_die}", total=1,
                                         remaining=1))
    return new_level


def _apply_level_row(char: Character, class_id: str,
                     lvl: dict | None) -> None:
    """Fila 'level' de la clase: proficiency bonus y espacios de
    conjuro (brujo → pool de pacto, recarga en descanso corto)."""
    if not lvl:
        return
    char.proficiency_bonus = int(lvl.get("prof_bonus",
                                         char.proficiency_bonus))
    sc = lvl.get("spellcasting") or {}
    target = (char.pact_slots
              if class_id.split(":")[-1].replace("-", " ") == "warlock"
              else char.spell_slots)
    for n in range(1, 10):
        slots = sc.get(f"spell_slots_level_{n}", 0)
        if slots:
            target[str(n)] = {"total": slots, "used": 0}


def _level_features(ctx, char, lvl, cls_data, class_id,
                    new_level) -> list[str]:
    """Nombres de rasgos ganados en este nivel — dos vías:
     5e-bits: entidad 'level' con features:[{name}]
     5etools: entidades 'class-feature' con className+level.
    Si la clase tiene subclass_id, sus features llevan
    subclassShortName = nombre de la subclase (5etools)."""
    gained = [f.get("name") if isinstance(f, dict) else str(f)
              for f in (lvl or {}).get("features") or []]
    cls_name = (cls_data or {}).get("name")
    if cls_name and ctx is not None:
        gained += _feature_names(ctx, new_level, "className", cls_name)
    sub_id = next(
        (c.subclass_id for c in char.classes if c.class_id == class_id),
        None)
    if sub_id and ctx is not None:
        try:
            srow = ctx.content_db().execute(
                "SELECT name FROM content_entities WHERE id = ?",
                (sub_id,)).fetchone()
        except Exception:   # noqa: BLE001 - subclass feats best-effort
            srow = None
        sub_name = srow["name"] if srow else None
        if sub_name:
            gained += _feature_names(ctx, new_level,
                                     "subclassShortName", sub_name)
    return gained


def _feature_names(ctx, new_level: int, field: str,
                   value: str) -> list[str]:
    """Entidades 'class-feature' del nivel filtradas por
    $.className o $.subclassShortName (5etools) — best-effort."""
    try:
        rows = ctx.content_db().execute(
            f"""SELECT data FROM content_entities
                WHERE entity_type = 'class-feature'
                AND json_extract(data, '$.level') = ?
                AND lower(json_extract(data, '$.{field}')) =
                    lower(?)""",
            (new_level, value)).fetchall()
        return [json.loads(r["data"]).get("name", "?") for r in rows]
    except Exception:      # noqa: BLE001 - features best-effort
        return []


def _level_resources(char, lvl) -> list[str]:
    """Contadores de clase del nivel → recursos rastreables.
    class_specific (5e-bits/Open5e): rage_count, ki_points,
    sorcery_points… — valores enteros >0 que se gastan y se
    recuperan (furias, dados de superioridad, puntos de ki).
    Devuelve las claves añadidas este nivel."""
    _SHORT_KEYS = ("ki_points", "superiority_dice", "action_surge",
                   "second_wind", "channel_divinity", "martial_arts")
    res_gained: list[str] = []
    for key, val in ((lvl or {}).get("class_specific") or {}).items():
        if not isinstance(val, int) or val <= 0:
            continue
        if key.endswith("_dice") and "superiority" not in key:
            continue          # brutal_critical_dice = daño, no usos
        if not any(tag in key for tag in
                   ("count", "points", "uses", "dice")):
            continue
        rid = f"cls.{key}"
        reset = ("short" if any(k in key for k in _SHORT_KEYS)
                 else "long")
        res = next((r for r in char.resources if r.id == rid), None)
        if res is None:
            from ..domain.character import Resource
            char.resources.append(Resource(
                id=rid, name=key.replace("_", " ").title(),
                current=val, max=val, reset_on=reset))
            res_gained.append(key)
        elif res.max != val:
            # el tope sube con el nivel — concede los usos nuevos
            res.current = min(val, res.current + max(0, val - res.max))
            res.max = val
    return res_gained


def _asi_gained(ctx, class_id: str, level: int) -> bool:
    """¿El nivel alcanzado otorga una mejora de característica?
    ability_score_bonuses en la entidad 'level' es acumulado:
    true si es mayor que en el nivel anterior."""
    if ctx is None or level < 2:
        return False
    source, class_index = class_id.split(":", 1)

    def _ab(lv: int) -> int:
        row = _content(ctx, f"{source}:{class_index}-{lv}")
        return int((row or {}).get("ability_score_bonuses") or 0)

    try:
        return _ab(level) > _ab(level - 1)
    except Exception:
        return False


def _item_damage(item_data: dict) -> str | None:
    """Expresión de daño del arma — multi-schema.

    5e-bits: damage.damage_dice · 5etools: dmg1+dmgType ·
    codexMUNDI: damage · dnd-data: properties.Damage."""
    dmg = item_data.get("damage")
    if isinstance(dmg, dict) and dmg.get("damage_dice"):
        return str(dmg["damage_dice"])
    if item_data.get("dmg1"):
        return str(item_data["dmg1"])
    if isinstance(dmg, str) and "d" in dmg:
        return dmg
    props = item_data.get("properties") or {}
    return props.get("Damage") if "d" in str(props.get("Damage", "")) \
        else None


@op("character.attack")
def character_attack(char: Character, p: dict, ctx):
    """Ataque con un arma del inventario: 1d20 + prof + mod (fue por
    defecto) y daño del arma resuelto desde su entidad de contenido."""
    item = next((i for i in char.inventory
                 if i.id == p.get("item_id")), None)
    if item is None:
        raise ValueError("objeto no encontrado en inventario")
    dmg_expr = "1d4"
    finesse = False
    if item.source_id:
        w = _content(ctx, item.source_id) or {}
        dmg_expr = _item_damage(w) or dmg_expr
        props = w.get("properties") or w.get("property") or []
        finesse = any(
            (x.get("index") or x.get("name") or "").lower() == "finesse"
            if isinstance(x, dict) else str(x).lower() in ("finesse", "f")
            for x in (props if isinstance(props, list) else [props]))
    # finesse: mejor de FUE/DES; si no, FUE (aproximación marcial)
    mod = max(char.abilities.modifier("str"),
              char.abilities.modifier("dex")) if finesse \
        else char.abilities.modifier("str")
    total_mod = char.proficiency_bonus + mod
    atk = roll("1d20")
    dmg = roll(dmg_expr)
    return {"operation_type": "noop", "payload": {}}, [
        {"type": "dice.roll.created", "payload": {
            "character": char.name, "weapon": item.name,
            "attack_roll": atk.total, "attack_mod": total_mod,
            "attack_total": atk.total + total_mod,
            "damage_expr": dmg_expr, "damage_total": dmg.total}}]


def _item_weight(sp: dict) -> float:
    """Peso en libras desde datos de entidad: 'weight' numérico
    (5e-bits/Open5e) o texto '6 lb.' (5etools properties)."""
    import re
    for k in ("weight", "weight_lb"):
        try:
            return float(sp.get(k) or 0)
        except (TypeError, ValueError):
            continue
    for k in ("Weight", "weight"):
        v = (sp.get("properties") or {}).get(k) or sp.get(k)
        if isinstance(v, str):
            m = re.search(r"[\d.]+", v)
            if m:
                return float(m.group(0))
    return 0.0


@op("character.inventory.add")
def inventory_add(char: Character, p: dict, ctx):
    import uuid as _uuid
    from ..domain.character import InventoryItem
    weight = p.get("weight")
    if weight is None and p.get("source_id"):
        weight = _item_weight(_content(ctx, p["source_id"]) or {})
    item = InventoryItem(
        id=p.get("id") or _uuid.uuid4().hex,
        name=p["name"],
        quantity=int(p.get("quantity", 1)),
        equipped=bool(p.get("equipped", False)),
        source_id=p.get("source_id"),
        weight=float(weight or 0),
    )
    # si el id ya existe (p.ej. undo de un remove parcial) se fusiona
    # la cantidad — duplicar el id rompería las búsquedas por item_id.
    # La inversa quita SOLO lo añadido: con el total fusionado un
    # "add 2" sobre un stack de 5 revertía 7. Y si el payload no
    # traía quantity, el fallback a item.quantity leía el total
    # fusionado — mismo bug.
    added = item.quantity
    existing = next((i for i in char.inventory if i.id == item.id), None)
    if existing is not None:
        existing.quantity += added
        item = existing
    else:
        char.inventory.append(item)
    return {"operation_type": "character.inventory.remove",
            "payload": {"item_id": item.id, "quantity": added}}, [
        {"type": "inventory.item.transferred",
         "payload": {"added": item.name, "quantity": item.quantity}}]


@op("character.inventory.remove")
def inventory_remove(char: Character, p: dict, ctx):
    idx = next((i for i, it in enumerate(char.inventory)
                if it.id == p["item_id"]), None)
    if idx is None:
        raise ValueError(f"item not found: {p['item_id']}")
    item = char.inventory[idx]
    qty = min(int(p.get("quantity", item.quantity)), item.quantity)
    item.quantity -= qty
    removed_item = None
    if item.quantity <= 0:
        removed_item = char.inventory.pop(idx)
    inv = {"operation_type": "character.inventory.add",
           "payload": (removed_item or item).model_dump() |
                      {"quantity": qty}}
    return inv, [{"type": "inventory.item.transferred",
                  "payload": {"removed": item.name, "quantity": qty}}]


_CP = {"pp": 1000, "gp": 100, "ep": 50, "sp": 10, "cp": 1}


def _purse_cp(char: Character) -> int:
    return sum(char.purse.get(k, 0) * v for k, v in _CP.items())


def _normalize_purse(total_cp: int) -> dict[str, int]:
    """Denominaciones mínimas: pp > gp > ep > sp > cp."""
    out = {}
    for coin in ("pp", "gp", "ep", "sp"):
        out[coin], total_cp = divmod(total_cp, _CP[coin])
    out["cp"] = total_cp
    return out


def _spend(char: Character, amount_cp: int) -> None:
    if _purse_cp(char) < amount_cp:
        raise ValueError("fondos insuficientes")
    char.purse = _normalize_purse(_purse_cp(char) - amount_cp)


@op("character.currency.earn")
def currency_earn(char: Character, p: dict, ctx):
    # snapshot, no spend: si ya se gastó parte del botín, spend daba
    # "fondos insuficientes" y normalizaba las denominaciones
    inv = {"operation_type": "character.currency.set",
           "payload": {"purse": dict(char.purse)}}
    for coin, n in p.items():
        if coin in _CP:
            char.purse[coin] = char.purse.get(coin, 0) + max(0, int(n))
    return inv, [{"type": "inventory.item.transferred",
                  "payload": {"earned": p, "purse": char.purse}}]


@op("character.currency.spend")
def currency_spend(char: Character, p: dict, ctx):
    """Gasta monedas con conversión automática (todo pasa a cp)."""
    before = dict(char.purse)
    needed = sum(max(0, int(p.get(k, 0))) * _CP[k]
                 for k in p if k in _CP)
    _spend(char, needed)
    inv = {"operation_type": "character.currency.set",
           "payload": {"purse": before}}
    return inv, [{"type": "inventory.item.transferred",
                  "payload": {"spent": p, "purse": char.purse}}]


@op("character.currency.set")
def currency_set(char: Character, p: dict, ctx):
    before = dict(char.purse)
    char.purse = {k: max(0, int(v)) for k, v in p["purse"].items()
                  if k in _CP}
    return {"operation_type": "character.currency.set",
            "payload": {"purse": before}}, []


@op("character.shop.buy")
def shop_buy(char: Character, p: dict, ctx):
    """Compra en una tienda (campaign entity kind='shop'): descuenta
    monedas, añade el objeto al inventario y decrementa stock — todo
    en la transacción de la operación."""
    if ctx is None or ctx.state_db() is None:
        raise ValueError("shop.buy requiere contexto de estado")
    row = ctx.state_db().execute(
        "SELECT data FROM campaign_entities WHERE id = ?",
        (p["shop_id"],)).fetchone()
    if row is None:
        raise ValueError("tienda no encontrada")
    shop = json.loads(row["data"])
    stock = shop.get("stock", [])
    entry = next((s for s in stock if s.get("name") == p["item"]), None)
    if entry is None or entry.get("quantity", 0) < 1:
        raise ValueError("sin stock")

    price_cp = int(entry["price_cp"])
    _spend(char, price_cp)
    inv_add, _ = HANDLERS["character.inventory.add"](
        char, {"name": p["item"], "quantity": 1,
               "source_id": entry.get("source_id")}, ctx)
    entry["quantity"] -= 1
    # bump de version + evento: la tienda es una entidad de campaña —
    # sin esto su stock quedaba desincronizado (ni evento ni versión)
    now = datetime.now(timezone.utc).isoformat()
    ctx.state_db().execute(
        "UPDATE campaign_entities SET data = ?, version = version+1, "
        "updated_at = ? WHERE id = ?",
        (json.dumps(shop), now, p["shop_id"]))
    # inversa real: devuelve objeto, repone stock y reembolsa monedas.
    # item_id = el objeto EXACTO añadido (por nombre quitaría el stack
    # de otra poción homónima ya en el inventario)
    inv = {"operation_type": "character.shop.refund",
           "payload": {"shop_id": p["shop_id"], "item": p["item"],
                       "item_id": inv_add["payload"]["item_id"],
                       "price_cp": price_cp}}
    return inv, [
        {"type": "inventory.item.transferred",
         "payload": {"bought": p["item"], "price_cp": price_cp,
                     "purse": char.purse}},
        {"type": "campaign.entity.updated",
         "payload": {"entity_id": p["shop_id"], "kind": "shop",
                     "reason": "sold"}}]


@op("character.effect.add")
def effect_add(char: Character, p: dict, ctx):
    """Añade un Effect declarativo (rasgo, aura, homebrew…)."""
    import uuid as _uuid
    from ..domain.effects import Effect
    eff = Effect(**{**p["effect"], "id": p["effect"].get("id")
                    or _uuid.uuid4().hex})
    if any(e.id == eff.id for e in char.effects):
        raise ValueError(f"efecto duplicado: {eff.id}")
    char.effects.append(eff)
    return {"operation_type": "character.effect.remove",
            "payload": {"effect_id": eff.id}}, [
        {"type": "character.condition.applied",
         "payload": {"effect": eff.name}}]


@op("character.effect.remove")
def effect_remove(char: Character, p: dict, ctx):
    idx = next((i for i, e in enumerate(char.effects)
                if e.id == p["effect_id"]), None)
    if idx is None:
        raise ValueError(f"efecto no encontrado: {p['effect_id']}")
    eff = char.effects.pop(idx)
    return {"operation_type": "character.effect.add",
            "payload": {"effect": eff.model_dump(mode="json")}}, [
        {"type": "character.condition.removed",
         "payload": {"effect": eff.name}}]


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
        slot = pool.setdefault(str(level), {"total": 0, "used": 0})
        if slot["used"] >= slot["total"]:
            raise ValueError(f"sin espacios de nivel {level}")
        slot["used"] += 1
    if _needs_conc(sp):
        char.concentrating_on = sp.get("name", spell_id)

    return _restore_inverse(before), [
        {"type": "resource.usage.changed",
         "payload": _spell_cast_payload(char, sp, spell_id, level,
                                        spell_level, ctx)}]


def _cast_level(sp: dict, level: int) -> tuple[int, int]:
    """(nivel de espacio, nivel del conjuro). Upcasting válido; no
    se puede lanzar un conjuro por debajo de su nivel."""
    spell_level = int(sp.get("level")
                      or (sp.get("properties") or {}).get("Level") or 0)
    if level and level < spell_level:
        raise ValueError(
            f"espacio insuficiente: {sp.get('name')} es de nivel "
            f"{spell_level}")
    return level or spell_level, spell_level


def _needs_conc(sp: dict) -> bool:
    """Concentración: "yes" (5e-bits/open5e), true, o flag en
    duration[] (5etools: duration:[{concentration:true}])."""
    return sp.get("concentration") in (True, "yes", "Yes") or any(
        d.get("concentration") for d in sp.get("duration") or []
        if isinstance(d, dict))


def _cast_ability(char: Character, ctx) -> str | None:
    """Característica de lanzamiento de la clase principal."""
    if not char.classes:
        return None
    cls_data = _content(ctx, char.classes[0].class_id) or {}
    from ..domain.classinfo import spellcasting_ability
    return spellcasting_ability(cls_data)


def _needs_attack(sp: dict) -> bool:
    """El conjuro usa tirada de ataque (flag o 'spell attack' en el
    texto — multi-schema)."""
    return bool(
        sp.get("attack") or sp.get("spellAttack")
        or (sp.get("meta") or {}).get("attack")
        or "spell attack" in str(sp.get("desc")
                                 or sp.get("entries") or ""))


def _slot_damage_expr(sp: dict, level: int, spell_level: int):
    """Daño escalado por espacio: damage_at_slot_level{slot:dice}
    (o por nivel de personaje) → expresión de dados."""
    dmg_map = {}
    for d in sp.get("damage") or []:
        if isinstance(d, dict) and d.get("damage_at_slot_level"):
            dmg_map.update(d["damage_at_slot_level"])
        elif isinstance(d, dict) and d.get("damage_at_character_level"):
            dmg_map.update(d["damage_at_character_level"])
    return dmg_map.get(str(level)) or dmg_map.get(str(spell_level)) \
        or sp.get("dmg1")


def _spell_cast_payload(char: Character, sp: dict, spell_id: str,
                        level: int, spell_level: int, ctx) -> dict:
    """Datos de juego del conjuro desde su entidad: CD de salvación
    (8 + prof + mod de lanzamiento de la clase), tirada de ataque de
    conjuro y daño escalado al nivel del espacio consumido."""
    payload = {"spell_cast": sp.get("name", spell_id),
               "level": level,
               "concentration": char.concentrating_on}
    cast_ability = _cast_ability(char, ctx)
    spell_dc = (rules()["combat"]["spell_dc_base"]
                + char.proficiency_bonus
                + char.abilities.modifier(cast_ability)
                ) if cast_ability else None
    if spell_dc and (sp.get("savingThrow") or sp.get("saves")
                     or sp.get("saving_throws") or sp.get("dc")):
        payload["spell_dc"] = spell_dc
    if cast_ability and _needs_attack(sp):
        atk = roll("1d20")
        atk_mod = char.proficiency_bonus + char.abilities.modifier(
            cast_ability)
        payload.update(spell_attack_roll=atk.total,
                       spell_attack_total=atk.total + atk_mod,
                       spell_attack_mod=atk_mod)
    expr = _slot_damage_expr(sp, level, spell_level)
    if expr:
        payload.update(damage_expr=str(expr),
                       damage_total=roll(str(expr)).total)
    return payload


@op("character.concentration.break")
def concentration_break(char: Character, p: dict, ctx):
    before = char.model_dump()
    spell = char.concentrating_on
    char.concentrating_on = None
    return _restore_inverse(before), [
        {"type": "resource.usage.changed",
         "payload": {"concentration_broken": spell}}]


@op("character.xp.add")
def xp_add(char: Character, p: dict, ctx):
    amount = int(p["amount"])
    # la inversa guarda el valor previo exacto: con -amount el clamp a
    # 0 inflaba el XP (xp=5, add(-10) → 0, undo +10 → 10 ≠ 5)
    inv = {"operation_type": "character.xp.set",
           "payload": {"xp": char.xp}}
    char.xp = max(0, char.xp + amount)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"xp": char.xp, "delta": amount}}]


@op("character.xp.set")
def xp_set(char: Character, p: dict, ctx):
    inv = {"operation_type": "character.xp.set",
           "payload": {"xp": char.xp}}
    char.xp = max(0, int(p["xp"]))
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"xp": char.xp}}]


@op("character.shop.refund")
def shop_refund(char: Character, p: dict, ctx):
    """Inversa real de shop.buy: devuelve el objeto, repone el stock y
    reembolsa las monedas — todo en la transacción de la operación."""
    if ctx is None or ctx.state_db() is None:
        raise ValueError("shop.refund requiere contexto de estado")
    # item_id exacto (ops nuevas); por nombre solo en inversas viejas
    item = (next((i for i in char.inventory if i.id == p.get("item_id")),
                 None) if p.get("item_id")
            else next((i for i in char.inventory
                       if i.name == p["item"]), None))
    if item is None:
        raise ValueError("objeto no encontrado para devolver")
    item.quantity -= 1
    if item.quantity <= 0:
        char.inventory.remove(item)
    price_cp = int(p["price_cp"])
    char.purse = _normalize_purse(_purse_cp(char) + price_cp)
    row = ctx.state_db().execute(
        "SELECT data FROM campaign_entities WHERE id = ?",
        (p["shop_id"],)).fetchone()
    if row:
        shop = json.loads(row["data"])
        for s in shop.get("stock", []):
            if s.get("name") == p["item"]:
                s["quantity"] = s.get("quantity", 0) + 1
                break
        now = datetime.now(timezone.utc).isoformat()
        ctx.state_db().execute(
            "UPDATE campaign_entities SET data = ?, version = version+1,"
            " updated_at = ? WHERE id = ?",
            (json.dumps(shop), now, p["shop_id"]))
    return {"operation_type": "character.shop.buy",
            "payload": {"shop_id": p["shop_id"], "item": p["item"]}}, [
        {"type": "inventory.item.transferred",
         "payload": {"refunded": p["item"], "price_cp": price_cp}}]


@op("character.journal.add")
def journal_add(char: Character, p: dict, ctx):
    """Entrada de diario/crónicas — reversible."""
    entry = p.get("entry") or p.get("text")
    if not entry or not isinstance(entry, str):
        raise ValueError("entrada de diario vacía")
    idx = len(char.narrative.journal)
    char.narrative.journal.append(entry)
    # la inversa señala LA entrada añadida — journal.pop quitaría la
    # última, que con entradas intermedias (el undo no es LIFO:
    # se puede deshacer cualquier op del historial) sería otra
    return {"operation_type": "character.journal.remove",
            "payload": {"index": idx, "entry": entry}}, [
        {"type": "inventory.item.transferred",
         "payload": {"journal_entry": entry}}]


@op("character.journal.remove")
def journal_remove(char: Character, p: dict, ctx):
    """Quita una entrada concreta por índice+contenido. Si el índice
    ya no coincide (entradas borradas antes), cae al texto."""
    j = char.narrative.journal
    idx = int(p.get("index", -1))
    entry = p.get("entry")
    if 0 <= idx < len(j) and j[idx] == entry:
        j.pop(idx)
    elif entry in j:
        j.remove(entry)
    else:
        raise ValueError("la entrada ya no está en el diario")
    return {"operation_type": "character.journal.insert",
            "payload": {"index": idx, "entry": entry}}, []


@op("character.journal.insert")
def journal_insert(char: Character, p: dict, ctx):
    """Re-inserta una entrada en su posición — inversa de remove."""
    j = char.narrative.journal
    idx = min(max(0, int(p.get("index", len(j)))), len(j))
    entry = p["entry"]
    j.insert(idx, entry)
    return {"operation_type": "character.journal.remove",
            "payload": {"index": idx, "entry": entry}}, []


@op("character.journal.pop")
def journal_pop(char: Character, p: dict, ctx):
    if not char.narrative.journal:
        raise ValueError("diario vacío — nada que quitar")
    entry = char.narrative.journal.pop()
    return {"operation_type": "character.journal.insert",
            "payload": {"index": len(char.narrative.journal),
                        "entry": entry}}, []


@op("character.ability.set")
def ability_set(char: Character, p: dict, ctx):
    """Edita una puntuación de característica (mejora de nivel, etc.)."""
    ability = p["ability"].lower()
    inv = {"operation_type": "character.ability.set",
           "payload": {"ability": ability,
                       "value": getattr(char.abilities, {
                           "str": "strength", "dex": "dexterity",
                           "con": "constitution", "int": "intelligence",
                           "wis": "wisdom", "cha": "charisma",
                       }.get(ability, ability))}}
    setattr(char.abilities,
            {"str": "strength", "dex": "dexterity", "con": "constitution",
             "int": "intelligence", "wis": "wisdom",
             "cha": "charisma"}.get(ability, ability),
            int(p["value"]))
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"ability": ability, "value": p["value"]}}]


@op("character.asi.apply")
def asi_apply(char: Character, p: dict, ctx):
    """Mejora de característica por nivel (ASI): +2 a una o +1 a cada
    una de dos (payload: {a1, a2?, amount}). Solo si hay mejoras
    disponibles según la tabla de la clase — feats no lo descuentan:
    elegir una dote sustituye a la mejora (asi.spent)."""
    amount = int(p.get("amount", 2))
    a1, a2 = p["ability"], p.get("ability2")
    if a2 and amount != 1:
        raise ValueError("+1 a cada una: amount=1 con dos características")
    if not a2 and amount not in (1, 2):
        raise ValueError("la mejora es +1 o +2")
    cost = amount * (2 if a2 else 1)
    if ctx is not None:
        # sin contexto (tests unitarios) no se puede consultar la
        # content DB — la API siempre pasa ctx y aquí se valida
        from ..domain.classinfo import asi_earned
        if char.asi_used + cost > asi_earned(char, ctx.content_db()):
            raise ValueError(
                "sin mejoras de característica disponibles")
    before = char.asi_used
    inv = {"operation_type": "character.state.restore",
           "payload": {"data": char.model_dump()}}
    from ..domain.character import _ABILITY_ALIASES as _AL
    for ab in (a1, a2):
        if not ab:
            continue
        key = _AL.get(ab.lower(), ab.lower())
        setattr(char.abilities, key,
                min(30, getattr(char.abilities, key) + amount))
    char.asi_used += cost                  # +1+1 = 2 puntos
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"asi": {"ability": a1, "ability2": a2,
                                      "amount": amount,
                                      "asi_used": char.asi_used,
                                      "asi_used_before": before}}}]


@op("character.asi.spent")
def asi_spent(char: Character, p: dict, ctx):
    """Marca una mejora como gastada al elegir una dote en su lugar."""
    if ctx is not None:
        from ..domain.classinfo import asi_earned
        if char.asi_used + 2 > asi_earned(char, ctx.content_db()):
            raise ValueError(
                "sin mejoras de característica disponibles")
    inv = {"operation_type": "character.state.restore",
           "payload": {"data": char.model_dump()}}
    char.asi_used += 2                     # una dote = una mejora (+2)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"asi_spent": True,
                              "asi_used": char.asi_used}}]


@op("character.resource.add")
def resource_add(char: Character, p: dict, ctx):
    """Define un recurso nuevo (homebrew: furia, ki, p. de hechicería)."""
    import uuid as _uuid
    from ..domain.character import Resource
    res = Resource(id=p.get("id") or _uuid.uuid4().hex, name=p["name"],
                   current=int(p.get("max", p.get("current", 0))),
                   max=int(p.get("max", 0)),
                   reset_on=p.get("reset_on", "long"))
    if any(r.name == res.name for r in char.resources):
        raise ValueError(f"recurso duplicado: {res.name}")
    char.resources.append(res)
    return {"operation_type": "character.resource.remove",
            "payload": {"resource_id": res.id}}, [
        {"type": "resource.usage.changed",
         "payload": {"resource_added": res.name}}]


@op("character.resource.remove")
def resource_remove(char: Character, p: dict, ctx):
    res = _resource(char, p["resource_id"])
    char.resources.remove(res)
    return {"operation_type": "character.resource.add",
            "payload": res.model_dump()}, [
        {"type": "resource.usage.changed",
         "payload": {"resource_removed": res.name}}]


@op("character.item.attune")
def item_attune(char: Character, p: dict, ctx):
    """Sintoniza un objeto mágico — máximo 3 (SRD)."""
    item = next((i for i in char.inventory if i.id == p["item_id"]), None)
    if item is None:
        raise ValueError("objeto no encontrado")
    # no-op en item ya sintonizado → inversa neutra: antes el undo
    # de un attune redundante DESsintonizaba un objeto legítimo
    inv = {"operation_type": "character.item.unattune"
           if not item.attuned else "character.item.noop",
           "payload": {"item_id": item.id}}
    if not item.attuned:
        limit = rules()["combat"]["attunement_max"]
        attuned = sum(1 for i in char.inventory if i.attuned)
        if attuned >= limit:
            raise ValueError(f"máximo {limit} objetos sintonizados")
        item.attuned = True
    return inv, [{"type": "inventory.item.transferred",
                  "payload": {"attuned": item.name}}]


@op("character.item.unattune")
def item_unattune(char: Character, p: dict, ctx):
    item = next((i for i in char.inventory if i.id == p["item_id"]), None)
    if item is None:
        raise ValueError("objeto no encontrado")
    item.attuned = False
    return {"operation_type": "character.item.attune",
            "payload": {"item_id": item.id}}, [
        {"type": "inventory.item.transferred",
         "payload": {"unattuned": item.name}}]


@op("character.inspiration.set")
def inspiration_set(char: Character, p: dict, ctx):
    inv = {"operation_type": "character.inspiration.set",
           "payload": {"value": char.inspiration}}
    char.inspiration = bool(p.get("value", True))
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"inspiration": char.inspiration}}]


@op("character.item.noop")
def item_noop(char: Character, p: dict, ctx):
    """Inversa neutra: el handler padre no mutó nada (p.ej. equipar
    algo ya equipado) — sin ella el undo rompería estado legítimo."""
    return {"operation_type": "character.item.noop",
            "payload": p}, []


@op("character.item.equip")
def item_equip(char: Character, p: dict, ctx):
    """Equipa un objeto (armadura/escudo/arma) — la CA derivada lo
    refleja automáticamente."""
    item = next((i for i in char.inventory if i.id == p["item_id"]), None)
    if item is None:
        raise ValueError("objeto no encontrado")
    # equipar algo ya equipado no muta — la inversa no puede ser
    # unequip (desequiparía y, peor, borraría la sintonía)
    already = item.equipped and not p.get("restore_attuned")
    item.equipped = True
    if p.get("restore_attuned"):            # deshacer un unequip
        item.attuned = True
    return {"operation_type": "character.item.noop" if already
            else "character.item.unequip",
            "payload": {"item_id": item.id}}, [
        {"type": "inventory.item.transferred",
         "payload": {"equipped": item.name}}]


@op("character.item.unequip")
def item_unequip(char: Character, p: dict, ctx):
    item = next((i for i in char.inventory if i.id == p["item_id"]), None)
    if item is None:
        raise ValueError("objeto no encontrado")
    was_attuned = item.attuned
    item.equipped = False
    item.attuned = False       # desequipar rompe la sintonía
    return {"operation_type": "character.item.equip",
            "payload": {"item_id": item.id, "restore_attuned":
                        was_attuned}}, [
        {"type": "inventory.item.transferred",
         "payload": {"unequipped": item.name}}]


def _item(char: Character, item_id: str):
    it = next((i for i in char.inventory if i.id == item_id), None)
    if it is None:
        raise ValueError("objeto no encontrado")
    return it


@op("character.item.charge.set")
def item_charge_set(char: Character, p: dict, ctx):
    """Configura cargas de un objeto (varita, pergamino…).
    `max` fija el tope
    `current` opcional (por defecto = max, recarga
    completa). `max: 0` desactiva las cargas. Reversible."""
    it = _item(char, p["item_id"])
    old = {"charges": it.charges, "charges_max": it.charges_max}
    new_max = int(p["max"])
    if new_max <= 0:
        it.charges = it.charges_max = None
    else:
        it.charges_max = new_max
        it.charges = min(new_max,
                         int(p.get("current", new_max)))
    return {"operation_type": "character.item.charge.restore",
            "payload": {"item_id": it.id, **old}}, [
        {"type": "inventory.item.charged",
         "payload": {"item": it.name,
                     "charges": it.charges,
                     "charges_max": it.charges_max}}]


@op("character.item.charge.use")
def item_charge_use(char: Character, p: dict, ctx):
    it = _item(char, p["item_id"])
    amount = int(p.get("amount", 1))
    if it.charges is None or it.charges < amount:
        raise ValueError("sin cargas suficientes")
    it.charges -= amount
    return {"operation_type": "character.item.charge.restore",
            "payload": {"item_id": it.id,
                        "charges": it.charges + amount,
                        "charges_max": it.charges_max}}, [
        {"type": "inventory.item.charged",
         "payload": {"item": it.name, "charges": it.charges,
                     "charges_max": it.charges_max}}]


@op("character.item.charge.restore")
def item_charge_restore(char: Character, p: dict, ctx):
    """Restaura cargas a un valor absoluto (descanso, recarga,
    corrección). Reversible."""
    it = _item(char, p["item_id"])
    old = {"charges": it.charges, "charges_max": it.charges_max}
    it.charges = p.get("charges")
    it.charges_max = p.get("charges_max", it.charges_max)
    return {"operation_type": "character.item.charge.restore",
            "payload": {"item_id": it.id, **old}}, [
        {"type": "inventory.item.charged",
         "payload": {"item": it.name, "charges": it.charges,
                     "charges_max": it.charges_max}}]


@op("character.item.weight.set")
def item_weight_set(char: Character, p: dict, ctx):
    """Peso en libras del objeto (capacidad de carga)."""
    it = _item(char, p["item_id"])
    old = it.weight
    it.weight = max(0.0, float(p["weight"]))
    return {"operation_type": "character.item.weight.set",
            "payload": {"item_id": it.id, "weight": old}}, [
        {"type": "inventory.item.transferred",
         "payload": {"weight": it.name, "value": it.weight}}]


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


@op("character.pin")
def pin_item(char: Character, p: dict, ctx):
    """Fija un ataque/conjuro/objeto en el resumen (favoritos)."""
    pid = p["id"]
    if pid not in char.pinned:
        char.pinned.append(pid)
    return {"operation_type": "character.unpin",
            "payload": {"id": pid}}, [
        {"type": "resource.usage.changed",
         "payload": {"pinned": pid}}]


@op("character.unpin")
def unpin_item(char: Character, p: dict, ctx):
    pid = p["id"]
    if pid in char.pinned:
        char.pinned.remove(pid)
    return {"operation_type": "character.pin",
            "payload": {"id": pid}}, []


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


@op("character.feat.learn")
def feat_learn(char: Character, p: dict, ctx):
    fid = p["feat_id"]
    if fid in char.feats_known:
        raise ValueError("dote ya conocida")
    # snapshot: la dote puede subir características (ASI fija) —
    # feat.forget como inversa no revertiría esos puntos
    inv = _restore_inverse(char.model_dump())
    char.feats_known.append(fid)
    # Dotes con mejora fija de característica (5etools ability:[{str:1}])
    asi = []
    feat = _content(ctx, fid) or {}
    from ..domain.classinfo import _SHORT_2_LONG
    for grp in feat.get("ability") or []:
        if isinstance(grp, dict):
            for k, v in grp.items():
                if k in _SHORT_2_LONG and isinstance(v, int):
                    attr = _SHORT_2_LONG[k]
                    setattr(char.abilities, attr,
                            getattr(char.abilities, attr) + v)
                    asi.append(f"{k} +{v}")
    return inv, [
        {"type": "resource.usage.changed",
         "payload": {"feat_learned": fid,
                     **({"asi": asi} if asi else {})}}]


@op("character.feat.forget")
def feat_forget(char: Character, p: dict, ctx):
    fid = p["feat_id"]
    if fid not in char.feats_known:
        raise ValueError("dote no conocida")
    # snapshot: si la dote subía características hay que REVERTIR esos
    # bonos — antes forget los dejaba y su inversa (feat.learn) los
    # volvía a aplicar: ASI duplicado tras undo
    inv = _restore_inverse(char.model_dump())
    char.feats_known.remove(fid)
    feat = _content(ctx, fid) or {}
    from ..domain.classinfo import _SHORT_2_LONG
    for grp in feat.get("ability") or []:
        if isinstance(grp, dict):
            for k, v in grp.items():
                if k in _SHORT_2_LONG and isinstance(v, int):
                    attr = _SHORT_2_LONG[k]
                    setattr(char.abilities, attr,
                            getattr(char.abilities, attr) - v)
    return inv, []


def _list_add_remove(lst: list, value: str, add: bool):
    if add:
        if value in lst:
            raise ValueError("ya presente")
        lst.append(value)
    else:
        if value not in lst:
            raise ValueError("no presente")
        lst.remove(value)


@op("character.feature.add")
def feature_add(char: Character, p: dict, ctx):
    """Rasgo opcional elegido manualmente (invocación, infusión,
    maniobra…). Si viene entity id se guarda el nombre real."""
    name = p.get("name")
    if not name and p.get("entity_id") and ctx is not None:
        try:
            row = ctx.content_db().execute(
                "SELECT name FROM content_entities WHERE id = ?",
                (p["entity_id"],)).fetchone()
            name = row["name"] if row else None
        except Exception:      # noqa: BLE001
            name = None
    name = (name or "").strip()
    if not name:
        raise ValueError("feature name requerido")
    _list_add_remove(char.features, name, True)
    return {"operation_type": "character.feature.remove",
            "payload": {"name": name}}, []


@op("character.feature.remove")
def feature_remove(char: Character, p: dict, ctx):
    _list_add_remove(char.features, p["name"], False)
    return {"operation_type": "character.feature.add",
            "payload": {"name": p["name"]}}, []


@op("character.subclass.set")
def subclass_set(char: Character, p: dict, ctx):
    """Fija la subclase de la clase indicada (índice en classes[])."""
    idx = int(p.get("class_index", 0))
    if not (0 <= idx < len(char.classes)):
        raise ValueError("class_index fuera de rango")
    old = char.classes[idx].subclass_id
    char.classes[idx].subclass_id = p["subclass_id"]
    return {"operation_type": "character.subclass.set",
            "payload": {"class_index": idx, "subclass_id": old}}, [
        {"type": "resource.usage.changed",
         "payload": {"subclass_set": p["subclass_id"]}}]


@op("character.identity.set")
def identity_set(char: Character, p: dict, ctx):
    """Edita identidad de cabecera de la hoja oficial: name, alignment,
    player_name, speed, species_id, background_id — reversible.
    field='speeds' actualiza una velocidad extra {fly: 40} (0 la quita)."""
    field = p["field"]
    allowed = {"name", "alignment", "player_name", "speed",
               "species_id", "background_id", "speeds", "senses"}
    if field not in allowed:
        raise ValueError(f"campo no editable: {field}")
    inv = {"operation_type": "character.identity.set",
           "payload": {"field": field, "value": getattr(char, field)}}
    if field == "speeds":
        prev = dict(char.speeds)
        for kind, v in (p.get("value") or {}).items():
            v = int(v)
            if v > 0:
                char.speeds[kind] = v
            else:
                char.speeds.pop(kind, None)
        inv = {"operation_type": "character.speeds.set",
               "payload": {"speeds": prev}}
        return inv, [{"type": "resource.usage.changed",
                      "payload": {"identity": "speeds"}}]
    value = int(p["value"]) if field == "speed" else p.get("value", "")
    setattr(char, field, value)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"identity": field}}]


@op("character.speeds.set")
def speeds_set(char: Character, p: dict, ctx):
    """Restaura el mapa completo de velocidades (inversa de
    identity.set field=speeds)."""
    prev = dict(char.speeds)
    char.speeds = {k: int(v) for k, v in (p.get("speeds") or {}).items()}
    return {"operation_type": "character.speeds.set",
            "payload": {"speeds": prev}}, []


@op("character.language.add")
def language_add(char: Character, p: dict, ctx):
    name = p["name"].strip().lower()
    _list_add_remove(char.languages, name, True)
    return {"operation_type": "character.language.remove",
            "payload": {"name": name}}, []


@op("character.language.remove")
def language_remove(char: Character, p: dict, ctx):
    name = p["name"].strip().lower()
    _list_add_remove(char.languages, name, False)
    return {"operation_type": "character.language.add",
            "payload": {"name": name}}, []


@op("character.reward.add")
def reward_add(char: Character, p: dict, ctx):
    rid = p["reward_id"]
    _list_add_remove(char.rewards, rid, True)
    return {"operation_type": "character.reward.remove",
            "payload": {"reward_id": rid}}, [
        {"type": "resource.usage.changed",
         "payload": {"reward_added": rid}}]


@op("character.reward.remove")
def reward_remove(char: Character, p: dict, ctx):
    rid = p["reward_id"]
    _list_add_remove(char.rewards, rid, False)
    return {"operation_type": "character.reward.add",
            "payload": {"reward_id": rid}}, []


@op("character.proficiency.add")
def proficiency_add(char: Character, p: dict, ctx):
    """Añade competencia: kind = skill|save|other (skill/save alimentan
    las tiradas automáticas
    'other' cubre armaduras, armas y
    herramientas como en la caja 'otras competencias' de la hoja)."""
    kind, name = p["kind"], p["name"].lower()
    lst = {"skill": char.skill_proficiencies,
           "save": char.save_proficiencies,
           "other": char.other_proficiencies}.get(kind)
    if lst is None:
        raise ValueError("kind debe ser skill|save|other")
    if name in lst:
        raise ValueError("ya competente")
    lst.append(name)
    return {"operation_type": "character.proficiency.remove",
            "payload": p}, [{"type": "resource.usage.changed",
                             "payload": {"proficiency": f"{kind}:{name}"}}]


@op("character.proficiency.remove")
def proficiency_remove(char: Character, p: dict, ctx):
    kind, name = p["kind"], p["name"].lower()
    lst = {"skill": char.skill_proficiencies,
           "save": char.save_proficiencies,
           "other": char.other_proficiencies}.get(kind)
    if lst is None or name not in lst:
        raise ValueError("competencia no encontrada")
    lst.remove(name)
    return {"operation_type": "character.proficiency.add",
            "payload": p}, []


@op("character.narrative.set")
def narrative_set(char: Character, p: dict, ctx):
    """Edita campos de trasfondo narrativo (personality, ideals, bonds,
    flaws, appearance, backstory) — reversible."""
    field = p["field"]
    if field not in Narrative.model_fields or field == "journal":
        raise ValueError(f"campo narrativo no editable: {field}")
    inv = {"operation_type": "character.narrative.set",
           "payload": {"field": field,
                       "value": getattr(char.narrative, field)}}
    setattr(char.narrative, field, p.get("value", ""))
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"narrative": field}}]


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
    from ..domain.character import InventoryItem
    import uuid as _uuid
    char.inventory.append(InventoryItem(
        id=_uuid.uuid4().hex, name=output["name"],
        quantity=int(output.get("quantity", 1))))
    return _restore_inverse(before), [
        {"type": "inventory.item.transferred",
         "payload": {"crafted": output["name"],
                     "consumed": [i["name"] for i in inputs]}}]


def _content(ctx, entity_id: str) -> dict | None:
    """Lee una entidad de la content DB (None si no hay ctx/DB)."""
    try:
        row = ctx.content_db().execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (entity_id,)).fetchone()
    except Exception:
        return None
    return json.loads(row["data"]) if row else None


def _resource(char: Character, rid: str):
    for r in char.resources:
        if r.id == rid:
            return r
    raise ValueError(f"resource not found: {rid}")


def _restore_resources(char: Character, resets: set[str]) -> None:
    for r in char.resources:
        if r.reset_on in resets:
            r.current = r.max


def _run_trigger(char: Character, trigger: Trigger) -> None:
    """Aplica los Effect con este trigger (p.ej. 'regain ki on short rest')."""
    from .engine import apply_triggered
    apply_triggered(char, trigger)


@op("noop")
def noop(entity, p: dict, ctx):
    """Inversa de operaciones sin efecto (condición inmune, remove
    sobre ausente, tiradas puras)."""
    return {"operation_type": "noop", "payload": {}}, []


def apply_operation(char: Character, operation_type: str,
                    payload: dict, ctx=None) -> tuple[dict, list[dict]]:
    handler = HANDLERS.get(operation_type)
    if handler is None:
        raise KeyError(f"unknown operation: {operation_type}")
    return handler(char, payload, ctx)
