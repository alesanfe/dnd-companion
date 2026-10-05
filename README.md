# D&D Companion

Plataforma **offline-first** para hoja de personaje, automatización
transparente de reglas y dirección de campañas de D&D, con soporte
paralelo para reglas 2014 (`dnd5e-2014`) y revisadas (`dnd5e-2024`),
contenido con procedencia verificable y herramientas colaborativas
de mesa.

[Arquitectura](docs/ARCHITECTURE.md) ·
[Requisitos](docs/REQUIREMENTS.md) ·
[Modelo de datos](docs/DATA_MODEL.md) ·
[Threat model](docs/THREAT_MODEL.md) ·
[Privacidad](docs/PRIVACY.md) ·
[Decisiones](docs/decisions/) ·
[Guía para agentes](AGENTS.md)

## Capturas

<table>
<tr>
  <td><img src="docs/assets/screenshots/character-sheet.png" alt="Ficha de personaje 2024: cabecera con clase y nivel, chips de PG, CA, iniciativa, velocidad, inspiración y condición envenenado; pestañas de Resumen, Acciones, Magia e Inventario; XP, puntos de golpe, descansos y condiciones" width="420"></td>
  <td><img src="docs/assets/screenshots/character-spells.png" alt="Pestaña de magia de una maga 2014: espacios de conjuro por nivel con círculos gastados, conjuros conocidos con botón Lanzar y chip de concentración activa" width="420"></td>
</tr>
<tr>
  <td><img src="docs/assets/screenshots/dm-combat.png" alt="Mesa del DM en la pestaña Combate: tracker de iniciativa con barras de PG por combatiente, condiciones con duración, calculadora de dificultad de encuentro y búsqueda de monstruos" width="420"></td>
  <td><img src="docs/assets/screenshots/dm-map.png" alt="Mapa táctico del VTT: cuadrícula con tokens de personajes y orcos, barras de PG sobre cada token, anillo de turno activo, cinta de iniciativa y pin de escena" width="420"></td>
</tr>
</table>
<p><sub>Ficha · Magia · Tracker de iniciativa · Mapa VTT —
interfaz en español (la app también va en inglés)</sub></p>

<details>
<summary>Más capturas — lista de fichas, acciones, inventario,
paleta ⌘K, compendio, campaña, DM, móvil</summary>

| Lista de fichas | Acciones + dados |
|---|---|
| ![Lista de personajes con HP, nivel, ruleset y favoritos](docs/assets/screenshots/character-list.png) | ![Pestaña Acciones: ataques del inventario, dados libres y log](docs/assets/screenshots/character-actions.png) |

| Inventario | Paleta de comandos |
|---|---|
| ![Inventario con mochila, equipar, atacar y monedas](docs/assets/screenshots/character-inventory.png) | ![Paleta ⌘K con resultados del compendio sobre la ficha](docs/assets/screenshots/command-palette.png) |

| Compendio | Entidad (spell) |
|---|---|
| ![Buscador de reglas con resultados multi-edición y fuente](docs/assets/screenshots/compendium.png) | ![Detalle de conjuro SRD con chips de nivel/escuela/alcance y diff entre ediciones](docs/assets/screenshots/content-entity.png) |

| Mesa DM — Sesión | Mapa — vista jugador |
|---|---|
| ![Tablero del DM en pestaña Sesión: campaña, sesiones, chat y petición de tirada](docs/assets/screenshots/dm-board.png) | ![El mismo mapa en Vista jugador: la niebla se vuelve opaca](docs/assets/screenshots/dm-map-player.png) |

| Móvil (PWA) | Asistente de creación |
|---|---|
| ![Ficha en móvil 390px: pestañas desplazables y nav inferior](docs/assets/screenshots/sheet-mobile.png) | ![Wizard de personaje: concepto, clase, origen, stats, revisión](docs/assets/screenshots/wizard.png) |

