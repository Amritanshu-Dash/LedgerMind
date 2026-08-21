-- >>> 0003_update_cache_data_statuses.sql

-- >>> Updates cache_data to the new status model:
-- 1.  system-ingested  → set only by the extraction code on first insert
-- 2.  in_progress      → user is working on it
-- 3.  approved         → user approved it
-- 4.  rejected         → user rejected it
--
-- >>> Also updates the reviewer rule:
--   1. reviewed_by may be NULL only when status = 'system-ingested'
--   2. for every other status, reviewed_by is required

-- ============================================================
-- 1. Drop the old status check constraint (whatever its name is)
-- ============================================================
-- First find the real name if needed, but most commonly it is this:

ALTER TABLE cache_data
DROP CONSTRAINT IF EXISTS cache_data_data_review_status_check;

-- ============================================================
-- 2. Add the new status check constraint
-- ============================================================

ALTER TABLE cache_data
ADD CONSTRAINT cache_data_data_review_status_check
CHECK (
    data_review_status IN (
        'system-ingested',
        'in_progress',
        'approved',
        'rejected'
    )
);

-- ============================================================
-- 3. Replace the old reviewer constraint
-- ============================================================

ALTER TABLE cache_data
DROP CONSTRAINT IF EXISTS reviewer_required_when_reviewed;

ALTER TABLE cache_data
ADD CONSTRAINT reviewer_required_when_reviewed
CHECK (
    data_review_status = 'system-ingested'
    OR (reviewed_by IS NOT NULL AND btrim(reviewed_by) <> '')
);

-- ============================================================
-- 4. Optional but recommended: change the column default
--    (we always set the status explicitly in code, but this is safer)
-- ============================================================
ALTER TABLE cache_data
ALTER COLUMN data_review_status SET DEFAULT 'system-ingested';

-- ============================================================
-- 5. Record this migration
-- ============================================================
INSERT INTO schema_migrations (version)
VALUES ('0003_update_cache_data_statuses')
ON CONFLICT (version) DO NOTHING;