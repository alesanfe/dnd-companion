"""Normalizador de stat blocks de monstruo.

La content DB agrega fuentes con schemas muy distintos:

  5e-bits SRD      hit_points, armor_class:[{value}], strength…,
                   challenge_rating, speed:{walk:"10 ft."}, actions[{desc}]
  Open5e v1        hit_points, armor_class:int, strength…, cr:float,
                   speed:{walk:10}, actions[{desc}]
  Open5e v2        hit_points, armor_class:int, ability_scores:{},
                   saving_throws:{} (totales), modifiers:{}
  5etools          hp:{average,formula}, ac:[12|{ac}], str…, cr:"1/4",
                   save:{str:"+5"}, speed:{walk:30}, action[{entries[]}]
  codexMUNDI       hp:"13 (3d8)", ac:"12", str…, cr:"1/4",
                   speed:str, action[{text}]
  dnd-data         properties:{…} (scrape D&D Beyond)

``normalize`` devuelve el bloque canónico usado por el tracker:

  {hp, ac, cr, abilities{str..cha}, saves{str..cha} (totales),
   initiative_mod, speed (texto), actions:[{name, text}]}
"""
from __future__ import annotations

import re

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
_LONG = {"str": "strength", "dex": "dexterity", "con": "constitution",
         "int": "intelligence", "wis": "wisdom", "cha": "charisma"}

_TAG_RE = re.compile(r"\{@\w+\s+([^}|]+?)(?:\|[^}]*)?\}|\{@\w+}")


def _mod(score: int) -> int:
    return (int(score) - 10) // 2


def _int(v, default=10) -> int:
    try:
        return int(str(v).split()[0].strip("()+"))
    except (TypeError, ValueError, IndexError):
        return default


def _cr_float(v) -> float:
    s = str(v or "0").split()[0]
    if "/" in s:
        try:
            a, b = s.split("/", 1)
            return float(a) / float(b)
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _abilities(d: dict) -> dict[str, int]:
    scores = d.get("ability_scores") or {}
    mods = d.get("modifiers") or {}
    out = {}
    for a in ABILITIES:
        v = (d.get(_LONG[a])            # 5e-bits / open5e v1
             or d.get(a)                # 5etools / codexmundi
             or scores.get(_LONG[a])    # open5e v2
             or (mods.get(_LONG[a], 0) + 10 if _LONG[a] in mods else None))
        out[a] = _int(v, 10)
    return out


def _saves(d: dict, abilities: dict) -> dict[str, int]:
    """Salvaciones como total fijo; default = modificador de stat."""
    out = {}
    explicit = d.get("saving_throws") or d.get("save") or {}
    for a in ABILITIES:
        v = explicit.get(_LONG[a]) or explicit.get(a)
        if v is None:
            v = d.get(f"{_LONG[a]}_save")          # 5e-bits
        out[a] = _int(v, _mod(abilities[a])) if v is not None \
            else _mod(abilities[a])
    return out


def _hp(d: dict) -> int:
    hp = d.get("hit_points") or d.get("hp")
    if isinstance(hp, dict):
        hp = hp.get("average")
    if hp is None:
        hp = (d.get("properties") or {}).get("Hit Points")
    return _int(hp, 1)


def _ac(d: dict) -> int:
    ac = d.get("armor_class") if "armor_class" in d else d.get("ac")
    if isinstance(ac, list):
        first = ac[0] if ac else 10
        ac = first.get("ac", first.get("value", 10)) \
            if isinstance(first, dict) else first
    if ac is None:
        ac = (d.get("properties") or {}).get("Armor Class")
    return _int(ac, 10)


def _speed(d: dict) -> str:
    sp = d.get("speed")
    if isinstance(sp, dict):
        parts = [f"{k} {v} ft." for k, v in sp.items()
                 if isinstance(v, (int, float, str)) and k != "unit"]
        return ", ".join(parts)
    return str(sp or "")


def _clean_text(s: str) -> str:
    """Expande tags 5etools: {@damage 1d4} -> 1d4, {@hit 2} -> +2."""
    s = _TAG_RE.sub(lambda m: m.group(1) or "", s)
    return re.sub(r"\s+", " ", s).strip()


def _actions(d: dict) -> list[dict]:
    acts = d.get("actions") or d.get("action") or []
    out = []
    for a in acts:
        if not isinstance(a, dict):
            continue
        text = (a.get("desc") or a.get("text")
                or " ".join(str(e) for e in (a.get("entries") or [])))
        out.append({"name": a.get("name", "?"),
                    "text": _clean_text(text)})
    return out


def normalize(data: dict | None) -> dict | None:
    """Stat block canónico + original bajo ``raw``. None si no hay data."""
    if not isinstance(data, dict) or not data:
        return None
    abilities = _abilities(data)
    return {
        "name": data.get("name"),
        "hp": _hp(data),
        "ac": _ac(data),
        "cr": _cr_float(
            (lambda c: c.get("cr") if isinstance(c, dict) else c)(
                data.get("challenge_rating", data.get("cr")))
            or (data.get("properties") or {}).get("Challenge Rating")),
        "abilities": abilities,
        "saves": _saves(data, abilities),
        "initiative_mod": _mod(abilities["dex"]),
        "speed": _speed(data),
        "actions": _actions(data),
        "raw": data,
    }
