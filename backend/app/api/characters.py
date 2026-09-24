"""Characters — state DB. Writes go through the operations log so every
change is idempotent and reversible (see domain/events.py)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.connections import content_db, state_db
from ..domain.character import (
    AbilityScores, Character, ClassLevel, HitDicePool, HitPoints,
)
from ..domain.ruleset import Ruleset
from ..engine.engine import resolve_stat

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
    char = Character(name=body.name, ruleset=body.ruleset, **body.data)
    conn.execute(
        """INSERT INTO characters
           (id, name, player_id, campaign_id, ruleset, version, data, updated_at)
           VALUES (?,?,?,?,?,1,?,?)""",
        (cid, body.name, body.player_id, body.campaign_id,
         body.ruleset.value, json.dumps(char.model_dump()), now),
    )
    conn.commit()
    return {"id": cid, "version": 1}


class WizardCreate(BaseModel):
    """Creación guiada: ids de entidades de la content DB + stats."""
    name: str
    ruleset: Ruleset = Ruleset.DND5E_2014
    class_id: str                       # content entity id, 'srd-2014:barbarian'
    species_id: str | None = None
    background_id: str | None = None
    abilities: dict = {}                # {'str':15,'dex':14,...}
    player_id: str | None = None
    campaign_id: str | None = None


def _content_row(entity_id: str) -> dict | None:
    row = content_db().execute(
        "SELECT data FROM content_entities WHERE id = ?",
        (entity_id,)).fetchone()
    return json.loads(row["data"]) if row else None


@router.post("/create-from-options", status_code=201)
def create_from_options(body: WizardCreate):
    """Construye un Character nivel 1 desde la content DB:
    HP = hit_die + mod CON, pool de hit dice, spell slots si es caster."""
    cls = _content_row(body.class_id)
    if cls is None:
        raise HTTPException(400, "class not found in content DB")

    abilities = AbilityScores(**(body.abilities or {}))
    hit_die = int(cls.get("hit_die", 8))
    hp_max = max(1, hit_die + abilities.modifier("con"))

    # spell slots y prof bonus nivel 1: entidad 'level' '{clase}-1'
    spell_slots: dict[str, dict[str, int]] = {}
    prof_bonus = 2
    source, class_index = body.class_id.split(":", 1)
    lvl = _content_row(f"{source}:{class_index}-1")
    if lvl:
        prof_bonus = int(lvl.get("prof_bonus", 2))
        sc = lvl.get("spellcasting") or {}
        for n in range(1, 10):
            slots = sc.get(f"spell_slots_level_{n}", 0)
            if slots:
                spell_slots[str(n)] = {"total": slots, "used": 0}

    char = Character(
        name=body.name,
        ruleset=body.ruleset,
        species_id=body.species_id,
        background_id=body.background_id,
        classes=[ClassLevel(class_id=body.class_id, level=1)],
        abilities=abilities,
        hp=HitPoints(current=hp_max, max=hp_max),
        hit_dice=[HitDicePool(die=f"d{hit_die}", total=1, remaining=1)],
        spell_slots=spell_slots,
        proficiency_bonus=prof_bonus,
    )

    conn = state_db()
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO characters
           (id, name, player_id, campaign_id, ruleset, version, data, updated_at)
           VALUES (?,?,?,?,?,1,?,?)""",
        (cid, body.name, body.player_id, body.campaign_id,
         body.ruleset.value, json.dumps(char.model_dump()), now))
    conn.commit()
    return {"id": cid, "version": 1}


@router.get("")
def list_characters(campaign_id: str | None = None):
    conn = state_db()
    sql = "SELECT id, name, ruleset, version, campaign_id FROM characters"
    params: list = []
    if campaign_id:
        sql += " WHERE campaign_id = ?"
        params.append(campaign_id)
    rows = conn.execute(sql, params).fetchall()
    return {"characters": [dict(r) for r in rows]}


EXPORT_VERSION = 1


