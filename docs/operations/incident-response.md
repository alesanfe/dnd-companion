# Respuesta a incidentes — D&D Companion

Servicio self-hosted single-node: el "equipo de guardia" es el
mantenedor. Este runbook prioriza **no perder `state.sqlite3`** y
restaurar el servicio rápido.

## Severidades

| Sev | Definición | Ejemplos |
|---|---|---|
| S1 | Pérdida/corrupción de datos de usuarios | `state.sqlite3` corrupto, ops aplicadas a ficha ajena (bypass de guard) |
| S2 | Servicio caído o función core rota | backend no responde, WS no conecta, sync offline pierde ops |
| S3 | Degradado con workaround | una pestaña de ficha rota, import falla para una fuente |
| S4 | Cosmético/menor | tema visual, texto sin traducir |

## Primeros pasos (cualquier sev)

1. `docker compose ps` + `docker compose logs --tail=200 backend`
   — la mayoría de S2 se diagnostican aquí.
2. `curl localhost:5173/api/health` (vía proxy) — distingue
   backend muerto de proxy muerto.
3. **Antes de tocar `./data/`**: parar el backend
   (`docker compose stop backend`) y copiar `state.sqlite3*` a un
   lado. Nunca diagnosticar sobre el original.

## Escenarios

### Backend no arranca / unhealthy

- `docker compose logs backend` — los fallos habituales: DB no
  escribible (`DND_DATA_DIR` sin permisos), puerto ocupado, schema
  migration fallando (`PRAGMA user_version` — ver
  `docs/DATA_MODEL.md`).
- Tras un deploy: `docker compose up -d --build backend` y verificar
  `curl :5173/api/health` antes de declarar OK.

### `state.sqlite3` corrupta o bloqueada (S1)

1. `docker compose stop backend`.
2. Copiar `data/state.sqlite3*` (incluye `-wal`/`-shm`) a backup.
3. `sqlite3 state.sqlite3 "PRAGMA integrity_check;"`.
4. Si está íntegra pero bloqueada: suele ser una transacción de
   escritura huérfana — reiniciar el contenedor la cierra (WAL se
   recupera al abrir).
5. Si está corrupta: restaurar el último backup
   (`backup-restore.md`) y registrar qué se perdió (RPO 24 h).

### Ola de conflictos de sync (S2/S3)

Síntoma: usuarios reportan "cambios que no se guardan" o cola de ops
pendiente que crece.

- Los conflictos son esperables (optimistic locking → 409). Es
  incidente si se **acumulan** o pierden.
- En el cliente: Ajustes → sincronización muestra cola y conflictos;
  resolución asistida (reintentar/descartar).
- Servidor: buscar `409` repetidos del mismo `entity_id` en logs —
  indica dos clientes editando lo mismo (expected) o un bug de
  versión stale (incidente).

### Registro público abierto (S1 de seguridad)

Si una instancia expuesta sufre altas abusivas:
`DND_ALLOW_REGISTRATION=0` en `environment` del backend + restart.
Los tokens existentes siguen válidos (TTL 30 d) — forzar expiración
borrando filas de `auth_tokens` si se sospecha compromiso.

### Bypass de permisos sospechado (S1)

Cualquier mutación de ficha/campaña ajena o fuga de visibilidad `dm`:

- Contener: `docker compose stop backend` (o bajar la instancia).
- El guard vive en el servidor (`api/campaigns.py`, `_DM_ROLES`,
  `_player_combat_op`, path WS en `main.py _dispatch_ws`) — auditar
  qué path faltó antes de reabrir.
- Comunicar a los usuarios afectados qué entidad se expuso.

## Registro

Todo S1/S2 se documenta al cerrarse: causa, señal que lo detectó,
acción, y si hace falta un ADR o una entrada en `TECH_DEBT.md`.
