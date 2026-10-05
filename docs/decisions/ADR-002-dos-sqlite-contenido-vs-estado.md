# ADR-002: Dos bases SQLite — contenido (read-only) separado de estado

## Contexto

La app mezcla dos datos de naturaleza opuesta: el compendio (SRD,
Open5e, imports del usuario — grande, importado, consultable con
FTS5) y el estado de juego (fichas, campañas, ops, tokens —
transaccional, auditado, pequeño).

## Decisión

- `content.db` — entidades de contenido del data-pipeline con
  `source_id`, `license`, `is_redistributable` por fila. No entra al
  repo; se regenera con `pipeline.cli`.
- `dnd_state.db` — fichas, campañas, ops, events, auth. Esquema
  versionado con `PRAGMA user_version` + `_SCHEMA_VERSION`
  (`state_schema.sql` con `IF NOT EXISTS`).

## Consecuencias

- Las licencias se respetan a nivel de fila: la UI puede ocultar
  contenido no redistribuible sin tocar el motor.
- El esquema de estado migra solo (no hay alembic); `content.db` se
  puede reimportar de cero sin tocar el juego del usuario.
- Una migración de contenido rota no compromete las fichas.
