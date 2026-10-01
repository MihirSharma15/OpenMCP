-- OpenMCP accounts, agents, and credentials.
-- token_hash is a sha256 hex digest. The raw secret is never stored.
-- No card numbers, PANs, or processor secrets.

CREATE TABLE IF NOT EXISTS accounts (
    account_id text PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id text PRIMARY KEY,
    account_id text NOT NULL REFERENCES accounts (account_id)
);

CREATE TABLE IF NOT EXISTS credentials (
    credential_id text PRIMARY KEY,
    account_id text NOT NULL REFERENCES accounts (account_id),
    agent_id text REFERENCES agents (agent_id),
    token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    scopes text[] NOT NULL CHECK (cardinality(scopes) > 0),
    expires_at timestamptz,
    revoked boolean NOT NULL DEFAULT false,
    CHECK (
        (
            agent_id IS NULL
            AND scopes <@ ARRAY['owner:billing']::text[]
        )
        OR (
            agent_id IS NOT NULL
            AND scopes <@ ARRAY['agent:execute']::text[]
        )
    )
);
