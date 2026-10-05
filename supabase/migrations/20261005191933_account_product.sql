-- Account schema only. Clerk remains the identity provider; browsers have no SQL access.
CREATE SCHEMA IF NOT EXISTS openmcp_product;
SET LOCAL search_path TO openmcp_product, pg_catalog;
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'openmcp_product_runtime') THEN
        CREATE ROLE openmcp_product_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;
CREATE TABLE IF NOT EXISTS accounts (
    account_id text PRIMARY KEY, clerk_subject text NOT NULL UNIQUE, stripe_customer_id text UNIQUE,
    status text NOT NULL DEFAULT 'active', balance_cents bigint NOT NULL DEFAULT 0,
    reserved_cents bigint NOT NULL DEFAULT 0 CHECK (reserved_cents >= 0),
    spent_cents bigint NOT NULL DEFAULT 0 CHECK (spent_cents >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS agents (
    agent_id text PRIMARY KEY, account_id text NOT NULL REFERENCES accounts,
    name text NOT NULL, spend_limit_cents bigint NOT NULL CHECK (spend_limit_cents > 0),
    spent_cents bigint NOT NULL DEFAULT 0 CHECK (spent_cents >= 0),
    reserved_cents bigint NOT NULL DEFAULT 0 CHECK (reserved_cents >= 0),
    expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (spent_cents + reserved_cents <= spend_limit_cents)
);
CREATE TABLE IF NOT EXISTS credentials (
    credential_id text PRIMARY KEY, agent_id text NOT NULL REFERENCES agents,
    token_hash text NOT NULL UNIQUE, revoked boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS top_ups (
    id text PRIMARY KEY, account_id text NOT NULL REFERENCES accounts,
    idempotency_key text NOT NULL, fingerprint text NOT NULL,
    amount_cents bigint NOT NULL CHECK (amount_cents > 0), status text NOT NULL DEFAULT 'creating',
    checkout_id text UNIQUE, checkout_url text, payment_intent_id text UNIQUE, charge_id text UNIQUE,
    expires_at timestamptz, credited_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
    refund_cents bigint NOT NULL DEFAULT 0, disputed_cents bigint NOT NULL DEFAULT 0,
    reversed_cents bigint NOT NULL DEFAULT 0, dispute_open boolean NOT NULL DEFAULT false, dispute_event_at bigint NOT NULL DEFAULT 0,
    deposit_transaction_id text, UNIQUE (account_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS executions (
    execution_id text PRIMARY KEY, account_id text NOT NULL REFERENCES accounts,
    agent_id text NOT NULL REFERENCES agents, credential_id text NOT NULL REFERENCES credentials,
    endpoint_id text NOT NULL, service jsonb NOT NULL, payload jsonb NOT NULL,
    idempotency_key text NOT NULL, fingerprint text NOT NULL, price_cents bigint NOT NULL,
    provider_price_cents bigint NOT NULL, status text NOT NULL DEFAULT 'reserved',
    payment_status text NOT NULL DEFAULT 'unsigned', fulfillment_status text NOT NULL DEFAULT 'pending',
    charged_cents bigint NOT NULL DEFAULT 0, refunded_cents bigint NOT NULL DEFAULT 0,
    provider_cost_cents bigint NOT NULL DEFAULT 0, payment_authorization text, challenge text,
    header_name text, payment_hash text, provider_receipt jsonb, data jsonb, error jsonb,
    ledger_transaction_id text NOT NULL, attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE (agent_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS executions_pending ON executions(next_attempt_at)
    WHERE status IN ('reserved', 'payment_pending', 'fulfillment_pending');
CREATE TABLE IF NOT EXISTS transactions (
    seq bigserial UNIQUE, id text PRIMARY KEY, account_id text NOT NULL REFERENCES accounts,
    type text NOT NULL, status text NOT NULL, amount_cents bigint NOT NULL,
    description text NOT NULL, balance_after_cents bigint, agent_id text REFERENCES agents,
    agent_name text, endpoint_id text, execution_id text REFERENCES executions,
    related_transaction_id text REFERENCES transactions, receipt_url text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS transactions_account ON transactions(account_id, seq DESC);
CREATE TABLE IF NOT EXISTS stripe_events (
    id text PRIMARY KEY, type text NOT NULL, object_id text NOT NULL, event_created bigint NOT NULL,
    status text NOT NULL DEFAULT 'pending', attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(), last_error text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS worker_health (
    singleton integer PRIMARY KEY CHECK (singleton = 1), heartbeat_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS request_limits (
    key text PRIMARY KEY, window_at timestamptz NOT NULL, hits integer NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_binding (
    singleton integer PRIMARY KEY CHECK(singleton=1), mode text NOT NULL,
    chain_id bigint NOT NULL, token text NOT NULL, treasury_address text
);

CREATE TABLE IF NOT EXISTS schema_version (
    singleton integer PRIMARY KEY CHECK(singleton=1), version integer NOT NULL
);
INSERT INTO schema_version VALUES(1,1) ON CONFLICT(singleton) DO NOTHING;

-- Each environment has its own NOLOGIN privilege role. Deployment provisions
-- a separate LOGIN member with a generated password outside migration history.
REVOKE ALL ON SCHEMA openmcp_product FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA openmcp_product FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA openmcp_product FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA openmcp_product REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA openmcp_product REVOKE ALL ON SEQUENCES FROM PUBLIC;
GRANT USAGE ON SCHEMA openmcp_product TO openmcp_product_runtime;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA openmcp_product TO openmcp_product_runtime;
GRANT DELETE ON request_limits TO openmcp_product_runtime;
REVOKE INSERT, UPDATE ON schema_version FROM openmcp_product_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA openmcp_product TO openmcp_product_runtime;
DO $$
DECLARE r text; t text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA openmcp_product FROM %I',r);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA openmcp_product FROM %I',r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA openmcp_product FROM %I',r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA openmcp_product REVOKE ALL ON TABLES FROM %I',r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA openmcp_product REVOKE ALL ON SEQUENCES FROM %I',r);
        END IF;
    END LOOP;
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='openmcp_product' LOOP
        EXECUTE format('ALTER TABLE openmcp_product.%I ENABLE ROW LEVEL SECURITY',t);
        IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='openmcp_product'
                      AND tablename=t AND policyname='backend_access') THEN
            EXECUTE format('CREATE POLICY backend_access ON openmcp_product.%I TO openmcp_product_runtime USING(true) WITH CHECK(true)',t);
        END IF;
    END LOOP;
END $$;
