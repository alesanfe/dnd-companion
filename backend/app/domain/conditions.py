"""Efectos mecánicos declarativos de condiciones (SRD).

Tabla de datos compartida por tiradas de personaje (api/operations)
y de combatiente (engine/combat_ops). roll_type admite
'attack|check|save|damage', 'save:dex', 'skill:x'.

Aliases ES→EN incluidos: los chips de la UI aceptan ambos idiomas.
"""

from ..rules import rules

# nombre → {adv: tipos con ventaja, dis: desventaja, fail: autofallo}
# — extraído del rules pack (srd_core.json → "conditions")
def _build_tables():
    raw = rules()["conditions"]
    rolls = {name: {k: set(v) if isinstance(v, list) else v
                    for k, v in spec.items()
                    if k in ("adv", "dis", "fail")}
             for name, spec in raw.items() if name != "comment"}
    incapacitated = {name for name, spec in raw.items()
                     if isinstance(spec, dict) and spec.get("incapacitated")}
    return rolls, incapacitated, rules()["condition_aliases"]

CONDITION_ROLLS, INCAPACITATED, _ALIASES = _build_tables()


def canon(condition: str) -> str:
    c = condition.strip().lower()
    return _ALIASES.get(c, c)


def mods_for(conditions: list[str], roll_type: str):
    """(adv, dis, fail, notes) para una tirada dadas las condiciones.
    'exhaustion N' escala: nivel 3+ también da desventaja en ataques
    y salvaciones (regla SRD de niveles de agotamiento)."""
    adv = dis = fail = False
    notes: list[str] = []
    base = roll_type.split(":")[0]
    for cond in conditions or []:
        c = canon(cond)
        level = 0
        if c.startswith("exhaustion"):
            try:
                level = int(c.rsplit(" ", 1)[1])
            except (IndexError, ValueError):
                level = 1
        rule = dict(CONDITION_ROLLS.get(c, {}))
        if level >= 3:
            rule["dis"] = set(rule.get("dis", ())) | {"attack", "save"}
            if base in ("attack", "save") or ":" in roll_type:
                notes.append(f"{cond}: desventaja (agotamiento 3+)")
                dis = True
        if not rule:
            continue
        if not rule:
            continue
        if any(roll_type == t or base == t for t in rule.get("adv", ())):
            adv = True; notes.append(f"{cond}: ventaja")
        if any(roll_type == t or base == t for t in rule.get("dis", ())):
            dis = True; notes.append(f"{cond}: desventaja")
        if roll_type in rule.get("fail", ()):
            fail = True; notes.append(f"{cond}: fallo automático")
    return adv, dis, fail, notes


def is_incapacitated(conditions: list[str]) -> str | None:
    """La condición incapacitante presente, o None."""
    for cond in conditions or []:
        if canon(cond) in INCAPACITATED:
            return cond
    return None
