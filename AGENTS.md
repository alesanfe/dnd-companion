# AGENTS.md — D&D Companion

## Contexto

App web/móvil (PWA) de hojas de personaje D&D + herramientas de DM.
Python 3.11 + FastAPI backend, React + Vite frontend, SQLite + FTS5.

## Comandos

```bash
# Backend
cd backend && pip install -e .[dev]
uvicorn app.main:app --reload          # dev server :8000
pytest backend/tests                   # tests

# Data pipeline — fuentes: 5e-bits (SRD CC-BY-4.0), Open5e v1 (OGL docs:
# tob, cc, dmag, vom, menagerie, blackflag, taldorei, a5e…), Open5e v2
# (schema rico: srd-2024, a5e-ag…), Foundry packs (YAML, CC-BY-4.0),
# 5etools (catálogo completo, NON-FREE — solo local), import-file
cd data-pipeline && pip install -e .
python -m pipeline.cli import-srd --edition 2014|2024
python -m pipeline.cli import-open5e --document <slug> --api v1|v2
python -m pipeline.cli import-5etools --path <clone>/data
python -m pipeline.cli import-foundry --path <clone>/packs/_source
python -m pipeline.cli import-file --path <json> --license <lic> --type <t> [--key <k>]

# Frontend
cd frontend && npm install && npm run dev
```

## Reglas del proyecto (no negociables)

- **Nunca** commitear datasets con copyright. Solo SRD CC-BY-4.0 entra al repo.
  `data/` está gitignored. Los imports privados del usuario quedan en su DB local.
- Toda entidad de contenido lleva `source_id`, `license`, `is_redistributable`.
- Reglas de juego van en el **motor de efectos declarativo**
  (`backend/app/engine/`), no como condicionales dispersos.
- Las **tablas normativas** (CR→XP, umbrales de encuentro, XP por
  nivel, habilidades por característica, condiciones, constantes de
  combate) viven en `backend/app/rules/srd_core.json` (SRD CC-BY-4.0)
  — leerlas vía `app.rules.rules()`; nunca duplicarlas en código.
- `ruleset` interno: `dnd5e-2014` | `dnd5e-2024` | `mixed`. Etiquetas tipo
  "5e"/"5.5e" solo en UI.
- Diferencias 2024 efectivas en el motor: agotamiento (-2×nivel a d20,
  -5ft×nivel de velocidad, muerte a 6) vía `domain/conditions.py`
  (ruleset-aware); inspiración heroica = reroll post-tirada del peor
  dado retenido (`/character/{id}/roll?heroic_reroll`, solo 2024;
  en 2014 es ventaja previa vía `use_inspiration`); maestría de arma
  — el arma 2024 declara `mastery.index` y `combat.attack` lo aplica
  automáticamente (`use_mastery=false` lo desactiva): sap/slow marcan
  al objetivo, vex marca al atacante (ambos consumibles en el próximo
  ataque, también en `combatant.action.roll`), topple=save CON→prone,
  graze=daño=mod en fallo, flex=dado versátil, push/evento de 10ft,
  cleave/nick solo se anotan (cadena manual). `character.attack`
  acepta `use_mastery` (solo flex/graze + nota — no hay objetivo).
- Todo cambio de estado = operación con `operation_id` + `entity_version`
  (idempotencia, optimistic locking, reversible).
- Eventos WebSocket pequeños y tipados (`character.hp.changed`, etc.), nunca
  la ficha completa.

## Modelo de acceso (auth)

- `optional_user`/`current_user` (api/auth.py): Bearer token de
  `auth_tokens` (TTL 30d); `member_role(camp, uid)` = owner | co_dm |
  player | guest | spectator. **Campaña sin `owner_id` = modo local
  abierto** — los guards pasan siempre; con owner, `_require_role`
  (api/campaigns.py) exige membresía y `_DM_ROLES` para lo administrativo.
- El `user_id` del body/payload es **spoofable**: con token se pisa con
  el uid autenticado (ops, join, transfer). El mismo guard va en REST
  **y** en el path WS de operaciones (main.py `_dispatch_ws`).
