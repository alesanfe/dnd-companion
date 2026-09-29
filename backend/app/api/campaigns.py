"""Campaigns + invite codes. Skeleton — real-time sync lands via ws/rooms."""
from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timezone

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import member_role, optional_user
from ..db.connections import content_db, state_db
from ..domain.ruleset import Ruleset
from ..ws.rooms import manager

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

_DM_ROLES = ("owner", "co_dm")


def _has_owner(conn, campaign_id: str) -> bool:
    row = conn.execute(
        "SELECT owner_id FROM campaigns WHERE id = ?",
        (campaign_id,)).fetchone()
    return bool(row and row["owner_id"])


def _require_role(conn, campaign_id: str, user: dict | None,
                  roles: tuple = _DM_ROLES + ("player", "guest")) -> None:
    """Si la campaña tiene dueño, exige membresía con el rol pedido;
    campañas locales (owner_id NULL, sin cuentas) quedan abiertas."""
    row = conn.execute(
        "SELECT owner_id FROM campaigns WHERE id = ?",
        (campaign_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "campaign not found")
    if row["owner_id"] is None:
        return                     # modo local: sin autenticación
    role = member_role(campaign_id, (user or {}).get("user_id"))
    if role not in roles:
        raise HTTPException(403, "sin permiso en esta campaña")


def _ev_is_dm(row) -> bool:
    """Evento marcado visibility=dm (tirada secreta del DM)."""
    try:
        return (json.loads(row["payload"]) or {}).get("visibility") \
            == "dm"
    except Exception:
        return False


def _ev_for_uid(row, uid: str | None) -> bool:
    """El evento es dm-only pero está dirigido a ESTE usuario — su
    destinatario (p.ej. el que tiró en secreto) sí lo lee en el feed."""
    if not uid:
        return False
    try:
        return (json.loads(row["payload"]) or {}).get("for_user") == uid
    except Exception:
        return False


def _ev_visible(row, uid: str | None, is_dm: bool) -> bool:
    return is_dm or not _ev_is_dm(row) or _ev_for_uid(row, uid)


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
        rows = conn.execute(
            """SELECT c.id, c.name, c.ruleset,
                      'dm' AS role, c.created_at
               FROM campaigns c ORDER BY c.created_at DESC""").fetchall()
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


@router.delete("/{campaign_id}/entities/{entity_id}")
async def delete_entity(campaign_id: str, entity_id: str,
                  user: dict | None = Depends(optional_user)):
    """Borra una entidad de campaña (y sus relaciones)."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    row = conn.execute(
        "SELECT name, kind, visibility FROM campaign_entities "
        "WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "entity not found")
    conn.execute(
        "DELETE FROM campaign_entities WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id))
    conn.execute(
        "DELETE FROM relationships WHERE campaign_id = ? "
        "AND (from_id = ? OR to_id = ?)",
        (campaign_id, entity_id, entity_id))
    conn.commit()
    await _notify_entity(campaign_id, entity_id, ["deleted"],
                         row["visibility"], row["kind"], row["name"])
    return {"deleted": entity_id}


async def _notify_entity(campaign_id: str, entity_id: str,
                         changed: list[str], visibility: str,
                         kind: str = "", name: str = "") -> None:
    """Broadcast ligero para refresco de clientes (pestaña Mapa del
    jugador, tablero del DM). visibility='dm' → solo sockets DM,
    así una entidad oculta no se delata a los jugadores."""
    from ..domain.events import Event, EventType
    ev = Event(event_id=uuid.uuid4().hex,
               type=EventType.ENTITY_UPDATED,
               campaign_id=campaign_id, aggregate_id=entity_id,
               aggregate_version=0, actor_id="dm",
               occurred_at=datetime.now(timezone.utc),
               payload={"kind": kind, "name": name,
                        "changed": changed, "visibility": visibility})
    await manager.broadcast(campaign_id, ev)


@router.delete("/{campaign_id}/sessions/{session_id}")
def delete_session(campaign_id: str, session_id: str,
                   user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    cur = conn.execute(
        "DELETE FROM sessions WHERE id = ? AND campaign_id = ?",
        (session_id, campaign_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "session not found")
    return {"deleted": session_id}


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
                "INSERT OR IGNORE INTO members (id, campaign_id, user_id, "
                "role, joined_at) VALUES (?,?,?,?,?)",
                (m["id"], camp["id"], m["user_id"], m["role"],
                 m.get("joined_at", now)))
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
            "version = version + 1 WHERE campaign_id = ?",
            (campaign_id,))
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


# --- Entidades de campaña: NPC, lugares, misiones, escenas, notas ----
# Visibilidad: 'public' (todos), 'dm' (solo DM) o parcial via known_to.

class EntityIn(BaseModel):
    kind: str                          # npc|location|quest|faction|scene|note
    name: str
    data: dict = {}
    visibility: str = "public"         # public|dm
    known_to: list[str] = []           # player/user ids con info parcial
    reveal_condition: str | None = None


@router.post("/{campaign_id}/entities", status_code=201)
async def create_entity(campaign_id: str, body: EntityIn,
                  user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user)
    role = member_role(campaign_id, (user or {}).get("user_id"))
    if role is not None and role not in ("owner", "co_dm") \
            and body.visibility == "dm":
        raise HTTPException(
            403, "solo el DM puede crear entidades ocultas")
    eid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO campaign_entities
           (id, campaign_id, kind, name, data, visibility, known_to,
            reveal_condition, version, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
        (eid, campaign_id, body.kind, body.name, json.dumps(body.data),
         body.visibility, json.dumps(body.known_to),
         body.reveal_condition, now, now))
    conn.commit()
    await _notify_entity(campaign_id, eid, ["created"],
                         body.visibility, body.kind, body.name)
    return {"id": eid}


@router.get("/{campaign_id}/entities")
def list_entities(campaign_id: str, kind: str | None = None,
                  viewer: str | None = None,
                  user: dict | None = Depends(optional_user)):
    """Visibilidad por rol: owner/co_dm ven todo; el resto solo public
    + entidades donde su user_id está en known_to. Sin token, `viewer`
    controla la vista (modo local/anónimo)."""
    conn = state_db()
    # membresía primero: sin el guard un extraño veía al menos las
    # entidades públicas de una mesa ajena
    _require_role(conn, campaign_id, user)
    uid = (user or {}).get("user_id")
    if user is not None:
        is_dm = member_role(campaign_id, uid) in ("owner", "co_dm")
        viewer_id = uid
    elif _has_owner(conn, campaign_id):
        # con dueño, un anónimo nunca es DM — solo ve lo público
        is_dm, viewer_id = False, ""
    else:
        is_dm = (viewer or "dm") == "dm"  # compat modo local
        viewer_id = viewer or "dm"
    sql = "SELECT * FROM campaign_entities WHERE campaign_id = ?"
    params: list = [campaign_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        e = dict(r)
        e["data"] = json.loads(e["data"])
        e["known_to"] = json.loads(e["known_to"])
        if not is_dm and e["visibility"] == "dm" \
                and viewer_id not in e["known_to"]:
            continue
        out.append(e)
    return {"entities": out}


@router.post("/{campaign_id}/entities/{entity_id}/reveal")
async def reveal_entity(campaign_id: str, entity_id: str,
                        user: dict | None = Depends(optional_user)):
    """El DM revela la entidad a todos los jugadores — evento WS."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """UPDATE campaign_entities
           SET visibility='public', revealed_at=?, updated_at=?,
               version=version+1
           WHERE id=? AND campaign_id=?""",
        (now, now, entity_id, campaign_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "entity not found")
    name = conn.execute("SELECT name FROM campaign_entities WHERE id = ?",
                        (entity_id,)).fetchone()["name"]
    from ..domain.events import Event, EventType
    ev = Event(event_id=uuid.uuid4().hex,
               type=EventType.ENTITY_REVEALED,
               campaign_id=campaign_id, aggregate_id=entity_id,
               aggregate_version=0, actor_id="dm",
               occurred_at=datetime.now(timezone.utc),
               payload={"name": name})
    conn.execute(
        """INSERT INTO events
           (event_id, campaign_id, aggregate_id, aggregate_version,
            actor_id, occurred_at, type, payload)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ev.event_id, campaign_id, entity_id, 0, "dm",
         ev.occurred_at.isoformat(), ev.type.value,
         json.dumps(ev.payload)))
    conn.commit()
    await manager.broadcast(campaign_id, ev)
    return {"id": entity_id, "visibility": "public"}