| Tema claro | Tema sepia |
|---|---|
| ![Ficha en tema claro: misma cabecera y pestañas sobre fondo claro](docs/assets/screenshots/sheet-light.png) | ![Ficha en tema sepia](docs/assets/screenshots/sheet-sepia.png) |

| Lectura fácil (dislexia) | Vista de impresión |
|---|---|
| ![Ficha con fuente de lectura fácil para dislexia](docs/assets/screenshots/sheet-dyslexia.png) | ![Hoja imprimible: todas las pestañas desplegadas en media print](docs/assets/screenshots/sheet-print.png) |

| Alto contraste | Ficha con reglas 2014 |
|---|---|
| ![Ficha en tema de alto contraste](docs/assets/screenshots/sheet-hc.png) | ![Ficha del mismo personaje con ruleset 2014](docs/assets/screenshots/character-sheet-2014.png) |

| Pestaña Características | Pestaña Historia |
|---|---|
| ![Pestaña Características: rasgos de clase y especie del personaje](docs/assets/screenshots/character-features.png) | ![Pestaña Historia: trasfondo, personalidad, aliados y notas](docs/assets/screenshots/character-backstory.png) |

| Pestaña Actividad | Sesión iniciada |
|---|---|
| ![Pestaña Actividad: historial de operaciones y chat de mesa](docs/assets/screenshots/character-activity.png) | ![Ficha con sesión de cuenta iniciada en la barra](docs/assets/screenshots/character-sheet-logged.png) |

| Subida de nivel | Inicio |
|---|---|
| ![Subir de nivel: qué gana la clase actual o multiclase a otra nueva](docs/assets/screenshots/level-up.png) | ![Inicio: continuar campaña o personaje, acciones rápidas y resumen de la mesa](docs/assets/screenshots/home.png) |

| Ajustes | Cuenta (login) |
|---|---|
| ![Ajustes: tema, idioma, accesibilidad y sincronización offline](docs/assets/screenshots/settings.png) | ![Ajustes — sección Cuenta con formulario de inicio de sesión](docs/assets/screenshots/settings-login.png) |

| Cuenta con sesión | Conflictos de sincronización |
|---|---|
| ![Ajustes — cuenta autenticada y fichas personales](docs/assets/screenshots/settings-logged.png) | ![Ajustes — conflictos de optimistic locking con reintentar y descartar](docs/assets/screenshots/settings-conflicts.png) |

| Métricas de sync | Comparador de ediciones |
|---|---|
| ![Ajustes — métricas de sincronización y cola pendiente](docs/assets/screenshots/settings-metrics.png) | ![Comparador: la misma entidad 2014 vs 2024 lado a lado con diff](docs/assets/screenshots/compare.png) |

| Campañas | Campaña — Mundo |
|---|---|
| ![Lista de campañas con rol, ruleset e importar campaña](docs/assets/screenshots/campaign-list.png) | ![Campaña — pestaña Mundo: lugares, mapas y PNJ con visibilidad por rol](docs/assets/screenshots/campaign-board.png) |

| Campaña — Mapa | Campaña — Sesiones |
|---|---|
| ![Campaña — pestaña Mapa con cinta de iniciativa y aviso de turno](docs/assets/screenshots/campaign-mapa.png) | ![Campaña — pestaña Sesiones (estado vacío)](docs/assets/screenshots/campaign-sesiones.png) |

| Mesa DM — Campaña | Mesa DM — diálogo de mapa |
|---|---|
| ![Mesa DM — pestaña Campaña: entidades privadas, miembros, relaciones y exportar VTT](docs/assets/screenshots/dm-campaign.png) | ![Mapa del DM con diálogo de token: nombre, ft por casilla y añadir token](docs/assets/screenshots/dm-map-dialog.png) |

| Asistente — clase | Asistente — origen |
|---|---|
| ![Wizard de personaje, paso 2: elección de clase](docs/assets/screenshots/wizard-step2.png) | ![Wizard de personaje, paso 3: origen](docs/assets/screenshots/wizard-step3.png) |

