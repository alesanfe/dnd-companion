"""Render canónico de entidades de contenido por tipo.

Complementa statblock.normalize (monstruos): aquí se normalizan
conjuros, objetos, dotes/features, razas/especies, clases y el resto
de tipos del corpus a campos comunes para la UI.

Salida: {kind, name, subtitle, fields:[{label, value}], desc, tags}.
"""
from __future__ import annotations

import re

_TAG_RE = re.compile(r"\{@\w+\s+([^}|]+?)(?:\|[^}]*)?\}|\{@\w+}")


def clean(s) -> str:
    """Texto 5etools/HTML → plano legible."""
    if s is None:
        return ""
    if isinstance(s, list):
        s = " ".join(str(x) for x in s)
    s = _TAG_RE.sub(lambda m: m.group(1) or "", str(s))
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _entries(d: dict) -> str:
    for k in ("desc", "entries", "description", "text"):
        v = d.get(k)
        if isinstance(v, list):
            return " ".join(clean(x) for x in v)
        if v:
            return clean(v)
    return ""


def _f(label, value):
    if value in (None, "", []):
        return None
    v = clean(value)
    # chips: nunca un párrafo entero — el detalle va en desc
    if len(v) > 140:
        v = v[:137].rstrip() + "…"
    return {"label": label, "value": v}


