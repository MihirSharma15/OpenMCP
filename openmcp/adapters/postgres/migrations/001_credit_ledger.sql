-- OpenMCP credit ledger. Amounts are integer cents.
-- No card numbers, processor secrets, or display fields.

CREATE TABLE IF NOT EXISTS credit_accounts (
    account_id text PRIMARY KEY,
    balance_cents bigint NOT NULL CHECK (balance_cents >= 0)
);

CREATE TABLE IF NOT EXISTS credit_deposits (
    charge_id text PRIMARY KEY,
    account_id text NOT NULL,
    amount_cents bigint NOT NULL CHECK (amount_cents > 0)
);

CREATE TABLE IF NOT EXISTS credit_debits (
    account_id text NOT NULL,
    idempotency_key text NOT NULL,
    price_cents bigint NOT NULL CHECK (price_cents > 0),
    balance_after_cents bigint NOT NULL CHECK (balance_after_cents >= 0),
    PRIMARY KEY (account_id, idempotency_key)
);
