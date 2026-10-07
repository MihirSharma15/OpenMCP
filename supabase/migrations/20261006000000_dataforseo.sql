-- DataForSEO protocol selection and exact, fractional-cent vendor costs.
SET LOCAL search_path TO openmcp_product, pg_catalog;
ALTER TABLE queries ADD COLUMN IF NOT EXISTS adapter text NOT NULL DEFAULT 'http';
ALTER TABLE queries DROP CONSTRAINT IF EXISTS queries_adapter_check;
ALTER TABLE queries ADD CONSTRAINT queries_adapter_check
    CHECK (adapter IN ('http', 'dataforseo'));
ALTER TABLE executions ADD COLUMN IF NOT EXISTS provider_cost_microusd bigint;
ALTER TABLE executions DROP CONSTRAINT IF EXISTS executions_provider_cost_microusd_check;
ALTER TABLE executions ADD CONSTRAINT executions_provider_cost_microusd_check
    CHECK (provider_cost_microusd >= 0);
UPDATE executions SET provider_cost_microusd = provider_cost_cents * 10000
    WHERE provider_cost_microusd IS NULL AND payment_status = 'confirmed';
-- These additions preserve the existing v1 schema contract so the migration can
-- run before rolling out the API and worker. New code checks the required columns.