# --- Grafo de relaciones --------------------------------------------

class RelationshipIn(BaseModel):
    from_id: str
    to_id: str
    type: str                          # knows|works_for|hates|family|...
    description: str | None = None
    visibility: str = "dm"
    world_date: str | None = None


@router.post("/{campaign_id}/relationships", status_code=201)
def create_relationship(campaign_id: str, body: RelationshipIn,
                        user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    rid = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO relationships
           (id, campaign_id, from_id, to_id, type, description,
            visibility, world_date, status, created_at)
           VALUES (?,?,?,?,?,?,?,?, 'active', ?)""",
        (rid, campaign_id, body.from_id, body.to_id, body.type,
         body.description, body.visibility, body.world_date,
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return {"id": rid}


@router.get("/{campaign_id}/relationships")
def list_relationships(campaign_id: str, entity_id: str | None = None,
                       viewer: str | None = None,
                       user: dict | None = Depends(optional_user)):
    """Mismo filtro que las entidades: un jugador solo ve las
    relaciones públicas — las de DM no se filtran."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    uid = (user or {}).get("user_id")
    if user is not None:
        is_dm = member_role(campaign_id, uid) in ("owner", "co_dm")
    else:
        # ?viewer solo vale en modo local; con dueño, anónimo ≠ DM
        is_dm = not _has_owner(conn, campaign_id) \
            and (viewer or "dm") == "dm"
    sql = "SELECT * FROM relationships WHERE campaign_id = ?"
    params: list = [campaign_id]
    if entity_id:
        sql += " AND (from_id = ? OR to_id = ?)"
        params += [entity_id, entity_id]
    if not is_dm:
        sql += " AND visibility != 'dm'"
    rows = conn.execute(sql, params).fetchall()
    return {"relationships": [dict(r) for r in rows]}


@router.delete("/{campaign_id}/relationships/{rel_id}", status_code=204)
def delete_relationship(campaign_id: str, rel_id: str,
                        user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    cur = conn.execute(
        "DELETE FROM relationships WHERE id = ? AND campaign_id = ?",
        (rel_id, campaign_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "relationship not found")


class PingIn(BaseModel):
    x: int
    y: int
    entity_id: str | None = None        # mapa donde se pulsó


@router.post("/{campaign_id}/ping")
async def map_ping(campaign_id: str, body: PingIn,
                   user: dict | None = Depends(optional_user)):
    """Ping efímero del mapa (botón derecho): señalar un punto a toda
    la mesa. Solo WS — no persiste en el feed de eventos."""
    from ..domain.events import Event, EventType
    conn = state_db()
    _require_role(conn, campaign_id, user)
    ev = Event(event_id=uuid.uuid4().hex, type=EventType.MAP_PING,
               campaign_id=campaign_id,
               aggregate_id=body.entity_id or campaign_id,
               aggregate_version=0,
               actor_id=(user or {}).get("name") or "?",
               occurred_at=datetime.now(timezone.utc),
               payload={"x": int(body.x), "y": int(body.y),
                        "entity_id": body.entity_id,
                        "by": (user or {}).get("name") or "?",
                        # el destinatario puede verificar que el ping
                        # es del mapa que está viendo
                        })
    await manager.broadcast(campaign_id, ev)
    return {"ok": True}


class PresentIn(BaseModel):
    entity_id: str | None = None   # None = cerrar la presentación


@router.post("/{campaign_id}/present")
async def present_entity(campaign_id: str, body: PresentIn,
                         user: dict | None = Depends(optional_user)):
    """'Mostrar al grupo' — el DM proyecta una entidad (nota, imagen de
    mapa, PNJ) en la pantalla de todos los jugadores (modal). La entidad
    debe ser visible para los jugadores: nada de filtrar secretos."""
    from ..domain.events import Event, EventType
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    payload: dict = {"entity_id": None}
    if body.entity_id:
        row = conn.execute(
            """SELECT id, kind, name, visibility, data
               FROM campaign_entities
               WHERE id = ? AND campaign_id = ?""",
            (body.entity_id, campaign_id)).fetchone()
        if row is None:
            raise HTTPException(404, "entity not found")
        # lo oculto al grupo no se puede proyectar — evita el leak de
        # proyectar una nota privada 'por error'
        if row["visibility"] != "public":
            raise HTTPException(
                400, "solo se proyectan entidades públicas")
        payload = {"entity_id": row["id"], "kind": row["kind"],
                   "name": row["name"], "data": json.loads(row["data"])}
    ev = Event(event_id=uuid.uuid4().hex, type=EventType.PRESENT,
               campaign_id=campaign_id,
               aggregate_id=body.entity_id or campaign_id,
               aggregate_version=0,
               actor_id=(user or {}).get("name") or "?",
               occurred_at=datetime.now(timezone.utc),
               payload=payload)
    await manager.broadcast(campaign_id, ev)
    return {"ok": True}


class TokenMove(BaseModel):
    token_id: str
    x: int
    y: int


@router.post("/{campaign_id}/entities/{entity_id}/token-move")
async def token_move(campaign_id: str, entity_id: str,
                     body: TokenMove,
                     user: dict | None = Depends(optional_user)):
    """Mueve un token del mapa. El DM mueve cualquiera; un jugador
    solo el suyo — el token vinculado a su ficha (`player_id` del
    token o del personaje referenciado por `ref_id`)."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    row = conn.execute(
        "SELECT * FROM campaign_entities WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "entity not found")
    data = json.loads(row["data"])
    tk = next((t for t in (data.get("tokens") or [])
               if t.get("id") == body.token_id), None)
    if tk is None:
        raise HTTPException(404, "token not found")
    uid = (user or {}).get("user_id")
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, uid) in _DM_ROLES
    if not is_dm:
        # solo el token cuya ficha pertenece al jugador
        owner_uid = tk.get("player_id")
        if owner_uid is None and tk.get("ref_id"):
            prow = conn.execute(
                "SELECT player_id FROM characters WHERE id = ?",
                (tk["ref_id"],)).fetchone()
            owner_uid = prow["player_id"] if prow else None
        if uid is None or owner_uid != uid:
            raise HTTPException(403, "ese token no es tuyo")
        # muros: una casilla adyacente ortogonal no se cruza si el
        # borde está murado (saltos largos/diagonales = rodear, libre)
        walls = set(data.get("walls") or [])
        dx, dy = int(body.x) - tk["x"], int(body.y) - tk["y"]
        if abs(dx) + abs(dy) == 1:
            edge = (f"{tk['x']},{tk['y']},S" if dy == 1 else
                    f"{tk['x']},{tk['y'] - 1},S" if dy == -1 else
                    f"{tk['x']},{tk['y']},E" if dx == 1 else
                    f"{tk['x'] - 1},{tk['y']},E")
            if edge in walls:
                raise HTTPException(400, "hay un muro en medio")
    cols = int(data.get("cols") or 16)
    rows = int(data.get("rows") or 10)
    tk["x"] = max(0, min(cols - 1, int(body.x)))
    tk["y"] = max(0, min(rows - 1, int(body.y)))
    conn.execute("UPDATE campaign_entities SET data = ? WHERE id = ?",
                 (json.dumps(data), entity_id))
    conn.commit()
    await _notify_entity(campaign_id, entity_id, ["data"],
                         row["visibility"], "map", row["name"])
    return {"x": tk["x"], "y": tk["y"]}


class EntityPatch(BaseModel):
    name: str | None = None
    data: dict | None = None
    visibility: str | None = None
    known_to: list[str] | None = None
    reveal_condition: str | None = None


@router.patch("/{campaign_id}/entities/{entity_id}")
async def patch_entity(campaign_id: str, entity_id: str, body: EntityPatch,
                       user: dict | None = Depends(optional_user)):
    """Actualiza campos de una entidad (orden de escena, estado, notas…)."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    row = conn.execute(
        "SELECT * FROM campaign_entities WHERE id = ? AND campaign_id = ?",
        (entity_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "entity not found")
    if (body.visibility is not None or body.known_to is not None) \
            and _has_owner(conn, campaign_id) \
            and member_role(campaign_id, (user or {}).get("user_id")) \
            not in _DM_ROLES:
        # la visibilidad es del DM — un jugador podría revelar
        # entidades ocultas (dm→public) u ocultarlas (public→dm)
        raise HTTPException(
            403, "solo el DM puede cambiar la visibilidad")
    sets, params = [], []
    if body.name is not None:
        sets.append("name = ?")
        params.append(body.name)
    if body.data is not None:
        merged = {**json.loads(row["data"]), **body.data}
        sets.append("data = ?")
        params.append(json.dumps(merged))
    if body.visibility is not None:
        sets.append("visibility = ?")
        params.append(body.visibility)
    if body.known_to is not None:
        sets.append("known_to = ?")
        params.append(json.dumps(body.known_to))
    if body.reveal_condition is not None:
        sets.append("reveal_condition = ?")
        params.append(body.reveal_condition)
    if not sets:
        return {"id": entity_id, "changed": []}
    sets += ["updated_at = ?", "version = version + 1"]
    params += [datetime.now(timezone.utc).isoformat(), entity_id]
    conn.execute(
        f"UPDATE campaign_entities SET {', '.join(sets)} WHERE id = ?",
        params)
    conn.commit()
    changed = [s.split(" = ")[0] for s in sets[:-2]]
    await _notify_entity(campaign_id, entity_id, changed,
                         body.visibility or row["visibility"],
                         row["kind"], row["name"])
    return {"id": entity_id, "changed": changed}


# --- Sesiones y línea temporal ---------------------------------------

class SessionIn(BaseModel):
    number: int | None = None
    title: str
    status: str = "prep"               # prep|active|done
    data: dict = {}


@router.post("/{campaign_id}/sessions", status_code=201)
def create_session(campaign_id: str, body: SessionIn,
                   user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    sid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO sessions
           (id, campaign_id, number, title, status, data, created_at,
            updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (sid, campaign_id, body.number, body.title, body.status,
         json.dumps(body.data), now, now))
    conn.commit()
    return {"id": sid}


@router.get("/{campaign_id}/sessions")
def list_sessions(campaign_id: str,
                  user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user)
    # escenas visibility=dm no se sirven a jugadores — el prep del DM
    # (notas, monstruos) no debe filtrarse a la mesa; en modo local
    # (sin owner) todo es visible
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, (user or {}).get("user_id")) \
        in _DM_ROLES
    rows = conn.execute(
        "SELECT * FROM sessions WHERE campaign_id = ? ORDER BY number",
        (campaign_id,)).fetchall()
    out = []
    for r in rows:
        s = dict(r)
        s["data"] = json.loads(s["data"])
        # escenas vinculadas a esta sesión, ordenadas
        scenes = conn.execute(
            "SELECT id, name, data, visibility FROM campaign_entities "
            "WHERE campaign_id = ? AND kind = 'scene' "
            "AND json_extract(data, '$.session_id') = ?",
            (campaign_id, s["id"])).fetchall()
        s["scenes"] = sorted(
            [{**dict(x), "data": json.loads(x["data"])} for x in scenes
             if is_dm or x["visibility"] != "dm"],
            key=lambda x: x["data"].get("order", 0))
        out.append(s)
    return {"sessions": out}


class SessionPatch(BaseModel):
    status: str | None = None        # prep|active|done
    title: str | None = None


@router.patch("/{campaign_id}/sessions/{session_id}")
async def patch_session(campaign_id: str, session_id: str,
                        body: SessionPatch,
                        user: dict | None = Depends(optional_user)):
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    if body.status and body.status not in ("prep", "active", "done"):
        raise HTTPException(400, "status inválido")
    sets, params = [], []
    if body.status:
        sets.append("status = ?")
        params.append(body.status)
    if body.title:
        sets.append("title = ?")
        params.append(body.title)
    if not sets:
        return {"id": session_id, "changed": []}
    cur = conn.execute(
        f"UPDATE sessions SET {', '.join(sets)} "
        "WHERE id = ? AND campaign_id = ?",
        (*params, session_id, campaign_id))
    # reveal_condition con evaluador real: 'session:<id>' o
    # 'session_active' se revelan cuando una sesión arranca —
    # sin esto el campo se guardaba y jamás se leía
    revealed: list[dict] = []
    if body.status == "active":
        rows = conn.execute(
            """SELECT id, name FROM campaign_entities
               WHERE campaign_id = ? AND visibility != 'public'
                 AND reveal_condition IN
                     ('session_active', ?)""",
            (campaign_id, f"session:{session_id}")).fetchall()
        if rows:
            now = datetime.now(timezone.utc).isoformat()
            ids = [r["id"] for r in rows]
            conn.execute(
                f"""UPDATE campaign_entities
                    SET visibility='public', revealed_at=?,
                        updated_at=?, version=version+1
                    WHERE id IN ({','.join('?' * len(ids))})""",
                (now, now, *ids))
            revealed = [dict(r) for r in rows]
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "session not found")
    for r in revealed:
        await _notify_reveal(conn, campaign_id, r["id"], r["name"])
    return {"id": session_id, "changed": sets,
            "revealed": [r["id"] for r in revealed]}


async def _notify_reveal(conn, campaign_id: str, entity_id: str,
                         name: str) -> None:
    """Persiste + broadcast del evento entity.revealed — usado por
    reveal manual y por reveal_condition auto al activar sesión."""
    from ..domain.events import Event, EventType
    ev = Event(event_id=uuid.uuid4().hex,
               type=EventType.ENTITY_REVEALED,
               campaign_id=campaign_id, aggregate_id=entity_id,
               aggregate_version=0, actor_id="dm",
               occurred_at=datetime.now(timezone.utc),
               payload={"name": name})
    conn.execute(
        """INSERT INTO events
           (event_id, campaign_id, aggregate_id, aggregate_version,
            actor_id, occurred_at, type, payload)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ev.event_id, campaign_id, entity_id, 0, "dm",
         ev.occurred_at.isoformat(), ev.type.value,
         json.dumps(ev.payload)))
    conn.commit()
    await manager.broadcast(campaign_id, ev)


@router.get("/{campaign_id}/timeline")
def timeline(campaign_id: str,
             user: dict | None = Depends(optional_user)):
    """Cronología del mundo: eventos + relaciones fechadas, ordenadas."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    # la línea temporal no filtra los eventos/relaciones del DM a
    # jugadores (misma regla que entities/relationships)
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, (user or {}).get("user_id")) \
        in _DM_ROLES
    events = conn.execute(
        "SELECT id, name, data, visibility FROM campaign_entities "
        "WHERE campaign_id = ? AND kind = 'event'", (campaign_id,)
    ).fetchall()
    rels = conn.execute(
        "SELECT * FROM relationships WHERE campaign_id = ? "
        "AND world_date IS NOT NULL", (campaign_id,)).fetchall()
    items = [
        {"kind": "event", "id": e["id"], "name": e["name"],
         "world_date": json.loads(e["data"]).get("world_date"),
         "data": json.loads(e["data"])}
        for e in events
        if is_dm or e["visibility"] != "dm"
    ] + [
        {"kind": "relationship", "id": r["id"],
         "name": f"{r['from_id']} → {r['to_id']}",
         "world_date": r["world_date"], "data": dict(r)}
        for r in rels
        if is_dm or r["visibility"] != "dm"
    ]
    items.sort(key=lambda x: x["world_date"] or "")
    return {"timeline": items}


@router.post("/{campaign_id}/scenes/{scene_id}/start", status_code=201)
def start_scene_combat(campaign_id: str, scene_id: str,
                       user: dict | None = Depends(optional_user)):
    """Inicia el combate preparado en una escena: crea el Combat con el
    nombre de la escena y añade los monstruos de data.monsters
    (content entity ids) como combatientes."""
    from ..domain.combat import Combat, Combatant
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    row = conn.execute(
        "SELECT data FROM campaign_entities WHERE id = ? AND campaign_id = ? "
        "AND kind = 'scene'", (scene_id, campaign_id)).fetchone()
    if row is None:
        raise HTTPException(404, "scene not found")
    scene = json.loads(row["data"])
    name = conn.execute(
        "SELECT name FROM campaign_entities WHERE id = ?",
        (scene_id,)).fetchone()["name"]
    combat = Combat(name=f"Escena: {name}", campaign_id=campaign_id)
    from ..domain import statblock
    content = content_db()
    for mid in scene.get("monsters", []):
        crow = content.execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (mid,)).fetchone()
        data = json.loads(crow["data"]) if crow else {}
        block = statblock.normalize(data)
        combat.combatants.append(Combatant(
            id=uuid.uuid4().hex, kind="monster",
            name=data.get("name", "?"), ref_id=mid,
            initiative=(block or {}).get("initiative_mod", 0) + 10,
            hp_current=(block or {}).get("hp", 1),
            hp_max=(block or {}).get("hp", 1),
            ac=(block or {}).get("ac", 10),
            stat_block=block))
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO combats (id, campaign_id, name, ruleset, version,
                                data, updated_at)
           VALUES (?,?,?,?,1,?,?)""",
        (cid, campaign_id, combat.name, "dnd5e-2014",
         json.dumps(combat.model_dump()), now))
    conn.commit()
    return {"combat_id": cid, "scene": name,
            "combatants": len(combat.combatants)}


@router.get("/{campaign_id}/events")
def campaign_events(campaign_id: str, limit: int = 100,
                    user: dict | None = Depends(optional_user)):
    """Feed de auditoría: todos los eventos de la campaña (tiradas,
    cambios de estado, revelaciones)."""
    conn = state_db()
    _require_role(conn, campaign_id, user)
    uid = (user or {}).get("user_id")
    # igual que en /state: las tiradas visibility=dm no se filtran a
    # jugadores por el feed de auditoría
    is_dm = not _has_owner(conn, campaign_id) or \
        member_role(campaign_id, uid) in _DM_ROLES
    # el filtrado de visibilidad es post-SQL: si los N últimos eventos
    # son dm-only, el jugador recibía menos de `limit` — sobre-muestrea
    # y recorta tras filtrar (mismo patrón que /operations/conflicts)
    rows = conn.execute(
        """SELECT event_id, type, aggregate_id, actor_id, occurred_at,
                  payload FROM events WHERE campaign_id = ?
           ORDER BY occurred_at DESC LIMIT ?""",
        (campaign_id, limit * 4)).fetchall()
    return {"events": [
        {**dict(r), "payload": json.loads(r["payload"])} for r in rows
        if _ev_visible(r, uid, is_dm)][:limit]}


@router.get("/{campaign_id}/export")
def export_campaign(campaign_id: str,
                    user: dict | None = Depends(optional_user)):
    """Backup completo de la campaña en JSON: entidades, miembros,
    sesiones, combates, personajes y eventos."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    def rows(table, where="campaign_id = ?"):
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE {where}",
            (campaign_id,)).fetchall()]
    camp = conn.execute("SELECT * FROM campaigns WHERE id = ?",
                        (campaign_id,)).fetchone()
    if camp is None:
        raise HTTPException(404, "campaign not found")
    return {
        "format": "dnd-companion-campaign",
        "format_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "campaign": dict(camp),
        "members": rows("members"),
        "entities": rows("campaign_entities"),
        "relationships": rows("relationships"),
        "sessions": rows("sessions"),
        "combats": rows("combats"),
        "characters": rows("characters"),
        "events": rows("events"),
    }


