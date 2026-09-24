# Arquitectura — D&D Companion

Documento de diseño. Refleja el plan acordado: plataforma offline-first para
hoja de personaje + dirección de campaña, con motor declarativo de efectos y
contenido con procedencia verificable.

## 1. Vista general

```
React + Vite PWA (IndexedDB, offline, instalable en móvil)
        │ REST + WebSocket (eventos pequeños tipados)
FastAPI ──┬── content.sqlite3  (reglas: read-only, FTS5, procedencia)
          └── state.sqlite3    (partida: personajes, campañas, ops log)
```

Separación estricta: **datos de reglas** ≠ **estado de partida**.

## 2. Contenido y licencias

- Fuentes oficiales: **SRD 5.1** (2014) y **SRD 5.2.1** (2024), CC-BY-4.0.
- Registro de procedencia: tabla `content_sources` (id, name, version, license,
  attribution_text, original_url, imported_at, content_hash,
  distribution_allowed).
- Cada entidad de contenido guarda: `source_id`, `source_document`,
  `source_version`, `source_page`, `license`, `is_redistributable`.
- Importaciones privadas: permitidas solo si el usuario tiene derechos; nunca
  se alojan ni redistribuyen; aisladas por `source_id`.
- `ruleset`: `dnd5e-2014` | `dnd5e-2024` | `mixed`. Etiquetas "5e"/"5.5e"
  solo en UI.

## 3. Motor de efectos (declarativo)

Reglas como datos, no como código. Modelo `Effect`:

```
id, name, trigger, conditions[], operations[],
duration, stacking_rule, priority, source, ruleset
```

**Triggers**: `on_apply`, `on_remove`, `on_turn_start`, `on_turn_end`,
`on_round_start`, `before_roll`, `after_roll`, `before_damage`, `after_damage`,
`on_hit`, `on_miss`, `on_save_success`, `on_save_failure`, `on_short_rest`,
`on_long_rest`, `on_level_up`.

**Operaciones**: `add_modifier`, `set_value`, `grant_advantage`,
`grant_disadvantage`, `add_dice`, `reroll`, `replace_roll`, `modify_damage`,
`grant_resistance`, `grant_vulnerability`, `grant_immunity`, `apply_condition`,
`remove_condition`, `consume_resource`, `restore_resource`, `grant_action`,
`grant_reaction`, `modify_speed`, `modify_armor_class`, `modify_range`.

Cubre: condiciones, dotes, rasgos de clase, objetos mágicos, concentración,
bonificadores temporales, auras, reacciones, resistencias, homebrew.

