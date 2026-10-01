# D&D Companion

Plataforma **offline-first** para hoja de personaje, automatización
transparente de reglas y dirección de campañas de D&D, con soporte
paralelo para reglas 2014 (`dnd5e-2014`) y revisadas (`dnd5e-2024`),
contenido con procedencia verificable y herramientas colaborativas
de mesa.

[Arquitectura](docs/ARCHITECTURE.md) ·
[Guía para agentes](AGENTS.md)

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

- El Bearer token del WebSocket viaja en `?token=` — aceptable en
  LAN/local; si se expone a internet debe migrarse a
  `Sec-WebSocket-Protocol` (ver AGENTS.md).
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
