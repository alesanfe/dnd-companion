# Dependencias

## Runtime de producción

| Dependencia | Versión | Para qué | Licencia |
|---|---|---|---|
| Python | ≥3.11 | backend + data-pipeline | PSF |
| FastAPI | ≥0.115 | API REST/WebSocket del backend | MIT |
| Uvicorn | ≥0.30 | ASGI server | BSD-3 |
| Pydantic | ≥2.7 | validación de esquemas y modelos | MIT |
| Node.js | 20 | build del frontend (Vite) + `npm ci` en Docker | MIT |
| React | 18 | SPA de la ficha y campañas | MIT |
| Dexie | ^4 | persistencia offline-first en IndexedDB | Apache-2.0 |
| react-router-dom | ^7 | routing del frontend | MIT |
| SQLite | stdlib Python | estado del backend (FTS5, WAL, `user_version`) | dominio público |
| Docker + Compose | estable | despliegue empaquetado (nginx → backend:8000) | Apache-2.0 |

Definidos en `backend/pyproject.toml`, `data-pipeline/pyproject.toml`
y `frontend/package.json` (con lockfile).

## Desarrollo/CI

| Herramienta | Para qué |
|---|---|
| pytest + httpx | 299 tests de backend |
| vitest + jsdom | 18 tests de frontend |
| Playwright | E2E y capturas (`tools/screenshots.mjs`) |

## Datos

| Fuente | Uso | Licencia |
|---|---|---|
| SRD 5e / 5e-bits | compendio base (`import-srd --edition 2014\|2024`) | CC-BY-4.0 |
| Open5e v1/v2 | documentos OGL (tob, cc, menagerie, a5e…) | OGL/CC según documento |
| Foundry packs | YAML de packs `_source` | CC-BY-4.0 |
| 5etools | catálogo completo — **NON-FREE, solo local** | no redistribuible: `data/` gitignored, nunca entra al repo |

Regla dura (ver AGENTS.md): toda entidad lleva `source_id`,
`license` e `is_redistributable`; nada con copyright se commitea.

## Política de actualización

- Dependabot en `.github/` para pip/npm/GHA — se revisan changelogs
  antes de mergear major bumps.
- Versiones nuevas (<7 días publicadas) se dejan madurar salvo CVE.
- Nada de rangos flotantes en producción: `pyproject` fija mínimos,
  el lockfile fija el resuelto.
