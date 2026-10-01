"""Account store cases against PostgresAccounts. Skips when Postgres is down."""

import hashlib
import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg import sql

from openmcp.adapters.postgres.accounts import PostgresAccounts, migrate
from openmcp.domain.accounts import (
    AuthenticationFailed,
    Scope,
    create_account,
    create_agent,
    issue_credential,
    resolve_bearer,
    revoke_credential,
)

DEFAULT_DATABASE_URL = "postgresql://openmcp:openmcp@localhost:5433/openmcp"
DATABASE_URL = os.environ.get("OPENMCP_PRODUCT_DATABASE_URL") or DEFAULT_DATABASE_URL
SENSITIVE_MARKERS = ("card", "pan", "cvc", "cvv", "expiry", "last4", "stripe", "password", "secret")
EXPECTED_COLUMNS = {
    "accounts": ["account_id"],
    "agents": ["agent_id", "account_id"],
    "credentials": [
        "credential_id",
        "account_id",
        "agent_id",
        "token_hash",
        "scopes",
        "expires_at",
        "revoked",
    ],
}


def _postgres_reachable(url: str) -> bool:
    try:
        conn = psycopg.connect(url, connect_timeout=2, autocommit=True)
    except Exception:
        return False
    try:
        conn.execute("SELECT 1")
    except Exception:
        return False
    finally:
        conn.close()
    return True


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(DATABASE_URL),
    reason="Postgres is not reachable at OPENMCP_PRODUCT_DATABASE_URL or localhost:5433",
)


@pytest.fixture
def database_url() -> str:
    return DATABASE_URL


@pytest.fixture
def schema(database_url):
    name = f"accounts_{uuid.uuid4().hex}"
    try:
        migrate(database_url, schema=name)
        yield name
    finally:
        _drop_schema(database_url, name)


@pytest.fixture
def store(database_url, schema):
    return PostgresAccounts(database_url, schema=schema)


def test_secret_is_hashed_and_absent_from_the_table(store, database_url, schema):
    issued = create_account(store)
    digest = hashlib.sha256(issued.secret.encode("utf-8")).hexdigest()
    record = store.credential_by_hash(digest)
    assert record is not None
    assert record.token_hash == digest
    assert record.token_hash != issued.secret
    assert record.agent_id is None
    assert record.scopes == frozenset({Scope.OWNER_BILLING})
    rows = _rows(database_url, schema, "SELECT account_id, token_hash, revoked FROM credentials")
    assert rows == [(issued.account_id, digest, False)]
    assert issued.secret not in str(rows)


def test_revoked_credential_cannot_resolve(store):
    issued = create_account(store)
    now = datetime.now(timezone.utc)
    owner = resolve_bearer(store, issued.secret, now=now)
    agent = create_agent(store, owner)
    credential = issue_credential(
        store,
        owner,
        agent_id=agent.agent_id,
        scopes={Scope.AGENT_EXECUTE},
    )
    assert resolve_bearer(store, credential.secret, now=now).agent_id == agent.agent_id
    revoke_credential(store, owner, credential.credential_id, agent_id=agent.agent_id)
    with pytest.raises(AuthenticationFailed) as caught:
        resolve_bearer(store, credential.secret, now=now)
    assert caught.value.reason == "revoked"


def test_tables_store_hashes_and_ids_only(store, database_url, schema):
    issued = create_account(store)
    now = datetime.now(timezone.utc)
    owner = resolve_bearer(store, issued.secret, now=now)
    agent = create_agent(store, owner)
    issue_credential(store, owner, agent_id=agent.agent_id, scopes={Scope.AGENT_EXECUTE})
    conn = psycopg.connect(database_url, autocommit=True)
    try:
        found = conn.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
            """,
            (schema,),
        ).fetchall()
    finally:
        conn.close()
    by_table: dict[str, list[str]] = {}
    for table_name, column_name in found:
        by_table.setdefault(table_name, []).append(column_name)
        lowered = column_name.lower()
        assert not any(marker in lowered for marker in SENSITIVE_MARKERS)
    assert by_table == EXPECTED_COLUMNS


def _drop_schema(dsn: str, schema: str) -> None:
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
    finally:
        conn.close()


def _rows(dsn: str, schema: str, statement: str):
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        return conn.execute(statement).fetchall()
    finally:
        conn.close()
