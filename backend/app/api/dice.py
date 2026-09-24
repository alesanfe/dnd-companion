"""Dice roller endpoint — '2d6+3', '1d20adv', '4d6kh3'."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..engine.dice import roll

router = APIRouter(prefix="/api/dice", tags=["dice"])


class RollIn(BaseModel):
    expression: str


@router.post("/roll")
def do_roll(body: RollIn):
    try:
        r = roll(body.expression)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"expression": r.expression, "rolls": r.rolls, "kept": r.kept,
            "modifier": r.modifier, "total": r.total}
