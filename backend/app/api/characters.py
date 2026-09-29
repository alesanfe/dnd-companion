"""Characters — state DB. Writes go through the operations log so every
change is idempotent and reversible (see domain/events.py)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import member_role, optional_user
from .campaigns import _DM_ROLES, _has_owner, _require_role
from ..db.connections import content_db, state_db
from ..domain.character import (
    AbilityScores, Character, ClassLevel, HitDicePool, HitPoints,
)
from ..domain.classinfo import (
    asi_earned as _asi_earned,
    background_languages as _background_languages,
    background_skills as _background_skills,
    hit_die as _hit_die,
    save_profs as _save_profs,
    species_asi as _species_asi,
    species_traits as _species_traits)
from ..domain.ruleset import Ruleset
from ..engine.engine import resolve_stat

router = APIRouter(prefix="/api/characters", tags=["characters"])


def _char_camp_guard(conn, campaign_id: str | None,
                     user: dict | None) -> None:
    """Si la ficha vive en una campaña con dueño, solo sus miembros
    la leen/mutan. Sin campaña (o campaña local sin owner) = abierto."""
    if campaign_id and _has_owner(conn, campaign_id):
        _require_role(conn, campaign_id, user)


_PRIVATE_NARRATIVE = ("secrets",)   # campos "solo PJ + DM" del dominio


def _can_see_private(conn, campaign_id: str | None,
                     player_id: str | None,
                     user: dict | None) -> bool:
    """Los campos privados de la ficha los ve su dueño y el DM;
    en campañas locales (sin owner) todo es visible."""
    if not campaign_id or not _has_owner(conn, campaign_id):
        return True
    uid = (user or {}).get("user_id")
    return player_id == uid or member_role(campaign_id, uid) in _DM_ROLES


def redact_private(data: dict) -> dict:
    """Copia de la ficha sin los campos marcados privados — para
    lectores que son miembros pero ni dueño ni DM."""
    nar = data.get("narrative") or {}
    if any(nar.get(k) for k in _PRIVATE_NARRATIVE):
        data = {**data, "narrative":
                {**nar, **{k: "" if isinstance(nar.get(k), str)
                           else ([] if isinstance(nar.get(k), list)
                                 else None)
                           for k in _PRIVATE_NARRATIVE}}}
    return data


def _char_write_guard(conn, campaign_id: str | None, player_id: str | None,
                      user: dict | None) -> None:
    """Mutación además de membresía: en campaña con dueño, un miembro
    no-DM solo toca la ficha cuyo player_id es el suyo (vacío = libre
    de reclamar); el DM mueve todas."""
    _char_camp_guard(conn, campaign_id, user)
    if campaign_id and player_id \
            and _has_owner(conn, campaign_id):
        uid = (user or {}).get("user_id")
        if member_role(campaign_id, uid) not in _DM_ROLES \
                and player_id != uid:
            raise HTTPException(403, "la ficha es de otro jugador")


def _bound_player_id(conn, campaign_id: str | None,
                     player_id: str | None,
                     user: dict | None) -> str | None:
    """Alta en campaña con dueño: un miembro no-DM solo crea fichas
    SUYAS (player_id = su uid; el del body sería spoofable). El DM sí
    asigna player_id arbitrarios."""
    uid = (user or {}).get("user_id")
    if campaign_id and _has_owner(conn, campaign_id) \
            and member_role(campaign_id, uid) not in _DM_ROLES:
        return uid
    return player_id


def _member_camps(conn, uid: str | None) -> set[str]:
    """Campañas donde el usuario es miembro u owner directo."""
    if not uid:
        return set()
    owned = {r["id"] for r in conn.execute(
        "SELECT id FROM campaigns WHERE owner_id = ?", (uid,))}
    joined = {r["campaign_id"] for r in conn.execute(
        "SELECT campaign_id FROM members WHERE user_id = ?", (uid,))}
    return owned | joined


class CharacterCreate(BaseModel):
    name: str
    ruleset: Ruleset = Ruleset.DND5E_2014
    player_id: str | None = None
    campaign_id: str | None = None
    data: dict = {}


@router.post("", status_code=201)
def create_character(body: CharacterCreate,
                     user: dict | None = Depends(optional_user)):
    conn = state_db()
    _char_camp_guard(conn, body.campaign_id, user)
    player_id = _bound_player_id(conn, body.campaign_id,
                                 body.player_id, user)
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    char = Character(name=body.name, ruleset=body.ruleset, **body.data)
    conn.execute(
        """INSERT INTO characters
           (id, name, player_id, campaign_id, ruleset, version, data, updated_at)
           VALUES (?,?,?,?,?,1,?,?)""",
        (cid, body.name, player_id, body.campaign_id,
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
def create_from_options(body: WizardCreate,
                        user: dict | None = Depends(optional_user)):
    """Construye un Character nivel 1 desde la content DB:
    HP = hit_die + mod CON, pool de hit dice, spell slots si es caster."""
    conn = state_db()
    _char_camp_guard(conn, body.campaign_id, user)
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
    player_id = _bound_player_id(conn, body.campaign_id,
                                 body.player_id, user)
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO characters
           (id, name, player_id, campaign_id, ruleset, version, data, updated_at)
           VALUES (?,?,?,?,?,1,?,?)""",
        (cid, body.name, player_id, body.campaign_id,
         body.ruleset.value, json.dumps(char.model_dump()), now))
    conn.commit()
    return {"id": cid, "version": 1}