**Trazabilidad**: todo valor derivado se explica ("CA 18 = 10 base +3 DES +3
armadura +2 escudo").

## 4. Hoja de personaje

- Wizard de creación (especie → clase → trasfondo → stats → equipo) con
  validación de reglas.
- **Acciones contextuales**: pestaña que agrupa acción / bonus action /
  reacción / movimiento, con recursos consumidos por cada una.
- **Descansos inteligentes**: preview de qué se restaura, gasto de hit dice,
  efectos que terminan, historial + deshacer.
- **Nivel/multiclase**: subida reversible, HP fijo o tirado, requisitos,
  dote vs mejora de característica, migración 2014↔2024, preview.
- **Estado narrativo**: personalidad, ideales/vínculos/defectos, diario,
  secretos (jugador+DM), relaciones con NPC, retrato.
- **Exportación**: JSON versionado, PDF de una página, tarjetas de conjuros,
  backup cifrado.

## 5. Herramientas del DM

```
Campaña
├── Arcos narrativos
├── Sesiones ── preparación, escenas, encuentros, notas, resumen
├── Personajes / NPC / Localizaciones / Facciones / Misiones
├── Cronología
└── Archivos
```

- **Grafo de relaciones**: vínculos dirigidos NPC↔NPC ("A odia a B") con
  visibilidad, fecha en mundo e historial.
- **Panel de preparación**: escenas ordenables (drag), duración estimada,
  NPC, localización, pistas, tiradas previstas, encuentro vinculado,
  "presentar a jugadores", estado (no iniciada/activa/resuelta/omitida).
- **Revelación selectiva**: cada entidad separa info pública / conocida por
  jugadores concretos / privada del DM, con condición de revelación e
  historial de quién sabe qué.

## 6. Tracker de combate

Iniciativa individual/grupo/manual, delay+ready, reacciones por ronda,
concentración automática, duraciones (turnos/rondas/minutos), daño/curación/
temp HP con resistencias-vulnerabilidades-inmunidades, tiradas secretas,
HP ocultos con estados aproximados (ileso/herido/grave), oleadas y refuerzos,
objetivos alternativos, log reversible, guardar/reanudar, plantillas, botín.

## 7. Constructor de encuentros

Más que XP/CR: economía de acciones, nº de enemigos, dispersión de niveles,
resistencias del grupo, vuelo, rango, visión, daño estimado, control de masas,
curación, entorno, descansos desde el último combate. Generación con filtros,
bloqueo de criaturas, variantes débil/élite, plantillas por bioma,
recomendaciones no vinculantes.

## 8. Economía

Inventario de grupo, contenedores, peso, munición, objetos no identificados,
historial de propietarios, reparto de botín, tiendas por localización
(stock/rareza/precio), conversión de monedas, deudas, fabricación/downtime,
objetos homebrew. **Transferencias = transacciones atómicas** (anti-dupe en
reconexiones).

## 9. Búsqueda y asistente de reglas

FTS5 + tolerancia a erratas + sinónimos ES/EN + filtros por fuente/versión +
referencias cruzadas + comparador 2014 vs 2024. Comandos:

```
/spell fire level:3 concentration:true
/monster undead cr:1..5 resistance:necrotic
/rule grapple ruleset:2024
```

Asistente de reglas **estrictamente basado en fuentes instaladas**: siempre
cita la fuente exacta; reconoce cuando no hay evidencia.

## 10. Sincronización

Cada cambio = operación:

```
operation_id, entity_id, entity_version, client_id,
user_id, timestamp, operation_type, payload
```

Idempotencia, optimistic locking, detección de conflictos, auditoría,
operaciones reversibles, snapshots, retry con backoff, estados
`pending|synced|rejected|conflict`.

Eventos WS pequeños: `character.hp.changed`, `combat.turn.advanced`,
`dice.roll.created`, `inventory.item.transferred`… con
`event_id, campaign_id, aggregate_id, aggregate_version, actor_id,
occurred_at, payload`.

**Roles**: propietario, codirector, jugador, invitado, espectador, NPC
delegado. Permisos por campaña, entidad y campo.

## 11. Mesa / accesibilidad

Objetivos táctiles grandes, alto contraste, temas claro/oscuro/sepia, escala
de texto, teclado completo, screen readers, reduced-motion, no solo color,
confirmación destructiva, deshacer rápido, modo concentración, modo una mano,
indicador visible de conexión/sync (offline visible, no silencioso).

## 12. Extensiones

Paquetes declarativos (reglas, contenido, temas, plantillas, traducciones,
importadores, exportadores) con manifest:

```
id, name, version, compatible_rulesets, required_app_version,
dependencies, license, attribution, capabilities
```

Sin JS arbitrario en el MVP — lenguaje declarativo validado.

## 13. Roadmap

| Fase | Contenido |
|---|---|
| **MVP** | Procedencia + SRD 5.1/5.2.1, hoja editable, dados, recursos/descansos/condiciones, PWA offline, export/import, tests del motor |
| **Grupo** | Campañas + permisos, tiempo real, tracker, solicitud de tiradas, notas/diario, NPC/lugares/misiones/relaciones, constructor de encuentros, botín, historial+deshacer |
| **Diferenciación** | Motor de efectos completo, homebrew, comparador de reglas, preparación por escenas, revelación selectiva, grafo, cronología, tiendas/fabricación, extensiones, asistente de reglas |
| **Opcional** | Mapa táctico simple (tokens, FoW, distancias, LoS) — no competir con VTT |
