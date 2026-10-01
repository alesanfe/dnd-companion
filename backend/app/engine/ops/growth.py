"""Handlers growth: nivel, XP, ASI, dotes, rasgos, identidad, diario y metadatos de ficha."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ...domain.character import Character, Narrative
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll
from ._base import (
    HANDLERS,
    _apply_level_row,
    _asi_gained,
    _bump_class,
    _content,
    _level_features,
    _level_resources,
    _list_add_remove,
    _resource,
    _restore_inverse,
    _run_trigger,
    op,
)

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
    from ...domain.classinfo import hit_die as _class_hit_die
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


@op("character.effect.add")
def effect_add(char: Character, p: dict, ctx):
    """Añade un Effect declarativo (rasgo, aura, homebrew…)."""
    import uuid as _uuid
    from ...domain.effects import Effect
    eff = Effect(**{**p["effect"], "id": p["effect"].get("id")
                    or _uuid.uuid4().hex})
    if any(e.id == eff.id for e in char.effects):
        raise ValueError(f"efecto duplicado: {eff.id}")
    char.effects.append(eff)
    # on_apply: el propio efecto recién añadido (y otros con ese
    # trigger) ejecuta sus ops mutantes — "al aplicar furia, -1 carga"
    _run_trigger(char, Trigger.ON_APPLY)
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
    # on_remove ANTES de quitarlo: su propio trigger "al retirarse"
    # debe disparar (p.ej. "al caer la furia, gana agotamiento")
    _run_trigger(char, Trigger.ON_REMOVE)
    eff = char.effects.pop(idx)
    return {"operation_type": "character.effect.add",
            "payload": {"effect": eff.model_dump(mode="json")}}, [
        {"type": "character.condition.removed",
         "payload": {"effect": eff.name}}]


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
        from ...domain.classinfo import asi_earned
        if char.asi_used + cost > asi_earned(char, ctx.content_db()):
            raise ValueError(
                "sin mejoras de característica disponibles")
    before = char.asi_used
    inv = {"operation_type": "character.state.restore",
           "payload": {"data": char.model_dump()}}
    from ...domain.character import _ABILITY_ALIASES as _AL
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
        from ...domain.classinfo import asi_earned
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
    from ...domain.character import Resource
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
    from ...domain.classinfo import _SHORT_2_LONG
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
    from ...domain.classinfo import _SHORT_2_LONG
    for grp in feat.get("ability") or []:
        if isinstance(grp, dict):
            for k, v in grp.items():
                if k in _SHORT_2_LONG and isinstance(v, int):
                    attr = _SHORT_2_LONG[k]
                    setattr(char.abilities, attr,
                            getattr(char.abilities, attr) - v)
    return inv, []


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
