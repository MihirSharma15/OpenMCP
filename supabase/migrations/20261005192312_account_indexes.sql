-- Cover account/credential lookups and ledger relationships highlighted by the
-- Supabase advisor. No balance or settlement semantics change.
SET LOCAL search_path TO openmcp_product, pg_catalog;
CREATE INDEX IF NOT EXISTS agents_account ON agents(account_id);
CREATE INDEX IF NOT EXISTS credentials_agent ON credentials(agent_id);
CREATE INDEX IF NOT EXISTS executions_account ON executions(account_id);
CREATE INDEX IF NOT EXISTS executions_credential ON executions(credential_id);
CREATE INDEX IF NOT EXISTS transactions_agent ON transactions(agent_id);
CREATE INDEX IF NOT EXISTS transactions_execution ON transactions(execution_id);
CREATE INDEX IF NOT EXISTS transactions_related ON transactions(related_transaction_id);
