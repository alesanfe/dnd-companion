# Threat Model — D&D Companion

## Activos

- Fichas de personaje y estado de partida (`state.sqlite3`).
- Contenido con licencias restringidas (imports privados del usuario).
- Credenciales: tokens Bearer de `auth_tokens` (TTL 30 d), contraseñas
  PBKDF2-SHA256 600k iteraciones.
- Información oculta del DM: escenas, entidades y timeline `visibility=dm`.

## Actores y trust boundaries

- Cliente PWA ↔ FastAPI (REST `/api` + WS `/ws`): frontera principal.
- DM ↔ jugadores/espectadores: frontera de rol dentro de la app.
- Instancia local (sin `owner_id`) ↔ instancia multiusuario: dos modos
  de confianza distintos.

## Amenazas y mitigaciones

| Amenaza | Mitigación |
|---|---|
| Suplantación de usuario | `user_id` del body/payload es spoofable por diseño → siempre se pisa con el uid del token autenticado, en REST y en el path WS (`_dispatch_ws`). |
| Escalada de rol | `member_role` se resuelve en servidor; ops `entity_kind=combat` son DM-only en ambos canales. Espectador = solo lectura (sin chat/typing/ops). |
| Fuga de info del DM | `visibility=dm` se filtra en servidor (state, events, entidades, relaciones, timeline); WS solo entrega a sockets dm/owner/local. |
| Fichas personales ajenas | `_personal_ownership`: con usuarios registrados solo el dueño las muta/lista; `?user_id=` suelto no la satisface en WS. |
| Jugador declara daño/tipo | En `combat.attack` el servidor elimina `damage_type`/`mode` del payload del jugador — la op la resuelve el servidor vs CA real sin exponerla. |
| Escritura en combate ajeno | `_campaignless_combat_guard`: solo PJ libres o del llamante; `_sync_character` nunca escribe en ficha de otro. |
| Transfer a medias | `inventory.transfer` guarda par `<id>:out`/`<id>:in` y `_undo_transfer` revierte ambas atómicamente. |
| Fuerza bruta de login | Throttle por usuario normalizado + por IP, persistente en `auth_throttle` (no en memoria). `secrets.compare_digest`. |
| Registro abierto en instancia expuesta | `DND_ALLOW_REGISTRATION=0`. |
| Token WS en logs de proxy | El Bearer viaja en `Sec-WebSocket-Protocol` (`bearer.<token>`); `?token=` queda solo como fallback de clientes antiguos. |
| Fuga de datasets con copyright | `data/` gitignored; procedencia obligatoria (`source_id`, `license`, `is_redistributable`); 5etools solo local. |
| CORS abierto | `DND_CORS_ORIGINS` lista cerrada; en Docker el front es same-origin. |
| Optimistic locking stale | `expected_version` obligatorio en PATCH → 409 + recarga; `token-move` reaplica delta sobre copia fresca. |
| SQLite bloqueado | UPDATE sin filas → `rollback` explícito (txn abierta bloquea WAL). |

## Asunciones

- Modo local abierto (campaña sin `owner_id`) asume entorno de confianza:
  los guards pasan siempre. Documentado como comportamiento esperado.
- La CA del objetivo no se expone al jugador (el servidor la resuelve).
- Retención: `events` se poda a 500 por campaña; `auth_tokens` y
  `auth_throttle` tienen GC perezosa.

## Deuda conocida

- Tokens de sesión en `auth_tokens` sin rotación automática (TTL 30 d
  como única caducidad).
- Rate limiting de ops WS por usuario no implementado (solo auth).
