-- 0002_cache_data_guardrails.sql
-- Adds enforcement rules to the existing cache_data table (created
-- manually via psql). Nothing here recreates the table — every
-- statement below is additive, safe to run against the table as it
-- already exists.

-- ============================================================
-- 1. reviewed_by is required for any row that isn't 'pending'.
-- Matches the project rule: a status change without a name attached
-- should be impossible, not just discouraged.
-- ============================================================
ALTER TABLE cache_data
    ADD CONSTRAINT reviewer_required_when_reviewed
    CHECK (
        data_review_status = 'pending'
        OR (reviewed_by IS NOT NULL AND btrim(reviewed_by) <> '')
    );

-- ============================================================
-- 2. main_db_status can only be set once a row is actually approved.
-- Closes the gap where main_db_status could be 'requested' on a row
-- that's still 'pending' or 'rejected'.
-- ============================================================
ALTER TABLE cache_data
    ADD CONSTRAINT main_db_status_only_when_approved
    CHECK (main_db_status IS NULL OR data_review_status = 'approved');

-- ============================================================
-- 3. Auto-maintain updated_at (every change) and reviewed_at
-- (whenever reviewed_by changes) — one less thing application code has
-- to remember to set correctly on every single update.
-- ============================================================
CREATE OR REPLACE FUNCTION handle_cache_data_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    IF NEW.reviewed_by IS DISTINCT FROM OLD.reviewed_by THEN
        NEW.reviewed_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cache_data_before_update ON cache_data;
CREATE TRIGGER cache_data_before_update
    BEFORE UPDATE ON cache_data
    FOR EACH ROW
    EXECUTE FUNCTION handle_cache_data_update();

-- ============================================================
-- 4. Enforce the delete rule at the DATABASE level — a row can only be
-- deleted while data_review_status = 'rejected'. Same guardian pattern
-- as the malware scanner earlier in the pipeline: this protects the rule
-- even against a direct SQL DELETE run outside the application code.
-- ============================================================
CREATE OR REPLACE FUNCTION prevent_delete_unless_rejected()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.data_review_status <> 'rejected' THEN
        RAISE EXCEPTION 'Cannot delete row %: data_review_status is ''%'', must be ''rejected''.',
            OLD.id, OLD.data_review_status;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_delete_only_when_rejected ON cache_data;
CREATE TRIGGER enforce_delete_only_when_rejected
    BEFORE DELETE ON cache_data
    FOR EACH ROW
    EXECUTE FUNCTION prevent_delete_unless_rejected();

INSERT INTO schema_migrations (version) VALUES ('0002_cache_data_guardrails')
    ON CONFLICT (version) DO NOTHING;

