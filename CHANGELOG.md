# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
El proyecto aún no publica versiones numeradas — `Unreleased` agrupa los
cambios sobre `main`.

## [Unreleased]

### Añadido

- **Reglas 2024 efectivas en el motor**:
  - Agotamiento: −2×nivel a tiradas d20, −5 ft×nivel de velocidad,
    muerte a nivel 6 (2014 conserva su tabla).
  - Inspiración heroica: reroll post-tirada del peor dado retenido
    (`/character/{id}/roll?heroic_reroll`), también en salvaciones de
    muerte (`character.death_save` y `combatant.death_save_roll` con
    `heroic`).
  - Weapon mastery (SRD 5.2): `combat.attack` aplica la propiedad del
    arma automáticamente en combates 2024 — sap/slow/vex son
    marcadores consumibles, topple = salvación CON → prone, graze =
    mod de daño en fallo, flex = dado versátil, push = evento 10 ft,
    cleave/nick = nota.
  - `sorprendido` (2024) = desventaja en iniciativa (ficha y tracker).
  - `combat.shove_grapple`: unarmed strike — 2024 = salvación FUE/DES
    del objetivo vs CD 8+FUE+prof; 2014 = contestada Atletismo.
    Opciones en el menú de ataque del mapa.
- **Concentración desde el tracker**: `combatant.damage` sobre un PJ
  emite la CD de concentración en el evento; la hoja avisa por WS.
- **Delegación de NPC**: el DM delega combatientes a jugadores
  (`combatant.delegate`); el delegado mueve el token y tira las
  acciones de su stat block.
- **Constructor de encuentros**: `POST /api/encounters/suggest`
  (presupuesto ajustado → composición greedy) + UI en el DM board.
- **Auditoría Fase A–F**: triggers declarativos cableados, undo
  compuesto de `inventory.transfer` (par `:out`/`:in` atómico), CAS
  en retry/undo, guards de autorización en fichas personales y
  combates sin campaña, visibilidad dm filtrada en servidor, proxies
  nginx endurecidos, throttle persistente de auth, tests de WS,
  concurrencia y componentes React.
- **Refactors AU**: `engine/ops.py`, `campaigns.py`, `combat_ops.py`
  y el shell de `CharacterSheet.jsx` partidos en módulos cohesivos.
- Poda i18n de claves muertas; GOBERNANZA: README, LICENSE (MIT),
  CONTRIBUTING, SECURITY, CHANGELOG.

### Corregido

- La línea duplicada de `combatant.death_save_roll` (residuo del
  split de combat_ops).
- `_undo_transfer` ya no queda documentado como pendiente:
  `inventory.transfer` revierte ambas fichas en una transacción.

## Notas de compatibilidad

- Sin releases publicadas todavía; la API de operaciones y los
  payloads de eventos pueden cambiar entre commits.
- Contenido de juego: solo SRD CC-BY-4.0 en el repositorio.