@router.get("")
def list_characters(campaign_id: str | None = None,
                    user: dict | None = Depends(optional_user)):
    """Lista enriquecida: nivel total, PG y clase principal extraídos
    del JSON para la vista de tarjetas."""
    conn = state_db()
    if campaign_id and _has_owner(conn, campaign_id):
        _require_role(conn, campaign_id, user)
    sql = """SELECT id, name, ruleset, version, campaign_id, player_id,
                    updated_at,
                    json_extract(data, '$.hp.current') AS hp_current,
                    json_extract(data, '$.hp.max') AS hp_max,
                    data
             FROM characters"""
    params: list = []
    if campaign_id:
        sql += " WHERE campaign_id = ?"
        params.append(campaign_id)
    rows = conn.execute(sql, params).fetchall()
    # fichas de campañas con dueño solo las ven sus miembros; el resto
    # (locales o sin campaña) sigue visible en modo local
    owned = {r["id"] for r in conn.execute(
        "SELECT id FROM campaigns WHERE owner_id IS NOT NULL")}
    mine = _member_camps(conn, (user or {}).get("user_id"))
    out = []
    for r in rows:
        if r["campaign_id"] in owned and r["campaign_id"] not in mine:
            continue
        d = dict(r)
        data = json.loads(d.pop("data"))
        classes = data.get("classes") or []
        d["level"] = sum(c.get("level", 1) for c in classes) or 1
        d["class_names"] = [
            (c.get("name") or c.get("class_id", "").split(":")[-1]
             ).replace("-", " ") for c in classes]
        # vista de grupo (party tracker): vitales para las tarjetas
        d["player_name"] = data.get("player_name") or ""
        d["hp_temp"] = (data.get("hp") or {}).get("temp") or 0
        d["conditions"] = data.get("conditions") or []
        d["condition_stacks"] = data.get("condition_stacks") or {}
        d["concentrating_on"] = data.get("concentrating_on")
        out.append(d)
    return {"characters": out}


class CharPatch(BaseModel):
    name: str | None = None
    campaign_id: str | None = None
    player_id: str | None = None      # reclamar (uid propio) / soltar


