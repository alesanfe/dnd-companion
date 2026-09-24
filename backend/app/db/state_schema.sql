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
