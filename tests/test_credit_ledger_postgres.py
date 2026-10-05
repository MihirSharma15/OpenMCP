"""Credit ledger cases against PostgresLedger. Skips when Postgres is down."""

import os
import threading
import time
import uuid

import psycopg
import pytest
from psycopg import sql

from openmcp.adapters.postgres import PostgresLedger, migrate
from openmcp.domain import credits
from openmcp.domain.credits import (
    ChargeStatus,
    DebitOutcome,
    DepositOutcome,
    debit_for_query,
    post_deposit,
)

ACCOUNT = "acct-1"
DEFAULT_DATABASE_URL = "postgresql://openmcp:openmcp@localhost:5433/openmcp"
DATABASE_URL = os.environ.get("OPENMCP_LEGACY_DATABASE_URL") or DEFAULT_DATABASE_URL
CARD_MARKERS = ("card", "pan", "cvc", "cvv", "expiry", "last4", "stripe", "secret", "password")
EXPECTED_COLUMNS = {
    "credit_accounts": ["account_id", "balance_cents"],
    "credit_deposits": ["charge_id", "account_id", "amount_cents"],
    "credit_debits": [
        "account_id",
        "idempotency_key",
        "price_cents",
        "balance_after_cents",
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
    reason="Postgres is not reachable at OPENMCP_LEGACY_DATABASE_URL or localhost:5433",
)


@pytest.fixture
def database_url() -> str:
    return DATABASE_URL


@pytest.fixture
def schema(database_url):
    name = f"ledger_{uuid.uuid4().hex}"
    try:
        migrate(database_url, schema=name)
        yield name
    finally:
        _drop_schema(database_url, name)


@pytest.fixture
def ledger(database_url, schema):
    return PostgresLedger(database_url, schema=schema)


def test_confirmed_deposit_sets_balance_to_1000(ledger):
    result = post_deposit(ledger, ACCOUNT, 1000, "ch_1000", status=ChargeStatus.CONFIRMED)
    assert result.outcome is DepositOutcome.POSTED
    assert result.amount_cents == 1000
    assert result.balance_cents == 1000
    assert ledger.balance_cents(ACCOUNT) == 1000


@pytest.mark.parametrize(
    "status",
    [ChargeStatus.PENDING, ChargeStatus.FAILED, ChargeStatus.UNKNOWN],
)
def test_unconfirmed_deposit_leaves_balance_at_zero(ledger, status):
    first = post_deposit(ledger, ACCOUNT, 1000, "ch_open", status=status)
    second = post_deposit(ledger, ACCOUNT, 1000, "ch_open", status=status)
    assert first.outcome is DepositOutcome.IGNORED
    assert second.outcome is DepositOutcome.IGNORED
    assert first.balance_cents == 0
    assert ledger.balance_cents(ACCOUNT) == 0


def test_replaying_confirmed_charge_does_not_double_credit(ledger, database_url, schema):
    first = post_deposit(ledger, ACCOUNT, 1000, "ch_once", status=ChargeStatus.CONFIRMED)
    replay = post_deposit(ledger, ACCOUNT, 1000, "ch_once", status=ChargeStatus.CONFIRMED)
    other_amount = post_deposit(ledger, ACCOUNT, 500, "ch_once", status=ChargeStatus.CONFIRMED)
    assert first.outcome is DepositOutcome.POSTED
    assert replay.outcome is DepositOutcome.REPLAYED
    assert replay.amount_cents == 1000
    assert other_amount.outcome is DepositOutcome.REPLAYED
    assert other_amount.amount_cents == 1000
    assert ledger.balance_cents(ACCOUNT) == 1000
    deposits = _rows(
        database_url,
        schema,
        "SELECT charge_id, account_id, amount_cents FROM credit_deposits",
    )
    assert deposits == [("ch_once", ACCOUNT, 1000)]


def test_debit_of_40_cents_from_1000_leaves_960(ledger):
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    result = debit_for_query(ledger, ACCOUNT, 40, "query-40")
    assert result.outcome is DebitOutcome.DEBITED
    assert result.price_cents == 40
    assert result.balance_cents == 960
    assert ledger.balance_cents(ACCOUNT) == 960


def test_debit_larger_than_balance_is_insufficient_credits(ledger):
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    result = debit_for_query(ledger, ACCOUNT, 1001, "query-over")
    assert result.outcome == "insufficient_credits"
    assert result.outcome is DebitOutcome.INSUFFICIENT_CREDITS
    assert result.balance_cents == 1000
    assert ledger.balance_cents(ACCOUNT) == 1000


def test_replaying_debit_idempotency_key_does_not_subtract_twice(ledger, database_url, schema):
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    first = debit_for_query(ledger, ACCOUNT, 40, "query-40")
    replay = debit_for_query(ledger, ACCOUNT, 40, "query-40")
    different_price = debit_for_query(ledger, ACCOUNT, 25, "query-40")
    assert first.outcome is DebitOutcome.DEBITED
    assert first.balance_cents == 960
    assert replay.outcome is DebitOutcome.REPLAYED
    assert replay.price_cents == 40
    assert replay.balance_cents == 960
    assert different_price.outcome is DebitOutcome.REPLAYED
    assert different_price.price_cents == 40
    assert ledger.balance_cents(ACCOUNT) == 960
    debits = _rows(
        database_url,
        schema,
        """
        SELECT account_id, idempotency_key, price_cents, balance_after_cents
        FROM credit_debits
        """,
    )
    assert debits == [(ACCOUNT, "query-40", 40, 960)]


def test_two_concurrent_connections_cannot_overdraw(monkeypatch, database_url, schema):
    _slow(monkeypatch, "_decide_debit")
    left = PostgresLedger(database_url, schema=schema)
    right = PostgresLedger(database_url, schema=schema)
    post_deposit(left, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    results = _run_together(
        lambda: debit_for_query(left, ACCOUNT, 1000, "query-a"),
        lambda: debit_for_query(right, ACCOUNT, 1000, "query-b"),
    )
    debited = [result for result in results if result.outcome is DebitOutcome.DEBITED]
    refused = [result for result in results if result.outcome is DebitOutcome.INSUFFICIENT_CREDITS]
    assert len(debited) == 1
    assert len(refused) == 1
    assert left.balance_cents(ACCOUNT) == 0
    assert right.balance_cents(ACCOUNT) == 0


def test_tables_store_only_ids_and_cent_amounts(ledger, database_url, schema):
    post_deposit(ledger, ACCOUNT, 1000, "ch_fund", status=ChargeStatus.CONFIRMED)
    debit_for_query(ledger, ACCOUNT, 40, "query-40")
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
        by_table: dict[str, list[str]] = {}
        for table_name, column_name in found:
            by_table.setdefault(table_name, []).append(column_name)
        assert set(by_table) == set(EXPECTED_COLUMNS)
        for table_name, columns in EXPECTED_COLUMNS.items():
            assert by_table[table_name] == columns
            for column_name in columns:
                lowered = column_name.lower()
                assert column_name.endswith(("_id", "_key", "_cents"))
                assert not any(marker in lowered for marker in CARD_MARKERS)
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        accounts = conn.execute("SELECT * FROM credit_accounts").fetchall()
        deposits = conn.execute("SELECT * FROM credit_deposits").fetchall()
        debits = conn.execute("SELECT * FROM credit_debits").fetchall()
    finally:
        conn.close()
    assert accounts == [(ACCOUNT, 960)]
    assert deposits == [("ch_fund", ACCOUNT, 1000)]
    assert debits == [(ACCOUNT, "query-40", 40, 960)]


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


def _slow(monkeypatch, name):
    original = getattr(credits, name)

    def slowed(*args, **kwargs):
        time.sleep(0.03)
        return original(*args, **kwargs)

    monkeypatch.setattr(credits, name, slowed)


def _run_together(*calls):
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)
    errors = []

    def run(index, call):
        try:
            barrier.wait(timeout=2)
            results[index] = call()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(index, call)) for index, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert errors == []
    return results
