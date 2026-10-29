-- second_brain: a knowledge store that doesn't rot.
-- Every fact carries confidence, expiry, and verification so stale or
-- unverified knowledge can't silently poison the system.
--
-- This schema is repo-agnostic. Copy it into your own database and
-- adapt the connection parameters via environment variables (see
-- knowledge_hygiene.py for the env var reference).

CREATE TABLE IF NOT EXISTS second_brain (
    id            BIGSERIAL PRIMARY KEY,
    topic         TEXT NOT NULL UNIQUE,           -- unique upsert key; hygiene reconciles stale dups
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

-- Auto-audit trigger: logs every insert, update, and delete to second_brain_events.
-- This ensures the audit trail is never bypassed — even direct SQL gets logged.
CREATE OR REPLACE FUNCTION fn_second_brain_audit() RETURNS TRIGGER AS $audit$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO second_brain_events (sb_id, event_type, metadata)
        VALUES (NEW.id, 'insert', jsonb_build_object(
            'topic', NEW.topic, 'category', NEW.category,
            'confidence', NEW.confidence, 'source', NEW.source
        ));
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        -- Only log if key fields actually changed
        IF OLD.content IS DISTINCT FROM NEW.content
           OR OLD.confidence IS DISTINCT FROM NEW.confidence
           OR OLD.verification IS DISTINCT FROM NEW.verification
           OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
           OR OLD.tags IS DISTINCT FROM NEW.tags THEN
            INSERT INTO second_brain_events (sb_id, event_type, old_confidence, new_confidence, metadata)
            VALUES (NEW.id, 'update', OLD.confidence, NEW.confidence, jsonb_build_object(
                'topic', NEW.topic,
                'content_changed', OLD.content IS DISTINCT FROM NEW.content,
                'confidence_changed', OLD.confidence IS DISTINCT FROM NEW.confidence,
                'verification_changed', OLD.verification IS DISTINCT FROM NEW.verification,
                'expires_at_changed', OLD.expires_at IS DISTINCT FROM NEW.expires_at,
                'tags_changed', OLD.tags IS DISTINCT FROM NEW.tags
            ));
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO second_brain_events (sb_id, event_type, old_confidence, metadata)
        VALUES (OLD.id, 'delete', OLD.confidence, jsonb_build_object(
            'topic', OLD.topic, 'category', OLD.category,
            'confidence', OLD.confidence
        ));
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$audit LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_second_brain_audit ON second_brain;
CREATE TRIGGER trg_second_brain_audit
    AFTER INSERT OR UPDATE OR DELETE ON second_brain
    FOR EACH ROW EXECUTE FUNCTION fn_second_brain_audit();
