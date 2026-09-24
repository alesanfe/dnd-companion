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

## Quickstart

```bash
# Content DB (SRD 2014 desde 5e-bits)
cd data-pipeline
pip install -e .
python -m pipeline.cli import-srd --edition 2014

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
