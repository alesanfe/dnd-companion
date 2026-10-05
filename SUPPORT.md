# Soporte

| Qué necesitas | Dónde |
|---|---|
| Reportar un bug | [Issues](https://github.com/alesanfe/dnd-companion/issues) — indica si es backend, frontend o pipeline, y pasos para reproducir |
| Proponer una feature | Issue con plantilla "Feature request" |
| Duda de uso | Issue etiqueta `question` |
| Vulnerabilidad de seguridad | **No** abras issue público — ver [SECURITY.md](SECURITY.md) |

## Antes de reportar

- Entorno: Docker Compose es la vía soportada; indica si el bug se
  reproduce con `docker compose up --build` o solo en dev local.
- El frontend es offline-first: si el bug es de sincronización,
  adjunta qué hay en la cola pendiente (Ajustes → Métricas de sync).
- La suite de referencia es `pytest` en `backend/` y `vitest` en
  `frontend/` — un bug reproducible merece un test.
