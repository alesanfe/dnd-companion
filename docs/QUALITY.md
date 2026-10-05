# Atributos de calidad prioritarios

Declaración explícita de qué importa más en este proyecto y cómo se mide.
Una decisión que empeore un atributo `crítico` exige justificación en el PR.

## Prioridades

| Atributo | Prioridad | Objetivo | Medición | Umbral |
|---|---|---|---|---|
| Integridad de datos | crítica | Ops idempotentes + optimistic locking — nunca estado a medias | tests de ops (undo, transfer, conflictos) | 0 operaciones parciales |
| Corrección de reglas | crítica | Motor declarativo fiel a 5e-2014/2024 | `backend/app/rules/srd_core.json` + tests | 0 divergencias vs tablas SRD |
| Usabilidad offline | alta | PWA funcional sin red | cola de ops + IndexedDB (Dexie) | ficha editable offline |
| Seguridad | alta | Roles DM/jugador/espectador enforce en servidor | guards en REST y WS | 0 bypass conocidos |
| Mantenibilidad | alta | Reglas en motor declarativo, no condicionales | `app/engine/` + `rules/srd_core.json` | sin reglas hardcodeadas |
| Rendimiento | media | Ficha interactiva fluida | sync ficha↔combate en misma txn | op < 200 ms local |

## Presupuestos (comprobables)

```yaml
budgets:
  backend_tests: pytest backend/tests   # verde
  frontend_build: npm run build         # limpio
  compile: python -m compileall         # sintaxis
```

## Lo que deliberadamente NO se persigue

Contenido con copyright en el repo (solo SRD CC-BY-4.0 — regla no
negociable), cuentas en la nube, sync multi-dispositivo automático
más allá de la cola de ops.
