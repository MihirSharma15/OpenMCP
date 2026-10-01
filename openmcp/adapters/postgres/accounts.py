"""PostgreSQL accounts, agents, and hashed credentials."""

import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

import psycopg
from psycopg import sql

from openmcp.ports.accounts import Account, AccountState, Agent, Credential

T = TypeVar("T")

_MIGRATION_PATH = Path(__file__).parent / "migrations" / "002_accounts.sql"
_SCHEMA_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def migrate(dsn: str, *, schema: str = "public") -> None:
    """Create the account tables in ``schema`` if they are not there yet.

    An empty DSN is the caller's concern: this function connects.
    """

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


class PostgresAccounts:
    """PostgreSQL ``AccountStore``.

    ``apply`` opens one transaction, takes ``pg_advisory_xact_lock`` so two
    connections cannot decide at the same time, loads an ``AccountState``, and
    writes the state returned by ``decide`` before commit. ``decide`` may
    return a one-time secret alongside that state. This adapter stores the
    state only and does not log the result.
    """

    def __init__(self, dsn: str, *, schema: str = "public") -> None:
        self._dsn = dsn
        self._schema = _validate_schema(schema)

    def apply(self, decide: Callable[[AccountState], tuple[AccountState, T]]) -> T:
        conn = self._connect()
        try:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                (f"openmcp.accounts.{self._schema}",),
            )
            state = _load(conn)
            updated, result = decide(state)
            if not isinstance(updated, AccountState):
                raise TypeError("decide must return an AccountState")
            _store(conn, updated)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def credential_by_hash(self, token_hash: str) -> Credential | None:
        if not isinstance(token_hash, str) or token_hash == "":
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT credential_id, account_id, agent_id, token_hash, scopes,
                       expires_at, revoked
                FROM credentials
                WHERE token_hash = %s
                """,
                (token_hash,),
            ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if row is None:
            return None
        return _credential_from_row(row)

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


def _load(conn: psycopg.Connection) -> AccountState:
    accounts = {
        account_id: Account(account_id=account_id)
        for (account_id,) in conn.execute("SELECT account_id FROM accounts")
    }
    agents = {
        agent_id: Agent(agent_id=agent_id, account_id=account_id)
        for agent_id, account_id in conn.execute("SELECT agent_id, account_id FROM agents")
    }
    credentials = {
        credential.credential_id: credential
        for credential in (
            _credential_from_row(row)
            for row in conn.execute(
                """
                SELECT credential_id, account_id, agent_id, token_hash, scopes,
                       expires_at, revoked
                FROM credentials
                """
            )
        )
    }
    return AccountState(accounts=accounts, agents=agents, credentials=credentials)


def _store(conn: psycopg.Connection, state: AccountState) -> None:
    conn.execute("DELETE FROM credentials")
    conn.execute("DELETE FROM agents")
    conn.execute("DELETE FROM accounts")
    _insert_accounts(conn, state.accounts)
    _insert_agents(conn, state.agents)
    _insert_credentials(conn, state.credentials)


def _insert_accounts(conn: psycopg.Connection, accounts: Mapping[str, Account]) -> None:
    if not accounts:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO accounts (account_id) VALUES (%s)",
            [(account.account_id,) for account in accounts.values()],
        )


def _insert_agents(conn: psycopg.Connection, agents: Mapping[str, Agent]) -> None:
    if not agents:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO agents (agent_id, account_id) VALUES (%s, %s)",
            [(agent.agent_id, agent.account_id) for agent in agents.values()],
        )


def _insert_credentials(conn: psycopg.Connection, credentials: Mapping[str, Credential]) -> None:
    if not credentials:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO credentials (
                credential_id, account_id, agent_id, token_hash, scopes, expires_at, revoked
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    credential.credential_id,
                    credential.account_id,
                    credential.agent_id,
                    credential.token_hash,
                    sorted(credential.scopes),
                    credential.expires_at,
                    credential.revoked,
                )
                for credential in credentials.values()
            ],
        )


def _credential_from_row(row: tuple) -> Credential:
    credential_id, account_id, agent_id, token_hash, scopes, expires_at, revoked = row
    return Credential(
        credential_id=credential_id,
        account_id=account_id,
        agent_id=agent_id,
        token_hash=token_hash,
        scopes=frozenset(scopes),
        expires_at=_utc(expires_at),
        revoked=bool(revoked),
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
