# AGENTS.md — D&D Companion

## Contexto

App web/móvil (PWA) de hojas de personaje D&D + herramientas de DM.
Python 3.11 + FastAPI backend, React + Vite frontend, SQLite + FTS5.

## Comandos

```bash
# Backend
cd backend && pip install -e .[dev]
uvicorn app.main:app --reload          # dev server :8000
pytest backend/tests                   # tests

# Data pipeline — fuentes: 5e-bits (SRD CC-BY-4.0), Open5e v1 (OGL docs:
# tob, cc, dmag, vom, menagerie, blackflag, taldorei, a5e…), Open5e v2
# (schema rico: srd-2024, a5e-ag…), Foundry packs (YAML, CC-BY-4.0),
# 5etools (catálogo completo, NON-FREE — solo local), import-file
cd data-pipeline && pip install -e .
python -m pipeline.cli import-srd --edition 2014|2024
python -m pipeline.cli import-open5e --document <slug> --api v1|v2
python -m pipeline.cli import-5etools --path <clone>/data
python -m pipeline.cli import-foundry --path <clone>/packs/_source
python -m pipeline.cli import-file --path <json> --license <lic> --type <t> [--key <k>]

# Frontend
cd frontend && npm install && npm run dev
```

## Reglas del proyecto (no negociables)

- **Nunca** commitear datasets con copyright. Solo SRD CC-BY-4.0 entra al repo.
  `data/` está gitignored. Los imports privados del usuario quedan en su DB local.
- Toda entidad de contenido lleva `source_id`, `license`, `is_redistributable`.
- Reglas de juego van en el **motor de efectos declarativo**
  (`backend/app/engine/`), no como condicionales dispersos.
- Las **tablas normativas** (CR→XP, umbrales de encuentro, XP por
  nivel, habilidades por característica, condiciones, constantes de
  combate) viven en `backend/app/rules/srd_core.json` (SRD CC-BY-4.0)
  — leerlas vía `app.rules.rules()`; nunca duplicarlas en código.
- `ruleset` interno: `dnd5e-2014` | `dnd5e-2024` | `mixed`. Etiquetas tipo
  "5e"/"5.5e" solo en UI.
- Todo cambio de estado = operación con `operation_id` + `entity_version`
  (idempotencia, optimistic locking, reversible).
- Eventos WebSocket pequeños y tipados (`character.hp.changed`, etc.), nunca
  la ficha completa.

## Modelo de acceso (auth)

- `optional_user`/`current_user` (api/auth.py): Bearer token de
  `auth_tokens` (TTL 30d); `member_role(camp, uid)` = owner | co_dm |
  player | guest | spectator. **Campaña sin `owner_id` = modo local
  abierto** — los guards pasan siempre; con owner, `_require_role`
  (api/campaigns.py) exige membresía y `_DM_ROLES` para lo administrativo.
- El `user_id` del body/payload es **spoofable**: con token se pisa con
  el uid autenticado (ops, join, transfer). El mismo guard va en REST
  **y** en el path WS de operaciones (main.py `_dispatch_ws`).
- Ops `entity_kind=combat` = DM-only (REST y WS); `character` = miembro
  y, si la ficha tiene `player_id`, solo su dueño (o el DM) la muta.
  Excepción: `combatant.death_save_roll` sobre el propio PJ (y su undo).
- Fichas libres (`player_id` NULL) se reclaman vía PATCH — el no-DM
  solo puede poner su propio uid o soltar la suya.
- Visibilidad `dm` se filtra en el servidor, no solo en la UI: eventos
  (/state, /events), escenas de sesiones, entidades, relaciones y
  timeline nunca salen a no-DM en campañas con owner.
- Sala WS: `visibility=dm` solo llega a sockets dm/owner/local;
  `payload.for_user` = entrega dirigida (petición secreta del DM).
  Espectador = solo lectura (sin chat/typing/ops). El `from` del
  chat/typing lo firma el servidor con la identidad del socket.
- Conflictos de optimistic locking: `POST /api/operations/conflicts/
  {id}/retry|dismiss` — resolución asistida desde Settings.

## Verificación

- `python -m compileall backend/app data-pipeline` — sintaxis
- `pytest backend/tests`
- `npm run build` en frontend/
