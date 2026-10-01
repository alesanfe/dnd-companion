"""Modificadores de tirada de ficha — lógica pura extraída de
api/operations.py (AU-22): modificador automático por tipo, efectos
declarativos, reglas de condición y penalizador de agotamiento 2024.
Sin dependencias de FastAPI/DB — también usable desde el engine."""
from __future__ import annotations

import re

from ..domain.character import Character
# Las reglas de condición viven en domain/conditions.py (compartidas
# con los combatientes); aquí solo se consultan para el personaje.
from ..domain.conditions import mods_for as _condition_mods_raw, pen_for


def _norm(s: str) -> str:
    """Normaliza ids de habilidad: 'sleight of hand' ≡
    'sleight-of-hand'."""
    return s.strip().lower().replace("-", " ")


# SRD 2014: habilidad → característica (nombre de habilidad en inglés)
_SKILL_ABILITIES = {
    "athletics": "str",
    "acrobatics": "dex", "sleight-of-hand": "dex", "stealth": "dex",
    "arcana": "int", "history": "int", "investigation": "int",
    "nature": "int", "religion": "int",
    "animal-handling": "wis", "insight": "wis", "medicine": "wis",
    "perception": "wis", "survival": "wis",
    "deception": "cha", "intimidation": "cha", "performance": "cha",
    "persuasion": "cha",
}


def _auto_modifier(char: Character, roll_type: str,
                   applied: list) -> int:
    """Modificador automático según tipo: check:dex, save:wis,
    skill:x — incluye competencia en salvación/habilidad."""
    extra = 0
    base_type, _, detail = roll_type.partition(":")
    detail = detail.strip().lower()
    if base_type in ("check", "save") and detail:
        extra += char.abilities.modifier(detail)
        applied.append(f"{detail}: {char.abilities.modifier(detail):+d}")
        if base_type == "save" and _norm(detail) in {
                _norm(x) for x in char.save_proficiencies}:
            extra += char.proficiency_bonus
            applied.append(f"prof: +{char.proficiency_bonus}")
    elif base_type == "skill" and detail:
        ability = _SKILL_ABILITIES.get(
            detail, _SKILL_ABILITIES.get(_norm(detail).replace(" ", "-"),
                                         "int"))
        extra += char.abilities.modifier(ability)
        applied.append(f"{ability}({detail}): "
                       f"{char.abilities.modifier(ability):+d}")
        if _norm(detail) in {_norm(x) for x in char.skill_proficiencies}:
            extra += char.proficiency_bonus
            applied.append(f"prof: +{char.proficiency_bonus}")
    return extra


def _effect_modifiers(char: Character, roll_type: str, adv: bool,
                      dis: bool, extra_mod: int, applied: list):
    """Mods declarativos de efectos pasivos / before_roll que
    aplican a esta tirada. Devuelve (adv, dis, extra_mod)."""
    for eff in char.effects:
        if eff.trigger is not None and eff.trigger.value != "before_roll":
            continue
        for o in eff.operations:
            tgt = o.target or ""
            if tgt not in (roll_type, f"*.{roll_type}", "*", "roll"):
                continue
            if o.op.value == "grant_advantage":
                adv = True
                applied.append(f"{eff.name}: ventaja")
            elif o.op.value == "grant_disadvantage":
                dis = True
                applied.append(f"{eff.name}: desventaja")
            elif o.op.value == "add_modifier" and o.value is not None:
                extra_mod += int(o.value)
                applied.append(f"{eff.name}: {int(o.value):+d}")
    return adv, dis, extra_mod


def _condition_mods(char: Character, roll_type: str):
    """Deriva ventaja/desventaja/autofallo desde char.conditions,
    leyendo el nivel de agotamiento de condition_stacks."""
    return _condition_mods_raw(char.conditions, roll_type,
                               char.condition_stacks,
                               getattr(char.ruleset, "value",
                                       char.ruleset))


def _exhaustion_pen(char: Character) -> int:
    """Penalizador -2×nivel a d20 del agotamiento 2024 (en 2014 la
    mecánica es ventaja/desventaja y va por mods_for)."""
    return pen_for(char.conditions, char.condition_stacks,
                   getattr(char.ruleset, "value", char.ruleset))


def _augment_expr(char, expr: str, roll_type: str,
                  use_inspiration: bool,
                  applied: list) -> tuple[str, bool]:
    """Inspiración + modificadores declarativos + reglas de condición
    sobre la expresión de dados. Devuelve (expr', auto_fail)."""
    adv = bool(use_inspiration and char.inspiration)
    if adv:
        applied.append("inspiración: ventaja")   # el cliente la consume
        # via la op inspiration.set{value:false} tras la tirada
    extra_mod = _auto_modifier(char, roll_type, applied)
    adv, dis, extra_mod = _effect_modifiers(char, roll_type, adv,
                                            False, extra_mod, applied)
    c_adv, c_dis, fail, c_notes = _condition_mods(char, roll_type)
    adv = adv or c_adv
    dis = dis or c_dis
    applied += c_notes
    if fail:
        return expr, True
    if "adv" not in expr and "dis" not in expr and "d20" in expr:
        # adv/dis va pegado al d20, ANTES del modificador —
        # "1d20+5adv" no parsea (el regex exige keep antes del mod)
        if adv and not dis:
            expr = _insert_keep(expr, "adv")
        elif dis and not adv:
            expr = _insert_keep(expr, "dis")
    pen = _exhaustion_pen(char)          # 2024: -2×nivel a d20 tests
    if pen and "d20" in expr:
        extra_mod -= pen
        applied.append(f"agotamiento: -{pen} (2024)")
    if extra_mod:
        expr += f"{extra_mod:+d}"
    return expr, False


def _insert_keep(expr: str, keep: str) -> str:
    """'1d20+5'+adv → '1d20adv+5': adv/dis va pegado AL d20, no antes
    del último modificador — '1d20+3adv+2' no parseaba (400 falso en
    ataques con bono compuesto)."""
    m = re.search(r"\d*d20", expr)
    return expr[:m.end()] + keep + expr[m.end():] if m else expr + keep