@router.patch("/{character_id}")
def patch_character(character_id: str, body: CharPatch,
                    user: dict | None = Depends(optional_user)):
    """Renombrar / reasignar campaña (los cambios de estado de juego van
    por /api/operations; esto es solo metadata)."""
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    _char_write_guard(conn, row["campaign_id"], row["player_id"], user)
    # mover A una campaña con dueño también exige membresía — si no,
    # cualquiera colaba fichas en mesas ajenas
    if "campaign_id" in body.model_fields_set and body.campaign_id:
        _char_camp_guard(conn, body.campaign_id, user)
    data = json.loads(row["data"])
    changed = []
    if body.name is not None:
        data["name"] = body.name
        changed.append("name")
    # fields_set distingue "no enviado" de null explícito — un
    # campaign_id=null saca al PJ de la campaña (antes era imposible)
    new_campaign = (body.campaign_id
                    if "campaign_id" in body.model_fields_set
                    else row["campaign_id"])
    if "campaign_id" in body.model_fields_set:
        changed.append("campaign_id")
    new_player = (body.player_id
                  if "player_id" in body.model_fields_set
                  else row["player_id"])
    if "player_id" in body.model_fields_set:
        changed.append("player_id")
        if row["campaign_id"] and _has_owner(conn, row["campaign_id"]) \
                and member_role(row["campaign_id"],
                                (user or {}).get("user_id")) \
                not in _DM_ROLES:
            # reclamar/soltar: un no-DM solo toma fichas LIBRES o
            # suelta las suyas — nunca reasigna el player_id de otro
            uid = (user or {}).get("user_id")
            if new_player not in (None, uid) \
                    or row["player_id"] not in (None, uid):
                raise HTTPException(
                    403, "solo puedes reclamar fichas libres "
                         "o soltar la tuya")
    conn.execute(
        """UPDATE characters SET name = ?, campaign_id = ?, player_id = ?,
           data = ?, version = version + 1, updated_at = ? WHERE id = ?""",
        (data["name"], new_campaign, new_player,
         json.dumps(data), datetime.now(timezone.utc).isoformat(),
         character_id))
    conn.commit()
    return {"id": character_id, "changed": changed}