- Ops `entity_kind=combat` = DM-only (REST y WS); `character` = miembro
  y, si la ficha tiene `player_id`, solo su dueño (o el DM) la muta.
  Excepciones del jugador sobre SU combatiente-PJ:
  `combatant.death_save_roll` (y su undo), `combat.attack` (ataque
  desde el mapa: el servidor resuelve impacto vs CA del objetivo sin
  exponerla y aplica el daño — `attacker_combatant_id` debe ser el
  combatiente-PJ del jugador) y `combat.shove_grapple` (empujón/
  agarrón — unarmed 2024 = salvación FUE/DES del objetivo vs
  8+FUE+prof; 2014 = contestada Atletismo; misma guardia de
  atacante).
- **Fichas sin campaña con `player_id`** (`_personal_ownership`):
  cuando hay usuarios registrados solo las muta su dueño — el guard
  de campaña no aplica porque `entity_camp` es None. En WS solo
  cuenta la identidad por token (`authed`): un `?user_id=` suelto
  es spoofable y NO la satisface (ni resuelve rol en campañas con
  owner → spectator). Sin usuarios (local puro) todo abierto. El
  listado `GET /characters` tampoco enumera fichas personales
  ajenas; `GET /campaigns` anónimo solo ve campañas sin owner; y
  historial/conflictos/dismiss de fichas personales son del dueño.
  `campaign_id=""` se normaliza a NULL en PATCH — un "" saltaba los
  dos branches de guards.
- **Combates sin campaña** (`_campaignless_combat_guard`): solo
  admiten combatientes-PJ libres o del llamante; si el tracker ya
  apunta a una ficha ajena, toda op posterior de un tercero es 403
  (y `award-xp` igual) — `_sync_character` no debe escribir en la
  hoja de otro usuario.
- Fichas libres (`player_id` NULL) se reclaman vía PATCH — el no-DM
  solo puede poner su propio uid o soltar la suya.
- Visibilidad `dm` se filtra en el servidor, no solo en la UI: eventos
  (/state, /events), escenas de sesiones, entidades, relaciones y
  timeline nunca salen a no-DM en campañas con owner.
- Sala WS: `visibility=dm` solo llega a sockets dm/owner/local;
  `payload.for_user` = entrega dirigida (petición secreta del DM).
  Espectador = solo lectura (sin chat/typing/ops). El `from` del
  chat/typing lo firma el servidor con la identidad del socket.
- Conflictos de optimistic locking: `POST /api/operations/conflicts/
  {id}/retry|dismiss` — resolución asistida desde Settings.
- El Bearer token del WS viaja en `?token=` (queda en logs de proxy)
  — aceptado para deployment local/LAN; si se expone a internet,
  migrarlo a `Sec-WebSocket-Protocol` o mensaje `auth` inicial.
- CORS: `DND_CORS_ORIGINS` (lista separada por comas; por defecto
  `http://localhost:5173`). En Docker el front es same-origin vía
  proxy nginx — CORS solo hace falta si el front vive en otro host.
- Deployment Docker: `frontend/nginx.conf` proxifica `/api` y `/ws`
  (con Upgrade) a `backend:8000` + fallback SPA. El backend NO
  publica 8000 al host (solo `expose` en la red interna); corre
  como `dnd` (uid 10001) con healthcheck `/api/health`; el front
  usa `node:20` + `npm ci` (paridad con CI, lockfile).
- `state_db()`: el schema corre solo si `PRAGMA user_version` <
  `_SCHEMA_VERSION` — añadir tablas = subir la constante y el DDL
  (IF NOT EXISTS) en `state_schema.sql`. Rate-limit de auth =
  `auth_throttle` (persistente, no en memoria).
- Retención: `events` se poda a las últimas 500 por campaña en cada
  op aplicada; `auth_tokens`/`auth_throttle` tienen GC perezosa.
- Constructor de encuentros: `POST /api/encounters/suggest`
  (presupuesto ajustado → composición greedy con `seed` opcional);
  UI en pestaña Combate del DM (📍 suelta al mapa, ▶ crea el
  combate con la composición).
- **Delegación**: op `combatant.delegate` (DM-only) fija
  `combatant.delegated_to = user_id`. El delegado mueve el token
  vinculado (`combatant_id`) y tira las acciones de su stat block
  (`combatant.action.roll`) — el check es `_is_own_char_combatant`,
  que cubre delegados. `combat.attack` sigue pidiendo un PJ con
  ficha. No gana ops de dirección (next_turn = 403).
