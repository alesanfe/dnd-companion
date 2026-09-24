"""Campaigns + invite codes. Skeleton — real-time sync lands via ws/rooms."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import state_db
from ..domain.ruleset import Ruleset

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    ruleset: Ruleset = Ruleset.DND5E_2014
    owner_id: str | None = None


@router.post("", status_code=201)
def create_campaign(body: CampaignCreate):
    conn = state_db()
    cid = uuid.uuid4().hex
    invite = secrets.token_urlsafe(6)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO campaigns
           (id, name, invite_code, ruleset, owner_id, data, created_at, updated_at)
           VALUES (?,?,?,?,?, '{}', ?, ?)""",
        (cid, body.name, invite, body.ruleset.value, body.owner_id, now, now),
    )
    conn.commit()
    return {"id": cid, "invite_code": invite}


class JoinIn(BaseModel):
    invite_code: str


@router.post("/join")
def join_campaign(body: JoinIn):
    """Unirse a una campaña por código de invitación."""
    conn = state_db()
    row = conn.execute(
        "SELECT id, name, ruleset FROM campaigns WHERE invite_code = ?",
        (body.invite_code,)).fetchone()
    if row is None:
        raise HTTPException(404, "campaign not found")
    return {"id": row["id"], "name": row["name"], "ruleset": row["ruleset"]}


@router.get("/{campaign_id}/state")
def campaign_state(campaign_id: str):
    """Snapshot para resync tras reconexión: personajes + combate activo
    + últimos eventos."""
    conn = state_db()
    chars = conn.execute(
        "SELECT id, name, ruleset, version, data FROM characters "
        "WHERE campaign_id = ?", (campaign_id,)).fetchall()
    combats = conn.execute(
        "SELECT id, name, version, data FROM combats WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    events = conn.execute(
        "SELECT * FROM events WHERE campaign_id = ? "
        "ORDER BY occurred_at DESC LIMIT 50", (campaign_id,)).fetchall()
    return {
        "characters": [{**dict(c), "data": json.loads(c["data"])}
                       for c in chars],
        "combats": [{**dict(c), "data": json.loads(c["data"])}
                    for c in combats],
        "events": [dict(e) for e in events],
    }
