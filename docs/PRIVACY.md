# Privacidad — D&D Companion

## Principio

App diseñada para self-hosting: los datos viven en la instancia del
usuario (o del grupo), no en un servicio central. No hay telemetría,
analytics ni llamadas salientes a terceros en runtime.

## Datos que almacena

- **Cuentas**: username + hash PBKDF2-SHA256 (600k iteraciones) y tokens
  de sesión en `auth_tokens` (TTL 30 d).
- **Contenido de partida**: fichas, campañas, chat, notas, mapas — en
  `state.sqlite3` local a la instancia.
- **Imports de contenido**: los datasets privados (p. ej. 5etools,
  Foundry packs) quedan en la DB local del usuario; nunca entran al repo
  ni se redistribuyen (`data/` gitignored, `is_redistributable=false`).

## Visibilidad

- `visibility=dm` se filtra en servidor en todos los canales (REST,
  eventos WS, escenas, entidades, timeline).
- Las peticiones secretas de jugadores solo llegan al socket del DM
  (`payload.for_user` = entrega dirigida).
- Fichas personales (sin campaña, con `player_id`) solo las lista/muta
  su dueño cuando hay usuarios registrados.

## Exposición de red

- En Docker el backend **no** publica el puerto 8000 al host: solo el
  front nginx (same-origin, proxy `/api` + `/ws`).
- CORS cerrado por defecto a `http://localhost:5173`
  (`DND_CORS_ORIGINS` para abrirlo conscientemente).
- El registro de usuarios puede cerrarse con `DND_ALLOW_REGISTRATION=0`
  en instancias expuestas.

## Retención

- `events`: últimos 500 por campaña (poda en cada op).
- `auth_tokens`/`auth_throttle`: GC perezosa al expirar.
- Historial de conflictos y fichas personales: solo accesibles a su dueño.
