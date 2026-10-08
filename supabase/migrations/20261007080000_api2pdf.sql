-- Add API2PDF without editing previously deployed migrations.
SET LOCAL search_path TO openmcp_product, pg_catalog;
ALTER TABLE queries DROP CONSTRAINT IF EXISTS queries_adapter_check;
ALTER TABLE queries ADD CONSTRAINT queries_adapter_check
    CHECK (adapter IN ('http', 'dataforseo', 'tavily', 'firecrawl', 'exa', 'openweather', 'companies_house', 'deepgram', 'builtwith', 'nansen', 'api2pdf'));
