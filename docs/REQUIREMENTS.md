# Requisitos — D&D Companion

## Alcance

PWA offline-first para hojas de personaje D&D 5e (2014 y 2024) y
dirección de campaña para el DM: combate, mapa táctico (VTT ligero),
compendio de contenido con procedencia, sesiones, chat y sincronización
por WebSocket.

## Requisitos funcionales

- **Fichas de personaje**: creación asistida (wizard), edición completa,
  descansos, subida de nivel, inventario, magia, rasgos, historia,
  actividad. Ruleset `dnd5e-2014` | `dnd5e-2024` | `mixed`.
- **Motor de efectos declarativo**: reglas como datos
  (`backend/app/engine/`), no condicionales dispersos. Tablas normativas
  en `backend/app/rules/srd_core.json`.
- **Operaciones**: todo cambio de estado = op con `operation_id` +
  `entity_version` (idempotencia, optimistic locking, undo reversible).
- **Combates**: tracker con iniciativa, daño/curación, salvaciones de
  muerte, condiciones, XP. Sincronización bidireccional ficha ↔ combate
  y mapa ↔ combate.
- **Mapa**: tokens con `ref_id`/`combatant_id`, niebla de guerra
  (`light_ft`/`vision_ft`), regla de movimiento, daño de zona,
  ataque token→token.
- **Compendio**: búsqueda FTS5 sobre SRD 2014/2024 e imports privados,
  siempre filtrable por fuente y licencia.
- **Campañas**: notas, decisiones, asistentes, sesiones con escenas,
  timeline, relaciones entre entidades.
- **Multiusuario**: roles owner/co_dm/player/guest/spectator, chat con
  identidad firmada por servidor, typing, peticiones secretas al DM.
- **Offline**: IndexedDB + cola de operaciones; conflictos de optimistic
  locking resolubles desde Settings.

## Requisitos no funcionales

- **Procedencia y licencias**: toda entidad de contenido lleva
  `source_id`, `license`, `is_redistributable`. Nunca commitear datasets
  con copyright; `data/` está gitignored.
- **Seguridad**: ver `THREAT_MODEL.md` — guards de rol en REST **y** WS,
  `user_id` del body siempre spoofable → se pisa con el uid autenticado.
- **Privacidad del DM**: visibilidad `dm` filtrada en servidor, no en UI.
- **Idempotencia**: reintentos de op no duplican efectos; undo siempre
  revierte la transacción completa (los transfers son dos ops revertidas
  atómicamente).
- **Tamaño de eventos WS**: eventos pequeños y tipados, nunca la ficha
  completa.
- **Docker**: backend no expone 8000 al host; nginx del front proxifica
  `/api` y `/ws`.

## Fuera de alcance (MVP)

- Automatización de todo el compendio de reglas (el motor cubre lo
  normativo; edge cases se resuelven como anotaciones manuales).
- Videollamada/voz integrada.
- Marketplace de contenido.
