"""Dice engine — parses '2d6+3', '1d20adv', '4d6kh3' and rolls."""
from __future__ import annotations

import random
import re
from typing import NamedTuple

_ROLL_RE = re.compile(
    r"^(?P<count>\d*)d(?P<sides>\d+)"
    r"(?P<keep>kh\d+|kl\d+|adv|dis)?"
    r"(?P<mod>[+-]\d+)?$",
    re.IGNORECASE,
)


class RollResult(NamedTuple):
    expression: str
    rolls: list[int]          # todos los dados tirados
    kept: list[int]           # los que cuentan
    modifier: int
    total: int


def _rng() -> random.Random:
    return random.SystemRandom()


def roll(expression: str, rng: random.Random | None = None) -> RollResult:
    """Roll a dice expression. Raises ValueError on bad input."""
    expr = expression.strip().lower().replace(" ", "")
    rng = rng or _rng()

    if expr.isdigit() or (expr.startswith("-") and expr[1:].isdigit()):
        v = int(expr)
        return RollResult(expression, [], [], v, v)

    m = _ROLL_RE.match(expr)
    if not m:
        raise ValueError(f"bad dice expression: {expression!r}")

    count = int(m.group("count") or 1)
    sides = int(m.group("sides"))
    if not (1 <= count <= 100 and 2 <= sides <= 1000):
        raise ValueError("dice out of range")
    mod = int(m.group("mod") or 0)
    keep = m.group("keep")

    rolls = [rng.randint(1, sides) for _ in range(count)]
    kept = list(rolls)

    if keep == "adv" and sides == 20:
        rolls.append(rng.randint(1, sides))
        kept = [max(rolls)]
    elif keep == "dis" and sides == 20:
        rolls.append(rng.randint(1, sides))
        kept = [min(rolls)]
    elif keep and keep.startswith("kh"):
        n = int(keep[2:])
        kept = sorted(rolls, reverse=True)[:n]
    elif keep and keep.startswith("kl"):
        n = int(keep[2:])
        kept = sorted(rolls)[:n]

    return RollResult(expression, rolls, kept, mod, sum(kept) + mod)
