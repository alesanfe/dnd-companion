# Operaciones — D&D Companion

Superficie operativa del despliegue típico (Docker Compose, single
node). El detalle vive en [`operations/`](operations/).

## Comandos habituales

```bash
docker compose up --build   # stack completo (nginx :80 → backend :8000)
docker compose logs -f      # logs
curl localhost/api/health   # healthcheck del backend
tools/seed_demo.py          # datos demo de desarrollo
```

## Documentos

| Doc | Contenido |
|---|---|
| [operations/README.md](operations/README.md) | Índice y mapa del área |
| [operations/slo.md](operations/slo.md) | SLI/SLO, RPO/RTO y error budget |
| [operations/backup-restore.md](operations/backup-restore.md) | Backup consistente de `state.sqlite3`, restore y regeneración del compendio |
| [operations/incident-response.md](operations/incident-response.md) | Severidades y escenarios (backend caído, DB bloqueada, ola de conflictos…) |

## Notas

- Self-host: quien despliega es el operador y controlador de datos
  (ver [PRIVACY.md](PRIVACY.md)).
- `DND_ALLOW_REGISTRATION=0` cierra el alta en instancias expuestas.
