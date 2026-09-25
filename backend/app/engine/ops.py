"""Operation handlers — every state change is applied here and returns
the inverse operation so it can be undone. Signature:

    handler(char, payload) -> (inverse_op, [event_payloads])

inverse_op = {"operation_type": ..., "payload": ...} that would undo the
change. Events describe what happened for WS broadcast + log.
"""
from __future__ import annotations

from typing import Callable

from ..domain.character import Character
from ..domain.effects import Trigger
from .dice import roll

Handler = Callable[[Character, dict, object], tuple[dict, list[dict]]]
HANDLERS: dict[str, Handler] = {}


def op(name: str):
    def wrap(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn
    return wrap


def _set_inverse(char: Character) -> dict:
    return {"operation_type": "character.hp.set",
            "payload": {"current": char.hp.current, "temp": char.hp.temp}}


@op("character.hp.damage")
def hp_damage(char: Character, p: dict, ctx):
    inv = _set_inverse(char)
    amount = max(0, int(p["amount"]))
    # resistencia/vulnerabilidad/inmunidad declarativas por tipo de daño
    dtype = str(p.get("type", "")).lower()
    mult, applied = 1.0, []
    for eff in char.effects:
        for o in eff.operations:
            tgt = (o.target or "").lower()
            if dtype and tgt not in (dtype, "*"):
                continue
            if o.op.value == "grant_immunity":
                mult = 0.0; applied.append(f"{eff.name}: inmunidad")
            elif o.op.value == "grant_resistance" and mult > 0.5:
                mult = 0.5; applied.append(f"{eff.name}: resistencia")
            elif o.op.value == "grant_vulnerability":
                mult *= 2.0; applied.append(f"{eff.name}: vulnerabilidad")
    amount = int(amount * mult)
    absorbed = min(char.hp.temp, amount)
    char.hp.temp -= absorbed
    char.hp.current = max(0, char.hp.current - (amount - absorbed))
    payload = {"amount": amount, "temp_absorbed": absorbed,
               "current": char.hp.current}
    if applied:
        payload["damage_effects"] = applied
        payload["damage_type"] = dtype
    if char.concentrating_on:
        # recibir daño exige tirada de CON: CD máx(10, daño/2)
        payload["concentration_check"] = True
        payload["concentration_dc"] = max(10, amount // 2)
        payload["spell"] = char.concentrating_on
    return inv, [{"type": "character.hp.changed", "payload": payload}]


@op("character.death_save")
def death_save(char: Character, p: dict, ctx):
    """Salvación de muerte (a 0 PG). El cliente pasa 'roll' (1d20 ya
    tirado): ≥10 éxito, <10 fallo, 1 = doble fallo, 20 = se recupera
    con 1 PG. Tres éxitos estabiliza, tres fallos es la muerte."""
    if char.hp.current > 0:
        raise ValueError("el personaje no está a 0 PG")
    inv = _set_inverse(char)
    roll = int(p["roll"])
    result = None
    if roll >= 20:
        char.hp.current = 1
        char.death_saves = {"success": 0, "fail": 0}
        result = "20 natural — recupera 1 PG"
    elif roll == 1:
        char.death_saves["fail"] = min(3, char.death_saves["fail"] + 2)
        result = "1 natural — doble fallo"
    elif roll >= 10:
        char.death_saves["success"] += 1
        result = "éxito"
    else:
        char.death_saves["fail"] += 1
        result = "fallo"
    if char.death_saves["fail"] >= 3:
        result += " — muerte"
        if "muerto" not in char.conditions:
            char.conditions.append("muerto")
    return inv, [{"type": "character.hp.changed",
                  "payload": {"death_save": roll, "result": result,
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
    return inv, [{"type": "character.hp.changed",
                  "payload": {"current": char.hp.current,
                              "temp": char.hp.temp}}]


@op("character.condition.apply")
def condition_apply(char: Character, p: dict, ctx):
    cond = p["condition"]
    inv = {"operation_type": "character.condition.remove",
           "payload": {"condition": cond}}
    if cond not in char.conditions:
        char.conditions.append(cond)
    return inv, [{"type": "character.condition.applied",
                  "payload": {"condition": cond}}]


@op("character.condition.remove")
def condition_remove(char: Character, p: dict, ctx):
    cond = p["condition"]
    inv = {"operation_type": "character.condition.apply",
           "payload": {"condition": cond}}
    if cond in char.conditions:
        char.conditions.remove(cond)
    return inv, [{"type": "character.condition.removed",
                  "payload": {"condition": cond}}]


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


@op("character.spell_slot.use")
def slot_use(char: Character, p: dict, ctx):
    lvl = str(p["level"])
    slot = char.spell_slots.setdefault(lvl, {"total": 0, "used": 0})
    inv = {"operation_type": "character.spell_slot.restore",
           "payload": {"level": int(lvl), "count": 1}}
    slot["used"] = min(slot["total"], slot["used"] + 1)
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
    pool = char.hit_dice[int(p.get("pool", 0))]
    pool.remaining = min(pool.total, pool.remaining + 1)
    char.hp.current = max(0, char.hp.current - int(p["healed"]))
    return {"operation_type": "character.hit_die.spend",
            "payload": {"pool": int(p.get("pool", 0))}}, []


@op("character.rest.short")
def rest_short(char: Character, p: dict, ctx):
    before = char.model_dump()
    _restore_resources(char, {"short"})
    _run_trigger(char, Trigger.ON_SHORT_REST)
    return _restore_inverse(before), [{"type": "character.hp.changed",
                                       "payload": {"rest": "short"}}]


@op("character.rest.long")
def rest_long(char: Character, p: dict, ctx):
    before = char.model_dump()
    char.hp.current = char.hp.max
    char.hp.temp = 0
    for slot in char.spell_slots.values():
        slot["used"] = 0
    # recupera la mitad de los dados de golpe (mín 1) por nivel total
    regain = max(1, char.total_level // 2)
    for pool in char.hit_dice:
        take = min(regain, pool.total - pool.remaining)
        pool.remaining += take
        regain -= take
    _restore_resources(char, {"short", "long"})
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
    return {"operation_type": "character.state.restore",
            "payload": {"data": current}}, []


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
    entry = next((c for c in char.classes if c.class_id == class_id), None)
    cls_data = _content(ctx, class_id)
    hit_die = _class_hit_die(cls_data or {})
    if entry is None:
        from ..domain.character import ClassLevel, HitDicePool
        char.classes.append(ClassLevel(class_id=class_id, level=1))
        char.hit_dice.append(HitDicePool(die=f"d{hit_die}", total=1,
                                         remaining=1))
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
            from ..domain.character import HitDicePool
            char.hit_dice.append(HitDicePool(die=f"d{hit_die}", total=1,
                                             remaining=1))

    # HP: fijo = hit_die/2 + 1 + CON ; tirado = rolled + CON
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
    if lvl:
        char.proficiency_bonus = int(lvl.get("prof_bonus",
                                             char.proficiency_bonus))
        sc = lvl.get("spellcasting") or {}
        for n in range(1, 10):
            slots = sc.get(f"spell_slots_level_{n}", 0)
            if slots:
                char.spell_slots[str(n)] = {"total": slots, "used": 0}

    # Rasgos ganados en este nivel — dos vías:
    #  5e-bits: entidad 'level' con features:[{name}]
    #  5etools: entidades 'class-feature' con className+level
    gained: list[str] = []
    for f in (lvl or {}).get("features") or []:
        gained.append(f.get("name") if isinstance(f, dict) else str(f))
    cls_name = (cls_data or {}).get("name")
    if cls_name and ctx is not None:
        try:
            rows = ctx.content_db().execute(
                """SELECT data FROM content_entities
                   WHERE entity_type = 'class-feature'
                   AND json_extract(data, '$.level') = ?
                   AND lower(json_extract(data, '$.className')) =
                       lower(?)""",
                (new_level, cls_name)).fetchall()
            gained += [json.loads(r["data"]).get("name", "?")
                       for r in rows]
        except Exception:      # noqa: BLE001 - features best-effort
            pass
    # Rasgos de SUBCLASE: si la clase tiene subclass_id, sus features
    # llevan subclassShortName = nombre de la subclase (5etools).
    sub_id = next(
        (c.subclass_id for c in char.classes if c.class_id == class_id),
        None)
    if sub_id and ctx is not None:
        try:
            srow = ctx.content_db().execute(
                "SELECT name FROM content_entities WHERE id = ?",
                (sub_id,)).fetchone()
            sub_name = srow["name"] if srow else None
            if sub_name:
                rows = ctx.content_db().execute(
                    """SELECT data FROM content_entities
                       WHERE entity_type = 'class-feature'
                       AND json_extract(data, '$.level') = ?
                       AND lower(json_extract(data,
                             '$.subclassShortName')) = lower(?)""",
                    (new_level, sub_name)).fetchall()
                gained += [json.loads(r["data"]).get("name", "?")
                           for r in rows]
        except Exception:      # noqa: BLE001 - subclass features best-effort
            pass
    for name in gained:
        if name and name not in char.features:
            char.features.append(name)

    _run_trigger(char, Trigger.ON_LEVEL_UP)
    return _restore_inverse(before), [
        {"type": "character.hp.changed",
         "payload": {"level_up": class_id, "level": new_level,
                     "hp_max": char.hp.max,
                     "features_gained": gained}}]


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


@op("character.inventory.add")
def inventory_add(char: Character, p: dict, ctx):
    import uuid as _uuid
    from ..domain.character import InventoryItem
    item = InventoryItem(
        id=p.get("id") or _uuid.uuid4().hex,
        name=p["name"],
        quantity=int(p.get("quantity", 1)),
        equipped=bool(p.get("equipped", False)),
        source_id=p.get("source_id"),
    )
    char.inventory.append(item)
    return {"operation_type": "character.inventory.remove",
            "payload": {"item_id": item.id, "quantity": item.quantity}}, [
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
    inv = {"operation_type": "character.currency.spend",
           "payload": dict(p)}
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
    import json as _json
    row = ctx.state_db().execute(
        "SELECT data FROM campaign_entities WHERE id = ?",
        (p["shop_id"],)).fetchone()
    if row is None:
        raise ValueError("tienda no encontrada")
    shop = _json.loads(row["data"])
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
    ctx.state_db().execute(
        "UPDATE campaign_entities SET data = ? WHERE id = ?",
        (_json.dumps(shop), p["shop_id"]))
    # inversa real: devuelve objeto, repone stock y reembolsa monedas
    inv = {"operation_type": "character.shop.refund",
           "payload": {"shop_id": p["shop_id"], "item": p["item"],
                       "price_cp": price_cp}}
    return inv, [
        {"type": "inventory.item.transferred",
         "payload": {"bought": p["item"], "price_cp": price_cp,
                     "purse": char.purse}}]


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


@op("character.spell.cast")
def spell_cast(char: Character, p: dict, ctx):
    """Lanza un conjuro: consume espacio (si level>0), marca
    concentración si el conjuro la requiere. Reversible via snapshot."""
    spell_id = p["spell_id"]
    level = int(p.get("level", 0))
    sp = _content(ctx, spell_id) or {}
    spell_level = int(sp.get("level")
                      or (sp.get("properties") or {}).get("Level") or 0)
    # upcasting válido; no se puede lanzar un conjuro por debajo de su nivel
    if level and level < spell_level:
        raise ValueError(
            f"espacio insuficiente: {sp.get('name')} es de nivel {spell_level}")
    if not level:
        level = spell_level
    before = char.model_dump()
    if level > 0:
        slot = char.spell_slots.setdefault(
            str(level), {"total": 0, "used": 0})
        if slot["used"] >= slot["total"]:
            raise ValueError(f"sin espacios de nivel {level}")
        slot["used"] += 1
    # concentración: "yes" (5e-bits/open5e), true, o flag en
    # duration[] (5etools: duration:[{concentration:true}])
    conc = sp.get("concentration")
    needs_conc = conc in (True, "yes", "Yes") or any(
        d.get("concentration") for d in sp.get("duration") or []
        if isinstance(d, dict))
    if needs_conc:
        char.concentrating_on = sp.get("name", spell_id)

    # Datos de juego del conjuro desde su entidad: CD de salvación
    # (8 + prof + mod de lanzamiento de la clase), tirada de ataque de
    # conjuro y daño escalado al nivel del espacio consumido.
    payload = {"spell_cast": sp.get("name", spell_id),
               "level": level,
               "concentration": char.concentrating_on}
    cast_ability = None
    if char.classes:
        cls_data = _content(ctx, char.classes[0].class_id) or {}
        from ..domain.classinfo import spellcasting_ability
        cast_ability = spellcasting_ability(cls_data)
    spell_dc = None
    if cast_ability:
        spell_dc = 8 + char.proficiency_bonus + \
            char.abilities.modifier(cast_ability)
    if spell_dc and (sp.get("savingThrow") or sp.get("saves")
                     or sp.get("saving_throws") or sp.get("dc")):
        payload["spell_dc"] = spell_dc
    needs_attack = sp.get("attack") or sp.get("spellAttack") \
        or (sp.get("meta") or {}).get("attack") \
        or "spell attack" in str(sp.get("desc")
                                 or sp.get("entries") or "")
    if needs_attack and cast_ability:
        atk = roll("1d20")
        atk_mod = char.proficiency_bonus + char.abilities.modifier(
            cast_ability)
        payload.update(spell_attack_roll=atk.total,
                       spell_attack_total=atk.total + atk_mod,
                       spell_attack_mod=atk_mod)
    # daño escalado por espacio: damage_at_slot_level{slot:dice}
    dmg_map = {}
    for d in sp.get("damage") or []:
        if isinstance(d, dict) and d.get("damage_at_slot_level"):
            dmg_map.update(d["damage_at_slot_level"])
        elif isinstance(d, dict) and d.get("damage_at_character_level"):
            dmg_map.update(d["damage_at_character_level"])
    expr = dmg_map.get(str(level)) or dmg_map.get(
        str(spell_level)) or sp.get("dmg1")
    if expr:
        payload.update(damage_expr=str(expr),
                       damage_total=roll(str(expr)).total)
    return _restore_inverse(before), [
        {"type": "resource.usage.changed", "payload": payload}]


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
    inv = {"operation_type": "character.xp.add",
           "payload": {"amount": -amount}}
    char.xp = max(0, char.xp + amount)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"xp": char.xp, "delta": amount}}]


@op("character.shop.refund")
def shop_refund(char: Character, p: dict, ctx):
    """Inversa real de shop.buy: devuelve el objeto, repone el stock y
    reembolsa las monedas — todo en la transacción de la operación."""
    if ctx is None or ctx.state_db() is None:
        raise ValueError("shop.refund requiere contexto de estado")
    import json as _json
    item = next((i for i in char.inventory if i.name == p["item"]), None)
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
        shop = _json.loads(row["data"])
        for s in shop.get("stock", []):
            if s.get("name") == p["item"]:
                s["quantity"] = s.get("quantity", 0) + 1
                break
        ctx.state_db().execute(
            "UPDATE campaign_entities SET data = ? WHERE id = ?",
            (_json.dumps(shop), p["shop_id"]))
    return {"operation_type": "character.shop.buy",
            "payload": {"shop_id": p["shop_id"], "item": p["item"]}}, [
        {"type": "inventory.item.transferred",
         "payload": {"refunded": p["item"], "price_cp": price_cp}}]


@op("character.journal.add")
def journal_add(char: Character, p: dict, ctx):
    """Entrada de diario/crónicas — reversible."""
    entry = p["entry"]
    char.narrative.journal.append(entry)
    return {"operation_type": "character.journal.pop",
            "payload": {}}, [
        {"type": "inventory.item.transferred",
         "payload": {"journal_entry": entry}}]


@op("character.journal.pop")
def journal_pop(char: Character, p: dict, ctx):
    entry = char.narrative.journal.pop() if char.narrative.journal else None
    return {"operation_type": "character.journal.add",
            "payload": {"entry": entry}}, []


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
    inv = {"operation_type": "character.item.unattune",
           "payload": {"item_id": item.id}}
    if not item.attuned:
        attuned = sum(1 for i in char.inventory if i.attuned)
        if attuned >= 3:
            raise ValueError("máximo 3 objetos sintonizados")
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


@op("character.item.equip")
def item_equip(char: Character, p: dict, ctx):
    """Equipa un objeto (armadura/escudo/arma) — la CA derivada lo
    refleja automáticamente."""
    item = next((i for i in char.inventory if i.id == p["item_id"]), None)
    if item is None:
        raise ValueError("objeto no encontrado")
    item.equipped = True
    if p.get("restore_attuned"):            # deshacer un unequip
        item.attuned = True
    return {"operation_type": "character.item.unequip",
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


@op("character.spell.learn")
def spell_learn(char: Character, p: dict, ctx):
    sid = p["spell_id"]
    if sid in char.spells_known:
        raise ValueError("conjuro ya conocido")
    char.spells_known.append(sid)
    return {"operation_type": "character.spell.forget",
            "payload": {"spell_id": sid}}, [
        {"type": "resource.usage.changed",
         "payload": {"spell_learned": sid}}]


@op("character.spell.forget")
def spell_forget(char: Character, p: dict, ctx):
    sid = p["spell_id"]
    if sid not in char.spells_known:
        raise ValueError("conjuro no conocido")
    char.spells_known.remove(sid)
    return {"operation_type": "character.spell.learn",
            "payload": {"spell_id": sid}}, []


@op("character.feat.learn")
def feat_learn(char: Character, p: dict, ctx):
    fid = p["feat_id"]
    if fid in char.feats_known:
        raise ValueError("dote ya conocida")
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
    return {"operation_type": "character.feat.forget",
            "payload": {"feat_id": fid}}, [
        {"type": "resource.usage.changed",
         "payload": {"feat_learned": fid,
                     **({"asi": asi} if asi else {})}}]


@op("character.feat.forget")
def feat_forget(char: Character, p: dict, ctx):
    fid = p["feat_id"]
    if fid not in char.feats_known:
        raise ValueError("dote no conocida")
    char.feats_known.remove(fid)
    return {"operation_type": "character.feat.learn",
            "payload": {"feat_id": fid}}, []


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
    """Añade competencia: kind = skill|save (usa las listas
    especializadas que alimentan las tiradas automáticas)."""
    kind, name = p["kind"], p["name"].lower()
    lst = {"skill": char.skill_proficiencies,
           "save": char.save_proficiencies}.get(kind)
    if lst is None:
        raise ValueError("kind debe ser skill|save")
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
           "save": char.save_proficiencies}.get(kind)
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
    inv = {"operation_type": "character.narrative.set",
           "payload": {"field": field,
                       "value": getattr(char.narrative, field, None)}}
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
    import json as _json
    try:
        row = ctx.content_db().execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (entity_id,)).fetchone()
    except Exception:
        return None
    return _json.loads(row["data"]) if row else None


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


def apply_operation(char: Character, operation_type: str,
                    payload: dict, ctx=None) -> tuple[dict, list[dict]]:
    handler = HANDLERS.get(operation_type)
    if handler is None:
        raise KeyError(f"unknown operation: {operation_type}")
    return handler(char, payload, ctx)
