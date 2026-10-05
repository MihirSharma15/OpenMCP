"""Database boundary tests with real transactions and restricted role permissions."""

import os
from unittest.mock import AsyncMock
from urllib.parse import quote

import psycopg
import pytest
from fastapi.testclient import TestClient

from openmcp.config import Settings
from openmcp.database import DatabaseManager, LeaseLost
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings
from openmcp.product.models import ProductError
from openmcp.product.settlement import Treasury
from openmcp.product.store import Store
from tests.test_product_postgres import postgres_url as postgres_url
from tests.test_product_postgres import store as store


def test_transaction_rolls_back_and_does_not_leak_settings(store):
    manager = store.database
    with pytest.raises(RuntimeError, match="abort"):
        with manager.transaction() as connection:
            connection.execute(
                "INSERT INTO accounts(account_id,clerk_subject) VALUES('rollback','rollback')"
            )
            raise RuntimeError("abort")
    with manager.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"] == 0
        connection.execute("SET LOCAL statement_timeout='1234ms'")
    with manager.transaction() as connection:
        assert connection.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "15s"
    with manager._pool.connection() as connection:
        assert connection.execute("SHOW search_path").fetchone()["search_path"] != manager.schema


def test_lease_cannot_survive_session_loss_or_early_unlock(store):
    with store.worker_lock() as lease:
        lease.assert_held()
        lease._connection.execute("SELECT pg_advisory_unlock_all()")
        with pytest.raises(LeaseLost):
            lease.assert_held()
        with pytest.raises(ProductError, match="worker lock was lost") as error:
            Treasury.ensure_lock(lease)
        assert error.value.code == "worker_lease_lost"
    with store.worker_lock() as lease:
        lease._connection.close()
        with pytest.raises(LeaseLost):
            lease.assert_held()
    with store.worker_lock() as replacement:
        replacement.assert_held()


def test_runtime_can_transact_but_cannot_create_or_delete_money(store, postgres_url):
    # SET ROLE during connection setup exercises the exact migration's NOLOGIN
    # role locally. Hosted acceptance uses a separate real LOGIN over Supavisor.
    separator = "&" if "?" in postgres_url else "?"
    url = os.environ.get("OPENMCP_TEST_RUNTIME_DATABASE_URL") or (
        postgres_url + separator + "options=" + quote("-c role=" + store.schema + "_runtime")
    )
    runtime = Store(DatabaseManager(url, store.schema, pool_max=1))
    try:
        runtime.database.check_schema_version()
        owner = runtime.bootstrap("restricted")
        assert runtime.account(owner["account_id"])["balance_cents"] == 0
        runtime.heartbeat()
        for statement in [
            "CREATE TABLE forbidden(id int)",
            "DELETE FROM accounts",
            "UPDATE schema_version SET version=2",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with runtime.connection() as connection:
                    connection.execute(statement)
        with psycopg.connect(postgres_url) as admin:
            for role in ["anon", "authenticated", "service_role"]:
                exists = admin.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
                ).fetchone()
                if exists:
                    assert not admin.execute(
                        "SELECT has_schema_privilege(%s,%s,'USAGE')", (role, store.schema)
                    ).fetchone()[0]
    finally:
        runtime.close()


def test_schema_check_never_creates_schema(postgres_url):
    manager = DatabaseManager(postgres_url, "account_missing_schema")
    try:
        with pytest.raises(RuntimeError, match="missing"):
            manager.check_schema_version()
        with psycopg.connect(postgres_url) as connection:
            assert (
                connection.execute("SELECT to_regnamespace('account_missing_schema')").fetchone()[0]
                is None
            )
    finally:
        manager.close()


def test_api_factory_uses_runtime_role_without_migrations_and_closes_pool(
    store, postgres_url, monkeypatch
):
    separator = "&" if "?" in postgres_url else "?"
    url = os.environ.get("OPENMCP_TEST_RUNTIME_DATABASE_URL") or (
        postgres_url + separator + "options=" + quote("-c role=" + store.schema + "_runtime")
    )
    settings = ProductSettings(
        _env_file=None,
        database_url=url,
        database_schema=store.schema,
        clerk_issuer="https://clerk.example",
        stripe_key="sk_test_fixture",
        stripe_webhook_secret="whsec_fixture",
    )

    def forbidden_migration(_):
        raise AssertionError("API startup must never apply DDL")

    monkeypatch.setattr(Store, "migrate", forbidden_migration)
    app = create_app(settings, verifier=AsyncMock(), stripe=AsyncMock())
    with TestClient(app):
        assert app.state.store.bootstrap("factory-account")["balance_cents"] == 0
    assert app.state.store.database._pool.closed


def test_product_url_does_not_configure_legacy_database(monkeypatch):
    monkeypatch.setenv("OPENMCP_PRODUCT_DATABASE_URL", "postgresql://product.invalid/db")
    monkeypatch.delenv("OPENMCP_LEGACY_DATABASE_URL", raising=False)
    assert Settings(_env_file=None).product_database_url == ""


@pytest.mark.parametrize(
    "url,provider",
    [
        ("postgresql://db:6543/db", "postgres"),
        ("postgresql://db:5432/db?sslmode=require", "supabase"),
    ],
)
def test_reject_unsafe_database_modes(url, provider):
    with pytest.raises(ValueError):
        DatabaseManager(url, provider=provider)
