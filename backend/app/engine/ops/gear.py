"""Handlers gear: inventario, monedas, tienda, equipamiento y ataque."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ...domain.character import Character, Narrative
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll
from ._base import (
    HANDLERS,
    _COIN_CP,
    _CP,
    _content,
    _item,
    _item_damage,
    _item_weight,
    _normalize_purse,
    _purse_cp,
    _spend,
    _weapon_props,
    op,
)

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
        finesse = bool(_weapon_props(w) & {"finesse", "f"})
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
    from ...domain.character import InventoryItem
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
