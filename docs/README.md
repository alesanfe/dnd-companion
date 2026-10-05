# Documentación — D&D Companion

## Arquitectura y dominio

- [Arquitectura](ARCHITECTURE.md) — FastAPI + React PWA, motor de efectos
- [Modelo de datos](DATA_MODEL.md) — fichas, campañas, contenido, ops

## Requisitos y gobernanza

- [Requisitos](REQUIREMENTS.md) — funcionales y no funcionales
- [Gobernanza](GOVERNANCE.md) — roles y proceso de decisión
- [Madurez](MATURITY.md) — autoevaluación por área
- [Calidad](QUALITY.md) — atributos prioritarios y presupuestos
- [Dependencias](DEPENDENCIES.md) — política e inventario
- [Deprecaciones](DEPRECATION.md) — ciclo de vida de features/ops
- [Deuda técnica](TECH_DEBT.md) — registro formal

## Seguridad y privacidad

- [Modelo de amenazas](THREAT_MODEL.md) — sesiones, tokens, visibilidad DM
- [Privacidad](PRIVACY.md) — datos de usuario y licencias de contenido

## Decisiones (ADRs)

- [Índice de ADRs](decisions/README.md) — ops idempotentes, dos SQLite,
  rol DM en frontend

## Operaciones

- [Operaciones](OPERATIONS.md) — índice operativo
- [Despliegue y runbook](operations/README.md) — respaldo y operación
- [SLO](operations/slo.md) — objetivos de fiabilidad (SLI/SLO, RPO/RTO)
- [Backup y restore](operations/backup-restore.md) — `state.sqlite3` y
  regeneración del compendio
- [Respuesta a incidentes](operations/incident-response.md) —
  severidades y escenarios
