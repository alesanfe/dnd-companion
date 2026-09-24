"""Efectos mecánicos declarativos de condiciones (SRD).

Tabla de datos compartida por tiradas de personaje (api/operations)
y de combatiente (engine/combat_ops). roll_type admite
'attack|check|save|damage', 'save:dex', 'skill:x'.

Aliases ES→EN incluidos: los chips de la UI aceptan ambos idiomas.
"""

# nombre → {adv: tipos con ventaja, dis: desventaja, fail: autofallo}
CONDITION_ROLLS = {
    "blinded":     {"dis": {"attack"}},
    "invisible":   {"adv": {"attack"}},
    "poisoned":    {"dis": {"attack", "check"}},
    "prone":       {"dis": {"attack"}},
    "restrained":  {"dis": {"attack", "save:dex"}},
    "frightened":  {"dis": {"check", "attack"}},
    "grappled":    {},
    "stunned":     {"fail": {"save:str", "save:dex"}},
    "paralyzed":   {"fail": {"save:str", "save:dex"}},
    "petrified":   {"fail": {"save:str", "save:dex"}},
    "unconscious": {"fail": {"save:str", "save:dex"}},
    "exhaustion":  {"dis": {"check"}},
}

# No pueden actuar ni reaccionar (bloquea action.roll)
INCAPACITATED = {"stunned", "incapacitated", "paralyzed",
                 "unconscious", "petrified"}

_ALIASES = {
    "cegado": "blinded", "cegada": "blinded",
    "invisible": "invisible",
    "envenenado": "poisoned", "envenenada": "poisoned",
    "tumbado": "prone", "derribado": "prone", "postrado": "prone",
    "apresado": "restrained", "apresada": "restrained",
    "asustado": "frightened", "atemorizado": "frightened",
    "agarrado": "grappled", "agarrada": "grappled",
    "aturdido": "stunned", "aturdida": "stunned",
    "paralizado": "paralyzed", "paralizada": "paralyzed",
    "petrificado": "petrified", "petrificada": "petrified",
    "inconsciente": "unconscious",
    "incapacitado": "incapacitated", "incapacitada": "incapacitated",
    "exhausto": "exhaustion", "agotado": "exhaustion",
    "muerto": "dead", "muerta": "dead",
}


def canon(condition: str) -> str:
    c = condition.strip().lower()
    return _ALIASES.get(c, c)


def mods_for(conditions: list[str], roll_type: str):
    """(adv, dis, fail, notes) para una tirada dadas las condiciones."""
    adv = dis = fail = False
    notes: list[str] = []
    base = roll_type.split(":")[0]
    for cond in conditions or []:
        rule = CONDITION_ROLLS.get(canon(cond))
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
