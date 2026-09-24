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
    return {"label": label, "value": clean(value)} \
        if value not in (None, "", []) else None


def _filter(fields):
    return [f for f in fields if f]


def _spell(d: dict) -> dict:
    props = d.get("properties") or {}
    lvl = d.get("level", props.get("Level", ""))
    lvl_txt = ("truco" if str(lvl) in ("0", "cantrip")
               else f"nivel {lvl}")
    duration = d.get("duration")
    if isinstance(duration, list):
        duration = ", ".join(
            clean(x.get("type", "") if isinstance(x, dict) else x)
            for x in duration)
    conc = d.get("concentration") in (True, "yes", "Yes") or any(
        x.get("concentration") for x in d.get("duration") or []
        if isinstance(x, dict))
    comps = d.get("components")
    if isinstance(comps, dict):
        comps = ", ".join(k for k, v in comps.items() if v)
    elif isinstance(comps, list):
        comps = ", ".join(str(x) for x in comps)
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
            _f("Componentes", comps or props.get("Components")),
            _f("Duración", duration),
            _f("Concentración", "sí" if conc else None),
            _f("Ritual", "sí" if d.get("ritual") in (True, "yes")
               else None),
        ]),
        "desc": _entries(d),
    }


def _item(d: dict) -> dict:
    props = d.get("properties") or {}
    dmg = d.get("damage") or {}
    rarity = d.get("rarity")
    if isinstance(rarity, dict):
        rarity = rarity.get("name")
    return {
        "kind": "item",
        "fields": _filter([
            _f("Tipo", d.get("equipment_category", {}).get("name")
               if isinstance(d.get("equipment_category"), dict)
               else d.get("type") or d.get("weapon_category")
               or props.get("Type")),
            _f("Rareza", rarity or props.get("Rarity")),
            _f("Sintonía", "sí" if d.get("requires_attunement") in
               (True, "yes") or d.get("reqAttune") in (True, "yes")
               else None),
            _f("Daño", f"{dmg.get('damage_dice', '')} "
                       f"{(dmg.get('damage_type') or {}).get('name', '')}"
               .strip() or d.get("dmg1")),
            _f("CA", d.get("armor_class", {}).get("base")
               if isinstance(d.get("armor_class"), dict)
               else d.get("ac")),
            _f("Peso", f"{d.get('weight')} lb"
               if d.get("weight") else props.get("Weight")),
            _f("Coste", (
                lambda c: f"{c.get('quantity', '')} {c.get('unit', '')}"
                .strip())(d.get("cost") or {})
               if d.get("cost") else props.get("Cost")),
            _f("Propiedades", ", ".join(
                p.get("name", str(p)) if isinstance(p, dict) else str(p)
                for p in d.get("properties")
                if isinstance(d.get("properties"), list)) or None),
        ]),
        "desc": _entries(d),
    }


def _class(d: dict) -> dict:
    from .classinfo import hit_die, save_profs
    return {
        "kind": "class",
        "fields": _filter([
            _f("Dado de golpe", f"d{hit_die(d)}"),
            _f("Salvaciones", ", ".join(save_profs(d))),
        ]),
        "desc": _entries(d),
    }


def render(entity_type: str, data: dict) -> dict:
    out = {"kind": entity_type, "fields": [], "desc": _entries(data)}
    if entity_type == "spell":
        out.update(_spell(data))
    elif entity_type in ("item", "magic-item", "equipment"):
        out.update(_item(data))
    elif entity_type == "class":
        out.update(_class(data))
    for f in ("prerequisite", "prerequisites"):
        v = data.get(f)
        if v:
            out["fields"].insert(0, _f("Requisito", v))
            break
    return out