| Asistente — características | Asistente — revisión |
|---|---|
| ![Wizard de personaje, paso 4: puntuaciones de característica](docs/assets/screenshots/wizard-step4.png) | ![Wizard de personaje, paso 5: revisión final antes de crear](docs/assets/screenshots/wizard-step5.png) |

| Asistente en móvil | Menú +Crear en móvil |
|---|---|
| ![Wizard a 390px: pasos apilados con nav inferior](docs/assets/screenshots/wizard-390.png) | ![Wizard a 390px — selector de clase](docs/assets/screenshots/wizard-390-class.png) |

| FAB móvil | Errores |
|---|---|
| ![Menú flotante +Crear en móvil: personaje, campaña o contenido](docs/assets/screenshots/fab-menu.png) | ![Ficha inexistente: estado "No encontrado" con enlace de vuelta](docs/assets/screenshots/error-404-char.png) |

| | |
|---|---|
| ![Página 404: dirección inexistente con enlace al inicio](docs/assets/screenshots/not-found.png) | |

</details>

<details>
<summary>Matriz responsive — las 4 superficies principales en 320/390/768/1024/1366/1920 px</summary>

| Superficie | 320 | 390 | 768 | 1024 | 1366 | 1920 |
|---|---|---|---|---|---|---|
| Inicio | ![Inicio — viewport 320 px](docs/assets/screenshots/resp/home-320.png) | ![Inicio — viewport 390 px](docs/assets/screenshots/resp/home-390.png) | ![Inicio — viewport 768 px](docs/assets/screenshots/resp/home-768.png) | ![Inicio — viewport 1024 px](docs/assets/screenshots/resp/home-1024.png) | ![Inicio — viewport 1366 px](docs/assets/screenshots/resp/home-1366.png) | ![Inicio — viewport 1920 px](docs/assets/screenshots/resp/home-1920.png) |
| Ficha | ![Ficha — viewport 320 px](docs/assets/screenshots/resp/sheet-320.png) | ![Ficha — viewport 390 px](docs/assets/screenshots/resp/sheet-390.png) | ![Ficha — viewport 768 px](docs/assets/screenshots/resp/sheet-768.png) | ![Ficha — viewport 1024 px](docs/assets/screenshots/resp/sheet-1024.png) | ![Ficha — viewport 1366 px](docs/assets/screenshots/resp/sheet-1366.png) | ![Ficha — viewport 1920 px](docs/assets/screenshots/resp/sheet-1920.png) |
| Compendio | ![Compendio — viewport 320 px](docs/assets/screenshots/resp/compendium-320.png) | ![Compendio — viewport 390 px](docs/assets/screenshots/resp/compendium-390.png) | ![Compendio — viewport 768 px](docs/assets/screenshots/resp/compendium-768.png) | ![Compendio — viewport 1024 px](docs/assets/screenshots/resp/compendium-1024.png) | ![Compendio — viewport 1366 px](docs/assets/screenshots/resp/compendium-1366.png) | ![Compendio — viewport 1920 px](docs/assets/screenshots/resp/compendium-1920.png) |
| Mapa DM | ![Mapa — viewport 320 px](docs/assets/screenshots/resp/dm-map-320.png) | ![Mapa — viewport 390 px](docs/assets/screenshots/resp/dm-map-390.png) | ![Mapa — viewport 768 px](docs/assets/screenshots/resp/dm-map-768.png) | ![Mapa — viewport 1024 px](docs/assets/screenshots/resp/dm-map-1024.png) | ![Mapa — viewport 1366 px](docs/assets/screenshots/resp/dm-map-1366.png) | ![Mapa — viewport 1920 px](docs/assets/screenshots/resp/dm-map-1920.png) |

</details>

Las capturas se regeneran con `node tools/screenshots.mjs`
(precisa Playwright, backend y frontend en marcha; la campaña de
demo se siembra con `python tools/seed_demo.py`).

## Estado

