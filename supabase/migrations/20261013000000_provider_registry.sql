-- Adapters are validated by the application registry. Adding a provider is not DDL.
SET LOCAL search_path TO openmcp_product, pg_catalog;
ALTER TABLE queries DROP CONSTRAINT IF EXISTS queries_adapter_check;
ALTER TABLE queries ADD CONSTRAINT queries_adapter_check
    CHECK (adapter ~ '^[a-z][a-z0-9_]{0,63}$');
-- An ordinary HTTP/Creator call may not report upstream cost. Do not invent an MPP split.
ALTER TABLE executions ALTER COLUMN provider_cost_cents DROP NOT NULL;
UPDATE schema_version SET version=2 WHERE singleton=1;
