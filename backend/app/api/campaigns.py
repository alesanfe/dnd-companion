"""Campaigns + invite codes. Skeleton — real-time sync lands via ws/rooms."""
from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timezone

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ._campaign_access import (
    _DM_ROLES, _ev_for_uid, _ev_is_dm, _ev_visible, _has_owner,
    _notify_entity, _require_role,
)
from .auth import member_role, optional_user
from ..db.connections import content_db, state_db
from ..domain.ruleset import Ruleset
from ..ws.rooms import manager

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    ruleset: Ruleset = Ruleset.DND5E_2014
    owner_id: str | None = None


@router.post("", status_code=201)
def create_campaign(body: CampaignCreate,
                    user: dict | None = Depends(optional_user)):
    conn = state_db()
    cid = uuid.uuid4().hex
    invite = secrets.token_urlsafe(6)
    now = datetime.now(timezone.utc).isoformat()
    owner = (user or {}).get("user_id") or body.owner_id
    conn.execute(
        """INSERT INTO campaigns
           (id, name, invite_code, ruleset, owner_id, data, created_at, updated_at)
           VALUES (?,?,?,?,?, '{}', ?, ?)""",
        (cid, body.name, invite, body.ruleset.value, owner, now, now),
    )
    if owner:
        conn.execute(
            "INSERT OR IGNORE INTO members "
            "(campaign_id, user_id, role, joined_at) VALUES (?,?,?,?)",
            (cid, owner, "owner", now))
    conn.commit()
    return {"id": cid, "invite_code": invite}


@router.get("")
def list_campaigns(user: dict | None = Depends(optional_user)):
    """Campañas del usuario (si hay token) o todas en modo local."""
    conn = state_db()
    uid = (user or {}).get("user_id")
    if uid:
        rows = conn.execute(
            """SELECT c.id, c.name, c.ruleset, m.role, c.created_at
               FROM campaigns c
               JOIN members m ON m.campaign_id = c.id
               WHERE m.user_id = ? ORDER BY c.created_at DESC""",
            (uid,)).fetchall()
    else:
        # sin token: solo campañas locales (sin owner). Antes se
        # devolvían TODAS como role='dm' — cualquier anónimo enumeraba
        # ids/nombres de mesas privadas
        rows = conn.execute(
            """SELECT c.id, c.name, c.ruleset,
                      'dm' AS role, c.created_at
               FROM campaigns c WHERE c.owner_id IS NULL
               ORDER BY c.created_at DESC""").fetchall()
    return {"campaigns": [dict(r) for r in rows]}


class JoinIn(BaseModel):
    invite_code: str
    user_id: str | None = None          # registra membresía si se pasa
    role: str = "player"