@router.get("/{campaign_id}/export-vtt")
def export_vtt(campaign_id: str,
               user: dict | None = Depends(optional_user)):
    """Export neutral para VTTs (Foundry/Roll20/…): personajes y
    combatientes como actores genéricos {name, type, hp, ac, abilities,
    conditions, cr}. No es un schema propietario — cada VTT lo mapea
    con un importador."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    camp = conn.execute("SELECT id, name FROM campaigns WHERE id = ?",
                        (campaign_id,)).fetchone()
    if camp is None:
        raise HTTPException(404, "campaign not found")

    def actor(name, kind, d):
        ab = d.get("abilities") or {}
        return {
            "name": name,
            "type": "npc" if kind != "character" else "character",
            "hp": {"current": (d.get("hp") or {}).get("current",
                                d.get("hp_current", 1)),
                   "max": (d.get("hp") or {}).get("max",
                             d.get("hp_max", 1)),
                   "temp": (d.get("hp") or {}).get("temp",
                              d.get("hp_temp", 0))},
            "ac": (d.get("derived") or {}).get("ac") or
                  d.get("ac") or (d.get("stat_block") or {}).get("ac"),
            "abilities": ab,
            "level": sum(c.get("level", 1)
                         for c in d.get("classes", [])) or None,
            "conditions": d.get("conditions", []),
            "cr": (d.get("stat_block") or {}).get("cr"),
            "spells": d.get("spells_known") or None,
        }

    actors, combats_out = [], []
    for r in conn.execute(
            "SELECT name, data FROM characters WHERE campaign_id = ?",
            (campaign_id,)).fetchall():
        actors.append(actor(r["name"], "character", json.loads(r["data"])))
    for r in conn.execute(
            "SELECT name, data FROM combats WHERE campaign_id = ?",
            (campaign_id,)).fetchall():
        cb = json.loads(r["data"])
        cbt = {"name": cb.get("name"), "round": cb.get("round"),
               "combatants": [
                   {**actor(c.get("name"), c.get("kind", "monster"), c),
                    "initiative": c.get("initiative")}
                   for c in cb.get("combatants", [])]}
        combats_out.append(cbt)
        actors.extend(cbt["combatants"])

    # escenas/mapa: el estado táctico completo (grid, niebla, muros,
    # luz, plantillas) para que otro VTT reconstruya el tablero
    scenes = []
    for r in conn.execute(
            """SELECT name, data FROM campaign_entities
               WHERE campaign_id = ? AND kind = 'map'""",
            (campaign_id,)).fetchall():
        d = json.loads(r["data"])
        scenes.append({
            "name": r["name"],
            "cols": d.get("cols"), "rows": d.get("rows"),
            "cell_ft": d.get("cell_ft"),
            "background_image": d.get("image_url"),
            "ambient_music": d.get("music_url"),
            "fog": d.get("fog") or [],
            "walls": d.get("walls") or [],
            "marks": d.get("marks") or {},
            "pins": d.get("pins") or [],
            "tokens": [{
                "name": tk.get("name"), "x": tk.get("x"), "y": tk.get("y"),
                "size": tk.get("size", 1), "color": tk.get("color"),
                "hp": tk.get("hp"), "hp_max": tk.get("max_hp"),
                "vision_ft": tk.get("vision_ft"),
                "light_ft": tk.get("light_ft"),
                "actor_ref": tk.get("ref_id"),
            } for tk in d.get("tokens", [])],
        })

    return {
        "format": "vtt-generic",
        "format_version": 2,
        "campaign": dict(camp),
        "actors": actors,
        "combats": combats_out,
        "scenes": scenes,
    }


# --- Solicitud de tirada (DM -> jugador) -----------------------------

class RollRequestIn(BaseModel):
    character_id: str
    expression: str = "1d20"
    reason: str = ""                   # 'tirada de percepción', 'save de SAB'
    secret: bool = False               # tirada oculta al resto


@router.post("/{campaign_id}/roll-request", status_code=202)
async def request_roll(campaign_id: str, body: RollRequestIn,
                       user: dict | None = Depends(optional_user)):
    """El DM pide una tirada; llega como evento a la sala WS."""
    conn = state_db()
    _require_role(conn, campaign_id, user, _DM_ROLES)
    from ..domain.events import Event, EventType
    payload = {"expression": body.expression, "reason": body.reason,
               "secret": body.secret}
    if body.secret and _has_owner(conn, campaign_id):
        # petición secreta: solo el dueño de la ficha (y los DM) la ven
        # — antes se emitía a toda la sala y delataba la tirada oculta
        prow = conn.execute(
            "SELECT player_id FROM characters WHERE id = ?",
            (body.character_id,)).fetchone()
        payload["for_user"] = prow["player_id"] if prow else None
        payload["visibility"] = "dm"
    event = Event(
        event_id=uuid.uuid4().hex,
        type=EventType.ROLL_REQUESTED,
        campaign_id=campaign_id,
        aggregate_id=body.character_id,
        aggregate_version=0,
        actor_id="dm",
        occurred_at=datetime.now(timezone.utc),
        payload=payload,
    )
    conn.execute(
        """INSERT INTO events
           (event_id, campaign_id, aggregate_id, aggregate_version,
            actor_id, occurred_at, type, payload)
           VALUES (?,?,?,?,?,?,?,?)""",
        (event.event_id, campaign_id, event.aggregate_id,
         event.aggregate_version, event.actor_id,
         event.occurred_at.isoformat(), event.type.value,
         json.dumps(event.payload)))
    conn.commit()
    await manager.broadcast(campaign_id, event)
    # push PWA al dueño de la ficha — le llega aunque tenga la app
    # cerrada (móvil en bolsillo antes de la sesión)
    prow = conn.execute(
        "SELECT player_id FROM characters WHERE id = ?",
        (body.character_id,)).fetchone()
    if prow and prow["player_id"]:
        from .push import send_push
        # webpush es I/O bloqueante — sacarlo del event loop o cada
        # push congela la sala entera unos cientos de ms
        await asyncio.to_thread(
            send_push, prow["player_id"], "Tirada solicitada",
            body.reason or body.expression, f"/campaign/{campaign_id}")
    return {"event_id": event.event_id}


# --- Reparto de tesoro del grupo -----------------------------------

_COINS = ("pp", "gp", "ep", "sp", "cp")


class LootSplit(BaseModel):
    coin: str = "gp"
    amount: int = 0


@router.post("/{campaign_id}/split-loot")
async def split_loot(campaign_id: str, body: LootSplit,
                     user: dict | None = Depends(optional_user)):
    """Reparte el tesoro entre las fichas de la campaña — cada parte es
    una op `character.currency.earn` real: auditable, deshacible y con
    broadcast a la sala (el que esté conectado ve su bolsa crecer)."""
    from .operations import OperationIn, apply_to_store
    conn = state_db()
    if _has_owner(conn, campaign_id):
        _require_role(conn, campaign_id, user, _DM_ROLES)
    if body.coin not in _COINS or body.amount <= 0:
        raise HTTPException(400, "tesoro inválido")
    rows = conn.execute(
        "SELECT id, version FROM characters WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    if not rows:
        return {"share": 0, "awarded": 0}
    share, rem = divmod(body.amount, len(rows))
    uid = (user or {}).get("user_id") or "dm"
    awarded = 0
    for i, r in enumerate(rows):
        part = share + (1 if i < rem else 0)
        if part <= 0:
            continue
        result = apply_to_store(OperationIn(
            operation_id=uuid.uuid4().hex, entity_id=r["id"],
            entity_version=r["version"], client_id="api:split-loot",
            user_id=uid, operation_type="character.currency.earn",
            entity_kind="character", payload={body.coin: part}))
        for event in result.pop("_event_objs", []):
            await manager.broadcast(campaign_id, event)
        awarded += 1
    return {"share": share, "awarded": awarded}


@router.post("/{campaign_id}/rest")
async def party_rest(campaign_id: str, kind: str = "long",
                     user: dict | None = Depends(optional_user)):
    """Descanso del grupo: aplica `character.rest.<kind>` a cada ficha
    de la campaña como op real (auditable, deshacible, broadcast) —
    el DM declara el descanso y todas las fichas se recuperan a la vez."""
    from .operations import OperationIn, apply_to_store
    if kind not in ("short", "long"):
        raise HTTPException(400, "kind debe ser short|long")
    conn = state_db()
    if _has_owner(conn, campaign_id):
        _require_role(conn, campaign_id, user, _DM_ROLES)
    rows = conn.execute(
        "SELECT id, version FROM characters WHERE campaign_id = ?",
        (campaign_id,)).fetchall()
    uid = (user or {}).get("user_id") or "dm"
    for r in rows:
        result = apply_to_store(OperationIn(
            operation_id=uuid.uuid4().hex, entity_id=r["id"],
            entity_version=r["version"], client_id="api:party-rest",
            user_id=uid,
            operation_type=f"character.rest.{kind}",
            entity_kind="character", payload={}))
        for event in result.pop("_event_objs", []):
            await manager.broadcast(campaign_id, event)
    return {"rested": len(rows), "kind": kind}


@router.get("/{campaign_id}/roll-requests/pending")
def pending_roll_requests(campaign_id: str, character_ids: str = "",
                          user: dict | None = Depends(optional_user)):
    """Peticiones de tirada aún sin responder.

    Una petición dice.roll.requested cuenta pendiente si el último
    evento dice.* de ese personaje es la petición (la respuesta del
    jugador emite dice.roll.created sobre el mismo aggregate_id).
    """
    ids = [x for x in character_ids.split(",") if x]
    if not ids:
        return {"pending": []}
    conn = state_db()
    _require_role(conn, campaign_id, user)
    # un jugador solo consulta SUS fichas: una petición secreta a otro
    # PJ filtraría el motivo del DM ("percepción: te mienten")
    uid = (user or {}).get("user_id")
    if _has_owner(conn, campaign_id) \
            and member_role(campaign_id, uid) not in _DM_ROLES:
        allowed = {r["id"] for r in conn.execute(
            f"""SELECT id FROM characters
                WHERE id IN ({",".join("?" * len(ids))})
                  AND (player_id = ? OR player_id IS NULL
                       OR player_id = '')""",
            (*ids, uid)).fetchall()}
        ids = [i for i in ids if i in allowed]
        if not ids:
            return {"pending": []}
    rows = conn.execute(
        f"""SELECT aggregate_id, type, occurred_at, payload
            FROM events
            WHERE campaign_id = ?
              AND aggregate_id IN ({",".join("?" * len(ids))})
              AND type IN ('dice.roll.requested', 'dice.roll.created')
            ORDER BY occurred_at""",
        (campaign_id, *ids)).fetchall()
    latest: dict[str, dict | None] = {}
    for r in rows:
        latest[r["aggregate_id"]] = (
            {**json.loads(r["payload"]), "at": r["occurred_at"]}
            if r["type"] == "dice.roll.requested" else None)
    return {"pending": [
        {"character_id": k, **v} for k, v in latest.items() if v]}
