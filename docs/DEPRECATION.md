# Deprecación — D&D Companion

Ciclo de vida para retirar APIs, formatos y features. El proyecto es
autoalojable y offline-first: **la compatibilidad hacia atrás importa
más que la velocidad de cambio** — un usuario puede estar semanas sin
sincronizar.

## Principios

- Los `operation_id` y tipos de op del log de operaciones **nunca se
  eliminan**: la cola de sync del cliente y el historial de ops de una
  entidad dependen de que el servidor siga entendiendo ops viejas.
- El esquema de `state.sqlite3` evoluciona por `PRAGMA user_version`
  + DDL `IF NOT EXISTS` — no hay migraciones destructivas.
- Los endpoints REST bajo `/api/` se retiran solo tras una versión
  publicada donde coexisten viejo y nuevo.
- Eventos WebSocket: los tipos nuevos son aditivos; los clientes
  ignoran tipos desconocidos. Cambiar el significado de un tipo
  existente exige sufijo nuevo (`*.v2`).

## Proceso

1. Marcar la feature como deprecated en el código y el changelog.
2. Mantener el camino viejo al menos una release menor.
3. Eliminar solo cuando el camino viejo deje de tener usuarios
   observables (p. ej., endpoint sin tráfico en logs del operador).

## Formato de exportación

Los exports JSON de ficha/campaña son el contrato más estable del
sistema: `import-file` e `import/export` de personaje deben aceptar
siempre los exports producidos por versiones anteriores.

## Nada se elimina sin aviso

Entre otras cosas, NO se retiran: el par ruleset `dnd5e-2014`,
los imports SRD/Open5e/Foundry, ni la lectura de IndexedDB offline
— son parte del contrato con el usuario.
