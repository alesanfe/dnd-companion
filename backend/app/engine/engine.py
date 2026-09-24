"""Effects engine — evaluates declarative Effects into a traceable result.

MVP scope: numeric stat resolution (add/set + armor_class aliasing) and
flags (advantage/disadvantage/resistance/vulnerability/immunity).
Dice rolls, durations and contextual triggers plug into the same model.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.effects import Effect, EffectCondition, Operation, StackingRule, Trigger

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


def check_conditions(conditions: list[EffectCondition],
                     ctx: dict) -> bool:
    """Evalúa condiciones declarativas contra un contexto (p.ej. campos
    del personaje o del ataque). Sin condiciones = siempre aplica."""
    for c in conditions:
        val = ctx.get(c.field)
        if c.eq is not None and val != c.eq:
            return False
        if c.ne is not None and val == c.ne:
            return False
        if c.in_ is not None and val not in c.in_:
            return False
        if c.gt is not None and not (isinstance(val, (int, float)) and val > c.gt):
            return False
        if c.lt is not None and not (isinstance(val, (int, float)) and val < c.lt):
            return False
    return True


def apply_triggered(char, trigger: Trigger, ctx: dict | None = None) -> None:
    """Ejecuta los effects del personaje cuyo trigger coincide.
    Subconjunto de ops que mutan estado: recursos y condiciones."""
    ctx = {**char.model_dump(), **(ctx or {})}
    for eff in char.effects:
        if eff.trigger != trigger:
            continue
        if not check_conditions(eff.conditions, ctx):
            continue
        for o in eff.operations:
            if o.op == Operation.RESTORE_RESOURCE:
                for r in char.resources:
                    if r.id == o.target:
                        r.current = r.max if o.value is None else min(
                            r.max, r.current + int(o.value))
            elif o.op == Operation.CONSUME_RESOURCE:
                for r in char.resources:
                    if r.id == o.target:
                        r.current = max(0, r.current - int(o.value or 1))
            elif o.op == Operation.APPLY_CONDITION:
                c = str(o.value)
                if c not in char.conditions:
                    char.conditions.append(c)
            elif o.op == Operation.REMOVE_CONDITION:
                c = str(o.value)
                if c in char.conditions:
                    char.conditions.remove(c)
