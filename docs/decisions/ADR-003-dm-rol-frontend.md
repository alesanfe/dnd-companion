# ADR-003: El rol DM se aplica en el servidor, la UI solo lo refleja

## Contexto

En campañas con dueño, el DM ve cosas que el jugador no debe ver:
entidades con `visibility=dm`, eventos secretos, ops administrativas
(del combate, del mapa). Un guard solo en frontend sería
transparente para cualquiera con DevTools.

## Decisión

- `member_role(camp, uid)` = owner | co_dm | player | guest |
  spectator. Campaña sin `owner_id` = modo local abierto.
- `ops entity_kind=combat` = DM-only (REST **y** path WS de
  operaciones); `entity_camp` se resuelve en servidor.
- Visibilidad `dm` se filtra **en el servidor**: `/state`, `/events`,
  entidades, escenas, relaciones y timeline nunca salen a no-DM.
- En WS, `visibility=dm` solo llega a sockets dm/owner/local;
  `payload.for_user` = entrega dirigida.
- El `user_id` del body/payload es spoofable → se pisa siempre con
  el uid del token.

## Consecuencias

- Un jugador con un cliente modificado no puede leer notas del DM ni
  ejecutar ops de combate ajenas.
- La UI simplemente oculta lo que no recibe — sin lógica de "¿debo
  mostrar esto?".
- Modo local (sin usuarios) queda abierto por diseño — no hay nada
  que proteger sin identidad.