def _prereq(v) -> str:
    """Normaliza prerequisite/prerequisites: texto, dict o
    [{'ability_score':{name}, minimum_score}] → 'STR 13'."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        ab = v.get("ability_score") or {}
        if ab:
            return f"{ab.get('name', '?')} {v.get('minimum_score', '')}".strip()
        return _names(v.get("options")) or ""
    if isinstance(v, list):
        return ", ".join(p for p in (_prereq(x) for x in v) if p)
    return ""


def _filter(fields):
    return [f for f in fields if f]


def _spell_duration(d: dict):
    """Duración: str suelto o lista 5etools [{type, concentration}]."""
    duration = d.get("duration")
    if isinstance(duration, list):
        duration = ", ".join(
            clean(x.get("type", "") if isinstance(x, dict) else x)
            for x in duration)
    return duration


def _spell_conc(d: dict) -> bool:
    return d.get("concentration") in (True, "yes", "Yes") or any(
        x.get("concentration") for x in d.get("duration") or []
        if isinstance(x, dict))


def _spell_comps(d: dict):
    comps = d.get("components")
    if isinstance(comps, dict):
        comps = ", ".join(k for k, v in comps.items() if v)
    elif isinstance(comps, list):
        comps = ", ".join(str(x) for x in comps)
    return comps


def _spell(d: dict) -> dict:
    props = d.get("properties") or {}
    lvl = d.get("level", props.get("Level", ""))
    lvl_txt = ("truco" if str(lvl) in ("0", "cantrip")
               else f"nivel {lvl}")
    return {
        "kind": "spell",
        "fields": _filter([
            _f("Nivel", lvl_txt),
            _f("Escuela", (d.get("school") or {}).get("name")
                 if isinstance(d.get("school"), dict)
                 else d.get("school") or props.get("School")),
            _f("Tiempo", d.get("casting_time")
                 or props.get("Casting Time")),
            _f("Alcance", (d.get("range") or {}).get("normal")
                 if isinstance(d.get("range"), dict)
                 else d.get("range") or props.get("Range")
                 or props.get("data-RangeAoe")),
            _f("Componentes", _spell_comps(d)
               or props.get("Components")),
            _f("Duración", _spell_duration(d)),
            _f("Concentración", "sí" if _spell_conc(d) else None),
            _f("Ritual", "sí" if d.get("ritual") in (True, "yes")
               else None),
        ]),
        "desc": _entries(d) + _higher(d),
    }


def _higher(d: dict) -> str:
    """Texto 'a niveles superiores' (upcast) — higher_level list/str
    · entriesHigherLevel[0].entries (5etools)."""
    for k in ("higher_level",):
        v = d.get(k)
        if isinstance(v, list):
            return " " + " ".join(clean(x) for x in v)
        if v:
            return " " + clean(v)
    for g in d.get("entriesHigherLevel") or []:
        if isinstance(g, dict) and g.get("entries"):
            return " " + " ".join(clean(x) for x in g["entries"])
    return ""


def _item_kind(d: dict, props: dict):
    return (d.get("equipment_category", {}).get("name")
            if isinstance(d.get("equipment_category"), dict)
            else d.get("type") or d.get("weapon_category")
            or props.get("Type"))


def _item_damage(d: dict, dmg: dict):
    return (f"{dmg.get('damage_dice', '')} "
            f"{(dmg.get('damage_type') or {}).get('name', '')}"
            .strip() or d.get("dmg1"))


def _item_cost(d: dict, props: dict):
    if not d.get("cost"):
        return props.get("Cost")
    c = d["cost"]
    return f"{c.get('quantity', '')} {c.get('unit', '')}".strip()


def _item_props(d: dict):
    pl = d.get("properties")
    return ", ".join(
        p.get("name", str(p)) if isinstance(p, dict) else str(p)
        for p in (pl if isinstance(pl, list) else [])) or None


def _item(d: dict) -> dict:
    props = d.get("properties") or {}
    dmg = d.get("damage") or {}
    rarity = d.get("rarity")
    if isinstance(rarity, dict):
        rarity = rarity.get("name")
    attuned = d.get("requires_attunement") in (True, "yes") \
        or d.get("reqAttune") in (True, "yes")
    return {
        "kind": "item",
        "fields": _filter([
            _f("Tipo", _item_kind(d, props)),
            _f("Rareza", rarity or props.get("Rarity")),
            _f("Sintonía", "sí" if attuned else None),
            _f("Daño", _item_damage(d, dmg)),
            _f("CA", d.get("armor_class", {}).get("base")
               if isinstance(d.get("armor_class"), dict)
               else d.get("ac")),
            _f("Peso", f"{d.get('weight')} lb"
               if d.get("weight") else props.get("Weight")),
            _f("Coste", _item_cost(d, props)),
            _f("Propiedades", _item_props(d)),
        ]),
        "desc": _entries(d),
    }


def _names(lst) -> str:
    """[{name}] o [str] → 'a, b, c'."""
    return ", ".join(
        x.get("name", "") if isinstance(x, dict) else str(x)
        for x in lst or [])


def _equip_text(opts) -> str:
    """equipment_options → 'elige 1: (a) hacha…; (b) 50 po'."""
    parts = []
    for o in opts or []:
        d = clean(o.get("desc")) if isinstance(o, dict) else clean(o)
        if d:
            parts.append(d)
    return "; ".join(parts)


def _bonuses(d: dict) -> str:
    """race.ability_bonuses [{ability_score:{name}, bonus}] → 'CON +2'."""
    parts = []
    for b in d.get("ability_bonuses") or []:
        ab = b.get("ability_score") or {}
        parts.append(f"{ab.get('name', '?')} +{b.get('bonus', 0)}")
    return ", ".join(parts)


def _species(d: dict) -> dict:
    """race (2014) / species + subspecies + subrace (2024)."""
    speed = d.get("speed")
    return {
        "kind": "species",
        "fields": _filter([
            _f("Velocidad",
               f"{speed} pies" if isinstance(speed, (int, float)) else None),
            _f("Tamaño", d.get("size") or _names(d.get("size_options"))),
            _f("Bonificadores", _bonuses(d)),
            _f("Idiomas", _names(d.get("languages"))
               or clean(d.get("language_desc"))),
            _f("Rasgos", _names(d.get("traits"))
               or _names(d.get("racial_traits"))),
            _f("Tipo de daño", (d.get("damage_type") or {}).get("name")
               if isinstance(d.get("damage_type"), dict)
               else d.get("damage_type")),
            _f("Subrazas", _names(d.get("subraces"))
               or _names(d.get("subspecies"))),
            _f("Edad", clean(d.get("age"))),
            _f("Alineamiento", clean(d.get("alignment"))
               if isinstance(d.get("alignment"), str) else None),
        ]),
        "desc": _entries(d),
    }


def _background(d: dict) -> dict:
    feat = d.get("feat")
    return {
        "kind": "background",
        "fields": _filter([
            _f("Características", _names(d.get("ability_scores"))),
            _f("Competencias", _names(d.get("proficiencies"))),
            _f("Dote", (feat or {}).get("name")
               if isinstance(feat, dict) else feat),
            _f("Equipo", _equip_text(d.get("equipment_options"))),
        ]),
        "desc": _entries(d),
    }


def _level(d: dict) -> dict:
    """Entidad 'level': progresión de una clase a un nivel concreto."""
    spec = d.get("class_specific") or {}
    details = ", ".join(
        f"{k.replace('_', ' ')}: {v}" for k, v in spec.items()
        if isinstance(v, (int, float, str, bool)))
    return {
        "kind": "level",
        "fields": _filter([
            _f("Clase", (d.get("class") or {}).get("name")),
            _f("Nivel", d.get("level")),
            _f("Bon. competencia",
               f"+{d['prof_bonus']}" if d.get("prof_bonus") else None),
            _f("Rasgos nuevos", _names(d.get("features"))),
            _f("Detalles", details),
        ]),
        "desc": _entries(d),
    }


def _subclass(d: dict) -> dict:
    return {
        "kind": "subclass",
        "fields": _filter([
            _f("Clase", (d.get("class") or {}).get("name")),
        ]),
        "desc": (clean(d.get("subclass_flavor")) + " " + _entries(d)).strip(),
    }


def _class(d: dict) -> dict:
    from .classinfo import hit_die, save_profs
    multiclass = d.get("multi_classing") or {}
    prereq = ", ".join(
        f"{(p.get('ability_score') or {}).get('name', '?')} "
        f"{p.get('minimum_score', '?')}"
        for p in multiclass.get("prerequisites") or [])
    return {
        "kind": "class",
        "fields": _filter([
            _f("Dado de golpe", f"d{hit_die(d)}"),
            _f("Salvaciones", ", ".join(save_profs(d))),
            _f("Competencias", _names(d.get("proficiencies"))),
            _f("Subclases", _names(d.get("subclasses"))),
            _f("Equipo inicial",
               _equip_text(d.get("starting_equipment_options"))),
            _f("Multiclase", prereq),
        ]),
        "desc": _entries(d),
    }


def render(entity_type: str, data: dict) -> dict:
    out = {"kind": entity_type, "fields": [], "desc": _entries(data)}
    if entity_type == "spell":
        out.update(_spell(data))
    elif entity_type in ("item", "magic-item", "equipment", "poison",
                         "weapon-property"):
        out.update(_item(data))
    elif entity_type == "class":
        out.update(_class(data))
    elif entity_type in ("race", "species", "subrace", "subspecies"):
        out.update(_species(data))
    elif entity_type == "background":
        out.update(_background(data))
    elif entity_type == "level":
        out.update(_level(data))
    elif entity_type == "subclass":
        out.update(_subclass(data))
    for f in ("prerequisite", "prerequisites"):
        v = _prereq(data.get(f))
        if v:
            out["fields"].insert(0, _f("Requisito", v))
            break
    return out
