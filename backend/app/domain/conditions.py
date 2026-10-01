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


def mods_for(conditions: list[str], roll_type: str,
             stacks: dict | None = None, ruleset: str = "dnd5e-2014"):
    """(adv, dis, fail, notes) para una tirada dadas las condiciones.
    'exhaustion N' escala: nivel 3+ también da desventaja en ataques
    y salvaciones (regla 2014). En 2024 el agotamiento no da
    desventaja: es -2×nivel a la tirada — ese penalizador numérico lo
    da pen_for(); aquí no se añade ventaja/desventaja alguna.
    El nivel puede venir del nombre ('exhaustion 3') o del mapa
    `stacks` (condition_stacks del personaje)."""
    adv = dis = fail = False
    notes: list[str] = []
    base = roll_type.split(":")[0]
    is2024 = ruleset == "dnd5e-2024"
    for cond in conditions or []:
        c = canon(cond)
        if c == "surprised" and not is2024:
            continue                # 2014: sorpresa ≠ desventaja init
        level = _exhaustion_level(c, stacks)
        rule = dict(CONDITION_ROLLS.get(c, {}))
        if level and is2024:
            # 2024: agotamiento = penalizador fijo, NO desventaja —
            # la regla de la tabla de niveles de 2014 no aplica
            if base in ("attack", "check", "save") or ":" in roll_type:
                notes.append(f"{cond}: -{level * rules()['combat']['exhaustion_penalty_per_level_2024']}"
                             " a la tirada (agotamiento 2024)")
            continue                       # sin 'dis' de la tabla
        if level >= 3:
            rule["dis"] = set(rule.get("dis", ())) | {"attack", "save"}
            if base in ("attack", "save") or ":" in roll_type:
                notes.append(f"{cond}: desventaja (agotamiento 3+)")
                dis = True
        if not rule:
            continue
        if any(roll_type == t or base == t for t in rule.get("adv", ())):
            adv = True
            notes.append(f"{cond}: ventaja")
        if any(roll_type == t or base == t for t in rule.get("dis", ())):
            dis = True
            notes.append(f"{cond}: desventaja")
        if roll_type in rule.get("fail", ()):
            fail = True
            notes.append(f"{cond}: fallo automático")
    return adv, dis, fail, notes


def pen_for(conditions: list[str], stacks: dict | None = None,
            ruleset: str = "dnd5e-2014") -> int:
    """Penalizador numérico a tiradas de d20 por agotamiento 2024
    (-2×nivel). En 2014 el agotamiento es desventaja (mods_for), no
    un número — devuelve 0."""
    if ruleset != "dnd5e-2024":
        return 0
    level = max((_exhaustion_level(canon(c), stacks)
                for c in conditions or []), default=0)
    return level * rules()["combat"]["exhaustion_penalty_per_level_2024"]


def _exhaustion_level(c: str, stacks: dict | None) -> int:
    """Nivel de agotamiento: 'exhaustion N' del nombre canónico o
    del mapa de stacks del personaje (es/en)."""
    if not c.startswith("exhaustion"):
        return 0
    try:
        level = int(c.rsplit(" ", 1)[1])
    except (IndexError, ValueError):
        level = 1
    if stacks:
        level = max(level, int(stacks.get(c, 0)
                               or stacks.get("exhaustion", 0)
                               or stacks.get("agotamiento", 0)))
    return level


def is_incapacitated(conditions: list[str]) -> str | None:
    """La condición incapacitante presente, o None."""
    for cond in conditions or []:
        if canon(cond) in INCAPACITATED:
            return cond
    return None
