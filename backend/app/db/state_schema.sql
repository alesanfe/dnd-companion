-- State DB: estado de partida (separado de la content DB de reglas).

CREATE TABLE IF NOT EXISTS campaigns (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    invite_code TEXT UNIQUE,
    ruleset     TEXT NOT NULL DEFAULT 'dnd5e-2014',
    owner_id    TEXT,
    data        TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    player_id   TEXT,
    campaign_id TEXT REFERENCES campaigns(id),
    ruleset     TEXT NOT NULL DEFAULT 'dnd5e-2014',
    version     INTEGER NOT NULL DEFAULT 1,   -- optimistic locking
    data        TEXT NOT NULL,                -- ficha completa JSON
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_characters_campaign
    ON characters(campaign_id);

-- Cada cambio es una operación: idempotente, auditable, reversible.
CREATE TABLE IF NOT EXISTS operations (
    operation_id   TEXT PRIMARY KEY,
    entity_id      TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    client_id      TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    payload        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'synced',  -- pending|synced|rejected|conflict
    inverse        TEXT                              -- payload para deshacer
);
CREATE INDEX IF NOT EXISTS idx_operations_entity
    ON operations(entity_id, entity_version);

CREATE TABLE IF NOT EXISTS events (
    event_id          TEXT PRIMARY KEY,
    campaign_id       TEXT NOT NULL,
    aggregate_id      TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL,
    actor_id          TEXT NOT NULL,
    occurred_at       TEXT NOT NULL,
    type              TEXT NOT NULL,
    payload           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_campaign
    ON events(campaign_id, occurred_at);

-- Tracker de combate: un combat por encuentro, combatants en data JSON.
CREATE TABLE IF NOT EXISTS combats (
    id          TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    name        TEXT NOT NULL,
    ruleset     TEXT NOT NULL DEFAULT 'dnd5e-2014',
    version     INTEGER NOT NULL DEFAULT 1,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_combats_campaign
    ON combats(campaign_id);

-- Miembros de campaña: rol por campaña (owner|co_dm|player|guest|
-- spectator|delegated_npc). La enforcement llega con auth.
CREATE TABLE IF NOT EXISTS members (
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'player',
    character_id TEXT,
    joined_at   TEXT NOT NULL,
    PRIMARY KEY (campaign_id, user_id)
);

-- Entidades de campaña: NPC, lugares, misiones, facciones, escenas,
-- notas. Visibilidad: public|dm|players — known_to lista jugadores
-- que conocen info parcial; reveal_* describe cuándo se revela.
CREATE TABLE IF NOT EXISTS campaign_entities (
    id           TEXT PRIMARY KEY,
    campaign_id  TEXT NOT NULL REFERENCES campaigns(id),
    kind         TEXT NOT NULL,   -- npc|location|quest|faction|scene|note
    name         TEXT NOT NULL,
    data         TEXT NOT NULL DEFAULT '{}',
    visibility   TEXT NOT NULL DEFAULT 'public',
    known_to     TEXT NOT NULL DEFAULT '[]',
    reveal_condition TEXT,
    revealed_at  TEXT,
    version      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_campaign
    ON campaign_entities(campaign_id, kind);

-- Grafo de relaciones dirigidas entre entidades/personajes.
CREATE TABLE IF NOT EXISTS relationships (
    id          TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    from_id     TEXT NOT NULL,    -- entity o character id
    to_id       TEXT NOT NULL,
    type        TEXT NOT NULL,    -- 'knows'|'works_for'|'hates'|'family'...
    description TEXT,
    visibility  TEXT NOT NULL DEFAULT 'dm',
    world_date  TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_campaign
    ON relationships(campaign_id);

-- Sesiones de juego: preparación por escenas enlazadas via
-- campaign_entities(kind='scene').data.session_id
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    number      INTEGER,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'prep',  -- prep|active|done
    data        TEXT NOT NULL DEFAULT '{}',    -- notas, resumen posterior
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_campaign
    ON sessions(campaign_id);
