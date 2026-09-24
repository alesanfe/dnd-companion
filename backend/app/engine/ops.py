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
    absorbed = min(char.hp.temp, amount)
    char.hp.temp -= absorbed
    char.hp.current = max(0, char.hp.current - (amount - absorbed))
    payload = {"amount": amount, "temp_absorbed": absorbed,
               "current": char.hp.current}
    if char.concentrating_on:
        # recibir daño exige tirada de CON para mantener el conjuro
        payload["concentration_check"] = True
        payload["spell"] = char.concentrating_on
    return inv, [{"type": "character.hp.changed", "payload": payload}]


@op("character.hp.heal")
def hp_heal(char: Character, p: dict, ctx):
    inv = _set_inverse(char)
    amount = max(0, int(p["amount"]))
    char.hp.current = min(char.hp.max, char.hp.current + amount)
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
    entry = next((c for c in char.classes if c.class_id == class_id), None)
    cls_data = _content(ctx, class_id)
    hit_die = int((cls_data or {}).get("hit_die", 8))
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

    _run_trigger(char, Trigger.ON_LEVEL_UP)
    return _restore_inverse(before), [
        {"type": "character.hp.changed",
         "payload": {"level_up": class_id, "level": new_level,
                     "hp_max": char.hp.max}}]


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
    before = char.model_dump()
    if level > 0:
        slot = char.spell_slots.setdefault(
            str(level), {"total": 0, "used": 0})
        if slot["used"] >= slot["total"]:
            raise ValueError(f"sin espacios de nivel {level}")
        slot["used"] += 1
    if sp.get("concentration") == "yes":
        char.concentrating_on = sp.get("name", spell_id)
    return _restore_inverse(before), [
        {"type": "resource.usage.changed",
         "payload": {"spell_cast": sp.get("name", spell_id),
                     "level": level,
                     "concentration": char.concentrating_on}}]


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
