# Contribuir

Gracias por contribuir a D&D Companion. Este documento resume el proceso;
las reglas inviolables del proyecto (seguridad, procedencia, contratos de
sincronización) están en [AGENTS.md](AGENTS.md) — léelo antes de tocar
código.

## Entorno de desarrollo

```bash
cd data-pipeline && pip install -e .
python -m pipeline.cli import-srd --edition 2014
cd ../backend && pip install -e .[dev] && uvicorn app.main:app --reload
cd ../frontend && npm install && npm run dev    # otra terminal
```

## Antes de enviar un PR

```bash
pytest backend/tests                 # suite backend completa
cd frontend && npm test && npm run build
python -m compileall backend/app data-pipeline   # sintaxis
```

## Reglas no negociables

1. **Nunca** se commitea contenido con copyright (`data/` está
   gitignored; solo SRD CC-BY-4.0 entra al repo).
2. Todo cambio de estado es una **operación** con `operation_id` +
   `entity_version` (idempotente, optimistic lock, reversible,
   auditable). Las ops nuevas llevan inversa.
3. Las reglas de juego van en el **motor declarativo**
   (`backend/app/engine/` + `rules/srd_core.json`), no en
   condicionales dispersos.
4. El `user_id` del body es spoofable: la identidad siempre sale del
   token Bearer autenticado. Los mismos guards aplican en REST y WS.
5. Eventos WS pequeños y tipados — nunca fichas completas.
6. i18n es/en para todo texto nuevo en UI (`frontend/src/i18n.jsx`).

## Proceso

- Issues para bugs (pasos para reproducir) y propuestas de feature.
- PRs pequeños y enfocados; describe el porqué, no solo el qué.
- Incluye tests para comportamiento nuevo (la suite vive en
  `backend/tests/` y Vitest junto a los componentes).
- Actualiza README/AGENTS.md si cambia un comando, una variable de
  entorno o una regla del proyecto.
