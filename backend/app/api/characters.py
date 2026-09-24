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


from ..domain.classinfo import (
    background_languages as _background_languages,
    background_skills as _background_skills,
    hit_die as _hit_die,
    save_profs as _save_profs,
    species_asi as _species_asi,
    species_traits as _species_traits)


@router.post("/create-from-options", status_code=201)
def create_from_options(body: WizardCreate):
    """Construye un Character nivel 1 desde la content DB:
    HP = hit_die + mod CON, pool de hit dice, spell slots si es caster."""
    cls = _content_row(body.class_id)
    if cls is None:
        raise HTTPException(400, "class not found in content DB")

    abilities = AbilityScores(**(body.abilities or {}))

    # traits de especie: ASI fijas aplicadas a las puntuaciones base
    if body.species_id:
        sp = _content_row(body.species_id) or {}
        for ab, bonus in _species_asi(sp).items():
            attr = {"str": "strength", "dex": "dexterity",
                    "con": "constitution", "int": "intelligence",
                    "wis": "wisdom", "cha": "charisma"}[ab]
            setattr(abilities, attr,
                    getattr(abilities, attr) + bonus)

    hit_die = _hit_die(cls)
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
        save_proficiencies=_save_profs(cls),
        skill_proficiencies=_background_skills(
            _content_row(body.background_id) or {}
            if body.background_id else {}),
        # rasgos de especie y lenguas del trasfondo — datos reales
        features=list(_species_traits(
            _content_row(body.species_id) or {}
            if body.species_id else {})),
        languages=list(_background_languages(
            _content_row(body.background_id) or {}
            if body.background_id else {})),
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


class CharPatch(BaseModel):
    name: str | None = None
    campaign_id: str | None = None


@router.patch("/{character_id}")
def patch_character(character_id: str, body: CharPatch):
    """Renombrar / reasignar campaña (los cambios de estado de juego van
    por /api/operations; esto es solo metadata)."""
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    data = json.loads(row["data"])
    changed = []
    if body.name is not None:
        data["name"] = body.name
        changed.append("name")
    if body.campaign_id is not None:
        changed.append("campaign_id")
    conn.execute(
        """UPDATE characters SET name = ?, campaign_id = ?, data = ?,
           version = version + 1, updated_at = ? WHERE id = ?""",
        (data["name"],
         body.campaign_id if body.campaign_id is not None
         else row["campaign_id"],
         json.dumps(data), datetime.now(timezone.utc).isoformat(),
         character_id))
    conn.commit()
    return {"id": character_id, "changed": changed}


@router.delete("/{character_id}")
def delete_character(character_id: str):
    """Borra la ficha (sus operaciones quedan en el historial)."""
    conn = state_db()
    cur = conn.execute("DELETE FROM characters WHERE id = ?",
                       (character_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "character not found")
    return {"deleted": character_id}


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


@router.get("/{character_id}/derived")
def derived_all(character_id: str):
    """Resumen derivado de la ficha: CA (armadura equipada + DES +
    escudo + efectos), iniciativa, percepción pasiva, CD/ataque de
    conjuro. Todo calculado — nada se guarda."""
    conn = state_db()
    row = conn.execute(
        "SELECT data FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    char = Character(**json.loads(row["data"]))
    content = content_db()
    dex_mod = char.abilities.modifier("dex")
    wis_mod = char.abilities.modifier("wis")

    # CA: armadura equipada del inventario (por source_id → equipo SRD)
    ac_base, ac_dex_max, ac_parts = 10, None, [("base", 10)]
    for it in char.inventory:
        if not it.equipped or not it.source_id:
            continue
        r = content.execute(
            "SELECT data FROM content_entities WHERE id = ?",
            (it.source_id,)).fetchone()
        eq = json.loads(r["data"]) if r else {}
        cat = (eq.get("equipment_category") or {}).get("index", "")
        if cat == "armor":
            base = (eq.get("armor_class") or {}).get("base", 10)
            ac_base = base
            ac_parts = [(it.name, base)]
            ac_dex_max = ((eq.get("armor_class") or {}).get("max_bonus")
                          if (eq.get("armor_class") or {}).get("dex_bonus")
                          else 0)
        elif cat == "shield" or "shield" in it.name.lower():
            bonus = (eq.get("armor_class") or {}).get("base", 2)
            ac_base += bonus
            ac_parts.append((it.name, bonus))
    dex_applied = dex_mod if ac_dex_max is None else min(dex_mod,
                                                         ac_dex_max)
    if dex_applied:
        ac_parts.append(("DES", dex_applied))
    for eff in char.effects:
        for o in eff.operations:
            if o.op.value == "add_modifier" and o.target == "armor_class":
                ac_base += int(o.value or 0)
                ac_parts.append((eff.name, int(o.value or 0)))

    # conjuros: característica de lanzamiento según la clase
    cast_ability = "int"
    if char.classes:
        cls = _content_row(char.classes[0].class_id) or {}
        cast_ability = ((cls.get("spellcasting") or {})
                        .get("spellcasting_ability") or {}
                        ).get("index", "int")
    cast_mod = char.abilities.modifier(cast_ability)
    pp = 10 + wis_mod + (char.proficiency_bonus
                         if "perception" in char.skill_proficiencies else 0)
    return {
        "armor_class": {"total": ac_base + dex_applied,
                        "breakdown": ac_parts},
        "initiative": dex_mod,
        "passive_perception": pp,
        "spell_save_dc": 8 + char.proficiency_bonus + cast_mod,
        "spell_attack": char.proficiency_bonus + cast_mod,
        "spellcasting_ability": cast_ability,
        "proficiency_bonus": char.proficiency_bonus,
        "next_level_xp": _next_level_xp(char.total_level, char.xp),
    }


# SRD 2014: XP acumulado necesario por nivel (índice = nivel actual)
_XP_TABLE = [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
             85000, 100000, 120000, 140000, 165000, 195000, 225000,
             265000, 305000, 355000]


def _next_level_xp(level: int, xp: int) -> int | None:
    if level >= 20:
        return None
    return _XP_TABLE[level] - xp


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
