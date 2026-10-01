"""Handlers de combate — tiradas del tracker: iniciativa, saves, acciones, checks y combat.attack."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from ...domain import statblock
from ...domain.combat import Combat, Combatant, hp_state
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll
from ._base import (
    COMBAT_HANDLERS, op, SKILL_ABILITY, _apply_dmg, _char_trigger, _double_dice, _find, _hp_inverse, _sync_character, _typed_amount, _weapon_attack, op
)

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
    from ...domain.conditions import mods_for, pen_for
    adv, dis, fail, notes = mods_for(c.conditions, f"save:{ability}",
                                     ruleset=combat.ruleset)
    # 2024: agotamiento = -2×nivel fijo (no desventaja)
    pen = pen_for(c.conditions, None, combat.ruleset)
    if pen:
        notes.append(f"agotamiento: -{pen} (2024)")
        total_mod -= pen
    if fail:
        return {"operation_type": "noop", "payload": {}}, [
            {"type": "dice.roll.created",
             "payload": {"combatant": c.name, "save": ability,
                         "auto_fail": True, "notes": notes}}]
    r = roll("1d20adv" if adv and not dis else
             "1d20dis" if dis and not adv else "1d20")
    total = r.total + total_mod
    dc = p.get("dc")
    if dc is not None:
        # triggers declarativos del PJ: "al superar/fallar salvación…"
        ok = total >= int(dc)
        _char_trigger(ctx, c,
                      Trigger.ON_SAVE_SUCCESS if ok
                      else Trigger.ON_SAVE_FAILURE,
                      {"save": {"ability": ability, "total": total,
                                "dc": int(dc), "success": ok}})
    return {"operation_type": "noop", "payload": {}}, [
        {"type": "dice.roll.created",
         "payload": {"combatant": c.name, "save": ability,
                     "roll": r.total, "total": total,
                     **({"dc": int(dc)} if dc is not None else {}),
                     **({"notes": notes} if notes else {})}}]


@op("combatant.action.roll")
def combatant_action_roll(combat: Combat, p: dict, ctx):
    """Rueda una acción del stat block del combatiente: parsea el texto
    normalizado buscando 'to hit' (+N) y dados de daño (NdM±K), y tira
    ambos. Acciones de salvación emiten la CD detectada."""
    import re
    c = _find(combat, p["combatant_id"])
    from ...domain.conditions import is_incapacitated, mods_for, pen_for
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

    adv, dis, _fail, notes = mods_for(c.conditions, "attack",
                                      ruleset=combat.ruleset)
    pen = pen_for(c.conditions, None, combat.ruleset)
    if pen:
        notes.append(f"agotamiento: -{pen} (2024)")
    # marcadores de maestría 2024 también en el stat block del monstruo
    markers = ("vex" in c.conditions) or ("sap" in c.conditions)
    inv = ({"operation_type": "combat.state.restore",
            "payload": {"data": combat.model_dump()}}
           if markers else {"operation_type": "noop", "payload": {}})
    if "vex" in c.conditions:
        adv = True
        c.conditions.remove("vex")
        notes.append("vex → ventaja (maestría)")
    if "sap" in c.conditions:
        dis = True
        c.conditions.remove("sap")
        notes.append("sap → desventaja (maestría)")
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
        mod = int(m_hit.group(1)) - pen
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
    return inv, [ev]


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
    from ...domain.conditions import mods_for, pen_for
    adv, dis, _fail, notes = mods_for(c.conditions, "check",
                                      ruleset=combat.ruleset)
    pen = pen_for(c.conditions, None, combat.ruleset)
    if pen:
        notes.append(f"agotamiento: -{pen} (2024)")
        total_mod -= pen
    r = roll("1d20adv" if adv and not dis else
             "1d20dis" if dis and not adv else "1d20")
    return {"operation_type": "noop", "payload": {}}, [
        {"type": "dice.roll.created",
         "payload": {"combatant": c.name, "skill": skill,
                     "roll": r.total, "total": r.total + total_mod,
                     "mod": total_mod,
                     **({"notes": notes} if notes else {})}}]


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
    from ...domain.conditions import is_incapacitated, mods_for, pen_for
    incap = is_incapacitated(atk.conditions)
    if incap:
        raise ValueError(f"{atk.name} está incapacitado ({incap})")
    row = ctx.state_db().execute(
        "SELECT data FROM characters WHERE id = ?",
        (atk.ref_id,)).fetchone()
    if row is None:
        raise ValueError("ficha del atacante no encontrada")
    from ...domain.character import Character
    char = Character(**json.loads(row["data"]))
    item, mod, hit_bonus, dmg_dice, dtype, wpn = _weapon_attack(
        char, str(p.get("item_name", "")), ctx)
    dtype = (p.get("damage_type") or dtype or "")
    # mismas reglas de condición que /character/attack + modo manual.
    # El agotamiento y las condiciones de la HOJA viven en la ficha —
    # el combatiente solo espeja las vitales, así que se unen ambas
    all_conds = list(set(atk.conditions) | set(char.conditions))
    char_rs = getattr(char.ruleset, "value", char.ruleset)
    adv, dis, fail, notes = mods_for(all_conds, "attack",
                                     char.condition_stacks,
                                     char_rs)
    pen = pen_for(all_conds, char.condition_stacks, char_rs)
    if pen:
        notes.append(f"agotamiento: -{pen} (2024)")
        hit_bonus -= pen
    mode = str(p.get("mode", "normal"))
    if mode == "adv":
        adv = True
    elif mode == "dis":
        dis = True
    # maestría de arma (2024): el arma declara su propiedad y los
    # marcadores 'vex' (ventaja) / 'sap' (desventaja) de impactos
    # previos se consumen aquí. Solo en combates con reglas 2024;
    # use_mastery=false lo desactiva por si el PJ no es competente.
    use_mastery = bool(p.get(
        "use_mastery", combat.ruleset == "dnd5e-2024"))
    from ..ops import _item_versatile, _weapon_mastery
    mastery = _weapon_mastery(wpn) if use_mastery else None
    # snapshot completo cuando hay marcadores/maestría que tocar:
    # hp.set solo restaura las condiciones del OBJETIVO, no las del
    # atacante ('vex'/'sap' consumidos)
    needs_full_inv = mastery is not None or \
        "vex" in atk.conditions or "sap" in atk.conditions
    before = combat.model_dump() if needs_full_inv else None
    if "vex" in atk.conditions:
        adv = True
        atk.conditions.remove("vex")
        notes.append("vex → ventaja (maestría)")
    if "sap" in atk.conditions:
        dis = True
        atk.conditions.remove("sap")
        notes.append("sap → desventaja (maestría)")
    hit = roll("1d20adv" if adv and not dis else
               "1d20dis" if dis and not adv else "1d20")
    hit_total = hit.total + hit_bonus
    crit = bool(hit.rolls) and max(hit.rolls) >= \
        rules()["combat"].get("attack_crit_on", 20)
    ac = tgt.ac or (tgt.stat_block or {}).get("ac", 10)
    hits = not fail and (crit or hit_total >= ac)
    # on_hit/on_miss del atacante (p.ej. "al impactar, restaura ki")
    # — muta la ficha; la guardia de versión la hace conflict-safe
    _char_trigger(ctx, atk, Trigger.ON_HIT if hits else Trigger.ON_MISS,
                  {"attack": {"hit": hits, "item": item.name,
                              "target": tgt.name}})
    ev = {"type": "dice.roll.created", "payload": {
        "combatant": atk.name, "attack": item.name, "target": tgt.name,
        "roll": hit.total, "total": hit_total, "hits": hits,
        **({"crit": True} if crit else {}),
        **({"notes": notes} if notes else {})}}
    if mastery:
        ev["payload"]["mastery"] = mastery
    full_inv = ({"operation_type": "combat.state.restore",
                 "payload": {"data": before}} if before else None)
    if not hits:
        # graze (2024): en fallo inflige daño = mod de característica
        if mastery == "gra":
            graze = max(0, mod)
            if graze:
                dmg_payload = _apply_dmg(tgt, graze, "graze")
                ev["payload"]["damage"] = graze
                _sync_character(tgt, ctx)
                return full_inv or _hp_inverse(tgt), [
                    ev, {"type": "character.hp.changed",
                         "payload": dmg_payload}]
        return (full_inv or
                {"operation_type": "noop", "payload": {}}, [ev])
    # efecto de maestría sobre el impacto — lo automático lo aplica el
    # motor; las cadenas de ataques extra (cleave/nick) solo se anotan
    if mastery == "flex":
        dmg_dice = _item_versatile(wpn) or dmg_dice
    elif mastery == "vex":
        if "vex" not in atk.conditions:
            atk.conditions.append("vex")
    elif mastery == "sap":
        if "sap" not in tgt.conditions:
            tgt.conditions.append("sap")
    elif mastery == "slow":
        if "slow" not in tgt.conditions:
            tgt.conditions.append("slow")
    elif mastery == "push":
        ev["payload"]["push_ft"] = 10    # el DM mueve el token
    elif mastery == "topple":
        con = ((tgt.stat_block or {}).get("abilities") or {}) \
            .get("con") or (tgt.stat_block or {}).get(
                "constitution") or 10
        con_mod = ((tgt.stat_block or {}).get("saves") or {}) \
            .get("con", (con - 10) // 2)
        dc = 8 + char.proficiency_bonus + mod
        sv = roll("1d20")
        ev["payload"]["topple_save"] = {
            "roll": sv.total + con_mod, "dc": dc,
            "prone": sv.total + con_mod < dc}
        if sv.total + con_mod < dc:
            tgt.conditions.append("prone")
    elif mastery in ("cleave", "nick"):
        ev["payload"]["mastery_note"] = (
            "cleave: ataque extra a un 2º objetivo a 5 ft" if
            mastery == "cleave" else
            "nick: ataque ligero extra sin gastar acción adicional")
    expr = _double_dice(dmg_dice) if crit else dmg_dice
    dmg_total = roll(f"{expr}{mod:+d}").total
    inv = full_inv or _hp_inverse(tgt)
    amount, note = _typed_amount(tgt, dmg_total, dtype.strip().lower())
    dmg_payload = _apply_dmg(tgt, amount, note)
    ev["payload"]["damage"] = amount
    _sync_character(tgt, ctx)
    return inv, [ev, {"type": "character.hp.changed",
                      "payload": dmg_payload}]
