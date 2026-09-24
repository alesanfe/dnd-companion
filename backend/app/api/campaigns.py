"""Campaigns + invite codes. Skeleton — real-time sync lands via ws/rooms."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter
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
