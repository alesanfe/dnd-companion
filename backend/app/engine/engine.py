"""Effects engine — evaluates declarative Effects into a traceable result.

MVP scope: numeric stat resolution (add/set + armor_class aliasing) and
flags (advantage/disadvantage/resistance/vulnerability/immunity).
Dice rolls, durations and contextual triggers plug into the same model.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.effects import Effect, Operation, StackingRule

# operation -> stat alias handled uniformly by 'target'
_OP_ALIASES = {Operation.MODIFY_ARMOR_CLASS: "armor_class"}


class ModifierEntry(BaseModel):
    """One line in the explanation: where a bonus came from."""
    source: str           # effect name
    op: Operation
    value: int | float | str | bool | None
    reason: str = ""


class StatBreakdown(BaseModel):
    stat: str
    base: float
    total: float
    entries: list[ModifierEntry] = Field(default_factory=list)
    advantage: bool = False
    disadvantage: bool = False
    resistances: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)
    immunities: list[str] = Field(default_factory=list)


def _matches(op_target: str, stat: str) -> bool:
    return op_target == stat or op_target == f"*.{stat}" or op_target == "*"


def resolve_stat(stat: str, base: float, effects: list[Effect]) -> StatBreakdown:
    """Resolve one derived stat through all passive effects.

    Order: set_value ops (by priority, lowest wins — last applied) then
    additive modifiers. Non-numeric ops land in the breakdown flags.
    """
    entries: list[ModifierEntry] = []
    sets: list[tuple[int, Effect, float]] = []
    adds: list[tuple[Effect, float]] = []
    out = StatBreakdown(stat=stat, base=base, total=base)

    for eff in sorted(effects, key=lambda e: e.priority):
        for op in eff.operations:
            op_name = op.op
            target = _OP_ALIASES.get(op_name, op.target)
            if op_name in (Operation.SET_VALUE,) and _matches(target, stat):
                sets.append((eff.priority, eff, float(op.value)))
            elif op_name in (Operation.ADD_MODIFIER,) and _matches(target, stat):
                adds.append((eff, float(op.value)))
            elif op_name == Operation.GRANT_ADVANTAGE and _matches(target, stat):
                out.advantage = True
                entries.append(ModifierEntry(
                    source=eff.name, op=op_name, value=op.value,
                    reason="ventaja"))
            elif op_name == Operation.GRANT_DISADVANTAGE and _matches(target, stat):
                out.disadvantage = True
                entries.append(ModifierEntry(
                    source=eff.name, op=op_name, value=op.value,
                    reason="desventaja"))
            elif op_name == Operation.GRANT_RESISTANCE:
                out.resistances.append(str(op.value))
            elif op_name == Operation.GRANT_VULNERABILITY:
                out.vulnerabilities.append(str(op.value))
            elif op_name == Operation.GRANT_IMMUNITY:
                out.immunities.append(str(op.value))

    if sets:
        _, eff, val = sets[-1]
        out.total = val
        entries.append(ModifierEntry(
            source=eff.name, op=Operation.SET_VALUE, value=val,
            reason=f"establece {stat} a {val:g}"))

    # stacking: HIGHEST/LOWEST collapse same-named contributions
    seen: dict[str, float] = {}
    for eff, val in adds:
        if eff.stacking_rule == StackingRule.HIGHEST:
            if eff.name in seen:
                seen[eff.name] = max(seen[eff.name], val)
                continue
            seen[eff.name] = val
        elif eff.stacking_rule == StackingRule.LOWEST:
            if eff.name in seen:
                seen[eff.name] = min(seen[eff.name], val)
                continue
            seen[eff.name] = val
        else:
            out.total += val
            entries.append(ModifierEntry(
                source=eff.name, op=Operation.ADD_MODIFIER, value=val,
                reason=f"{val:+g}"))
    for name, val in seen.items():
        out.total += val
        entries.append(ModifierEntry(
            source=name, op=Operation.ADD_MODIFIER, value=val,
            reason=f"{val:+g} (no apilable)"))
    out.entries = entries
    return out
