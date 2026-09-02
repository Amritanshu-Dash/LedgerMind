-- 0005_cache_data_required_file_fields.sql
-- Files must belong to a query.
-- File name and comments must always be present.

ALTER TABLE cache_data
    ALTER COLUMN unique_query_id SET NOT NULL;

ALTER TABLE cache_data
    ALTER COLUMN original_filename SET NOT NULL;

ALTER TABLE cache_data
    ALTER COLUMN comments SET NOT NULL;

INSERT INTO schema_migrations (version)
VALUES ('0005_cache_data_required_file_fields')
ON CONFLICT (version) DO NOTHING;