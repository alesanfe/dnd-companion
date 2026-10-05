# Madurez por feature — dnd-companion

Escala: ✅ completo · 🟡 funcional con límites · 🔴 prototipo.

| Feature | Estado | Notas |
|---|---|---|
| Ficha 2014/2024 (ops idempotentes) | ✅ | Motor de efectos + ops con versión |
| Magia, inventario, condiciones, descansos | ✅ | Reglas declarativas en `engine/` |
| Wizard de creación | ✅ | Species/clase/trasfondo con search |
| Mapa VTT (tokens, niebla, alcance) | ✅ | Optimistic lock + rebase |
| Combate (tracker, área, delegación) | ✅ | Sync ficha↔combate↔mapa |
| Mesa del DM (sesiones, feed, wiki) | ✅ | Visibilidad `dm` en servidor |
| Compendio + búsqueda FTS | ✅ | content.db separada, licencias por fila |
| Offline-first + cola IndexedDB | ✅ | flushQueue + conflictos en Ajustes |
| PWA + push (VAPID) | ✅ | |
| i18n ES/EN + temas/densidad | ✅ | dark/light/sepia/hc + compacto |
| Multi-usuario por instancia | ✅ | Roles campaña + fichas personales |
| Importación de fuentes | 🟡 | SRD/Open5e/Foundry OK; 5etools y dnd-data solo local (NON-FREE) |
| Móvil | 🟡 | PWA instalable; app nativa no |

## Criterio para subir

- 🟡→✅ requiere tests en `backend/tests` + captura en README +
  sin deuda abierta en `TECH_DEBT.md` para esa feature.
