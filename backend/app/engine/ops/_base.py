"""Operation handlers — núcleo compartido.

    handler(char, payload, ctx) -> (inverse_op, [event_payloads])

inverse_op = {"operation_type": ..., "payload": ...} que deshace el
cambio. Los eventos describen qué pasó para broadcast WS + log.

Split de ops.py (AU-22): este módulo lleva el registro (HANDLERS,
apply_operation, _sync_combat) y los helpers que usan los dominios;
los handlers viven en vitals.py, gear.py, magic.py, growth.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable

from ...domain.character import Character, Narrative
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll

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


def _damage_mult(char: Character, dtype: str) -> tuple[float, list]:
    """Multiplicador por inmunidad/resistencia/vulnerabilidad
    declarativas (grant_*) filtradas por tipo de daño o '*' →
    (mult, [notas])."""
    mult, applied = 1.0, []
    for eff in char.effects:
        # pasivos + triggers de contexto de daño (un grant bajo
        # before_damage/after_damage ES de este momento); el resto
        # de triggers no son propiedades permanentes
        if eff.trigger is not None and eff.trigger not in (
                Trigger.BEFORE_DAMAGE, Trigger.AFTER_DAMAGE):
            continue
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


_COIN_CP = {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}


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


def _slots_for(char: Character, lvl: str, pool: str | None):
    """El pool de espacios a usar: 'pact' = pacto del brujo,
    'regular' = normal; sin pool → pacto si existe ese nivel."""
    if pool == "pact":
        return char.pact_slots
    if pool == "regular" or not char.pact_slots:
        return char.spell_slots
    return char.pact_slots if lvl in char.pact_slots else char.spell_slots


def _restore_inverse(before: dict) -> dict:
    return {"operation_type": "character.state.restore",
            "payload": {"data": before}}


def _bump_class(char: Character, class_id: str, hit_die: int) -> int:
    """+1 nivel en la clase (o entrada nueva en multiclase) y su dado
    de golpe. Devuelve el nivel resultante."""
    from ...domain.character import ClassLevel, HitDicePool
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
    # el id de clase viene en formatos distintos por fuente —
    # 'class:warlock' (5e-bits), 'warlock|phb' (5etools), 'warlock'
    # solo: 'warlock' como PALABRA en cualquier segmento cubre todos
    # sin depender de cuál separador usa la fuente
    is_warlock = "warlock" in class_id.lower() \
        .replace("|", " ").replace(":", " ").replace("-", " ").split()
    target = char.pact_slots if is_warlock else char.spell_slots
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
            from ...domain.character import Resource
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


def _weapon_props(w: dict) -> set:
    """Propiedades del arma normalizadas a minúsculas. Los esquemas
    divergen: 'properties' como lista de dicts {index|name} (5e-bits,
    Open5e), 'property' como strings o lista (5etools: 'F'=finesse),
    o un dict suelto. Un `.get` sobre strings petaba con
    AttributeError y 'property' no se leía (finesse → FUE siempre)."""
    props = w.get("properties") or w.get("property") or []
    if isinstance(props, dict):
        props = list(props)
    elif not isinstance(props, list):
        props = [props]
    return {
        (str(x.get("index") or x.get("name") or "").lower()
         if isinstance(x, dict) else str(x).lower())
        for x in props}


def _is_finesse(w: dict) -> bool:
    props = _weapon_props(w)
    return bool(props & {"finesse", "f"}) or "ranged" in \
        str(w.get("weapon_range", "")).lower()


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


_CP = _COIN_CP


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
    from ...domain.classinfo import spellcasting_ability
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


def _item(char: Character, item_id: str):
    it = next((i for i in char.inventory if i.id == item_id), None)
    if it is None:
        raise ValueError("objeto no encontrado")
    return it


def _list_add_remove(lst: list, value: str, add: bool):
    if add:
        if value in lst:
            raise ValueError("ya presente")
        lst.append(value)
    else:
        if value not in lst:
            raise ValueError("no presente")
        lst.remove(value)


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


def _run_trigger(char: Character, trigger: Trigger,
                 ctx: dict | None = None) -> None:
    """Aplica los Effect con este trigger (p.ej. 'regain ki on short rest').
    `ctx` nutre las EffectCondition ('damage.amount', 'attack.hit'…)."""
    from ..engine import apply_triggered
    apply_triggered(char, trigger, ctx)


_VITAL_OPS = {
    "character.hp.damage", "character.hp.heal", "character.hp.set",
    "character.death_save", "character.state.restore",
    "character.rest.short", "character.rest.long", "character.level_up",
    "character.tick", "character.condition.apply",
    "character.condition.remove", "character.hit_die.spend",
    "character.hit_die.unspend",
}


def _sync_combat(char: Character, ctx) -> None:
    """Espejo inverso de combat_ops._sync_character: si la ficha está
    en un combate activo de su campaña, el combatiente vinculado sigue
    el estado vital de la hoja. Sin esto, daño/curación/salvaciones
    aplicadas desde la ficha del jugador dejaban el tracker del DM
    desfasado hasta que alguien tocaba el combate."""
    cid = getattr(ctx, "entity_id", None)
    conn = getattr(ctx, "state_db", lambda: None)()
    if cid is None or conn is None:
        return
    row = conn.execute(
        "SELECT campaign_id FROM characters WHERE id = ?",
        (cid,)).fetchone()
    if row is None or not row["campaign_id"]:
        return
    from ...domain.combat import Combat
    rows = conn.execute(
        """SELECT id, data, version FROM combats
           WHERE campaign_id = ?
             AND json_extract(data,'$.status') = 'active'""",
        (row["campaign_id"],)).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        combat = Combat(**json.loads(r["data"]))
        cbt = next((c for c in combat.combatants
                    if c.kind == "character" and c.ref_id == cid), None)
        if cbt is None:
            continue
        before = cbt.model_dump_json()
        cbt.hp_current = char.hp.current
        cbt.hp_temp = char.hp.temp
        cbt.hp_max = char.hp.max
        cbt.death_saves = dict(char.death_saves)
        # solo las condiciones de estado vital — igual que
        # _sync_character no toca el resto del tracker
        for cond in ("muerto", "dead", "estable"):
            if cond in char.conditions and cond not in cbt.conditions:
                cbt.conditions.append(cond)
            elif cond not in char.conditions and \
                    cond in cbt.conditions:
                cbt.conditions.remove(cond)
        if cbt.model_dump_json() == before:
            continue                    # nada vital cambió → no bump
        cur = conn.execute(
            "UPDATE combats SET data = ?, version = ?, updated_at = ?"
            " WHERE id = ? AND version = ?",
            (combat.model_dump_json(), r["version"] + 1, now,
             r["id"], r["version"]))
        if cur.rowcount == 0:
            raise ValueError("el combate vinculado cambió durante la"
                             " op de ficha — reintenta")


def apply_operation(char: Character, operation_type: str,
                    payload: dict, ctx=None) -> tuple[dict, list[dict]]:
    handler = HANDLERS.get(operation_type)
    if handler is None:
        raise KeyError(f"unknown operation: {operation_type}")
    result = handler(char, payload, ctx)
    if operation_type in _VITAL_OPS:
        _sync_combat(char, ctx)
    return result
