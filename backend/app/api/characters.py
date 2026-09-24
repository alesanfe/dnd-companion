"""Characters — state DB. Writes go through the operations log so every
change is idempotent and reversible (see domain/events.py)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db
from ..domain.ruleset import Ruleset

router = APIRouter(prefix="/api/characters", tags=["characters"])


class CharacterCreate(BaseModel):
    name: str
    ruleset: Ruleset = Ruleset.DND5E_2014
    player_id: str | None = None
    campaign_id: str | None = None
    data: dict = {}


@router.post("", status_code=201)
def create_character(body: CharacterCreate):
    conn = state_db()
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO characters
           (id, name, player_id, campaign_id, ruleset, version, data, updated_at)
           VALUES (?,?,?,?,?,1,?,?)""",
        (cid, body.name, body.player_id, body.campaign_id,
         body.ruleset.value, json.dumps(body.data), now),
    )
    conn.commit()
    return {"id": cid, "version": 1}


@router.get("/{character_id}")
def get_character(character_id: str):
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    out = dict(row)
    out["data"] = json.loads(out["data"])
    return out
