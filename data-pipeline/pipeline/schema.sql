-- Content DB: datos de reglas (read-only en runtime).
-- Todo lleva procedencia + licencia. Ver docs/ARCHITECTURE.md §2.

CREATE TABLE IF NOT EXISTS content_sources (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    version              TEXT,
    license              TEXT NOT NULL,
    attribution_text     TEXT,
    original_url         TEXT,
    imported_at          TEXT NOT NULL,
    content_hash         TEXT,
    distribution_allowed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS content_entities (
    id                  TEXT PRIMARY KEY,          -- '{source_id}:{index}'
    entity_type         TEXT NOT NULL,             -- spell|monster|class|...
    name                TEXT NOT NULL,
    ruleset             TEXT NOT NULL,             -- dnd5e-2014|dnd5e-2024|mixed
    source_id           TEXT NOT NULL REFERENCES content_sources(id),
    source_document     TEXT,
    source_version      TEXT,
    source_page         TEXT,
    license             TEXT NOT NULL,
    is_redistributable  INTEGER NOT NULL DEFAULT 0,
    data                TEXT NOT NULL              -- JSON normalizado completo
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON content_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON content_entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_ruleset ON content_entities(ruleset);

-- FTS5 standalone: entity_id apunta a content_entities.id
CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    entity_id UNINDEXED,
    name,
    body
);
