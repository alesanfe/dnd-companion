"""Extractores de info de clase/especie/trasfondo — multi-schema.

Usados por la creación de personaje (api/characters.py) y por el
render de entidades (domain/render.py).
"""
from __future__ import annotations

import re

_ABILITY_SHORT = {"strength": "str", "dexterity": "dex",
                  "constitution": "con", "intelligence": "int",
                  "wisdom": "wis", "charisma": "cha"}
_SHORT_2_LONG = {v: k for k, v in _ABILITY_SHORT.items()}


def hit_die(cls: dict) -> int:
    """Dado de golpe: 5e-bits hit_die=12 · 5etools hd.faces ·
    open5e '1d12' · codexMUNDI hitDie · dnd-data properties."""
    props = cls.get("properties") or {}
    for cand in (cls.get("hit_die"), (cls.get("hd") or {}).get("faces"),
                 cls.get("hit_dice"), cls.get("hitDie"),
                 props.get("Hit Dice")):
        if cand:
            s = str(cand)
            m = re.search(r"d(\d+)", s) or re.search(r"\d+", s)
            if m:
                return int(m.group(1) if m.re.pattern.startswith("d")
                           else m.group())
    return 8


def save_profs(cls: dict) -> list[str]:
    """Salvaciones competentes: saving_throws[] · proficiency[] ·
    prof_saving_throws · saves."""
    out: list[str] = []

    def add(v):
        key = _ABILITY_SHORT.get(str(v).strip().lower(),
                                 str(v).strip().lower()[:3])
        if key in _ABILITY_SHORT.values() and key not in out:
            out.append(key)

    for s in cls.get("saving_throws") or []:
        add((s.get("index") or s.get("name", ""))
            if isinstance(s, dict) else s)
    for s in cls.get("proficiency") or []:
        add(s)
    for s in (cls.get("prof_saving_throws")
              or cls.get("saves") or "").split(","):
        add(s)
    return out


def species_asi(sp: dict) -> dict[str, int]:
    """ASI fijas de especie (ignora 'choose'): ability_bonuses[] ·
    ability[] multi-schema."""
    out: dict[str, int] = {}
    for b in sp.get("ability_bonuses") or []:
        if isinstance(b, dict):
            ab = (b.get("ability_score") or {}).get("index")
            if ab in _ABILITY_SHORT.values() and isinstance(
                    b.get("bonus"), int):
                out[ab] = out.get(ab, 0) + b["bonus"]
    for grp in sp.get("ability") or []:
        if isinstance(grp, dict):
            for k, v in grp.items():
                if k in _ABILITY_SHORT.values() and isinstance(v, int):
                    out[k] = out.get(k, 0) + v
    return out


def species_traits(sp: dict) -> list[str]:
    """Nombres de rasgos raciales: 5e-bits traits[] · 5etools
    entries[].name."""
    out = []
    for t in sp.get("traits") or []:
        out.append(t.get("name") if isinstance(t, dict) else str(t))
    for e in sp.get("entries") or []:
        if isinstance(e, dict) and e.get("name"):
            out.append(str(e["name"]))
    return [t for t in out if t]


def background_languages(bg: dict) -> list[str]:
    """Lenguas concedidas: 5e-bits language_options (choose → no fija)
    · 5etools languageProficiencies / languages."""
    out: list[str] = []
    for grp in bg.get("languageProficiencies") or []:
        if isinstance(grp, dict):
            out.extend(k for k, v in grp.items()
                       if v is True and k != "choose")
    for l in bg.get("languages") or []:
        if isinstance(l, str):
            out.append(l)
    return out


def background_skills(bg: dict) -> list[str]:
    """Skills del trasfondo: starting_proficiencies[] ·
    skillProficiencies[]."""
    out: list[str] = []
    for pr in bg.get("starting_proficiencies") or []:
        name = (pr.get("name") or "") if isinstance(pr, dict) else str(pr)
        if name.lower().startswith("skill:"):
            out.append(name.split(":", 1)[1].strip().lower())
    for grp in bg.get("skillProficiencies") or []:
        if isinstance(grp, dict):
            out.extend(k for k, v in grp.items()
                       if v is True and k != "choose")
    return out
