"""PostgreSQL credit ledger. One transaction and advisory lock per decision."""

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeVar

import psycopg
from psycopg import sql

from openmcp.ports.ledger import LedgerState, PostedDebit, PostedDeposit

T = TypeVar("T")

_MIGRATION_PATH = Path(__file__).parent / "migrations" / "001_credit_ledger.sql"
_SCHEMA_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def migrate(dsn: str, *, schema: str = "public") -> None:
    """Create the credit ledger tables in ``schema`` if they are not there yet."""

    schema = _validate_schema(schema)
    conn = psycopg.connect(dsn)
    try:
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        for statement in _statements(_MIGRATION_PATH.read_text(encoding="utf-8")):
            conn.execute(statement)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class PostgresLedger:
    """PostgreSQL ``CreditLedger``.

    ``apply`` opens one transaction, takes ``pg_advisory_xact_lock`` so two
    connections cannot decide at the same time, loads a ``LedgerState``, and
    writes the state returned by ``decide`` before commit. The domain replaces
    the whole snapshot, so the lock covers every account in this schema.
    """

    def __init__(self, dsn: str, *, schema: str = "public") -> None:
        self._dsn = dsn
        self._schema = _validate_schema(schema)

    def apply(self, decide: Callable[[LedgerState], tuple[LedgerState, T]]) -> T:
        conn = self._connect()
        try:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                (f"openmcp.credit_ledger.{self._schema}",),
            )
            state = _load(conn)
            updated, result = decide(state)
            if not isinstance(updated, LedgerState):
                raise TypeError("decide must return a LedgerState")
            _store(conn, updated)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def balance_cents(self, account_id: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT balance_cents FROM credit_accounts WHERE account_id = %s",
                (account_id,),
            ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if row is None:
            return 0
        return int(row[0])

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self._dsn)
        try:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self._schema)))
        except Exception:
            conn.rollback()
            conn.close()
            raise
        return conn


def _validate_schema(schema: str) -> str:
    if not isinstance(schema, str) or _SCHEMA_NAME.fullmatch(schema) is None:
        raise ValueError("schema must be a single unquoted identifier")
    return schema


def _statements(script: str) -> list[str]:
    statements = []
    for chunk in script.split(";"):
        lines = []
        for line in chunk.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            lines.append(line)
        statement = "\n".join(lines).strip()
        if statement:
            statements.append(statement)
    return statements


def _load(conn: psycopg.Connection) -> LedgerState:
    balances = {
        account_id: int(cents)
        for account_id, cents in conn.execute(
            "SELECT account_id, balance_cents FROM credit_accounts"
        )
    }
    deposits = {
        charge_id: PostedDeposit(account_id=account_id, amount_cents=int(amount))
        for charge_id, account_id, amount in conn.execute(
            "SELECT charge_id, account_id, amount_cents FROM credit_deposits"
        )
    }
    debits = {
        (account_id, idempotency_key): PostedDebit(
            price_cents=int(price),
            balance_after_cents=int(balance_after),
        )
        for account_id, idempotency_key, price, balance_after in conn.execute(
            """
            SELECT account_id, idempotency_key, price_cents, balance_after_cents
            FROM credit_debits
            """
        )
    }
    return LedgerState(balances=balances, deposits=deposits, debits=debits)


def _store(conn: psycopg.Connection, state: LedgerState) -> None:
    conn.execute("DELETE FROM credit_debits")
    conn.execute("DELETE FROM credit_deposits")
    conn.execute("DELETE FROM credit_accounts")
    _insert_balances(conn, state.balances)
    _insert_deposits(conn, state.deposits)
    _insert_debits(conn, state.debits)


def _insert_balances(conn: psycopg.Connection, balances: Mapping[str, int]) -> None:
    if not balances:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO credit_accounts (account_id, balance_cents) VALUES (%s, %s)",
            list(balances.items()),
        )


def _insert_deposits(conn: psycopg.Connection, deposits: Mapping[str, PostedDeposit]) -> None:
    if not deposits:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO credit_deposits (charge_id, account_id, amount_cents)
            VALUES (%s, %s, %s)
            """,
            [
                (charge_id, deposit.account_id, deposit.amount_cents)
                for charge_id, deposit in deposits.items()
            ],
        )


def _insert_debits(conn: psycopg.Connection, debits: Mapping[tuple[str, str], PostedDebit]) -> None:
    if not debits:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO credit_debits (
                account_id, idempotency_key, price_cents, balance_after_cents
            )
            VALUES (%s, %s, %s, %s)
            """,
            [
                (account_id, idempotency_key, debit.price_cents, debit.balance_after_cents)
                for (account_id, idempotency_key), debit in debits.items()
            ],
        )
