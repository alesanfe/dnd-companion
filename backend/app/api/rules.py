"""Rules assistant — strictly grounded in installed sources.
Always cites the exact entity; says 'no evidence' when nothing matches.
Never answers from general knowledge."""
from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel

from ..db.connections import content_db

router = APIRouter(prefix="/api/rules", tags=["rules"])

# tipos que contienen texto de reglas consultable
_RULE_TYPES = ("rule", "rule-section", "condition", "spell", "feature",
               "trait", "feat")


@router.get("/tables")
def tables():
    """Tablas normativas del rules pack SRD (app/rules/srd_core.json)
    expuestas al frontend: habilidades por característica, resúmenes
    de condiciones, constantes de combate y metadatos de licencia."""
    from ..rules import rules
    r = rules()
    return {
        "meta": r["meta"],
        "ability_skills": r["ability_skills"],
        "conditions": {k: v.get("es") for k, v in r["conditions"].items()
                       if isinstance(v, dict)},
        "combat": r["combat"],
        "level_xp": r["level_xp"]["values"],
    }


class AskIn(BaseModel):
    question: str
    ruleset: str | None = None         # dnd5e-2014 | dnd5e-2024
    limit: int = 5


@router.post("/ask")
def ask(body: AskIn):
    conn = content_db()
    # FTS sobre name+body; bm25 ordena por relevancia
    sql = """
        SELECT e.id, e.entity_type, e.name, e.ruleset, e.source_id,
               e.license, e.data,
               snippet(content_fts, 2, '[', ']', '…', 40) AS excerpt
        FROM content_fts f
        JOIN content_entities e ON e.id = f.entity_id
        WHERE content_fts MATCH ?
    """
    params: list = [_fts_query(body.question)]
    placeholders = ",".join("?" * len(_RULE_TYPES))
    sql += f" AND e.entity_type IN ({placeholders})"
    params.extend(_RULE_TYPES)
    if body.ruleset:
        sql += " AND e.ruleset = ?"
        params.append(body.ruleset)
    sql += " ORDER BY bm25(content_fts) LIMIT ?"
    params.append(body.limit * 3)

    citations = []
    for r in conn.execute(sql, params).fetchall():
        data = json.loads(r["data"])
        citations.append({
            "entity_id": r["id"],
            "name": r["name"],
            "entity_type": r["entity_type"],
            "ruleset": r["ruleset"],
            "citation": {
                "source_id": r["source_id"],
                "license": r["license"],
            },
            "excerpt": r["excerpt"],
            "text": _rule_text(data),
        })
        if len(citations) >= body.limit:
            break

    return {
        "question": body.question,
        "evidence_found": bool(citations),
        "answer": None,      # nunca inventamos: el cliente compone la respuesta
        "citations": citations,
    }


def _fts_query(question: str) -> str:
    """Convierte lenguaje natural en query FTS5 segura (OR de términos)."""
    stop = {"de", "la", "el", "en", "que", "un", "una", "como", "cómo",
            "qué", "se", "a", "y", "o", "con", "por", "para", "the", "a",
            "of", "how", "what", "is", "does", "do", "can", "i", "my"}
    terms = [t.strip("¿?¡!.,;:()\"'") for t in question.lower().split()]
    terms = [t for t in terms if len(t) > 2 and t not in stop]
    return " OR ".join(terms) if terms else '""'


def _rule_text(data: dict) -> str:
    for key in ("desc", "description"):
        v = data.get(key)
        if isinstance(v, list):
            return "\n".join(str(x) for x in v)
        if isinstance(v, str):
            return v
    return ""