> [!IMPORTANT]
> Desarrollo activo, pre-1.0: la API y el formato de las operaciones
> pueden cambiar entre commits. Suite actual: 299 tests de backend
> + 18 de frontend, en verde.

## Qué es

D&D Companion resuelve tres problemas de la mesa digital:

- **La ficha y el combate están sincronizados de verdad** — daño,
  curación, salvaciones de muerte y condiciones fluyen en ambos
  sentidos entre la hoja del jugador y el tracker del DM dentro de
  la misma transacción.
- **Las reglas no están quemadas en código** — condiciones, rasgos,
  dotes y objetos son `Effect` declarativos con triggers; el motor
  explica qué aplicó y por qué. Las diferencias 2014/2024
  (agotamiento, inspiración heroica, weapon mastery, sorpresa,
  unarmed strike) se resuelven por `ruleset`.
- **Todo el contenido tiene procedencia** — cada entidad registra
  fuente, licencia y si es redistribuible; solo el SRD CC-BY-4.0 se
  distribuye con el proyecto.

## Funcionalidad actual

**Ficha de personaje** — HP/temp, dados de golpe, descansos,
espacios de conjuro, recursos, condiciones, inventario, monedas con
conversión, XP, inspiración, concentración, sintonía, diario,
export/import JSON, subida de nivel multiclase.

**Reglas 2024 efectivas en el motor** — agotamiento −2×nivel a d20
(+ velocidad y muerte a 6), inspiración heroica como reroll
post-tirada (incl. salvaciones de muerte), weapon mastery con las
9 propiedades del SRD 5.2, sorpresa = desventaja en iniciativa,
unarmed strike como salvación vs CD. 2014 conserva su mecánica.

**Combate** — iniciativa (manual o tirada por servidor), HP
sincronizado con la ficha, condiciones con duración en rondas,
salvaciones de muerte (pifia/crítico), ataque token→token con CA
resuelta en el servidor, empujón/agarrón, daño de zona con
salvación por token, escenas → combate con un clic.

**Campaña** — entidades con visibilidad por rol (public/dm/
known_to), revelación selectiva, relaciones, cronología, sesiones
con escenas ordenadas, tiendas con stock (compra atómica + refund
al deshacer), miembros por invitación, feed de eventos, tiradas
retransmitidas por WebSocket, chat de voz WebRTC.

**Contenido** — SRD 2014 + 2024, buscador FTS con comandos
(`level:3 cr:1..5 ruleset:2024`), comparador de ediciones, homebrew
aislado, paquetes declarativos, asistente de reglas con citas.

**Offline-first** — la ficha funciona sin conexión (IndexedDB),
las operaciones se encolan y se reenvían al reconectar; el badge
muestra lo pendiente.

**Auth y privacidad** — cuentas locales + Bearer, roles
owner/co_dm/player/spectator, visibilidad `dm` filtrada en el
servidor, fichas personales con `player_id`.

**Accesibilidad** — temas oscuro/claro/sepia/alto contraste,
escala de texto, reducción de movimiento, objetivos táctiles ≥44px,
PWA instalable, i18n es/en.

## Inicio rápido

### Requisitos

- Python 3.11+
- Node.js 20+
- Git
- Docker (solo para el despliegue empaquetado)

### Opción A — Docker Compose (recomendada)

```bash
git clone https://github.com/alesanfe/dnd-companion.git
cd dnd-companion
docker compose up --build
```

Abre http://localhost:5173 — el front (nginx) sirve la PWA y
proxifica `/api` y `/ws` al backend. Verificación:
`curl http://localhost:5173/api/health` debe devolver
`{"status": "ok"}`.

### Opción B — desarrollo

```bash
# Contenido (content DB)
cd data-pipeline
pip install -e .
python -m pipeline.cli import-srd --edition 2014
python -m pipeline.cli import-srd --edition 2024

# Backend (:8000)
cd ../backend
pip install -e .[dev]
uvicorn app.main:app --reload

# Frontend (:5173) — en otra terminal
cd ../frontend
npm install
npm run dev
```