- **Reglas en ops de jugador**: en `combat.attack` el payload del
  jugador NO declara `damage_type` ni `mode` (se eliminan en
  `_player_combat_op` — declararlos era vuln/resist/adv a voluntad).
- `inventory.transfer` es **no-reversible** (sin `inverse`): el undo
  de una sola mitad duplicaba objetos — pendiente undo compuesto.
- Auth: PBKDF2-SHA256 600k iteraciones con migración perezosa de los
  hashes a 100k al primer login; `secrets.compare_digest`; throttle
  por usuario normalizado + por IP; `DND_ALLOW_REGISTRATION=0`
  cierra el alta en instancias expuestas.

## Sincronización ficha ↔ combate

- Bidireccional dentro de la misma transacción SQLite: ops de combate
  sobre un PJ (`combat_ops._sync_character`) actualizan la ficha; ops
  vitales de ficha (`ops._sync_combat`, set `_VITAL_OPS`: hp.damage/
  heal/set, death_save, state.restore, rests, level_up, tick,
  condition.apply/remove, hit_die.*) actualizan al combatiente
  vinculado (`ref_id`) en combates `active` de su campaña.
- Ambos espejos bumpean `version` con guardia optimista y solo tocan
  el estado vital (PG/temp/salvaciones/condiciones muerto·dead·
  estable) — nunca las condiciones persistentes ajenas.
- `OpContext` lleva `entity_id` (apply_to_store) para que la ficha
  encuentre su campaña/combate. El frontend refresca por
  `aggregate_id` o `payload.character_id` (sheet) y por `ref_id` de
  combatientes (DmBoard).

## Sincronización mapa ↔ combate (VTT)

- Token ↔ combatiente: `token.ref_id` = id de ficha (PG en vivo);
  `token.combatant_id` = id del combatiente (monstruos). El badge de
  iniciativa y el anillo de turno casan por ref_id **o nombre**.
- `MapBoard` props: `combatants` (lista del tracker) + `combat`
  (entidad, para ops). Botón "Del combate" vuelca combatientes como
  tokens (sin duplicar; tamaño desde `stat_block.size`).
- Daño de zona (casillas pintadas): CD>0 tira salvación por token
  (motor de ficha o `combatant.save`) → mitad al superar; el tipo de
  daño activa res/imm/vul del stat block vía `combatant.damage`.
- Ataque token→token (⚔): arma del inventario de la ficha o acción
  del stat block vs CA real del objetivo → daño por op auditable.
- Token suelto → combate: botón ＋⚔ (`combatant.add`, initiative
  server-rolled) y el token queda enlazado por `combatant_id`.
- El jugador también ataca desde su token (vista readOnly): misma op
  `combat.attack` — autorizada solo si el atacante es su PJ.
- `combat.version` stale: MapBoard sigue la versión en
  `combatVerRef` tras cada op — dos ops seguidas no chocan en 409.
- `PATCH /entities/{id}` acepta `expected_version` (optimistic lock →
  409): el frontend siempre la manda; MapBoard recarga al chocar.
  `token-move` escribe con guardia de versión y reaplica el delta
  sobre la copia fresca si otro escritor ganó. Tras un UPDATE que no
  cambia filas hay que hacer `rollback` — la txn de escritura
  dejada abierta bloquea WAL al siguiente writer.
- Token: `image_url` = retrato (clip circular; vacío = iniciales),
  `light_ft`/`vision_ft` = niebla, `size` = footprint en casillas.
- Regla al arrastrar: pies recorridos en vivo + presupuesto de
  movimiento del turno (acumulado por token, reset al cambiar el
  activo; velocidad de la ficha/stat block — avisa, no bloquea).
- `MapPieces.jsx` = capas de presentación SVG (MapToken, MapPin,
  InitiativeRibbon); la lógica (arrastre, ataques, alcance, niebla)
  sigue en `MapBoard.jsx`.

## Verificación

- `python -m compileall backend/app data-pipeline` — sintaxis
- `pytest backend/tests`
- `npm run build` en frontend/
