"""Handlers de combate — paquete por dominio (split de combat_ops.py).

_base.py    registro + helpers compartidos + apply_combat_operation
turns.py    next/prev_turn, combat.end, combat.state.restore
roster.py   combatant.add/remove/delegate/add_raw
vitals.py   daño, curación, salvaciones de muerte, condiciones
rolls.py    iniciativa, saves, action.roll, check, combat.attack
"""
from ._base import (  # noqa: F401
    COMBAT_HANDLERS, apply_combat_operation, op, SKILL_ABILITY,
)
# los submódulos registran handlers al importarse (@op)
from . import rolls, roster, turns, vitals  # noqa: E402,F401
# re-export: los tests/importadores usaban los handlers como attrs
# del módulo combat_ops — preservar la superficie
from .turns import (  # noqa: E402,F401
    next_turn, prev_turn, combat_end, combat_restore,
)
from .roster import (  # noqa: E402,F401
    combatant_add, combatant_remove, combatant_delegate,
    combatant_add_raw,
)
from .vitals import (  # noqa: E402,F401
    combatant_damage, combatant_heal, combatant_death_save,
    combatant_death_save_roll, combatant_death_save_set,
    combatant_hp_set, combatant_cond_apply, combatant_cond_remove,
    noop,
)
from .rolls import (  # noqa: E402,F401
    combatant_initiative_roll, combatant_initiative, combatant_save,
    combatant_action_roll, combatant_check, combat_attack,
)
