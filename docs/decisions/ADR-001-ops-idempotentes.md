# ADR-001: Mutaciones de ficha como ops idempotentes con optimistic locking

## Contexto

La ficha de personaje se edita desde varias ventanas y en modo
offline (PWA). Un CRUD REST clásico (`PATCH /characters/:id`)
permitiría que dos escrituras se pisen silenciosamente, y al
reconectar no habría forma de saber qué cambios aplicar ni en qué
orden.

## Decisión

Todas las mutaciones son ops nombradas (`character.hp.damage`,
`character.spell.prepare`, `map.token.move`…) enviadas a
`POST /entities/{id}/ops` con:

- `op_id` único por op → idempotencia (reintentos seguros).
- `version` esperada → optimistic locking; un 409 devuelve el estado
  fresco y el cliente re-aplica el patch sobre él (`patchEntityRebase`).
- Cada op se persiste en el event log → auditoría, timeline y
  undo/replay.

En offline las ops se encolan en IndexedDB (`lib/db.js`) y se envían
al reconectar (`flushQueue`); los 409 se marcan como conflictos para
resolución manual en Ajustes.

## Consecuencias

- Ninguna escritura se pierde ni duplica, aunque la red corte a mitad.
- Toda acción queda auditada (feed de eventos de campaña).
- El cliente carga con la complejidad del rebase/encolado; los
  componentes UI solo llaman a `op(tipo, payload)`.
