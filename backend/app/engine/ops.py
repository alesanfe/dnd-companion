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

Handler = Callable[[Character, dict], tuple[dict, list[dict]]]
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
def hp_damage(char: Character, p: dict):
    inv = _set_inverse(char)
    amount = max(0, int(p["amount"]))
    absorbed = min(char.hp.temp, amount)
    char.hp.temp -= absorbed
    char.hp.current = max(0, char.hp.current - (amount - absorbed))
    return inv, [{"type": "character.hp.changed",
                  "payload": {"amount": amount, "temp_absorbed": absorbed,
                              "current": char.hp.current}}]


@op("character.hp.heal")
def hp_heal(char: Character, p: dict):
    inv = _set_inverse(char)
    amount = max(0, int(p["amount"]))
    char.hp.current = min(char.hp.max, char.hp.current + amount)
    return inv, [{"type": "character.hp.changed",
                  "payload": {"healed": amount, "current": char.hp.current}}]


@op("character.hp.set")
def hp_set(char: Character, p: dict):
    inv = _set_inverse(char)
    char.hp.current = max(0, min(char.hp.max, int(p["current"])))
    char.hp.temp = max(0, int(p.get("temp", char.hp.temp)))
    return inv, [{"type": "character.hp.changed",
                  "payload": {"current": char.hp.current,
                              "temp": char.hp.temp}}]


@op("character.condition.apply")
def condition_apply(char: Character, p: dict):
    cond = p["condition"]
    inv = {"operation_type": "character.condition.remove",
           "payload": {"condition": cond}}
    if cond not in char.conditions:
        char.conditions.append(cond)
    return inv, [{"type": "character.condition.applied",
                  "payload": {"condition": cond}}]


@op("character.condition.remove")
def condition_remove(char: Character, p: dict):
    cond = p["condition"]
    inv = {"operation_type": "character.condition.apply",
           "payload": {"condition": cond}}
    if cond in char.conditions:
        char.conditions.remove(cond)
    return inv, [{"type": "character.condition.removed",
                  "payload": {"condition": cond}}]


@op("character.resource.consume")
def resource_consume(char: Character, p: dict):
    res = _resource(char, p["resource_id"])
    amount = max(0, int(p.get("amount", 1)))
    inv = {"operation_type": "character.resource.restore",
           "payload": {"resource_id": res.id, "amount": min(amount, res.current)}}
    res.current = max(0, res.current - amount)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"resource_id": res.id, "current": res.current}}]


@op("character.resource.restore")
def resource_restore(char: Character, p: dict):
    res = _resource(char, p["resource_id"])
    amount = max(0, int(p.get("amount", res.max)))
    inv = {"operation_type": "character.resource.consume",
           "payload": {"resource_id": res.id,
                       "amount": min(amount, res.max - res.current)}}
    res.current = min(res.max, res.current + amount)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"resource_id": res.id, "current": res.current}}]


@op("character.spell_slot.use")
def slot_use(char: Character, p: dict):
    lvl = str(p["level"])
    slot = char.spell_slots.setdefault(lvl, {"total": 0, "used": 0})
    inv = {"operation_type": "character.spell_slot.restore",
           "payload": {"level": int(lvl), "count": 1}}
    slot["used"] = min(slot["total"], slot["used"] + 1)
    return inv, [{"type": "resource.usage.changed",
                  "payload": {"spell_slot": lvl, "used": slot["used"]}}]


@op("character.hit_die.spend")
def hit_die_spend(char: Character, p: dict):
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
def hit_die_unspend(char: Character, p: dict):
    pool = char.hit_dice[int(p.get("pool", 0))]
    pool.remaining = min(pool.total, pool.remaining + 1)
    char.hp.current = max(0, char.hp.current - int(p["healed"]))
    return {"operation_type": "character.hit_die.spend",
            "payload": {"pool": int(p.get("pool", 0))}}, []


@op("character.rest.short")
def rest_short(char: Character, p: dict):
    before = char.model_dump()
    _restore_resources(char, {"short"})
    _run_trigger(char, Trigger.ON_SHORT_REST)
    return _restore_inverse(before), [{"type": "character.hp.changed",
                                       "payload": {"rest": "short"}}]


@op("character.rest.long")
def rest_long(char: Character, p: dict):
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
def state_restore(char: Character, p: dict):
    """Undo de operaciones complejas: restaura un snapshot previo."""
    current = char.model_dump()
    restored = Character(**p["data"])
    char.__dict__.update(restored.__dict__)
    return {"operation_type": "character.state.restore",
            "payload": {"data": current}}, []


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
                    payload: dict) -> tuple[dict, list[dict]]:
    handler = HANDLERS.get(operation_type)
    if handler is None:
        raise KeyError(f"unknown operation: {operation_type}")
    return handler(char, payload)
