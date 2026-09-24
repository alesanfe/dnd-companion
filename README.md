# D&D Companion

Plataforma **offline-first** para hoja de personaje, automatización transparente de
reglas y dirección de campañas de D&D, con soporte paralelo para reglas 2014
(`dnd5e-2014`) y revisadas (`dnd5e-2024`), contenido con procedencia verificable
y herramientas colaborativas de mesa.

## Estructura

```
dnd-companion/
├── backend/         # FastAPI — API REST + WebSocket, motor de efectos
├── frontend/        # React + Vite PWA — hoja de personaje, mesa del DM
├── data-pipeline/   # Importers: fuentes JSON -> content DB (SQLite+FTS5)
├── docs/            # Arquitectura y decisiones de diseño
└── data/            # Bases de datos generadas (gitignored)
```

## Principios de diseño

1. **Datos de reglas separados del estado de partida.** El contenido (hechizos,
   monstruos, clases) vive en una content-DB de solo lectura; el estado
   (personajes, campañas, combates) en otra.
2. **Motor declarativo de efectos.** Nada de `if clase == "barbarian"` en el
   código: condiciones, rasgos, dotes y objetos se modelan como `Effect`
   con triggers y operaciones declarativas. Ver `backend/app/engine/`.
3. **Procedencia verificable.** Cada pieza de contenido registra fuente,
   licencia y si es redistribuible. Solo se distribuye contenido CC-BY-4.0
   (SRD). Las importaciones privadas las gestiona el usuario y quedan aisladas.
4. **Sincronización por operaciones.** Cada cambio es una operación con id,
   versión de entidad e idempotencia — reversible y auditable.
5. **Offline-first.** La ficha funciona sin conexión (IndexedDB) y sincroniza
   al reconectar.

## Funcionalidad actual

**Ficha de personaje** — HP/temp, dados de golpe, descansos, espacios de
conjuro, recursos, condiciones, inventario, monedas (pp/gp/ep/sp/cp con
conversión), XP, inspiración, concentración, sintonía (máx 3), diario,
export/import JSON, subida de nivel multiclase.

**Automatización de reglas** — motor de efectos declarativo (triggers +
operaciones, explicables), tiradas con ventaja/desventaja por condiciones y
efectos, mods automáticos por `check:X`/`save:X`/`skill:X`, ataque
arma-completo (impacto+daño), lanzamiento de conjuros con validación de
nivel y concentración, stats derivadas (CA por armadura equipada, iniciativa,
percepción pasiva, CD/ataque de conjuro, XP para próximo nivel).

**Combate** — iniciativa (manual o tirada por servidor), HP sincronizado
con la ficha, condiciones, salvaciones de muerte (pifia/crítico SRD),
añadir grupo/monstruos del bestiario, escenas → combate con un clic.

**Campaña** — entidades con visibilidad por rol (public/dm/known_to),
revelación selectiva, relaciones, cronología, sesiones con escenas
ordenadas, tiendas con stock (compra atómica + refund al deshacer),
miembros por invitación, feed de eventos, export de backup, tiradas
de jugadores retransmitidas por WS.

**Contenido** — SRD 2014 + 2024 (species/subspecies/poisons/weapon-mastery),
buscador FTS con comandos (`level:3 cr:1..5 ruleset:2024`), comparador de
ediciones, homebrew aislado, paquetes declarativos (manifest sin código
ejecutable), asistente de reglas con citas exactas.

**Auth** — cuentas locales + tokens Bearer, enforcement de visibilidad por
rol (owner/co_dm/player), modo anónimo local preservado.

**Accesibilidad** — temas oscuro/claro/sepia/alto contraste, escala de
texto, reducción de movimiento, modo mesa, indicador online/cola offline,
objetivos táctiles ≥44px, PWA instalable.

## Quickstart

```bash
# Content DB — fuentes disponibles:
cd data-pipeline
pip install -e .

# SRD oficial 5e-bits (CC-BY-4.0, redistribuible)
python -m pipeline.cli import-srd --edition 2014
python -m pipeline.cli import-srd --edition 2024

# Open5e API: documentos OGL/CC — Tome of Beasts 1-3 (+2023),
# Creature Codex, Deep Magic, Vault of Magic, Menagerie, Black Flag,
# Tal'Dorei, Tome of Heroes, A5E… (~5.600 entidades)
python -m pipeline.cli import-open5e --document tob   # o sin --document: todo

# 5etools — TODO el catálogo WotC pero NON-FREE: solo local, nunca
# se redistribuye (is_redistributable=False en toda la fuente)
#   git clone https://github.com/5etools-mirror-3/5etools-src
python -m pipeline.cli import-5etools --path 5etools-src/data

# JSON privado/homebrew
python -m pipeline.cli import-file --path <json> --license <lic> --type <tipo>

# Backend
cd ../backend
pip install -e .[dev]
uvicorn app.main:app --reload

# Frontend
cd ../frontend
npm install
npm run dev
```

Ver `docs/ARCHITECTURE.md` para el diseño completo.
