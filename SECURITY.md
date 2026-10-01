# Seguridad

## Reportar una vulnerabilidad

**No abras una issue pública.** Contacta al mantenedor directamente
por el canal privado de GitHub (Report a vulnerability en la pestaña
Security del repositorio) o por el email del perfil del autor.

Incluye: versión/commit afectado, pasos para reproducir, impacto
estimado y si hay algún workaround.

## Modelo de seguridad (resumen)

- **Autenticación**: PBKDF2-SHA256 600k iteraciones, tokens Bearer
  con TTL 30d, throttle persistente por usuario e IP.
  `DND_ALLOW_REGISTRATION=0` cierra el alta en instancias expuestas.
- **Autorización**: roles owner/co_dm/player/spectator por campaña;
  el `user_id` de payloads nunca sustituye al del token. Visibilidad
  `dm` se filtra en el servidor (eventos, escenas, entidades, stats
  ocultos de monstruos).
- **Combates**: ops de tracker son DM-only; el jugador solo puede
  `combat.attack`, `combat.shove_grapple` y `combatant.death_save_roll`
  sobre SU combatiente — y el payload no puede declarar `mode`/
  `damage_type` a voluntad.
- **WS**: la sala de campaña requiere membresía; espectadores son
  solo lectura; `visibility=dm` solo llega a sockets DM/owner.
- **Contenido**: solo SRD CC-BY-4.0 en el repo; las importaciones
  non-free son locales y marcadas `is_redistributable=false`.

## Limitaciones conocidas (deployment)

- El token del WS viaja en `?token=` — queda en logs de proxy.
  Aceptable en LAN/local; para exposición a internet, migrar a
  `Sec-WebSocket-Protocol` o mensaje `auth` inicial.
- El proxy nginx no lleva rate-limit ni cabeceras de seguridad
  extra; se recomienda TLS terminado en el proxy si se expone.
- `backend/data/` contiene fichas y campañas en SQLite — proteger
  ese directorio al desplegar.

El detalle completo del modelo de acceso está en
[AGENTS.md](AGENTS.md#modelo-de-acceso-auth).