@router.post("/join")
def join_campaign(body: JoinIn,
                  user: dict | None = Depends(optional_user)):
    """Unirse a una campaña por código de invitación. Con token se
    registra como miembro con su rol (el token manda sobre user_id)."""
    conn = state_db()
    row = conn.execute(
        "SELECT id, name, ruleset FROM campaigns WHERE invite_code = ?",
        (body.invite_code,)).fetchone()
    if row is None:
        raise HTTPException(404, "campaign not found")
    uid = (user or {}).get("user_id") or body.user_id
    if uid:
        # entrar con código siempre es player/guest — los roles DM los
        # asigna un DM existente, nunca el propio cliente
        role = body.role if body.role in ("player", "guest") else "player"
        conn.execute(
            "INSERT OR IGNORE INTO members "
            "(campaign_id, user_id, role, joined_at) VALUES (?,?,?,?)",
            (row["id"], uid, role,
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return {"id": row["id"], "name": row["name"], "ruleset": row["ruleset"]}


@router.post("/import", status_code=201)
def import_campaign(body: dict,
                    user: dict | None = Depends(optional_user)):
    """Restaura un backup de `GET /{id}/export`. Conserva los ids
    originales; los que ya existen se ignoran (restaurar ≠ duplicar)."""
    conn = state_db()
    camp = body.get("campaign") or {}
    if not camp.get("id"):
        raise HTTPException(400, "formato inválido")
    now = datetime.now(timezone.utc).isoformat()
    if conn.execute("SELECT 1 FROM campaigns WHERE id = ?",
                    (camp["id"],)).fetchone():
        raise HTTPException(409, "la campaña ya existe (usa otro id)")
    invite = camp.get("invite_code") or uuid.uuid4().hex[:8]
    if conn.execute("SELECT 1 FROM campaigns WHERE invite_code = ?",
                    (invite,)).fetchone():
        invite = uuid.uuid4().hex[:8]       # código ya en uso → nuevo
    # con token, el importador pasa a ser el dueño — el owner_id del
    # bundle es spoofable (podría atribuir la campaña a otra persona);
    # sin sesión se conserva el del backup (restauración local)
    uid = (user or {}).get("user_id")
    owner = uid or camp.get("owner_id")
    try:
        conn.execute(
            "INSERT INTO campaigns (id, name, ruleset, invite_code, "
            "created_at, updated_at, owner_id) VALUES (?,?,?,?,?,?,?)",
            (camp["id"], camp["name"], camp.get("ruleset", "dnd5e-2014"),
             invite, camp.get("created_at", now),
             camp.get("updated_at", now), owner))
        if owner:
            conn.execute(
                "INSERT OR IGNORE INTO members "
                "(campaign_id, user_id, role, joined_at) VALUES (?,?,?,?)",
                (camp["id"], owner, "owner", now))
        for e in body.get("entities", []):
            conn.execute(
                "INSERT OR IGNORE INTO campaign_entities "
                "(id, campaign_id, kind, name, visibility, known_to, data,"
                " revealed_at, created_at, updated_at, version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (e["id"], camp["id"], e["kind"], e["name"], e["visibility"],
                 e.get("known_to", "[]"), e.get("data", "{}"),
                 e.get("revealed_at"), e.get("created_at", now),
                 e.get("updated_at", now), e.get("version", 1)))
        for m in body.get("members", []):
            conn.execute(
                "INSERT OR IGNORE INTO members (campaign_id, user_id, "
                "role, character_id, joined_at) VALUES (?,?,?,?,?)",
                (camp["id"], m["user_id"], m["role"],
                 m.get("character_id"), m.get("joined_at", now)))
        for s in body.get("sessions", []):
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, campaign_id, number, "
                "title, status, data, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (s["id"], camp["id"], s.get("number"), s["title"],
                 s.get("status", "prep"), s.get("data", "{}"),
                 s.get("created_at", now), s.get("updated_at", now)))
        for c in body.get("combats", []):
            conn.execute(
                "INSERT OR IGNORE INTO combats (id, campaign_id, name, "
                "ruleset, version, data, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (c["id"], camp["id"], c["name"], c.get("ruleset"),
                 c.get("version", 1), c.get("data", "{}"),
                 c.get("updated_at", now)))
        for ch in body.get("characters", []):
            conn.execute(
                "INSERT OR IGNORE INTO characters (id, name, player_id, "
                "campaign_id, ruleset, version, data, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ch["id"], ch["name"], ch.get("player_id"), camp["id"],
                 ch.get("ruleset", "dnd5e-2014"), ch.get("version", 1),
                 ch.get("data", "{}"), ch.get("updated_at", now)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"id": camp["id"], "entities": len(body.get("entities", [])),
            "characters": len(body.get("characters", []))}


