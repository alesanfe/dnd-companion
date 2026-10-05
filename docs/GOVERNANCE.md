# Gobernanza — dnd-companion

## Roles

- **Mantenedor**: revisa PRs, decide qué fuentes de contenido se
  soportan, corta releases, administra el despliegue de referencia.
- **Contribuidor**: issues, PRs, traducciones y packs de contenido
  licitables.

## Proceso de cambios

- PR con CI verde (`ci.yml`, `security.yml`, `scorecard.yml`).
- Regla de juego nueva: efecto declarativo en `backend/app/engine/`
  + test + actualización de `rules/srd_core.json` si usa tablas.
- Op nueva: payload tipado, guard de rol en REST y WS, test de
  idempotencia y de optimistic locking.
- Fuente de contenido nueva: licencia verificada — **jamás**
  commitear datasets NON-FREE; `data/` está gitignored.
- ADR en `docs/decisions/` para decisiones arquitectónicas — no se
  borran, se marcan *Superseded*.

## Contenido con copyright

- Solo SRD CC-BY-4.0 (y fuentes igualmente abiertas) entra al repo.
- 5etools / dnd-data se importan solo en local del usuario
  (`make import-5etools`, `make import-dnddata`) — nunca en CI.

## Releases

- El stack completo corre con `docker-compose` — una release es
  un tag + imágenes publicadas; sin artefactos binarios por SO.