@router.get("/{character_id}/export")
def export_character(character_id: str):
    """JSON versionado y portable de la ficha completa."""
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    return {
        "format": "dnd-companion-character",
        "format_version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "character": json.loads(row["data"]),
    }


class ImportIn(BaseModel):
    character: dict
    campaign_id: str | None = None
    player_id: str | None = None


@router.post("/import", status_code=201)
def import_character(body: ImportIn):
    """Importa una ficha exportada. Revalida contra el modelo actual."""
    char = Character(**body.character)
    conn = state_db()
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO characters
           (id, name, player_id, campaign_id, ruleset, version, data, updated_at)
           VALUES (?,?,?,?,?,1,?,?)""",
        (cid, char.name, body.player_id, body.campaign_id,
         char.ruleset.value, json.dumps(char.model_dump()), now))
    conn.commit()
    return {"id": cid, "version": 1}


@router.get("/{character_id}/actions")
def contextual_actions(character_id: str):
    """Acciones agrupadas por economía de acción: qué puede hacer el
    personaje AHORA. Deriva de inventario (armas), conjuros conocidos
    (por casting_time) y efectos activos (grant_action/reaction)."""
    conn = state_db()
    row = conn.execute(
        "SELECT data FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    char = Character(**json.loads(row["data"]))
    content = content_db()

    groups: dict[str, list] = {
        "action": [], "bonus_action": [], "reaction": [],
        "movement": [], "free": [],
    }
    for basic in ("Attack", "Dash", "Disengage", "Dodge", "Help",
                  "Hide", "Search", "Use Object"):
        groups["action"].append({"name": basic, "source": "basic"})
    groups["reaction"].append(
        {"name": "Opportunity Attack", "source": "basic"})
    groups["movement"].append({"name": "Move", "source": "basic"})

    str_mod = char.abilities.modifier("str")
    dex_mod = char.abilities.modifier("dex")

    # armas del inventario → ataques con bonificador calculado
    for item in char.inventory:
        if not item.source_id:
            continue
        w = _content_row(item.source_id)
        if not w:
            continue
        cat = (w.get("equipment_category") or {}).get("index", "")
        if "weapon" not in cat:
            continue
        props = [p.get("index") for p in w.get("properties", [])]
        mod = dex_mod if "finesse" in props else str_mod
        dmg = (w.get("damage") or {}).get("damage_dice", "1d4")
        groups["action"].append({
            "name": f"Ataque: {item.name}",
            "source": item.source_id,
            "hit": f"+{char.proficiency_bonus + mod}",
            "damage": f"{dmg}{mod:+d}",
        })

    # conjuros conocidos → agrupados por tiempo de lanzamiento
    for sid in char.spells_known:
        sp = _content_row(sid)
        if not sp:
            continue
        ct = str(sp.get("casting_time", "1 action")).lower()
        if "bonus" in ct:
            g = "bonus_action"
        elif "reaction" in ct:
            g = "reaction"
        elif "minute" in ct or "hour" in ct:
            g = "free"                       # fuera de combate
        else:
            g = "action"
        groups[g].append({"name": f"Conjuro: {sp.get('name')}",
                          "source": sid, "casting_time": ct})

    # efectos que conceden acciones (p.ej. haste, rogue cunning action)
    for eff in char.effects:
        for o in eff.operations:
            if o.op.value == "grant_action":
                groups[str(o.value or "action")].append(
                    {"name": eff.name, "source": eff.source or eff.id})
            elif o.op.value == "grant_reaction":
                groups["reaction"].append(
                    {"name": eff.name, "source": eff.source or eff.id})

    return {"character_id": character_id, "actions": groups}


@router.get("/{character_id}/derived/{stat}")
def derived_stat(character_id: str, stat: str, base: float = 10):
    """Stat resuelto por el motor de efectos, con trazabilidad:
    'CA 18 = 10 base +3 armadura +2 escudo'."""
    conn = state_db()
    row = conn.execute(
        "SELECT data FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    char = Character(**json.loads(row["data"]))
    return resolve_stat(stat, base, char.effects).model_dump()


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
