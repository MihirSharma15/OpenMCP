"""Incremental PostgreSQL accounting. Every balance mutation locks its owning account.

No snapshots, public balance setters, or memory fallback. Agent usage and wallet
reservations are committed in the same transaction as the purchase record.
"""

import hashlib
import secrets
from datetime import timedelta

from psycopg import sql
from psycopg.types.json import Jsonb

from openmcp.database import DatabaseManager

from .config import Service
from .models import Principal, ProductError, fingerprint, identifier, now


class Store:
    def __init__(self, dsn, schema="openmcp_product"):
        self.database = dsn if isinstance(dsn, DatabaseManager) else DatabaseManager(dsn, schema)
        self.dsn, self.schema = self.database.dsn, self.database.schema

    def connection(self):
        return self.database.transaction()

    def migrate(self):
        # Explicit operator/test entry point only; never called by API/worker startup.
        from .migrate import migrate

        migrate(self.dsn, self.schema)

    def close(self):
        self.database.close()

    def bind_runtime(self, settings):
        with self.connection() as c:
            c.execute(
                "INSERT INTO runtime_binding(singleton,mode,chain_id,token) VALUES(1,%s,%s,%s) ON CONFLICT(singleton) DO NOTHING",
                (settings.mode, settings.chain_id, settings.token.lower()),
            )
            row = c.execute("SELECT * FROM runtime_binding WHERE singleton=1 FOR UPDATE").fetchone()
            if (row["mode"], row["chain_id"], row["token"]) != (
                settings.mode,
                settings.chain_id,
                settings.token.lower(),
            ):
                raise ValueError(
                    "This PostgreSQL schema is bound to another payment mode/network/token; use a separate schema for live funds"
                )

    def bind_treasury(self, address):
        with self.connection() as c:
            row = c.execute(
                "SELECT treasury_address FROM runtime_binding WHERE singleton=1 FOR UPDATE"
            ).fetchone()
            if not row:
                raise ValueError("Bind runtime configuration before loading a treasury")
            if row["treasury_address"] and row["treasury_address"] != address.lower():
                raise ValueError(
                    "This schema is bound to another treasury; reconcile its outstanding payments before a planned migration"
                )
            c.execute(
                "UPDATE runtime_binding SET treasury_address=%s WHERE singleton=1",
                (address.lower(),),
            )

    def sync_catalog(self, providers, *, prune=True):
        if providers is None:
            return
        with self.connection() as c:
            provider_ids = []
            endpoint_ids = []
            for provider in providers:
                provider_ids.append(provider.provider_id)
                c.execute(
                    "INSERT INTO providers(provider_id,name,description,secret_ref) "
                    "VALUES(%s,%s,%s,%s) ON CONFLICT(provider_id) DO UPDATE SET "
                    "name=EXCLUDED.name, description=EXCLUDED.description, "
                    "secret_ref=EXCLUDED.secret_ref",
                    (
                        provider.provider_id,
                        provider.name,
                        provider.description,
                        provider.secret_ref,
                    ),
                )
            for provider in providers:
                for query in provider.queries:
                    if not prune:
                        owner = c.execute(
                            "SELECT provider_id FROM queries WHERE endpoint_id=%s",
                            (query.endpoint_id,),
                        ).fetchone()
                        if owner and owner["provider_id"] != provider.provider_id:
                            raise ValueError("Another provider owns this endpoint ID")
                    endpoint_ids.append(query.endpoint_id)
                    c.execute(
                        "INSERT INTO queries(endpoint_id,provider_id,name,description,price_cents,"
                        "input_schema,output_schema,url,recipient,enabled,mode,keywords,"
                        "supports_idempotency,settlement,adapter) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(endpoint_id) DO UPDATE SET "
                        "provider_id=EXCLUDED.provider_id, name=EXCLUDED.name, "
                        "description=EXCLUDED.description, price_cents=EXCLUDED.price_cents, "
                        "input_schema=EXCLUDED.input_schema, output_schema=EXCLUDED.output_schema, "
                        "url=EXCLUDED.url, recipient=EXCLUDED.recipient, enabled=EXCLUDED.enabled, "
                        "mode=EXCLUDED.mode, keywords=EXCLUDED.keywords, "
                        "supports_idempotency=EXCLUDED.supports_idempotency, "
                        "settlement=EXCLUDED.settlement, adapter=EXCLUDED.adapter",
                        (
                            query.endpoint_id,
                            provider.provider_id,
                            query.name,
                            query.description,
                            query.price_cents,
                            Jsonb(query.input_schema),
                            Jsonb(query.output_schema),
                            query.url,
                            query.recipient,
                            query.enabled,
                            query.mode,
                            Jsonb(query.keywords),
                            query.supports_idempotency,
                            query.settlement,
                            query.adapter,
                        ),
                    )
            if prune:
                self._delete_missing(c, "queries", "endpoint_id", endpoint_ids)
                self._delete_missing(c, "providers", "provider_id", provider_ids)

    @staticmethod
    def _delete_missing(connection, table, column, keep):
        if keep:
            connection.execute(
                sql.SQL("DELETE FROM {} WHERE NOT ({} = ANY(%s))").format(
                    sql.Identifier(table), sql.Identifier(column)
                ),
                (keep,),
            )
        else:
            connection.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))

    def worker_lock(self):
        return self.database.worker_lease()

    def rate_limit(self, key, maximum):
        with self.connection() as c:
            row = c.execute(
                "INSERT INTO request_limits(key,window_at,hits) VALUES(%s,date_trunc('minute',now()),1) "
                "ON CONFLICT(key) DO UPDATE SET window_at=date_trunc('minute',now()),hits="
                "CASE WHEN request_limits.window_at=date_trunc('minute',now()) THEN request_limits.hits+1 ELSE 1 END RETURNING hits",
                (hashlib.sha256(key.encode()).hexdigest(),),
            ).fetchone()
        if row["hits"] > maximum:
            raise ProductError(
                "rate_limited", "Too many requests. Retry after one minute.", 429, True
            )

    def bootstrap(self, subject):
        with self.connection() as c:
            c.execute(
                "INSERT INTO accounts(account_id,clerk_subject) VALUES (%s,%s) "
                "ON CONFLICT (clerk_subject) DO NOTHING",
                (identifier("acct"), subject),
            )
            return c.execute("SELECT * FROM accounts WHERE clerk_subject=%s", (subject,)).fetchone()

    def account_for_subject(self, subject):
        with self.connection() as c:
            row = c.execute("SELECT * FROM accounts WHERE clerk_subject=%s", (subject,)).fetchone()
            if not row:
                raise ProductError("account_not_initialized", "Initialize your account first.", 409)
            return row

    def account(self, account_id):
        with self.connection() as c:
            return self._account(c, account_id)

    @staticmethod
    def _account(c, account_id):
        row = c.execute(
            "SELECT * FROM accounts WHERE account_id=%s FOR UPDATE", (account_id,)
        ).fetchone()
        if not row:
            raise ProductError("not_found", "Account not found.", 404)
        return row

    @staticmethod
    def _owned(c, table, column, value, account_id):
        # Identifiers are internal constants, never request parameters.
        row = c.execute(
            sql.SQL("SELECT * FROM {} WHERE {}=%s AND account_id=%s").format(
                sql.Identifier(table), sql.Identifier(column)
            ),
            (value, account_id),
        ).fetchone()
        if not row:
            raise ProductError("not_found", "Resource not found.", 404)
        return row

    def authenticate_agent(self, token):
        with self.connection() as c:
            row = c.execute(
                "SELECT c.*,a.account_id,a.expires_at AS grant_expires_at FROM credentials c "
                "JOIN agents a USING(agent_id) WHERE token_hash=%s",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
            if (
                not row
                or row["revoked"]
                or min(row["expires_at"], row["grant_expires_at"]) <= now()
            ):
                raise ProductError(
                    "unauthenticated", "Agent credential is invalid, expired, or revoked.", 401
                )
            return Principal(row["account_id"], row["agent_id"], row["credential_id"])

    @staticmethod
    def allowance(agent):
        return {
            "agent_id": agent["agent_id"],
            "spend_limit_cents": agent["spend_limit_cents"],
            "spent_cents": agent["spent_cents"],
            "reserved_cents": agent["reserved_cents"],
            "remaining_cents": agent["spend_limit_cents"]
            - agent["spent_cents"]
            - agent["reserved_cents"],
            "expires_at": agent["expires_at"],
        }

    def wallet(self, principal):
        with self.connection() as c:
            row = self._account(c, principal.account_id)
            agent = None
            if principal.agent_id:
                agent = self.allowance(
                    self._owned(c, "agents", "agent_id", principal.agent_id, principal.account_id)
                )
            return {
                "account_id": row["account_id"],
                "balance_cents": row["balance_cents"],
                "reserved_cents": row["reserved_cents"],
                "available_cents": max(0, row["balance_cents"] - row["reserved_cents"]),
                "deficit_cents": max(0, -row["balance_cents"]),
                "spent_cents": row["spent_cents"],
                "currency": "usd_credits",
                "status": row["status"],
                "agent": agent,
            }

    def create_agent(self, account_id, name, cap, expires_at):
        expiry = expires_at or now() + timedelta(days=7)
        if expiry.tzinfo is None or not now() < expiry <= now() + timedelta(days=30):
            raise ProductError(
                "invalid_expiry", "Expiry must be within the next 30 days in UTC.", 422
            )
        if not name.strip():
            raise ProductError("invalid_name", "Agent name is required.", 422)
        with self.connection() as c:
            self._account(c, account_id)
            row = c.execute(
                "INSERT INTO agents(agent_id,account_id,name,spend_limit_cents,expires_at) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING *",
                (identifier("agt"), account_id, name.strip(), cap, expiry),
            ).fetchone()
            return self._agent_public(c, row)

    def _agent_public(self, c, row):
        credentials = c.execute(
            "SELECT credential_id,created_at,expires_at,revoked FROM credentials "
            "WHERE agent_id=%s ORDER BY created_at",
            (row["agent_id"],),
        ).fetchall()
        status = "active"
        if row["expires_at"] <= now():
            status = "expired"
        elif row["spent_cents"] + row["reserved_cents"] >= row["spend_limit_cents"]:
            status = "exhausted"
        elif credentials and all(x["revoked"] for x in credentials):
            status = "revoked"
        return {
            **self.allowance(row),
            "name": row["name"],
            "status": status,
            "credentials": credentials,
        }

    def agents(self, account_id, limit=20, cursor=None):
        with self.connection() as c:
            rows = c.execute(
                "SELECT * FROM agents WHERE account_id=%s AND (%s::text IS NULL OR agent_id>%s) "
                "ORDER BY agent_id LIMIT %s",
                (account_id, cursor, cursor, limit + 1),
            ).fetchall()
            return {
                "items": [self._agent_public(c, row) for row in rows[:limit]],
                "next_cursor": rows[limit - 1]["agent_id"] if len(rows) > limit else None,
            }

    def issue(self, account_id, agent_id):
        secret = "omcp_" + secrets.token_urlsafe(32)
        with self.connection() as c:
            self._account(c, account_id)
            row = self._owned(c, "agents", "agent_id", agent_id, account_id)
            if row["expires_at"] <= now():
                raise ProductError(
                    "agent_expired", "Create a new agent; this authorization expired.", 409
                )
            count = c.execute(
                "SELECT count(*) AS n FROM credentials WHERE agent_id=%s AND NOT revoked",
                (agent_id,),
            ).fetchone()["n"]
            if count >= 5:
                raise ProductError(
                    "credential_limit", "Revoke an existing credential before issuing another.", 409
                )
            cred = identifier("cred")
            c.execute(
                "INSERT INTO credentials(credential_id,agent_id,token_hash,expires_at) VALUES (%s,%s,%s,%s)",
                (cred, agent_id, hashlib.sha256(secret.encode()).hexdigest(), row["expires_at"]),
            )
            return {
                "agent_id": agent_id,
                "credential_id": cred,
                "secret": secret,
                "expires_at": row["expires_at"],
            }

    def revoke(self, account_id, agent_id, credential_id):
        with self.connection() as c:
            self._account(c, account_id)
            self._owned(c, "agents", "agent_id", agent_id, account_id)
            row = c.execute(
                "UPDATE credentials SET revoked=true WHERE credential_id=%s AND agent_id=%s "
                "RETURNING credential_id,created_at,expires_at,revoked",
                (credential_id, agent_id),
            ).fetchone()
            if not row:
                raise ProductError("not_found", "Credential not found.", 404)
            return row

    def save_customer(self, account_id, customer_id):
        with self.connection() as c:
            row = self._account(c, account_id)
            if row["stripe_customer_id"] and row["stripe_customer_id"] != customer_id:
                raise ProductError("customer_conflict", "Stripe customer association changed.", 409)
            c.execute(
                "UPDATE accounts SET stripe_customer_id=%s WHERE account_id=%s",
                (customer_id, account_id),
            )

    def create_top_up(self, account_id, key, amount):
        digest = fingerprint({"amount_cents": amount})
        with self.connection() as c:
            self._account(c, account_id)
            row = c.execute(
                "SELECT * FROM top_ups WHERE account_id=%s AND idempotency_key=%s",
                (account_id, key),
            ).fetchone()
            if row:
                if row["fingerprint"] != digest:
                    raise ProductError(
                        "idempotency_conflict", "This key was used for a different amount.", 409
                    )
                return row
            return c.execute(
                "INSERT INTO top_ups(id,account_id,idempotency_key,fingerprint,amount_cents) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING *",
                (identifier("top"), account_id, key, digest, amount),
            ).fetchone()

    def top_up(self, account_id, top_id):
        with self.connection() as c:
            return self._owned(c, "top_ups", "id", top_id, account_id)

    @staticmethod
    def top_up_public(row):
        return {
            k: row[k]
            for k in ("id", "amount_cents", "status", "checkout_url", "expires_at", "credited_at")
        } | {"currency": "usd"}

    def top_up_internal(self, top_id):
        with self.connection() as c:
            return c.execute("SELECT * FROM top_ups WHERE id=%s", (top_id,)).fetchone()

    def checkout_state(self, top_id, session, *, paid=False):
        with self.connection() as c:
            initial = c.execute("SELECT account_id FROM top_ups WHERE id=%s", (top_id,)).fetchone()
            if not initial:
                raise ProductError("unknown_top_up", "Unknown checkout association.", 409)
            account = self._account(c, initial["account_id"])
            row = c.execute("SELECT * FROM top_ups WHERE id=%s FOR UPDATE", (top_id,)).fetchone()
            if row["checkout_id"] and row["checkout_id"] != session["id"]:
                raise ProductError("checkout_mismatch", "Checkout association does not match.", 409)
            c.execute(
                "UPDATE top_ups SET checkout_id=%s, checkout_url=COALESCE(%s,checkout_url), "
                "expires_at=to_timestamp(%s), payment_intent_id=COALESCE(%s,payment_intent_id) WHERE id=%s",
                (
                    session["id"],
                    session.get("url"),
                    session.get("expires_at"),
                    session.get("payment_intent"),
                    top_id,
                ),
            )
            if paid and not row["credited_at"]:
                txn = identifier("txn")
                balance = account["balance_cents"] + row["amount_cents"]
                c.execute(
                    "UPDATE accounts SET balance_cents=%s WHERE account_id=%s",
                    (balance, account["account_id"]),
                )
                c.execute(
                    "UPDATE top_ups SET credited_at=now(), status='credited', deposit_transaction_id=%s WHERE id=%s",
                    (txn, top_id),
                )
                self._transaction(
                    c,
                    txn,
                    account["account_id"],
                    "deposit",
                    "completed",
                    row["amount_cents"],
                    "Wallet top-up",
                    balance,
                )
                self._apply_reversal(c, top_id)
            elif not row["credited_at"]:
                status = (
                    "failed"
                    if session.get("_failed")
                    else "expired"
                    if session.get("status") == "expired"
                    else "processing"
                    if session.get("status") == "complete"
                    else "awaiting_payment"
                )
                c.execute("UPDATE top_ups SET status=%s WHERE id=%s", (status, top_id))
            return c.execute("SELECT * FROM top_ups WHERE id=%s", (top_id,)).fetchone()

    def funding_reversal(
        self,
        top_id,
        *,
        charge_id,
        refund_cents,
        disputed_cents=None,
        dispute_open=False,
        event_created=0,
    ):
        with self.connection() as c:
            initial = c.execute("SELECT account_id FROM top_ups WHERE id=%s", (top_id,)).fetchone()
            if not initial:
                raise ProductError("unknown_top_up", "Unknown payment association.", 409)
            self._account(c, initial["account_id"])
            row = c.execute("SELECT * FROM top_ups WHERE id=%s FOR UPDATE", (top_id,)).fetchone()
            if row["charge_id"] and row["charge_id"] != charge_id:
                raise ProductError("charge_mismatch", "Charge association does not match.", 409)
            c.execute(
                "UPDATE top_ups SET charge_id=%s,refund_cents=GREATEST(refund_cents,%s) WHERE id=%s",
                (charge_id, refund_cents, top_id),
            )
            if disputed_cents is not None and event_created >= row["dispute_event_at"]:
                c.execute(
                    "UPDATE top_ups SET disputed_cents=%s,dispute_open=%s,dispute_event_at=%s WHERE id=%s",
                    (disputed_cents, dispute_open, event_created, top_id),
                )
            self._apply_reversal(c, top_id)

    def _apply_reversal(self, c, top_id):
        row = c.execute("SELECT * FROM top_ups WHERE id=%s", (top_id,)).fetchone()
        if row["credited_at"]:
            desired = min(row["amount_cents"], row["refund_cents"] + row["disputed_cents"])
            delta = desired - row["reversed_cents"]
            if delta:
                account = c.execute(
                    "UPDATE accounts SET balance_cents=balance_cents-%s WHERE account_id=%s RETURNING *",
                    (delta, row["account_id"]),
                ).fetchone()
                self._transaction(
                    c,
                    identifier("txn"),
                    row["account_id"],
                    "reversal",
                    "completed",
                    -delta,
                    "Funding reversal" if delta > 0 else "Dispute resolved: funding restored",
                    account["balance_cents"],
                    related=row["deposit_transaction_id"],
                )
                c.execute("UPDATE top_ups SET reversed_cents=%s WHERE id=%s", (desired, top_id))
        c.execute(
            "UPDATE accounts SET status=CASE WHEN balance_cents<reserved_cents OR EXISTS "
            "(SELECT 1 FROM top_ups WHERE account_id=%s AND dispute_open) THEN 'restricted' ELSE 'active' END "
            "WHERE account_id=%s",
            (row["account_id"], row["account_id"]),
        )

    @staticmethod
    def _transaction(
        c,
        txn,
        account,
        kind,
        status,
        amount,
        description,
        balance,
        *,
        agent=None,
        name=None,
        endpoint=None,
        execution=None,
        related=None,
        receipt=None,
    ):
        c.execute(
            "INSERT INTO transactions(id,account_id,type,status,amount_cents,description,balance_after_cents,agent_id,agent_name,endpoint_id,execution_id,related_transaction_id,receipt_url) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                txn,
                account,
                kind,
                status,
                amount,
                description,
                balance,
                agent,
                name,
                endpoint,
                execution,
                related,
                receipt,
            ),
        )

    def reserve(self, principal, key, body, service):
        digest = fingerprint(body)
        with self.connection() as c:
            account = self._account(c, principal.account_id)
            row = c.execute(
                "SELECT * FROM executions WHERE agent_id=%s AND idempotency_key=%s",
                (principal.agent_id, key),
            ).fetchone()
            if row:
                if row["fingerprint"] != digest:
                    raise ProductError(
                        "idempotency_conflict", "This key belongs to a different purchase.", 409
                    )
                return row
            grant = self._owned(c, "agents", "agent_id", principal.agent_id, principal.account_id)
            credential = c.execute(
                "SELECT * FROM credentials WHERE credential_id=%s AND agent_id=%s FOR UPDATE",
                (principal.credential_id, principal.agent_id),
            ).fetchone()
            if (
                not credential
                or credential["revoked"]
                or min(grant["expires_at"], credential["expires_at"]) <= now()
            ):
                raise ProductError(
                    "unauthenticated", "Agent authorization expired or was revoked.", 401
                )
            if account["status"] != "active":
                raise ProductError(
                    "account_restricted",
                    "Resolve the account funding issue before purchasing.",
                    403,
                )
            if service.price_cents > body["max_price_cents"]:
                raise ProductError(
                    "price_exceeds_maximum", "Service price exceeds the approved maximum.", 409
                )
            if account["balance_cents"] - account["reserved_cents"] < service.price_cents:
                raise ProductError("insufficient_funds", "Insufficient available credits.", 402)
            if (
                grant["spend_limit_cents"] - grant["spent_cents"] - grant["reserved_cents"]
                < service.price_cents
            ):
                raise ProductError(
                    "spending_limit_exceeded", "Agent allowance is insufficient.", 403
                )
            execution, txn = identifier("exe"), identifier("txn")
            row = c.execute(
                "INSERT INTO executions(execution_id,account_id,agent_id,credential_id,endpoint_id,service,payload,idempotency_key,fingerprint,price_cents,provider_price_cents,ledger_transaction_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    execution,
                    principal.account_id,
                    principal.agent_id,
                    principal.credential_id,
                    service.endpoint_id,
                    Jsonb(service.model_dump()),
                    Jsonb(body["payload"]),
                    key,
                    digest,
                    service.price_cents,
                    service.provider_price_cents,
                    txn,
                ),
            ).fetchone()
            c.execute(
                "UPDATE accounts SET reserved_cents=reserved_cents+%s WHERE account_id=%s",
                (service.price_cents, principal.account_id),
            )
            c.execute(
                "UPDATE agents SET reserved_cents=reserved_cents+%s WHERE agent_id=%s",
                (service.price_cents, principal.agent_id),
            )
            self._transaction(
                c,
                txn,
                principal.account_id,
                "purchase",
                "pending",
                -service.price_cents,
                service.name,
                None,
                agent=principal.agent_id,
                name=grant["name"],
                endpoint=service.endpoint_id,
                execution=execution,
            )
            return row

    def execution_for_key(self, agent_id, key, body):
        with self.connection() as c:
            row = c.execute(
                "SELECT * FROM executions WHERE agent_id=%s AND idempotency_key=%s", (agent_id, key)
            ).fetchone()
            if row and row["fingerprint"] != fingerprint(body):
                raise ProductError(
                    "idempotency_conflict", "This key belongs to a different purchase.", 409
                )
            return row

    def execution(self, principal, execution_id):
        with self.connection() as c:
            row = self._owned(c, "executions", "execution_id", execution_id, principal.account_id)
            if principal.agent_id and row["agent_id"] != principal.agent_id:
                raise ProductError("not_found", "Execution not found.", 404)
            return row

    def execution_internal(self, execution_id):
        with self.connection() as c:
            return c.execute(
                "SELECT * FROM executions WHERE execution_id=%s", (execution_id,)
            ).fetchone()

    @staticmethod
    def execution_public(row):
        fields = (
            "execution_id",
            "endpoint_id",
            "status",
            "price_cents",
            "charged_cents",
            "refunded_cents",
            "data",
            "provider_receipt",
            "ledger_transaction_id",
            "error",
            "created_at",
        )
        return {k: row[k] for k in fields} | {
            "currency": "usd_credits",
            "status_url": f"/v1/executions/{row['execution_id']}",
        }

    def pending_executions(self, limit=10):
        with self.connection() as c:
            return c.execute(
                "SELECT * FROM executions WHERE status IN ('reserved','payment_pending','fulfillment_pending') AND next_attempt_at<=now() ORDER BY created_at LIMIT %s",
                (limit,),
            ).fetchall()

    def uncertain_signed(self, excluding):
        with self.connection() as c:
            return c.execute(
                "SELECT execution_id FROM executions WHERE execution_id<>%s AND payment_authorization IS NOT NULL AND payment_status='signed' LIMIT 1",
                (excluding,),
            ).fetchone()

    def mark_sent(self, execution_id):
        """Journal an API-key call before the POST. A second update does not match."""
        with self.connection() as c:
            row = c.execute(
                "UPDATE executions SET payment_status='sent',status='payment_pending',updated_at=now() "
                "WHERE execution_id=%s AND payment_status='unsigned' AND status='reserved' "
                "RETURNING execution_id",
                (execution_id,),
            ).fetchone()
            if not row:
                raise ProductError(
                    "payment_journal_conflict", "Payment was already journaled.", 409
                )

    def mark_signed(self, execution_id, authorization, challenge, header_name, payment_hash):
        with self.connection() as c:
            row = c.execute(
                "UPDATE executions SET payment_authorization=%s,challenge=%s,header_name=%s,payment_hash=%s,payment_status='signed',status='payment_pending',updated_at=now() "
                "WHERE execution_id=%s AND payment_authorization IS NULL AND status='reserved' RETURNING execution_id",
                (authorization, challenge, header_name, payment_hash, execution_id),
            ).fetchone()
            if not row:
                raise ProductError(
                    "payment_journal_conflict", "Payment was already journaled.", 409
                )

    def mark_paid(self, execution_id, receipt, *, data=None, cost_microusd=None):
        if cost_microusd is not None and (type(cost_microusd) is not int or cost_microusd < 0):
            raise ValueError("Provider cost must be nonnegative integer micro-USD")
        with self.connection() as c:
            c.execute(
                "UPDATE executions SET payment_status='confirmed',provider_receipt=%s,"
                "provider_cost_microusd=COALESCE(%s,provider_price_cents*10000),"
                "provider_cost_cents=CASE WHEN %s::bigint IS NULL THEN provider_price_cents "
                "ELSE ceil(%s::numeric/10000)::bigint END,"
                "data=COALESCE(%s,data),status='fulfillment_pending',updated_at=now() "
                "WHERE execution_id=%s AND status IN ('reserved','payment_pending','fulfillment_pending','needs_review')",
                (
                    Jsonb(receipt),
                    cost_microusd,
                    cost_microusd,
                    cost_microusd,
                    None if data is None else Jsonb(data),
                    execution_id,
                ),
            )

    def finish(self, execution_id, *, data=None, refund_reason=None, payment_reverted=False):
        with self.connection() as c:
            initial = c.execute(
                "SELECT account_id FROM executions WHERE execution_id=%s", (execution_id,)
            ).fetchone()
            self._account(c, initial["account_id"])
            row = c.execute(
                "SELECT * FROM executions WHERE execution_id=%s FOR UPDATE", (execution_id,)
            ).fetchone()
            if row["status"] in ("completed", "refunded"):
                return row
            if refund_reason is None and row["payment_status"] != "confirmed":
                raise ProductError(
                    "payment_unconfirmed", "Cannot complete an unconfirmed payment.", 409
                )
            if refund_reason and row["payment_status"] == "signed" and not payment_reverted:
                raise ProductError(
                    "payment_ambiguous", "Reconcile the signed payment before refunding.", 409
                )
            charge = 0 if refund_reason else row["price_cents"]
            account = c.execute(
                "UPDATE accounts SET reserved_cents=reserved_cents-%s,balance_cents=balance_cents-%s,spent_cents=spent_cents+%s WHERE account_id=%s RETURNING *",
                (row["price_cents"], charge, charge, row["account_id"]),
            ).fetchone()
            c.execute(
                "UPDATE agents SET reserved_cents=reserved_cents-%s,spent_cents=spent_cents+%s WHERE agent_id=%s",
                (row["price_cents"], charge, row["agent_id"]),
            )
            status = "refunded" if refund_reason else "completed"
            receipt_url = (row["provider_receipt"] or {}).get("explorer_url")
            error = (
                {"code": "purchase_failed", "message": refund_reason, "retryable": False}
                if refund_reason
                else None
            )
            c.execute(
                "UPDATE executions SET status=%s,fulfillment_status=%s,charged_cents=%s,refunded_cents=%s,data=%s,error=%s,updated_at=now(),payment_status=CASE WHEN %s THEN 'reverted' ELSE payment_status END WHERE execution_id=%s",
                (
                    status,
                    "failed" if refund_reason else "completed",
                    charge,
                    row["price_cents"] if refund_reason else 0,
                    Jsonb(data),
                    Jsonb(error),
                    payment_reverted,
                    execution_id,
                ),
            )
            c.execute(
                "UPDATE transactions SET status=%s,balance_after_cents=%s,receipt_url=%s WHERE id=%s",
                (status, account["balance_cents"], receipt_url, row["ledger_transaction_id"]),
            )
            if refund_reason:
                agent = c.execute(
                    "SELECT name FROM agents WHERE agent_id=%s", (row["agent_id"],)
                ).fetchone()
                self._transaction(
                    c,
                    identifier("txn"),
                    row["account_id"],
                    "refund",
                    "completed",
                    row["price_cents"],
                    "Service failure: credits returned",
                    account["balance_cents"],
                    agent=row["agent_id"],
                    name=agent["name"],
                    endpoint=row["endpoint_id"],
                    execution=execution_id,
                    related=row["ledger_transaction_id"],
                )
            # Funding restriction may have been caused by reservations exceeding balance.
            c.execute(
                "UPDATE accounts SET status=CASE WHEN balance_cents<reserved_cents OR EXISTS "
                "(SELECT 1 FROM top_ups WHERE account_id=%s AND dispute_open) THEN 'restricted' ELSE 'active' END WHERE account_id=%s",
                (row["account_id"], row["account_id"]),
            )
            return c.execute(
                "SELECT * FROM executions WHERE execution_id=%s", (execution_id,)
            ).fetchone()

    def retry_execution(self, execution_id, reason, delay, max_attempts):
        with self.connection() as c:
            row = c.execute(
                "UPDATE executions SET attempts=attempts+1,next_attempt_at=now()+(%s * interval '1 second'),error=%s,updated_at=now() WHERE execution_id=%s AND status IN ('reserved','payment_pending','fulfillment_pending') RETURNING *",
                (
                    delay,
                    Jsonb({"code": "payment_pending", "message": reason, "retryable": True}),
                    execution_id,
                ),
            ).fetchone()
            if row and row["attempts"] >= max_attempts:
                self._needs_review(c, execution_id, reason)

    @staticmethod
    def _needs_review(c, execution_id, reason):
        c.execute(
            "UPDATE executions SET status='needs_review',error=%s,updated_at=now() WHERE execution_id=%s AND status NOT IN ('completed','refunded')",
            (Jsonb({"code": "needs_review", "message": reason, "retryable": False}), execution_id),
        )
        c.execute(
            "UPDATE transactions SET status='needs_review' WHERE execution_id=%s AND type='purchase' AND status NOT IN ('completed','refunded')",
            (execution_id,),
        )

    def needs_review(self, execution_id, reason):
        with self.connection() as c:
            self._needs_review(c, execution_id, reason)

    def requeue(self, execution_id):
        with self.connection() as c:
            row = c.execute(
                "UPDATE executions SET status=CASE WHEN payment_status='confirmed' THEN 'fulfillment_pending' WHEN payment_authorization IS NOT NULL THEN 'payment_pending' ELSE 'reserved' END,attempts=0,next_attempt_at=now(),error=NULL WHERE execution_id=%s AND status='needs_review' RETURNING *",
                (execution_id,),
            ).fetchone()
            if not row:
                raise ProductError(
                    "not_reviewable", "Only an execution needing review can be requeued.", 409
                )
            c.execute(
                "UPDATE transactions SET status='pending' WHERE execution_id=%s AND type='purchase' AND status NOT IN ('completed','refunded')",
                (execution_id,),
            )
            return row

    @staticmethod
    def transaction_public(row):
        return {k: v for k, v in row.items() if k not in {"seq", "account_id"}} | {
            "currency": "usd_credits"
        }

    def transactions(self, account_id, limit, cursor, kind, status):
        try:
            position = int(cursor) if cursor else 9223372036854775807
        except (ValueError, TypeError) as exc:
            raise ProductError("invalid_cursor", "Invalid transaction cursor.", 422) from exc
        if not 0 <= position <= 9223372036854775807:
            raise ProductError("invalid_cursor", "Invalid transaction cursor.", 422)
        with self.connection() as c:
            rows = c.execute(
                "SELECT * FROM transactions WHERE account_id=%s AND seq<%s AND (%s::text IS NULL OR type=%s) AND (%s::text IS NULL OR status=%s) ORDER BY seq DESC LIMIT %s",
                (account_id, position, kind, kind, status, status, limit + 1),
            ).fetchall()
            return {
                "items": [self.transaction_public(row) for row in rows[:limit]],
                "next_cursor": str(rows[limit - 1]["seq"]) if len(rows) > limit else None,
            }

    def transaction(self, account_id, txn_id):
        with self.connection() as c:
            return self.transaction_public(self._owned(c, "transactions", "id", txn_id, account_id))

    def accept_event(self, event):
        with self.connection() as c:
            c.execute(
                "INSERT INTO stripe_events(id,type,object_id,event_created) VALUES (%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (event["id"], event["type"], event["data"]["object"]["id"], event["created"]),
            )

    def pending_events(self):
        with self.connection() as c:
            return c.execute(
                "SELECT * FROM stripe_events WHERE status='pending' AND next_attempt_at<=now() ORDER BY created_at LIMIT 50"
            ).fetchall()

    def event_done(self, event_id):
        with self.connection() as c:
            c.execute(
                "UPDATE stripe_events SET status='processed',last_error=NULL WHERE id=%s",
                (event_id,),
            )

    def event_retry(self, event_id, code, delay):
        with self.connection() as c:
            c.execute(
                "UPDATE stripe_events SET attempts=attempts+1,last_error=%s,next_attempt_at=now()+(%s*interval '1 second') WHERE id=%s",
                (code, delay, event_id),
            )

    def heartbeat(self):
        with self.connection() as c:
            c.execute("DELETE FROM request_limits WHERE window_at<now()-interval '2 minutes'")
            c.execute(
                "INSERT INTO worker_health(singleton,heartbeat_at) VALUES(1,now()) ON CONFLICT(singleton) DO UPDATE SET heartbeat_at=now()"
            )

    def review(self):
        with self.connection() as c:
            executions = c.execute(
                "SELECT execution_id,status,payment_status,attempts,error,updated_at FROM executions "
                "WHERE status IN ('needs_review','payment_pending','fulfillment_pending') ORDER BY created_at LIMIT 100"
            ).fetchall()
            events = c.execute(
                "SELECT id,type,attempts,last_error,created_at FROM stripe_events "
                "WHERE status='pending' ORDER BY created_at LIMIT 100"
            ).fetchall()
            return {"executions": executions, "stripe_events": events}

    def health(self):
        with self.connection() as c:
            alive = c.execute(
                "SELECT heartbeat_at > now()-interval '120 seconds' AS alive FROM worker_health WHERE singleton=1"
            ).fetchone()
            review = c.execute(
                "SELECT count(*) AS n FROM executions WHERE status='needs_review'"
            ).fetchone()["n"]
            events = c.execute(
                "SELECT count(*) AS n,count(*) FILTER (WHERE attempts>0) AS errors FROM stripe_events WHERE status='pending'"
            ).fetchone()
            return {
                "database": True,
                "stripe_pending": events["n"],
                "stripe_retries": events["errors"],
                "worker": bool(alive and alive["alive"]),
                "needs_review": review,
            }

    def service_count(self, mode):
        with self.connection() as c:
            return c.execute(
                "SELECT count(*) AS n FROM queries WHERE enabled AND mode=%s", (mode,)
            ).fetchone()["n"]

    def requires_treasury(self, mode):
        """Keep recovery enabled even after an MPP provider leaves the catalog."""
        with self.connection() as c:
            return c.execute(
                "SELECT EXISTS(SELECT 1 FROM queries WHERE enabled AND mode=%s "
                "AND settlement='mpp') OR EXISTS(SELECT 1 FROM executions "
                "WHERE status NOT IN ('completed','refunded','failed') "
                "AND COALESCE(service->>'settlement','mpp')='mpp') AS required",
                (mode,),
            ).fetchone()["required"]

    def enabled_queries(self, mode):
        with self.connection() as c:
            rows = c.execute(
                "SELECT q.endpoint_id, q.name, q.description, q.price_cents, q.input_schema, "
                "q.output_schema, q.url, q.recipient, q.enabled, q.mode, q.keywords, "
                "q.supports_idempotency, q.settlement, q.adapter, q.provider_id, p.name AS provider_name, "
                "p.description AS provider_description "
                "FROM queries q JOIN providers p ON p.provider_id=q.provider_id "
                "WHERE q.enabled AND q.mode=%s",
                (mode,),
            ).fetchall()
        return [
            {
                "provider_id": row["provider_id"],
                "provider_name": row["provider_name"],
                "provider_description": row["provider_description"],
                "service": self._as_service(row),
            }
            for row in rows
        ]

    def service(self, endpoint_id, mode):
        with self.connection() as c:
            row = c.execute(
                "SELECT * FROM queries WHERE endpoint_id=%s AND enabled AND mode=%s",
                (endpoint_id, mode),
            ).fetchone()
        return None if row is None else self._as_service(row)

    def catalog_service(self, endpoint_id):
        with self.connection() as c:
            row = c.execute("SELECT * FROM queries WHERE endpoint_id=%s", (endpoint_id,)).fetchone()
        return None if row is None else self._as_service(row)

    @staticmethod
    def _as_service(row):
        return Service.model_validate(
            {
                "endpoint_id": row["endpoint_id"],
                "name": row["name"],
                "description": row["description"],
                "keywords": row["keywords"],
                "url": row["url"],
                "recipient": row["recipient"],
                "price_cents": row["price_cents"],
                "input_schema": row["input_schema"],
                "output_schema": row["output_schema"],
                "enabled": row["enabled"],
                "mode": row["mode"],
                "supports_idempotency": row["supports_idempotency"],
                "settlement": row["settlement"],
                "adapter": row["adapter"],
            }
        )

    def provider_secret_ref(self, endpoint_id):
        """Environment variable name for an API-key query. Never the key itself."""
        with self.connection() as c:
            row = c.execute(
                "SELECT p.secret_ref FROM queries q "
                "JOIN providers p ON p.provider_id=q.provider_id WHERE q.endpoint_id=%s",
                (endpoint_id,),
            ).fetchone()
        if not row or not row["secret_ref"]:
            return None
        return row["secret_ref"]

    def disabled_endpoints(self):
        with self.connection() as c:
            return {
                row["endpoint_id"]
                for row in c.execute("SELECT endpoint_id FROM disabled_services").fetchall()
            }

    def disable_service(self, endpoint_id, reason):
        with self.connection() as c:
            c.execute(
                "INSERT INTO disabled_services(endpoint_id,reason) VALUES(%s,%s) "
                "ON CONFLICT(endpoint_id) DO UPDATE SET reason=EXCLUDED.reason,disabled_at=now()",
                (endpoint_id, reason),
            )

    def service_disabled(self, endpoint_id):
        with self.connection() as c:
            return (
                c.execute(
                    "SELECT 1 FROM disabled_services WHERE endpoint_id=%s", (endpoint_id,)
                ).fetchone()
                is not None
            )

    def enable_service(self, endpoint_id):
        with self.connection() as c:
            row = c.execute(
                "DELETE FROM disabled_services WHERE endpoint_id=%s RETURNING endpoint_id",
                (endpoint_id,),
            ).fetchone()
        if row is None:
            raise ProductError("not_disabled", "That service is not disabled.", 404)
