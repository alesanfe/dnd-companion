# Modelo de datos — D&D Companion

Dos bases SQLite separadas por responsabilidad:

## `content.sqlite3` — reglas (read-only en runtime)

Contenido de juego importado con procedencia verificable.

- **Entidades de contenido**: spells, items, monsters, classes, species,
  feats, rules… cada una con `source_id`, `source_document`,
  `source_version`, `source_page`, `license`, `is_redistributable` y
  `ruleset` (`dnd5e-2014` | `dnd5e-2024`).
- **`content_sources`**: registro de fuentes (id, name, version, license,
  attribution_text, original_url, imported_at, content_hash,
  distribution_allowed).
- Índices FTS5 para búsqueda del compendio.
- Las tablas normativas no viven aquí: `backend/app/rules/srd_core.json`
  (SRD CC-BY-4.0) leído vía `app.rules.rules()`.

## `state.sqlite3` — partida (mutable)

El schema corre solo si `PRAGMA user_version < _SCHEMA_VERSION`; añadir
tabla = subir la constante + DDL `IF NOT EXISTS` en `state_schema.sql`.

- **`characters`**: fichas completas (JSON) + `player_id`, `campaign_id`,
  `entity_version`.
- **`campaigns` / `campaign_members`**: `owner_id` (NULL = modo local
  abierto) y roles owner/co_dm/player/guest/spectator.
- **`operations`**: log de ops con `operation_id`, `entity_kind`,
  `entity_id`, `payload`, `entity_version` — base de idempotencia y undo.
- **`combats` / `combatants`**: tracker de iniciativa, `delegated_to`,
  `ref_id` a ficha.
- **`entities`**: mapa/sesiones — tokens (`ref_id`, `combatant_id`,
  `light_ft`, `vision_ft`, `size`), escenas, timeline, relaciones;
  `visibility` (`all` | `dm`) con `version` para optimistic lock.
- **`events`**: eventos WS tipados; se poda a los últimos 500 por
  campaña en cada op aplicada.
- **`auth_tokens` / `auth_throttle`**: sesiones (TTL 30 d) y rate-limit
  persistente; ambos con GC perezosa.
- **`encounters` / notas / decisiones / asistentes**: datos de DM por
  campaña.

## Invariantes

- Toda mutación pasa por el pipeline de ops (nada de writes directos al
  estado vital fuera de `_VITAL_OPS`).
- `entity_version` siempre se compara antes de escribir (409 al conflicto).
- `visibility=dm` nunca sale del servidor a no-DM en campañas con owner.
