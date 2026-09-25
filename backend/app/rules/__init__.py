"""Rules pack loader — las tablas normativas (CR→XP, umbrales de
encuentro, XP por nivel, habilidades, condiciones) viven en
srd_core.json con metadatos de licencia, no dispersas por el código.

    from app.rules import rules
    rules()["cr_xp"]["5"]          # 1800
    rules()["level_xp"]["values"]  # tabla de subida de nivel
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PACK = Path(__file__).with_name("srd_core.json")


@lru_cache(maxsize=1)
def rules() -> dict:
    """El rules pack SRD completo (cacheado; es inmutable en runtime)."""
    return json.loads(_PACK.read_text(encoding="utf-8"))