@router.get("/{campaign_id}/members")
def list_members(campaign_id: str,
                 user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user)
    rows = conn.execute(
        "SELECT user_id, role, joined_at FROM members "
        "WHERE campaign_id = ?", (campaign_id,)).fetchall()
    return {"members": [dict(r) for r in rows]}


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str,
                 user: dict | None = Depends(optional_user)):
    """Ficha mínima de campaña (nombre, ruleset, código)."""
    conn = state_db()
    row = conn.execute(
        "SELECT id, name, ruleset, invite_code, owner_id, created_at "
        "FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "campaign not found")
    # en campañas con dueño solo los miembros ven la ficha — antes
    # cualquiera con el id veía nombre/ruleset (y sondeaba ids)
    _require_role(conn, campaign_id, user)
    out = dict(row)
    # el invite_code es la única credencial de acceso: solo lo ve el DM
    if row["owner_id"] is not None and \
            member_role(campaign_id, (user or {}).get("user_id")) \
            not in _DM_ROLES:
        out.pop("invite_code", None)
    out.pop("owner_id", None)
    return out


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: str,
                    user: dict | None = Depends(optional_user)):
    """Borra la campaña y sus datos asociados. Las fichas NO se
    borran — se desvinculan (campaign_id NULL), son de los jugadores."""
    conn = state_db()
    row = conn.execute("SELECT 1 FROM campaigns WHERE id = ?",
                       (campaign_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "campaign not found")
    # solo el owner (en local sin dueño queda abierto)
    _require_role(conn, campaign_id, user, ("owner",))
    combat_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM combats WHERE campaign_id = ?",
        (campaign_id,)).fetchall()]
    try:
        for table in ("campaign_entities", "relationships",
                      "sessions", "members", "events", "combats"):
            conn.execute(f"DELETE FROM {table} WHERE campaign_id = ?",
                         (campaign_id,))
        if combat_ids:
            conn.execute(
                "DELETE FROM operations WHERE entity_id IN "
                f"({','.join('?' * len(combat_ids))})",
                combat_ids)
        conn.execute(
            "UPDATE characters SET campaign_id = NULL, "
            "version = version + 1, updated_at = ?"
            " WHERE campaign_id = ?",
            (datetime.now(timezone.utc).isoformat(), campaign_id))
        conn.execute("DELETE FROM campaigns WHERE id = ?",
                     (campaign_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"deleted": campaign_id}


@router.get("/{campaign_id}/state")
def campaign_state(campaign_id: str,
                   user: dict | None = Depends(optional_user)):
    """Snapshot para resync tras reconexión: personajes + combate activo
    + últimos eventos."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    uid = (user or {}).get("user_id")
    # eventos visibility=dm (tiradas secretas del DM) no se sirven a
    # jugadores — antes el resync filtraba los totales por REST aunque
    # el WS sí los ocultara
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, uid) in _DM_ROLES
    chars = conn.execute(
        "SELECT id, name, ruleset, version, player_id, data "
        "FROM characters WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    combats = conn.execute(
        "SELECT id, name, version, data FROM combats WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    # vista de jugador en el resync: los PG exactos y los stat blocks
    # son del DM — misma redacción que GET /api/combat/{id}?reveal_hp=0
    from ..domain.combat import Combat, hp_state
    combats_out = []
    for cb in combats:
        data = json.loads(cb["data"])
        if not is_dm:
            combat = Combat(**data)
            data = combat.model_dump()
            for i, c in enumerate(combat.combatants):
                data["combatants"][i]["hp_state"] = hp_state(c)
                for k in ("hp_current", "hp_max", "hp_temp",
                          "stat_block"):
                    data["combatants"][i][k] = None
        combats_out.append({**dict(cb), "data": data})
    # 'secrets' de la ficha es solo PJ+DM — el resync servía la data
    # completa a cualquier miembro igual que GET /characters/{id}
    from .characters import redact_private
    chars_out = []
    for c in chars:
        data = json.loads(c["data"])
        if not is_dm and c["player_id"] != uid:
            data = redact_private(data)
        chars_out.append({**dict(c), "data": data})
    events = conn.execute(
        "SELECT * FROM events WHERE campaign_id = ? "
        "ORDER BY occurred_at DESC LIMIT 200", (campaign_id,)).fetchall()
    return {
        "characters": chars_out,
        "combats": combats_out,
        "events": [dict(e) for e in events
                   if _ev_visible(e, uid, is_dm)][:50],
        # presencia actual en la sala WS (resync tras reconexión)
        "presence": manager.present(campaign_id),
    }


