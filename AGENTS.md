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

# Data pipeline
cd data-pipeline && pip install -e .
python -m pipeline.cli import-srd --edition 2014|2024
python -m pipeline.cli import-file --path <json> --license <lic>

# Frontend
cd frontend && npm install && npm run dev
```

## Reglas del proyecto (no negociables)

- **Nunca** commitear datasets con copyright. Solo SRD CC-BY-4.0 entra al repo.
  `data/` está gitignored. Los imports privados del usuario quedan en su DB local.
- Toda entidad de contenido lleva `source_id`, `license`, `is_redistributable`.
- Reglas de juego van en el **motor de efectos declarativo**
  (`backend/app/engine/`), no como condicionales dispersos.
- `ruleset` interno: `dnd5e-2014` | `dnd5e-2024` | `mixed`. Etiquetas tipo
  "5e"/"5.5e" solo en UI.
- Todo cambio de estado = operación con `operation_id` + `entity_version`
  (idempotencia, optimistic locking, reversible).
- Eventos WebSocket pequeños y tipados (`character.hp.changed`, etc.), nunca
  la ficha completa.

## Verificación

- `python -m compileall backend/app data-pipeline` — sintaxis
- `pytest backend/tests`
- `npm run build` en frontend/
