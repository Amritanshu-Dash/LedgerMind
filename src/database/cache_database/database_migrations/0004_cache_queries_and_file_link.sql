-- 0004_cache_queries_and_file_link.sql
-- Adds the query side of cache DB.
-- Does not rebuild cache_data. Only adds a link column.

-- ------------------------------------------------------------
-- 1. Query table
-- One row per user question.
-- Files (if any) live in cache_data and point back here.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cache_queries (
    unique_query_id       BIGSERIAL PRIMARY KEY,
    original_query        TEXT NOT NULL,
    system_converted_query TEXT NOT NULL,
    query_sense           TEXT NOT NULL,
    attachment_count      INTEGER NOT NULL DEFAULT 0,
    attachment_summary    TEXT NOT NULL DEFAULT '0 attachments',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT cache_queries_attachment_count_check
        CHECK (attachment_count >= 0)
);

-- ------------------------------------------------------------
-- 2. Link each extracted file to the query that brought it in.
-- Old file rows can stay NULL (tests you already ran).
-- ------------------------------------------------------------
ALTER TABLE cache_data
    ADD COLUMN IF NOT EXISTS unique_query_id BIGINT;

ALTER TABLE cache_data
    DROP CONSTRAINT IF EXISTS cache_data_unique_query_id_fkey;

ALTER TABLE cache_data
    ADD CONSTRAINT cache_data_unique_query_id_fkey
    FOREIGN KEY (unique_query_id)
    REFERENCES cache_queries (unique_query_id)
    ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_cache_data_unique_query_id
    ON cache_data (unique_query_id);

CREATE INDEX IF NOT EXISTS idx_cache_queries_created_at
    ON cache_queries (created_at);

-- ------------------------------------------------------------
-- 3. Record this migration
-- ------------------------------------------------------------
INSERT INTO schema_migrations (version)
VALUES ('0004_cache_queries_and_file_link')
ON CONFLICT (version) DO NOTHING;