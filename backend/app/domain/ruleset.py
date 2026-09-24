"""Stable internal ruleset ids. UI labels ('5e', '5.5e') map at the edge."""
from enum import Enum


class Ruleset(str, Enum):
    DND5E_2014 = "dnd5e-2014"   # SRD 5.1, reglas de 2014
    DND5E_2024 = "dnd5e-2024"   # SRD 5.2.1, reglas revisadas
    MIXED = "mixed"             # campaña/entidad que mezcla ambas
