"""PostgreSQL connection boundary shared by local and Supabase account storage.

Money operations use short transactions. A signing worker uses a separate,
non-reconnecting session, because its advisory lock must survive commits.
"""

import re
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class LeaseLost(RuntimeError):
    pass


class WorkerLease:
    def __init__(self, connection, schema):
        self._connection = connection
        self._schema = schema
        self._pid = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]

    def assert_held(self):
        try:
            if self._connection.closed:
                raise LeaseLost("Worker database session closed")
            row = self._connection.execute(
                "SELECT pg_backend_pid() AS pid, EXISTS(SELECT FROM pg_locks "
                "WHERE locktype='advisory' AND pid=pg_backend_pid() AND granted "
                "AND classid=(hashtext(%s)::bigint & 4294967295)::oid "
                "AND objid=170921 AND objsubid=2) AS held",
                (self._schema,),
            ).fetchone()
            if row["pid"] != self._pid or not row["held"]:
                raise LeaseLost("Worker database session changed")
        except psycopg.Error as exc:
            raise LeaseLost("Worker database session lost") from exc


class DatabaseManager:
    def __init__(self, dsn, schema="openmcp_product", *, provider="postgres", pool_max=4):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
            raise ValueError("Invalid database schema")
        if provider not in {"postgres", "supabase"}:
            raise ValueError("Unsupported database provider")
        if not 1 <= pool_max <= 20:
            raise ValueError("Database pool maximum must be between 1 and 20")
        options = self.validate_dsn(dsn, provider)
        if provider == "supabase" and options.get("user", "").split(".")[0] in {
            "postgres",
            "supabase_admin",
            "service_role",
            "anon",
            "authenticated",
            "",
        }:
            raise ValueError("Supabase runtime requires a dedicated application login")
        self.dsn, self.schema, self.provider = dsn, schema, provider
        self._kwargs = {
            "row_factory": dict_row,
            "connect_timeout": 10,
            "prepare_threshold": None,
            "application_name": "openmcp-account",
        }
        # Certificate verification uses libpq's system trust store unless a CA is supplied.
        if provider == "supabase" and "sslrootcert" not in options:
            self._kwargs["sslrootcert"] = "system"
        self._pool = ConnectionPool(
            dsn,
            kwargs=self._kwargs,
            min_size=0,
            max_size=pool_max,
            timeout=15,
            max_waiting=64,
            open=False,
            name="openmcp-account",
            check=ConnectionPool.check_connection,
        )

    @staticmethod
    def validate_dsn(dsn, provider="postgres"):
        if not dsn:
            raise ValueError("Account database connection is required")
        try:
            options = conninfo_to_dict(dsn)
        except psycopg.ProgrammingError:
            raise ValueError("Invalid database connection configuration") from None
        if not options.get("host") or not options.get("dbname"):
            raise ValueError("Account database needs an explicit host and database")
        if options.get("port") == "6543":
            raise ValueError("Transaction pooling is unsupported; use direct or session port 5432")
        if provider == "supabase" and options.get("sslmode") != "verify-full":
            raise ValueError("Supabase requires sslmode=verify-full and a trusted CA")
        return options

    @classmethod
    def from_settings(cls, settings):
        return cls(
            settings.database_url,
            settings.database_schema,
            provider=settings.database_provider,
            pool_max=settings.database_pool_max,
        )

    @contextmanager
    def transaction(self):
        self._pool.open()
        with self._pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    sql.SQL(
                        "SET LOCAL search_path TO {}, pg_catalog;"
                        "SET LOCAL statement_timeout = '15s';"
                        "SET LOCAL lock_timeout = '5s';"
                        "SET LOCAL idle_in_transaction_session_timeout = '30s'"
                    ).format(sql.Identifier(self.schema))
                )
                yield connection

    @contextmanager
    def worker_lease(self):
        # Never borrow this from the general pool or reconnect after acquiring the lock.
        with psycopg.connect(self.dsn, **self._kwargs, autocommit=True) as connection:
            connection.execute("SET statement_timeout = '15s'")
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s),170921) AS acquired", (self.schema,)
            ).fetchone()["acquired"]
            try:
                yield WorkerLease(connection, self.schema) if acquired else None
            finally:
                # Explicit unlock also handles session poolers retaining the server
                # connection after our client disconnects. Never reuse it locally.
                try:
                    if acquired and not connection.closed:
                        connection.execute(
                            "SELECT pg_advisory_unlock(hashtext(%s),170921)", (self.schema,)
                        )
                except psycopg.Error:
                    pass
                finally:
                    connection.close()

    def check_schema_version(self):
        try:
            with self.transaction() as connection:
                row = connection.execute(
                    "SELECT version FROM schema_version WHERE singleton=1"
                ).fetchone()
                if self.provider == "supabase":
                    privileges = connection.execute(
                        "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls "
                        "OR has_schema_privilege(current_user,%s,'CREATE') AS privileged "
                        "FROM pg_roles WHERE rolname=current_user",
                        (self.schema,),
                    ).fetchone()
                    if privileges["privileged"]:
                        raise RuntimeError(
                            "Supabase runtime must use a restricted application role"
                        )
            if not row or row["version"] != 1:
                raise RuntimeError("Account schema is incompatible; run account migrate")
        except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
            raise RuntimeError("Account schema is missing; run account migrate") from None

    def close(self):
        self._pool.close()
