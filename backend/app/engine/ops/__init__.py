"""Operation handlers — paquete por dominio (split de ops.py, AU-22).

_base.py    registro + helpers compartidos + apply_operation
vitals.py   PG, salvaciones de muerte, condiciones, descansos, recursos
gear.py     inventario, monedas, tienda, equipamiento, ataque
magic.py    conjuros, libro, pacto, concentración
growth.py   nivel, XP, ASI, dotes, rasgos, identidad, diario

Importar el paquete registra todos los handlers en HANDLERS.
"""
from ._base import (  # noqa: F401
    HANDLERS, apply_operation, op,
    # re-exportados para quien importaba desde engine.ops
    _apply_level_row, _damage_mult, _is_finesse, _item_damage,
    _item_versatile, _weapon_mastery,
)
# los submódulos registran sus handlers al importarse (@op)
from . import growth, gear, magic, vitals  # noqa: E402,F401
