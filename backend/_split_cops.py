"""Split engine/combat_ops.py -> engine/combat_ops/ por dominio."""
import ast
import re
import subprocess
from pathlib import Path

SRC = Path("backend/app/engine/combat_ops.py.bak")
OUT = Path("backend/app/engine/combat_ops")
OUT.mkdir(exist_ok=True)

raw = subprocess.check_output(
    ["git", "show", "HEAD:backend/app/engine/combat_ops.py"])
lines = raw.decode("utf-8").splitlines()
tree = ast.parse("\n".join(lines))

blocks = []
for node in tree.body:
    if node.lineno <= 20:             # docstring + imports
        continue
    if isinstance(node, ast.FunctionDef):
        name = node.name
        start = min([node.lineno] +
                    [d.lineno for d in node.decorator_list])
    elif isinstance(node, ast.Assign):
        name = getattr(node.targets[0], "id", "?")
        start = node.lineno
    elif isinstance(node, ast.AnnAssign):
        name = getattr(node.target, "id", "?")
        start = node.lineno
    else:
        continue
    decos = [ast.unparse(d) for d in getattr(node, "decorator_list", [])]
    op_name = decos[0][4:-1].strip("'\"") \
        if decos and decos[0].startswith("op(") else None
    blocks.append((start, node.end_lineno, name, op_name))

TURNS = {"combat.next_turn", "combat.prev_turn", "combat.end",
         "combat.state.restore"}
ROSTER = {"combatant.add", "combatant.remove", "combatant.delegate",
          "combatant.add_raw"}
VITALS = {"combatant.damage", "combatant.heal", "combatant.death_save",
          "combatant.death_save_roll", "combatant.death_save.set",
          "combatant.hp.set", "combatant.condition.apply",
          "combatant.condition.remove", "noop"}

def domain(op_name):
    if op_name in TURNS:
        return "turns"
    if op_name in ROSTER:
        return "roster"
    if op_name in VITALS:
        return "vitals"
    return "rolls"                    # initiative/save/check/attack

helper_names = {b[2] for b in blocks if not b[3]}
dom_uses = {d: set() for d in ("turns", "roster", "vitals", "rolls")}
dom_blocks = {d: [] for d in dom_uses}
base_blocks = []

for lo, hi, name, op_name in blocks:
    body = "\n".join(lines[lo - 1:hi])
    if op_name:
        d = domain(op_name)
        dom_blocks[d].append(body)
        for h in helper_names:
            if re.search(rf"\b{re.escape(h)}\b", body):
                dom_uses[d].add(h)
    else:
        base_blocks.append(body)

HEADER_BASE = '''"""Handlers de combate — núcleo compartido.

    handler(combat, payload, ctx) -> (inverse_op, [event_payloads])

ctx.content_db() da acceso a la DB de reglas para que 'combatant.add'
copie el stat block por entity id.

Split de combat_ops.py (AU-22): registro (COMBAT_HANDLERS,
apply_combat_operation), helpers compartidos y sincronía con la ficha
(_sync_character); los handlers viven en turns/roster/vitals/rolls."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable

from ...domain import statblock
from ...domain.combat import Combat, Combatant, hp_state
from ...domain.effects import Trigger
from ...rules import rules
from ..dice import roll

Handler = Callable[[Combat, dict, object], tuple[dict, list[dict]]]
COMBAT_HANDLERS: dict[str, Handler] = {}


def op(name: str):
    def wrap(fn: Handler) -> Handler:
        COMBAT_HANDLERS[name] = fn
        return fn
    return wrap


'''

DOCS = {
    "turns": "ciclo de turno: next/prev, fin de combate y restore",
    "roster": "altas/bajas de combatientes y delegación",
    "vitals": "PG, salvaciones de muerte y condiciones del "
              "combatiente",
    "rolls": "tiradas del tracker: iniciativa, saves, acciones, "
             "checks y combat.attack",
}

for d, bl in dom_blocks.items():
    imp = "from ._base import (\n    COMBAT_HANDLERS, op"
    for h in sorted(dom_uses[d]):
        imp += f", {h}"
    imp += "\n)\n"
    body = (f'"""Handlers de combate — {DOCS[d]}."""\n'
            "from __future__ import annotations\n\n"
            "import json\nimport uuid\n"
            "from datetime import datetime, timezone\n\n"
            "from ...domain import statblock\n"
            "from ...domain.combat import Combat, Combatant, hp_state\n"
            "from ...domain.effects import Trigger\n"
            "from ...rules import rules\n"
            "from ..dice import roll\n"
            + imp + "\n"
            + "\n\n\n".join(bl) + "\n")
    (OUT / f"{d}.py").write_text(body, encoding="utf-8")
    print(d, len(bl), "handlers")

(OUT / "_base.py").write_text(
    HEADER_BASE + "\n\n\n".join(base_blocks) + "\n",
    encoding="utf-8")
print("base:", len(base_blocks), "bloques")
