# Backup y restauración — D&D Companion

## Qué hay que proteger

| Fichero | Contenido | ¿Backup? |
|---|---|---|
| `data/state.sqlite3` (+ `-wal`/`-shm`) | personajes, campañas, combates, sesiones, ops, usuarios, tokens | **Sí — la pieza valiosa** |
| `data/content.sqlite3` | compendio importado (SRD/Open5e/homebrew) | Solo si contiene homebrew propio; lo público se regenera con `data-pipeline` |
| `.env`/compose overrides | `DND_CORS_ORIGINS` y configuración local | Sí (son pocos valores) |

## Backup

Con el backend parado o usando la API online de SQLite (nunca copiar
el `.sqlite3` a lo bruto con el WAL caliente):

```bash
# 1) recomendado: backup consistente sin parar el servicio
docker compose exec backend \
  python -c "import sqlite3; s=sqlite3.connect('/data/state.sqlite3'); \
             d=sqlite3.connect('/data/backups/state-$(date +%F).sqlite3'); \
             s.backup(d); d.close()"

# 2) alternativa: parar y copiar fichero + wal
docker compose stop backend
cp data/state.sqlite3* backups/
docker compose start backend
```

Frecuencia objetivo: diaria (RPO 24 h, ver `slo.md`). Rotar con la
política habitual (7 diarios + 4 semanales basta para self-hosted).

## Restauración

```bash
docker compose stop backend
cp backups/state-YYYY-MM-DD.sqlite3 data/state.sqlite3
rm -f data/state.sqlite3-wal data/state.sqlite3-shm   # wal del estado nuevo
docker compose start backend
curl localhost:5173/api/health        # o el puerto real del front
```

Verificación post-restore: abrir una ficha conocida y comprobar que
`version`/PG coinciden con lo esperado; revisar
`docker compose logs backend` por errores de `user_version`.

## Regenerar `content.sqlite3`

```bash
cd data-pipeline
python -m pipeline.cli import-srd --edition 2014
python -m pipeline.cli import-srd --edition 2024
python -m pipeline.cli import-open5e --document <slug>   # por cada doc OGL usado
# imports privados (5etools, import-file): re-ejecutar con los clones
# locales originales — no se distribuyen, cada instancia los importa
```

## Prueba de restauración

Ejercicio semestral mínimo: restaurar `state.sqlite3` en un directorio
`data/` alternativo, `docker compose up` contra él y verificar que las
fichas abren y la cola de sync no reporta conflictos espurios.
