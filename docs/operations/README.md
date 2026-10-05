# Operaciones

Documentos de despliegue y operación del servicio:

- Despliegue local/desarrollo: `docker compose up` en la raíz
  (ver [docker-compose.yml](../../docker-compose.yml)).
- Arquitectura y componentes: [../ARCHITECTURE.md](../ARCHITECTURE.md).
- Modelo de datos y retención: [../DATA_MODEL.md](../DATA_MODEL.md).
- Amenazas y controles: [../THREAT_MODEL.md](../THREAT_MODEL.md).

## Runbooks

- [slo.md](slo.md) — SLI/SLO, RPO/RTO y error budget del despliegue
  típico (compose single-node).
- [backup-restore.md](backup-restore.md) — backup consistente de
  `state.sqlite3`, restauración y regeneración del compendio.
- [incident-response.md](incident-response.md) — severidades y
  escenarios: backend caído, DB corrupta/bloqueada, ola de conflictos
  de sync, registro abierto, bypass de permisos.