@router.delete("/{character_id}")
def delete_character(character_id: str,
                     user: dict | None = Depends(optional_user)):
    """Borra la ficha (sus operaciones quedan en el historial)."""
    conn = state_db()
    row = conn.execute(
        "SELECT campaign_id, player_id FROM characters WHERE id = ?",
        (character_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    _char_write_guard(conn, row["campaign_id"], row["player_id"], user)
    cur = conn.execute("DELETE FROM characters WHERE id = ?",
                       (character_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "character not found")
    return {"deleted": character_id}


EXPORT_VERSION = 1


@router.get("/{character_id}/export")
def export_character(character_id: str,
                     user: dict | None = Depends(optional_user)):
    """JSON versionado y portable de la ficha completa."""
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    _char_camp_guard(conn, row["campaign_id"], user)
    data = json.loads(row["data"])
    if not _can_see_private(conn, row["campaign_id"],
                            row["player_id"], user):
        data = redact_private(data)
    return {
        "format": "dnd-companion-character",
        "format_version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "character": data,
    }


class ImportIn(BaseModel):
    character: dict
    campaign_id: str | None = None
    player_id: str | None = None


@router.post("/import", status_code=201)
def import_character(body: ImportIn,
                     user: dict | None = Depends(optional_user)):
    """Importa una ficha exportada. Revalida contra el modelo actual."""
    char = Character(**body.character)
    conn = state_db()
    _char_camp_guard(conn, body.campaign_id, user)
    player_id = _bound_player_id(conn, body.campaign_id,
                                 body.player_id, user)
    cid = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO characters
           (id, name, player_id, campaign_id, ruleset, version, data, updated_at)
           VALUES (?,?,?,?,?,1,?,?)""",
        (cid, char.name, player_id, body.campaign_id,
         char.ruleset.value, json.dumps(char.model_dump()), now))
    conn.commit()
    return {"id": cid, "version": 1}


@router.get("/{character_id}/actions")
def contextual_actions(character_id: str,
                       user: dict | None = Depends(optional_user)):
    """Acciones agrupadas por economía de acción: qué puede hacer el
    personaje AHORA. Deriva de inventario (armas), conjuros conocidos
    (por casting_time) y efectos activos (grant_action/reaction)."""
    conn = state_db()
    row = conn.execute(
        "SELECT data, campaign_id FROM characters WHERE id = ?",
        (character_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    _char_camp_guard(conn, row["campaign_id"], user)
    char = Character(**json.loads(row["data"]))

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
    _weapon_actions(char, groups, str_mod, dex_mod)
    _spell_actions(char, groups)
    _effect_actions(char, groups)

    return {"character_id": character_id, "actions": groups}


def _weapon_actions(char, groups, str_mod, dex_mod) -> None:
    """Armas del inventario → ataques con bonificador calculado."""
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


def _spell_actions(char, groups) -> None:
    """Conjuros conocidos → agrupados por tiempo de lanzamiento."""
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


def _effect_actions(char, groups) -> None:
    """Efectos que conceden acciones (p.ej. haste, cunning action)."""
    for eff in char.effects:
        for o in eff.operations:
            if o.op.value == "grant_action":
                groups[str(o.value or "action")].append(
                    {"name": eff.name, "source": eff.source or eff.id})
            elif o.op.value == "grant_reaction":
                groups["reaction"].append(
                    {"name": eff.name, "source": eff.source or eff.id})


@router.get("/{character_id}/derived/{stat}")
def derived_stat(character_id: str, stat: str, base: float = 10,
                 user: dict | None = Depends(optional_user)):
    """Stat resuelto por el motor de efectos, con trazabilidad:
    'CA 18 = 10 base +3 armadura +2 escudo'."""
    conn = state_db()
    row = conn.execute(
        "SELECT data, campaign_id FROM characters WHERE id = ?",
        (character_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    _char_camp_guard(conn, row["campaign_id"], user)
    char = Character(**json.loads(row["data"]))
    return resolve_stat(stat, base, char.effects).model_dump()


@router.get("/{character_id}/derived")
def derived_all(character_id: str,
                user: dict | None = Depends(optional_user)):
    """Resumen derivado de la ficha: CA (armadura equipada + DES +
    escudo + efectos), iniciativa, percepción pasiva, CD/ataque de
    conjuro. Todo calculado — nada se guarda."""
    conn = state_db()
    row = conn.execute(
        "SELECT data, campaign_id FROM characters WHERE id = ?",
        (character_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    _char_camp_guard(conn, row["campaign_id"], user)
    char = Character(**json.loads(row["data"]))
    content = content_db()
    dex_mod = char.abilities.modifier("dex")
    wis_mod = char.abilities.modifier("wis")
    ac_total, ac_parts = _armor_class(char, content, dex_mod)

    # conjuros: característica de lanzamiento según la clase
    # (multi-schema — classinfo cubre 5e-bits/5etools/open5e)
    cast_ability = "int"
    if char.classes:
        from ..domain.classinfo import spellcasting_ability
        cls = _content_row(char.classes[0].class_id) or {}
        cast_ability = spellcasting_ability(cls) or "int"
    cast_mod = char.abilities.modifier(cast_ability)
    from ..rules import rules
    cbase = rules()["combat"]
    pp = cbase["passive_score_base"] + wis_mod + (
        char.proficiency_bonus
        if "perception" in char.skill_proficiencies else 0)
    return {
        "armor_class": {"total": ac_total, "breakdown": ac_parts},
        "initiative": dex_mod,
        "passive_perception": pp,
        "spell_save_dc": cbase["spell_dc_base"] +
                         char.proficiency_bonus + cast_mod,
        "spell_attack": char.proficiency_bonus + cast_mod,
        "spellcasting_ability": cast_ability,
        # tope 2014/2024: nivel total + mod de lanzamiento (mín. 1)
        "prepared_limit": max(1, char.total_level + cast_mod),
        "proficiency_bonus": char.proficiency_bonus,
        # umbral del siguiente nivel (tabla level_xp) y cuánto falta
        "next_level_xp": _next_level_xp(char.total_level),
        "xp_to_next": _xp_to_next(char.total_level, char.xp),
        # regla de agotamiento: penalizadores activos por nivel
        "exhaustion": _exhaustion(char),
        "asi_available": _asi_available(char),
        # defensas concedidas por efectos activos (resistencia al
        # fuego del dragonborn, inmunidad de conjuro, vulnerabilidad)
        "defenses": _defenses(char),
    }


def _armor_piece(content, it):
    """Pieza equipada → (kind, valor, tope de DES) o None.
    kind: 'armor' (reemplaza base) o 'shield' (suma bonus)."""
    r = content.execute(
        "SELECT data FROM content_entities WHERE id = ?",
        (it.source_id,)).fetchone()
    eq = json.loads(r["data"]) if r else {}
    cat = (eq.get("equipment_category") or {}).get("index", "")
    ac = eq.get("armor_class") or {}
    if cat == "armor":
        return ("armor", ac.get("base", 10),
                ac.get("max_bonus") if ac.get("dex_bonus") else 0)
    if cat == "shield" or "shield" in it.name.lower():
        return ("shield", ac.get("base", 2), None)
    return None


def _armor_class(char, content, dex_mod: int):
    """CA: armadura equipada del inventario (por source_id → equipo
    SRD) + escudo + efectos add_modifier. Devuelve (total, partes)."""
    ac_base, ac_dex_max, ac_parts = 10, None, [("base", 10)]
    for it in char.inventory:
        if not it.equipped or not it.source_id:
            continue
        piece = _armor_piece(content, it)
        if piece is None:
            continue
        kind, val, dex_max = piece
        if kind == "armor":
            ac_base, ac_dex_max = val, dex_max
            ac_parts = [(it.name, val)]
        else:
            ac_base += val
            ac_parts.append((it.name, val))
    dex_applied = dex_mod if ac_dex_max is None else min(dex_mod,
                                                         ac_dex_max)
    if dex_applied:
        ac_parts.append(("DES", dex_applied))
    for eff in char.effects:
        for o in eff.operations:
            if o.op.value == "add_modifier" and o.target == "armor_class":
                ac_base += int(o.value or 0)
                ac_parts.append((eff.name, int(o.value or 0)))
    return ac_base + dex_applied, ac_parts


def _defenses(char) -> dict:
    """Union de los grant_* declarativos por tipo de daño
    (target = tipo: fire, bludgeoning, * = todos). El prefijo
    'condition:<nombre>' marca inmunidad a una condición."""
    out = {"resistances": set(), "vulnerabilities": set(),
           "immunities": set(), "condition_immunities": set()}
    key = {"grant_resistance": "resistances",
           "grant_vulnerability": "vulnerabilities",
           "grant_immunity": "immunities"}
    for eff in char.effects:
        for o in eff.operations:
            tgt = str(o.target or "*").lower()
            if o.op.value == "grant_immunity" and \
                    tgt.startswith("condition:"):
                out["condition_immunities"].add(tgt.split(":", 1)[1])
            elif o.op.value in key:
                out[key[o.op.value]].add(tgt)
    return {k: sorted(v) for k, v in out.items()}


def _next_level_xp(level: int) -> int | None:
    """XP acumulado necesario para el siguiente nivel (umbral)."""
    from ..domain.xp import level_xp_table
    if level >= 20:
        return None
    return level_xp_table()[level]


def _xp_to_next(level: int, xp: int) -> int | None:
    t = _next_level_xp(level)
    return None if t is None else max(0, t - xp)


_EXHAUSTION = [                        # niveles 1-6, acumulativos
    "desventaja en pruebas de característica",
    "velocidad reducida a la mitad",
    "desventaja en ataques y salvaciones",
    "PG máximos reducidos a la mitad",
    "velocidad 0",
    "muerte",
]


def _exhaustion(char) -> list[str]:
    lvl = (char.condition_stacks.get("exhaustion")
           or char.condition_stacks.get("agotamiento") or 0)
    return _EXHAUSTION[:min(lvl, 6)]


def _asi_available(char) -> int:
    """Mejoras de característica ganadas − gastadas (puntos).
    Cada nivel con ability_score_bonuses en la tabla de la clase
    otorga 2 puntos de mejora (+2, +1/+1 o una dote)."""
    return max(0, _asi_earned(char, content_db()) - char.asi_used)


@router.get("/{character_id}")
def get_character(character_id: str,
                  user: dict | None = Depends(optional_user)):
    conn = state_db()
    row = conn.execute(
        "SELECT * FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "character not found")
    _char_camp_guard(conn, row["campaign_id"], user)
    out = dict(row)
    data = json.loads(out["data"])
    # 'secrets' es solo PJ+DM: cualquier miembro leía la ficha íntegra
    if not _can_see_private(conn, row["campaign_id"],
                            row["player_id"], user):
        data = redact_private(data)
    out["data"] = data
    return out