### Verificación

```bash
curl http://localhost:8000/api/health   # → {"status": "ok"}
```

`npm run dev` sirve la app en http://localhost:5173.

## Fuentes de contenido

El pipeline importa catálogos a la content DB (SQLite + FTS5),
cada uno con su `source_id`, licencia y flag de redistribución:

| Fuente | Comando | Licencia |
|---|---|---|
| 5e-bits SRD 2014/2024 | `import-srd --edition 2014\|2024` | CC-BY-4.0 |
| Open5e v1 (ToB, CC, DMag…) | `import-open5e --document <slug>` | OGL/CC |
| Open5e v2 (SRD 5.2 completo) | `import-open5e --api v2 --document srd-2024` | CC-BY-4.0 |
| Foundry dnd5e packs | `import-foundry --path <packs/_source>` | CC-BY-4.0 |
| JSON propio | `import-file --path <json> --license <lic> --type <tipo>` | la que declares |
| 5etools / homebrew / UA / dnd-data | `import-5etools` / `import-dnddata` | **NON-FREE — solo local** |

Las fuentes non-free nunca se redistribuyen: quedan en la DB local
del usuario con `is_redistributable = false`.

## Arquitectura

```text
dnd-companion/
├── backend/         # FastAPI — REST + WebSocket, motor de efectos
│   └── app/engine/  # ops/ (ficha) y combat_ops/ (tracker)
├── frontend/        # React + Vite PWA — hoja, mesa del DM, mapa VTT
├── data-pipeline/   # Importers → content DB (SQLite + FTS5)
├── docs/            # Arquitectura y decisiones de diseño
└── data/            # DBs generadas (gitignored)
```

Principios (detalle en `AGENTS.md`):

1. **Dos DBs**: contenido de solo lectura aparte del estado de
   partida.
2. **Motor declarativo**: nada de `if clase == "barbarian"` —
   `Effect` con triggers y operaciones.
3. **Operaciones idempotentes y reversibles**: cada cambio lleva
   `operation_id` + `entity_version` (optimistic locking) e inversa;
   el historial es auditable y deshacible (incl. undo compuesto de
   `inventory.transfer`).
4. **Eventos pequeños y tipados** por WS — nunca la ficha completa.
5. **Offline-first**: cola IndexedDB + reenvío al reconectar.

## Pruebas

```bash
pytest backend/tests            # 299 tests
cd frontend && npm test         # 18 tests (Vitest)
npm run build                   # build + PWA
```

## Limitaciones conocidas

- El Bearer token del WebSocket viaja en `Sec-WebSocket-Protocol`
  (`bearer.<token>`); `?token=` queda como fallback pero expone el
  token en logs de proxy (ver AGENTS.md).
- `cleave`/`nick` (weapon mastery) solo se anotan en el log — el
  encadenamiento del segundo ataque lo dirige el DM.

## Documentación

- [AGENTS.md](AGENTS.md) — reglas del proyecto, modelo de acceso,
  contratos de sincronización ficha↔combate↔mapa.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — diseño completo.
- [CHANGELOG.md](CHANGELOG.md) — historial de cambios.
- [CONTRIBUTING.md](CONTRIBUTING.md) — proceso y reglas de cambio.
- [SECURITY.md](SECURITY.md) — reporte privado de vulnerabilidades
  y modelo de seguridad.

## Contribución y soporte

Lee [CONTRIBUTING.md](CONTRIBUTING.md) antes de abrir una issue o
enviar un cambio — resume el proceso; las reglas inviolables están
en AGENTS.md. Las vulnerabilidades se reportan en privado según
[SECURITY.md](SECURITY.md).

## Licencia

El código se distribuye bajo licencia [MIT](LICENSE). El contenido
del SRD es CC-BY-4.0 de sus autores originales; el contenido no
libre (5etools, homebrew, UA) nunca entra al repositorio.
