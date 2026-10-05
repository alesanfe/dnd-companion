# SLO — D&D Companion

Objetivos de fiabilidad para el despliegue típico (self-hosted,
single-node, `docker compose up`). No son contratos con terceros: son
el presupuesto que guía las decisiones de operación.

## Contexto de despliegue

- `backend` (uvicorn :8000, solo red interna) + `frontend` (nginx :5173,
  proxy `/api` y `/ws`).
- Estado en `./data/`: `content.sqlite3` (read-only, regenerable) y
  `state.sqlite3` (mutable, WAL — la pieza valiosa).
- Healthcheck compose: `GET /api/health` cada 30 s, 3 reintentos.

## SLI / SLO

| SLI | SLO | Medición |
|---|---|---|
| Disponibilidad HTTP | ≥ 99 % mensual excluyendo mantenimiento | `GET /api/health` |
| Lecturas REST (ficha, compendio) | p95 < 200 ms | logs de uvicorn / proxy |
| Mutaciones REST (ops) | p95 < 500 ms | idem |
| Entrega de eventos WS | < 2 s desde la op aplicada | observado en mesa |
| Conflicto sync mal resuelto | 0 ops perdidas en la cola offline | revisión de `SyncQueue` |

## RPO / RTO

| | Objetivo | Mecanismo |
|---|---|---|
| RPO | 24 h | backup diario de `state.sqlite3` (ver `backup-restore.md`) |
| RTO | 1 h | `docker compose up -d` con `./data` restaurado |

`content.sqlite3` no cuenta para RPO: se regenera re-importando las
fuentes con `data-pipeline` (SRD/Open5e son públicos; el homebrew del
usuario vive en su copia local — documentarlo en el backup si se
quiere conservar).

## Error budget y consecuencias

- Si el healthcheck falla 3 veces seguidas, compose reinicia el
  backend (`restart: unless-stopped`).
- Si `state.sqlite3` reporta errores de escritura o locks sostenidos:
  prioridad máxima — es la única copia de personajes y campañas (ver
  `incident-response.md` §"Base de datos corrupta/bloqueada").
- Una caída del frontend (nginx) no toca datos: levantar el
  contenedor recupera el servicio íntegro.
