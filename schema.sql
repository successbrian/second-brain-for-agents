-- second_brain: a knowledge store that doesn't rot.
-- Every fact carries confidence, expiry, and verification so stale or
-- unverified knowledge can't silently poison the system.
--
-- This schema is repo-agnostic. Copy it into your own database and
-- adapt the connection parameters via environment variables (see
-- knowledge_hygiene.py for the env var reference).

CREATE TABLE IF NOT EXISTS second_brain (
    id            BIGSERIAL PRIMARY KEY,
    topic         TEXT NOT NULL,                  -- what this fact is about (dups allowed; hygiene tool reconciles)
    category      TEXT NOT NULL,                  -- fact | rule | research | ...
    content       TEXT NOT NULL,                  -- the fact itself
    confidence    TEXT NOT NULL DEFAULT 'medium', -- low | medium | high | expired
    source        TEXT,                           -- where it came from
    verification  TEXT,                           -- how it was verified
    expires_at    TIMESTAMPTZ,                    -- NULL = never; >90d = ask first
    tags          TEXT[],                         -- for indexing
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Operational noise (system_state, quick-scan, pipeline_state) does NOT go here.
-- Give it a separate state log, and keep the brain for durable facts.

CREATE INDEX IF NOT EXISTS idx_second_brain_topic  ON second_brain (topic);
CREATE INDEX IF NOT EXISTS idx_second_brain_tags   ON second_brain USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_second_brain_expiry ON second_brain (expires_at);
CREATE INDEX IF NOT EXISTS idx_second_brain_cat    ON second_brain (category, confidence);

-- Audit log — append-only, never deleted
-- Records every insert, update, and expire operation for provenance tracing.
CREATE TABLE IF NOT EXISTS second_brain_events (
    id          BIGSERIAL PRIMARY KEY,
    sb_id       INTEGER REFERENCES second_brain(id),
    event_type  TEXT NOT NULL
                CHECK (event_type IN ('insert','update','expire','delete')),
    old_confidence TEXT,
    new_confidence TEXT,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sb_events_sb_id ON second_brain_events (sb_id);
CREATE INDEX IF NOT EXISTS idx_sb_events_type  ON second_brain_events (event_type);
